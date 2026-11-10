"""Explicit real-Redis and real nginx/TLS integration; never emulator or skip.

Requires SCMS_DISPOSABLE_REDIS=True and SCMS_TRACKING_REDIS_TEST_URL pointing
at a dedicated throwaway Redis DB. Tests FLUSH that DB and temporarily change
server maxmemory/eviction settings. Never run against a shared/deployed service.
The nginx check also needs nginx and openssl executables (SCMS_NGINX may override).
"""

import http.client
import os
import re
import shutil
import socket
import ssl
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from urllib.parse import urlencode

import pytest
from django.conf import settings as django_settings

from complaints import tracking_limits as limits


@pytest.fixture
def real_backend(settings):
    url = os.environ.get("SCMS_TRACKING_REDIS_TEST_URL", "")
    if os.environ.get("SCMS_DISPOSABLE_REDIS") != "True" or not url:
        pytest.fail("Explicit disposable Redis acknowledgement and test URL are required; no fallback or skip.")
    settings.ANONYMOUS_TRACKING_REDIS_URL = url
    settings.ANONYMOUS_TRACKING_SOURCE_SECRET = "synthetic-integration-source-secret-" + "b" * 32
    settings.ANONYMOUS_TRACKING_LIMITER_READY = True
    settings.ANONYMOUS_TRACKING_ENABLED = True
    settings.ANONYMOUS_PRIVACY_READY = True
    settings.DEBUG = False
    settings.CSRF_USE_SESSIONS = False
    settings.SCMS_HTTPS_MODE = "direct"
    settings.SECURE_PROXY_SSL_HEADER = None
    settings.SECURE_SSL_REDIRECT = settings.SESSION_COOKIE_SECURE = settings.CSRF_COOKIE_SECURE = True
    client = limits.redis_client(url)
    try:
        assert client.info("server")["redis_version"]
        limits.verify_ephemeral_backend(client)
    except Exception:
        pytest.fail("Disposable real Redis is missing or unsafe; no emulator fallback.")
    # Only this explicitly disposable integration DB is flushed/seeded. Production
    # must never bypass the epoch or reset source allowances this way.
    client.flushdb()
    limits.invalidate_backend(client)
    yield client
    client.flushdb()
    limits.invalidate_backend(client)


def warm_test_instance(client):
    seconds, micros = client.time()
    client.set(limits.EPOCH_KEY, str(seconds * 1000000 + micros - 601000000))


def test_real_redis_atomic_allowance_across_connections(real_backend):
    warm_test_instance(real_backend)
    with ThreadPoolExecutor(max_workers=16) as pool:
        allowed = list(pool.map(lambda _: limits.consume_attempt("198.51.100.18")[0], range(24)))
    assert sum(allowed) == 10
    keys = real_backend.keys("scms:b13:source:*")
    assert len(keys) == 1 and re.fullmatch(r"scms:b13:source:[a-f0-9]{64}", keys[0])
    assert real_backend.zcard(keys[0]) == 10 and 1 <= real_backend.ttl(keys[0]) <= 600
    assert "198.51.100.18" not in str(keys)


def test_real_redis_lost_epoch_refuses_even_after_cached_verification(real_backend):
    warm_test_instance(real_backend)
    assert limits.consume_attempt("198.51.100.18")[0]
    real_backend.delete(limits.EPOCH_KEY)
    with pytest.raises(limits.TrackingUnavailable):
        limits.consume_attempt("198.51.100.19")
    assert len(real_backend.keys("scms:b13:source:*")) == 1
    assert real_backend.get(limits.EPOCH_KEY)


def test_real_redis_removes_expired_window_entries(real_backend):
    warm_test_instance(real_backend)
    limits.consume_attempt("198.51.100.18")
    key = real_backend.keys("scms:b13:source:*")[0]
    seconds, micros = real_backend.time()
    old = seconds * 1000000 + micros - 601000000
    real_backend.zadd(key, {"synthetic-old-attempt": old})
    assert limits.consume_attempt("198.51.100.18")[0]
    assert real_backend.zscore(key, "synthetic-old-attempt") is None
    assert real_backend.zcard(key) == 2


def test_real_redis_ipv6_prefix_shares_allowance(real_backend):
    warm_test_instance(real_backend)
    for number in range(1, 11):
        assert limits.consume_attempt(f"2001:db8:1234:5678::{number:x}")[0]
    assert not limits.consume_attempt("2001:db8:1234:5678:ffff:ffff:ffff:ffff")[0]
    assert limits.consume_attempt("2001:db8:1234:5679::1")[0]


def test_real_redis_unsafe_configuration_is_refused(real_backend):
    original = real_backend.config_get("maxmemory-policy")["maxmemory-policy"]
    try:
        real_backend.config_set("maxmemory-policy", "allkeys-lru")
        with pytest.raises(limits.TrackingUnavailable):
            limits.consume_attempt("198.51.100.18")
        assert not real_backend.keys("scms:b13:source:*")
    finally:
        real_backend.config_set("maxmemory-policy", original)


def test_real_redis_noeviction_oom_is_unavailable(real_backend):
    warm_test_instance(real_backend)
    original = real_backend.config_get("maxmemory")["maxmemory"]
    try:
        real_backend.config_set("maxmemory", 1)
        with pytest.raises(limits.TrackingUnavailable):
            limits.consume_attempt("198.51.100.18")
        assert not real_backend.keys("scms:b13:source:*")
    finally:
        real_backend.config_set("maxmemory", original)


@pytest.fixture
def tls_proxy(real_backend, settings, live_server, tmp_path, request):
    executable = os.environ.get("SCMS_NGINX") or shutil.which("nginx")
    if not executable or not shutil.which("openssl"):
        pytest.fail("Real nginx and openssl are required; no simulated proxy or skip.")
    settings.SCMS_HTTPS_MODE = "proxy"
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.ANONYMOUS_TRACKING_TRUSTED_PROXY_CIDRS = ["127.0.0.1/32"]
    settings.ALLOWED_HOSTS = [*django_settings.ALLOWED_HOSTS, "127.0.0.1"]
    warm_test_instance(real_backend)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
        "-keyout", str(key), "-out", str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # The negative case deliberately rewrites Host; it must fail same-origin CSRF.
    host = "127.0.0.1" if getattr(request, "param", "preserve") == "rewrite" else "$http_host"
    (tmp_path / "logs").mkdir()
    config = tmp_path / "nginx.conf"
    config.write_text(f'''
error_log stderr crit;
pid "{tmp_path / 'nginx.pid'}";
events {{ worker_connections 64; }}
http {{
    access_log off;
    server {{
        listen 127.0.0.1:{port} ssl;
        ssl_certificate "{cert}";
        ssl_certificate_key "{key}";
        client_max_body_size 1k;
        location / {{
            proxy_pass {live_server.url};
            proxy_set_header Host {host};
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For "";
            proxy_set_header X-Forwarded-Host "";
        }}
    }}
}}
''')
    process = subprocess.Popen([executable, "-p", str(tmp_path), "-c", str(config), "-g", "daemon off;"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 5
        while True:
            if process.poll() is not None:
                pytest.fail("Real nginx TLS proxy failed to start.")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    pytest.fail("Real nginx TLS proxy did not become ready.")
                time.sleep(.05)
        yield port, ssl.create_default_context(cafile=str(cert))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def proxy_request(proxy, source, method, path="/complaints/track/", token=None, forged="203.0.113.99"):
    port, context = proxy
    connection = http.client.HTTPSConnection("127.0.0.1", port, context=context,
                                            source_address=(source, 0), timeout=5)
    headers = {"X-Real-IP": forged, "X-Forwarded-For": forged}
    body = None
    if method == "POST":
        body = urlencode({"reference": "b" * 32, "csrfmiddlewaretoken": token})
        headers |= {"Content-Type": "application/x-www-form-urlencoded", "Cookie": "csrftoken=" + token,
                    "Origin": f"https://127.0.0.1:{port}"}
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.getheaders(), response.read()
    finally:
        connection.close()


def csrf_token(proxy, source, path="/complaints/track/"):
    status, headers, body = proxy_request(proxy, source, "GET", path)
    assert status == 200
    cookies = SimpleCookie()
    for name, value in headers:
        if name.lower() == "set-cookie":
            cookies.load(value)
    assert cookies["csrftoken"]["secure"] and b"b" * 32 not in body
    return cookies["csrftoken"].value


@pytest.mark.django_db(transaction=True)
def test_real_tls_proxy_preserves_two_client_buckets_and_overwrites_spoofed_headers(tls_proxy):
    first = csrf_token(tls_proxy, "127.0.0.2")
    for value in range(10):
        assert proxy_request(tls_proxy, "127.0.0.2", "POST", token=first, forged=f"203.0.113.{value}")[0] == 200
    assert proxy_request(tls_proxy, "127.0.0.2", "POST", token=first)[0] == 429
    second = csrf_token(tls_proxy, "127.0.0.3")
    assert proxy_request(tls_proxy, "127.0.0.3", "POST", token=second)[0] == 200


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("tls_proxy", ["rewrite"], indirect=True)
def test_real_proxy_rewritten_host_fails_csrf(tls_proxy):
    token = csrf_token(tls_proxy, "127.0.0.2")
    assert proxy_request(tls_proxy, "127.0.0.2", "POST", token=token)[0] == 403


@pytest.mark.django_db(transaction=True)
def test_real_proxy_preserves_b11_same_origin_form(tls_proxy, settings, routing_configuration):
    settings.COMPLAINT_INTAKE_ENABLED = settings.ANONYMOUS_INTAKE_ENABLED = True
    settings.COMPLAINT_EMERGENCY_NOTICE = "SYNTHETIC TEST only, not campus policy."
    path = "/complaints/anonymous/"
    token = csrf_token(tls_proxy, "127.0.0.2", path)
    status, _, body = proxy_request(tls_proxy, "127.0.0.2", "POST", path, token)
    # Missing B11 operation token/input is safe validation (400), not CSRF (403).
    assert status == 400 and b"b" * 32 not in body
