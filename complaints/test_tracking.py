"""B13 real Django/DB lookup plus Lua execution in an in-memory Redis emulator.

No external Redis/deployment acceptance is implied by emulator tests.
"""

import hashlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import fakeredis
import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.models import Session
from django.db import connection
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import SecurityEvent
from complaints import tracking_limits as limits, tracking_views
from complaints.checks import check_tracking_privacy
from complaints.models import AnonymousIntakeReceipt, Attachment, Complaint, IntakeReceipt
from complaints.privacy_middleware import AnonymousExceptionReporter, AnonymousPrivacyMiddleware
from complaints.tracking import restricted_tracking
from workflow.history_service import record_history
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db
REFERENCE = "a" * 32
PRIVATE = "private-person@example.test"
PEER = "198.51.100.18"


@pytest.fixture
def backend(settings, monkeypatch):
    settings.SCMS_HTTPS_MODE = "direct"
    settings.SECURE_PROXY_SSL_HEADER = None
    settings.SECURE_SSL_REDIRECT = True
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    settings.ANONYMOUS_TRACKING_TRUSTED_PROXY_CIDRS = []
    settings.DEBUG = False
    settings.CSRF_USE_SESSIONS = False
    settings.ANONYMOUS_PRIVACY_READY = True
    settings.ANONYMOUS_TRACKING_ENABLED = True
    settings.ANONYMOUS_TRACKING_LIMITER_READY = True
    settings.ANONYMOUS_TRACKING_REDIS_URL = "redis://synthetic-redis.invalid:6379/0"
    settings.ANONYMOUS_TRACKING_SOURCE_SECRET = "synthetic-test-source-secret-" + "b" * 32
    client = fakeredis.FakeRedis(decode_responses=True)
    client.set(limits.EPOCH_KEY, "0")  # The synthetic instance has completed warmup.
    config = {"save": "", "appendonly": "no", "maxmemory-policy": "noeviction",
              "maxmemory": "1048576", "slowlog-log-slower-than": "-1", "notify-keyspace-events": ""}
    info = {"server": {"uptime_in_seconds": 1000, "redis_version": "7.4.2"},
            "replication": {"role": "master", "connected_slaves": 0},
            "persistence": {"rdb_bgsave_in_progress": 0, "aof_enabled": 0, "aof_rewrite_in_progress": 0}}
    # fakeredis executes the production Lua script. Configuration/uptime checks
    # are explicit test doubles; real server acceptance belongs to E03.
    client.config_get = Mock(side_effect=lambda name: {name: config[name]})
    client.info = Mock(side_effect=lambda section: info[section])
    # fakeredis does not parse Redis 7's shebang. Execute the unchanged Lua body
    # here; real-Redis integration separately checks the complete flagged script
    # and its OOM policy. Never remove the production script header.
    emulator_eval = client.eval
    def eval_body(script, *args):
        assert script.startswith("#!lua\n")
        return emulator_eval(script.split("\n", 1)[1], *args)
    client.eval = eval_body
    monkeypatch.setattr(limits, "redis_client", lambda url: client)
    yield client, config, info
    client.close()


@pytest.fixture
def complaint(complaint_factory):
    item = complaint_factory(anonymous=True, title=PRIVATE, description=PRIVATE * 2,
                             resolution_remarks=PRIVATE)
    Complaint.objects.filter(pk=item.pk).update(reference_digest=hashlib.sha256(REFERENCE.encode()).hexdigest())
    item.refresh_from_db()
    record_history(item.complaint_id, "SUBMITTED", "ANONYMOUS", new_state="SUBMITTED", remarks=PRIVATE)
    record_history(item.complaint_id, "ALLOCATED", "SYSTEM", "SUBMITTED", "ASSIGNED", remarks=PRIVATE)
    return item


def lookup(client, reference=REFERENCE, *, page=1, peer=PEER, **headers):
    return client.post(reverse("complaints:track_reference"),
                       urlencode({"reference": reference, "page": page}),
                       content_type="application/x-www-form-urlencoded", secure=True,
                       REMOTE_ADDR=peer, **headers)


def test_valid_reference_returns_only_permitted_fields_and_history(backend, complaint, client):
    response = lookup(client)
    assert response.status_code == 200
    result = response.context["result"]
    assert set(result) == {"complaint", "history", "page", "pages"}
    assert set(result["complaint"]) == {"complaint_id", "category", "location", "status", "is_escalated"}
    assert result["complaint"]["complaint_id"] == complaint.complaint_id
    assert [row["new_state"] for row in result["history"]] == ["Submitted", "Assigned"]
    assert all(set(row) == {"event", "previous_state", "new_state", "occurred_at"} for row in result["history"])
    for value in (REFERENCE, complaint.reference_digest, PRIVATE):
        assert value not in response.content.decode() and value not in str(result)
    assert b"evidence/" not in response.content and b"submitted_by" not in response.content


@pytest.mark.parametrize("reference", ["", "bad", "a" * 31, "a" * 33, "A" * 32, "g" * 32,
                                        "<script>alert(1)</script>", "SCMS-2026-000001", "a" * 200])
def test_malformed_and_unknown_have_same_response(backend, client, reference):
    unknown = lookup(client, "b" * 32)
    malformed = lookup(client, reference)
    # Mask only Django's randomized CSRF token when comparing complete HTML.
    mask = lambda content: re.sub(rb'value="[A-Za-z0-9]{64}"', b'value="CSRF"', content)
    assert malformed.status_code == unknown.status_code == 200
    assert mask(malformed.content) == mask(unknown.content)
    assert malformed.context["result"] is None


def test_unknown_and_malformed_each_perform_one_same_shape_lookup(backend):
    counts = []
    for value in ("b" * 32, "bad", None):
        with CaptureQueriesContext(connection) as queries:
            assert restricted_tracking(value) is None
        assert len(queries) == 1
        assert "reference_digest" in queries[0]["sql"] and "submitted_by_id" in queries[0]["sql"]
        counts.append(len(queries))
    assert counts == [1, 1, 1]


def test_reference_does_not_authorize_authenticated_complaint(backend, complaint_factory, client):
    item = complaint_factory()
    assert lookup(client, item.complaint_id).context["result"] is None
    assert lookup(client, REFERENCE).context["result"] is None


def test_lookup_never_creates_session_or_lookup_database_records(backend, complaint, client):
    models = (Complaint, ComplaintHistory, Session, SecurityEvent, IntakeReceipt, AnonymousIntakeReceipt, Attachment)
    before = {model: list(model.objects.values()) for model in models}
    assert lookup(client).status_code == 200
    assert {model: list(model.objects.values()) for model in models} == before


def test_signed_in_account_is_isolated_without_logout(backend, complaint, client, user_factory):
    user = user_factory(email=PRIVATE)
    client.force_login(user)
    sessions = list(Session.objects.values())
    response = lookup(client, HTTP_AUTHORIZATION=PRIVATE, HTTP_USER_AGENT=PRIVATE)
    assert response.status_code == 200 and response.wsgi_request.user.is_anonymous
    assert list(Session.objects.values()) == sessions and "sessionid" not in response.cookies
    assert PRIVATE.encode() not in response.content
    assert client.get(reverse("accounts:landing_complainant"), secure=True).status_code == 200


def test_tenth_allowed_eleventh_throttled_before_any_database_lookup(backend, complaint, client):
    for _ in range(10):
        assert lookup(client).status_code == 200
    with CaptureQueriesContext(connection) as queries:
        response = lookup(client)
    assert response.status_code == 429 and 1 <= int(response["Retry-After"]) <= 600
    assert len(queries) == 0 and complaint.complaint_id.encode() not in response.content


def test_malformed_unknown_valid_and_changed_forwarding_headers_share_limit(backend, complaint, client):
    for i in range(10):
        value = ["bad", "b" * 32, REFERENCE][i % 3]
        assert lookup(client, value, HTTP_X_FORWARDED_FOR=f"203.0.113.{i}").status_code == 200
    assert lookup(client).status_code == 429
    assert lookup(client, peer="198.51.100.19").status_code == 200


def test_rolling_window_has_no_fixed_boundary_burst(backend):
    with patch("time.time", return_value=10000):
        for _ in range(5):
            assert limits.consume_attempt(PEER) == (True, 0)
    with patch("time.time", return_value=10599):
        for _ in range(5):
            assert limits.consume_attempt(PEER) == (True, 0)
        assert limits.consume_attempt(PEER) == (False, 1)
    with patch("time.time", return_value=10600):
        for _ in range(5):
            assert limits.consume_attempt(PEER) == (True, 0)
        assert limits.consume_attempt(PEER) == (False, 599)


def test_concurrent_clients_cannot_exceed_ten_slots(backend):
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda i: limits.consume_attempt(PEER)[0], range(24)))
    assert sum(results) == 10
    assert backend[0].zcard(backend[0].keys("scms:b13:source:*")[0]) == 10


def test_nonce_collision_fails_closed_instead_of_overwriting_an_attempt(backend):
    with patch.object(limits.secrets, "token_hex", return_value="c" * 32):
        assert limits.consume_attempt(PEER) == (True, 0)
        with pytest.raises(limits.TrackingUnavailable):
            limits.consume_attempt(PEER)


@pytest.mark.django_db(transaction=True)
def test_newly_issued_anonymous_reference_tracks_through_http(backend, routing_configuration, settings, client):
    settings.COMPLAINT_INTAKE_ENABLED = True
    settings.ANONYMOUS_INTAKE_ENABLED = True
    settings.COMPLAINT_EMERGENCY_NOTICE = "SYNTHETIC TEST notice, not campus policy."
    form = client.get(reverse("complaints:anonymous_submit"), secure=True)
    response = client.post(reverse("complaints:anonymous_submit"), {
        "request_token": form.context["request_token"],
        "category": routing_configuration["category"].pk,
        "location": routing_configuration["location"].code,
        "title": "Synthetic light problem", "priority": "LOW",
        "description": "This synthetic room's light does not work properly.",
    }, secure=True)
    assert response.status_code == 200
    reference, identifier = response.context["reference"], response.context["complaint_id"]
    tracked = lookup(client, reference)
    assert tracked.context["result"]["complaint"]["complaint_id"] == identifier
    assert len(tracked.context["result"]["history"]) == 2
    assert reference.encode() not in tracked.content


def test_ipv4_and_mapped_ipv6_share_allowance(backend):
    for _ in range(10):
        assert limits.consume_attempt(PEER)[0]
    assert not limits.consume_attempt("::ffff:" + PEER)[0]


def test_only_ephemeral_hmac_nonce_time_is_stored_and_expires(backend, settings):
    client = backend[0]
    with patch("time.time", return_value=10000):
        limits.consume_attempt(PEER)
        keys = client.keys("scms:b13:source:*")
        assert len(keys) == 1 and re.fullmatch(r"scms:b13:source:[a-f0-9]{64}", keys[0])
        assert client.ttl(keys[0]) == 600
        members = client.zrange(keys[0], 0, -1, withscores=True)
        assert re.fullmatch(r"[a-f0-9]{32}", members[0][0])
        assert members[0][1] == 10000000000
        assert PEER not in str(keys + members) and REFERENCE not in str(keys + members)
    with patch("time.time", return_value=10600.001):
        assert client.keys("scms:b13:source:*") == []


@pytest.mark.parametrize("name,value", [("save", "900 1"), ("appendonly", "yes"),
                                       ("maxmemory-policy", "allkeys-lru"), ("maxmemory", "0"),
                                       ("slowlog-log-slower-than", "10000"), ("notify-keyspace-events", "AKE")])
def test_persistence_eviction_or_command_logging_fails_before_source_storage(backend, name, value):
    backend[1][name] = value
    with pytest.raises(limits.TrackingUnavailable):
        limits.consume_attempt(PEER)
    assert backend[0].keys("scms:b13:source:*") == []


@pytest.mark.parametrize("section,key,value", [("replication", "role", "slave"),
                                              ("replication", "connected_slaves", 1),
                                              ("persistence", "rdb_bgsave_in_progress", 1),
                                              ("persistence", "aof_enabled", 1),
                                              ("persistence", "aof_rewrite_in_progress", 1)])
def test_backend_restart_or_replication_is_unavailable(backend, client, section, key, value):
    backend[2][section][key] = value
    assert lookup(client).status_code == 503
    assert backend[0].keys("scms:b13:source:*") == []


def test_restart_quarantine_finishes_at_full_window(backend):
    backend[0].delete(limits.EPOCH_KEY)
    with patch("time.time", return_value=10000):
        with pytest.raises(limits.TrackingUnavailable):
            limits.consume_attempt(PEER)
        assert backend[0].keys("scms:b13:source:*") == []
    with patch("time.time", return_value=10599):
        with pytest.raises(limits.TrackingUnavailable):
            limits.consume_attempt(PEER)
    with patch("time.time", return_value=10600):
        assert limits.consume_attempt(PEER) == (True, 0)


@pytest.mark.parametrize("source", ["", "not-an-ip", None, "198.51.100.18, 203.0.113.1"])
def test_invalid_peer_fails_closed(backend, client, source):
    assert lookup(client, peer=source).status_code == 503
    assert backend[0].keys("scms:b13:source:*") == []


def test_backend_failure_masks_exception_and_does_not_query_complaints(backend, client, caplog):
    backend[0].eval = Mock(side_effect=RuntimeError(PRIVATE))
    with CaptureQueriesContext(connection) as queries:
        response = lookup(client)
    assert response.status_code == 503 and len(queries) == 0
    assert PRIVATE not in caplog.text and PRIVATE.encode() not in response.content


@pytest.mark.parametrize("reply", [[9, 0], [1, -1], [0, 601], [1, "0"]])
def test_invalid_backend_reply_never_authorizes_lookup(backend, reply):
    backend[0].eval = Mock(return_value=reply)
    with pytest.raises(limits.TrackingUnavailable):
        limits.consume_attempt(PEER)


@pytest.mark.parametrize("setting,value", [("ANONYMOUS_TRACKING_ENABLED", False),
                                           ("ANONYMOUS_PRIVACY_READY", False),
                                           ("ANONYMOUS_TRACKING_LIMITER_READY", False),
                                           ("ANONYMOUS_TRACKING_REDIS_URL", ""),
                                           ("ANONYMOUS_TRACKING_REDIS_URL", "redis://["),
                                           ("ANONYMOUS_TRACKING_REDIS_URL", "redis://bad:1/0?socket_timeout=0"),
                                           ("ANONYMOUS_TRACKING_SOURCE_SECRET", "short"),
                                           ("DEBUG", True), ("CSRF_USE_SESSIONS", True)])
def test_tracking_release_gates_block_get_and_post(backend, settings, client, setting, value):
    setattr(settings, setting, value)
    assert client.get(reverse("complaints:track_reference"), secure=True).status_code == 503
    assert lookup(client).status_code == 503
    assert backend[0].keys("scms:b13:source:*") == []


def test_tracking_remains_available_when_new_intake_is_disabled(backend, settings, complaint, client):
    settings.COMPLAINT_INTAKE_ENABLED = False
    settings.ANONYMOUS_INTAKE_ENABLED = False
    assert lookup(client).context["result"]["complaint"]["complaint_id"] == complaint.complaint_id


def test_view_without_consumed_allowance_fails_closed(backend):
    request = RequestFactory().post("/complaints/track/", secure=True)
    request.anonymous_tracking = request.anonymous_privacy_isolated = True
    assert tracking_views.track_reference(request).status_code == 503


def test_deployment_check_clearly_refuses_invalid_release_config(backend, settings):
    assert check_tracking_privacy(None) == []
    settings.ANONYMOUS_TRACKING_LIMITER_READY = False
    assert [error.id for error in check_tracking_privacy(None)] == ["complaints.E003"]
    settings.ANONYMOUS_TRACKING_ENABLED = False
    assert check_tracking_privacy(None) == []


@pytest.mark.parametrize("misordered", [False, True])
def test_missing_or_late_privacy_middleware_cannot_bypass_limit(backend, settings, misordered):
    name = "complaints.privacy_middleware.AnonymousPrivacyMiddleware"
    settings.MIDDLEWARE = [item for item in settings.MIDDLEWARE if item != name]
    if misordered:
        settings.MIDDLEWARE.append(name)
    assert lookup(Client()).status_code == 503
    assert backend[0].keys("scms:b13:source:*") == []


def test_csrf_cross_origin_and_http_transport_are_refused(backend):
    client = Client(enforce_csrf_checks=True)
    url = reverse("complaints:track_reference")
    assert client.get(url, secure=True).status_code == 200
    assert lookup(client).status_code == 403
    token = client.cookies["csrftoken"].value
    data = urlencode({"reference": REFERENCE, "csrfmiddlewaretoken": token})
    assert client.post(url, data, content_type="application/x-www-form-urlencoded", secure=True,
                       HTTP_ORIGIN="https://other.example.test").status_code == 403
    assert client.post(url, data, content_type="application/x-www-form-urlencoded", secure=True,
                       HTTP_ORIGIN="https://testserver").status_code == 200
    assert client.post(url, data, content_type="application/x-www-form-urlencoded").status_code == 301


def test_get_never_looks_up_url_credentials_or_consumes_an_attempt(backend, complaint, client):
    response = client.get(reverse("complaints:track_reference") + "?reference=" + REFERENCE, secure=True)
    assert response.status_code == 200 and not response.context["searched"]
    assert REFERENCE.encode() not in response.content and not response.wsgi_request.GET
    assert backend[0].keys("scms:b13:source:*") == []
    assert client.put(reverse("complaints:track_reference"), secure=True).status_code == 405


@pytest.mark.parametrize("header,status", [("HTTP_ORIGIN", 403), ("HTTP_REFERER", 403), ("HTTP_HOST", 400)])
def test_security_refusals_do_not_log_private_header_values(backend, caplog, header, status):
    client = Client(enforce_csrf_checks=True)
    url = reverse("complaints:track_reference")
    client.get(url, secure=True)
    token = client.cookies["csrftoken"].value
    value = REFERENCE + ".invalid" if header == "HTTP_HOST" else "https://" + REFERENCE + ".invalid/"
    response = client.post(url, urlencode({"reference": REFERENCE, "csrfmiddlewaretoken": token}),
                           content_type="application/x-www-form-urlencoded", secure=True, **{header: value})
    assert response.status_code == status
    assert REFERENCE not in caplog.text and REFERENCE.encode() not in response.content


def test_empty_and_duplicate_reference_parameters_do_not_bypass_validation(backend, complaint, client):
    url = reverse("complaints:track_reference")
    for data in ("", urlencode({"reference": [REFERENCE, REFERENCE]}, doseq=True)):
        response = client.post(url, data, content_type="application/x-www-form-urlencoded", secure=True)
        assert response.status_code == 200 and response.context["result"] is None


def test_large_or_multipart_requests_are_refused_before_body_parsing(backend, client):
    url = reverse("complaints:track_reference")
    assert lookup(client, "a" * 1100).status_code == 400
    assert client.post(url, {"reference": REFERENCE}, secure=True).status_code == 400


def test_free_text_actors_and_unknown_states_never_appear_in_history(backend, complaint, client):
    record_history(complaint.complaint_id, "STATUS_CHANGED", "STAFF", "ASSIGNED", "IN_PROGRESS", remarks=PRIVATE)
    record_history(complaint.complaint_id, "STATUS_CHANGED", "STAFF", "IN_PROGRESS", PRIVATE)
    response = lookup(client)
    assert len(response.context["result"]["history"]) == 3
    for value in (PRIVATE, "STAFF", "SYSTEM", "ANONYMOUS", "resolution_remarks"):
        assert value not in str(response.context["result"])


def test_history_is_paginated_at_25_without_reference_in_next_page_form(backend, complaint, client):
    for _ in range(30):
        record_history(complaint.complaint_id, "STATUS_CHANGED", "SYSTEM", "ASSIGNED", "IN_PROGRESS", remarks=PRIVATE)
    first, second = lookup(client), lookup(client, page=2)
    assert len(first.context["result"]["history"]) == 25
    assert len(second.context["result"]["history"]) == 7
    assert first.context["result"]["pages"] == 2
    assert second.context["result"]["history"][-1]["occurred_at"] <= first.context["result"]["history"][0]["occurred_at"]
    assert REFERENCE.encode() not in first.content + second.content


def test_lookup_escapes_master_labels_and_does_not_grant_other_routes(backend, complaint, client):
    Complaint.objects.filter(pk=complaint.pk).update(category="<script>bad</script>")
    response = lookup(client)
    assert b"<script>" not in response.content and b"&lt;script&gt;" in response.content
    assert client.get(reverse("complaints:acknowledgement", args=[complaint.complaint_id]), secure=True).status_code == 302
    assert client.get(reverse("complaints:download_evidence", args=[999]), {"reference": REFERENCE}, secure=True).status_code == 404
    assert not Session.objects.exists() and not SecurityEvent.objects.exists()


def test_private_headers_and_error_report_scrub_source_reference_cookie_and_query(backend):
    request = RequestFactory().post("/complaints/track/?reference=" + REFERENCE,
                                    urlencode({"reference": REFERENCE}),
                                    content_type="application/x-www-form-urlencoded", secure=True,
                                    REMOTE_ADDR=PEER, HTTP_USER_AGENT=PRIVATE,
                                    HTTP_COOKIE="sessionid=" + PRIVATE)
    response = AnonymousPrivacyMiddleware(lambda req: HttpResponse("ok"))(request)
    request.user = AnonymousUser()
    assert not request.GET and "REMOTE_ADDR" not in request.META and "HTTP_USER_AGENT" not in request.META
    assert not request.COOKIES and not hasattr(request, "tracking_source")
    assert "no-store" in response["Cache-Control"] and response["Referrer-Policy"] == "no-referrer"
    assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert "form-action 'self'" in response["Content-Security-Policy"]
    try:
        raise RuntimeError(PRIVATE + REFERENCE + PEER)
    except RuntimeError:
        report = AnonymousExceptionReporter(request, *sys.exc_info()).get_traceback_text()
    assert all(value not in report for value in (PRIVATE, REFERENCE, PEER))


def test_unexpected_tracking_error_is_generic_and_not_logged(backend, client, caplog):
    with patch.object(tracking_views, "restricted_tracking", side_effect=ValueError(PRIVATE + REFERENCE)):
        response = lookup(client)
    assert response.status_code == 500
    assert PRIVATE not in caplog.text and REFERENCE not in caplog.text
    assert PRIVATE.encode() not in response.content and REFERENCE.encode() not in response.content


def test_real_redis_connection_configuration_disallows_retries_and_uses_timeouts(settings):
    # This verifies connection construction without contacting an external host.
    url = "redis://synthetic-redis.invalid:6379/0"
    with patch.object(limits.Redis, "from_url") as create:
        limits.redis_client.cache_clear()
        limits.redis_client(url)
        kwargs = create.call_args.kwargs
        assert kwargs["socket_timeout"] == kwargs["socket_connect_timeout"] == 1
        assert kwargs["retry"].get_retries() == 0
        limits.redis_client.cache_clear()


def test_successful_backend_verification_is_cached_for_at_most_30_seconds(backend):
    client = backend[0]
    with patch.object(limits.time, "monotonic", return_value=100):
        limits.consume_attempt(PEER)
        checked = client.config_get.call_count, client.info.call_count
        assert checked == (6, 3)
    with patch.object(limits.time, "monotonic", return_value=129.9):
        limits.consume_attempt(PEER)
        assert (client.config_get.call_count, client.info.call_count) == checked
    with patch.object(limits.time, "monotonic", return_value=130):
        limits.consume_attempt(PEER)
        assert (client.config_get.call_count, client.info.call_count) == (12, 6)


def test_failed_backend_verification_is_never_cached(backend):
    backend[1]["save"] = "900 1"
    for _ in range(2):
        with pytest.raises(limits.TrackingUnavailable):
            limits.consume_attempt(PEER)
    assert backend[0].config_get.call_count == 2
    backend[1]["save"] = ""
    assert limits.consume_attempt(PEER)[0]


def test_eval_error_invalidates_a_cached_backend_verification(backend):
    client = backend[0]
    limits.consume_attempt(PEER)
    with patch.object(client, "eval", side_effect=RuntimeError(PRIVATE)):
        with pytest.raises(limits.TrackingUnavailable):
            limits.consume_attempt(PEER)
    backend[1]["save"] = "900 1"
    with pytest.raises(limits.TrackingUnavailable):
        limits.consume_attempt(PEER)


def test_expired_successful_check_rechecks_and_refuses_changed_configuration(backend):
    with patch.object(limits.time, "monotonic", return_value=100):
        limits.consume_attempt(PEER)
    backend[1]["appendonly"] = "yes"
    with patch.object(limits.time, "monotonic", return_value=130):
        with pytest.raises(limits.TrackingUnavailable):
            limits.consume_attempt(PEER)
    assert backend[0].zcard(backend[0].keys("scms:b13:source:*")[0]) == 1


def test_ipv6_addresses_within_one_64_share_limit_but_other_prefix_is_independent(backend):
    for value in range(1, 11):
        assert limits.consume_attempt(f"2001:db8:1234:5678::{value:x}")[0]
    assert not limits.consume_attempt("2001:db8:1234:5678:ffff:ffff:ffff:ffff")[0]
    assert limits.consume_attempt("2001:db8:1234:5679::1")[0]


def test_proxy_mode_separates_verified_clients_and_scrubs_forwarding_headers(backend, settings, client):
    settings.SCMS_HTTPS_MODE = "proxy"
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.ANONYMOUS_TRACKING_TRUSTED_PROXY_CIDRS = ["192.0.2.8/32"]
    for _ in range(10):
        response = lookup(client, peer="192.0.2.8", HTTP_X_REAL_IP=PEER)
        assert response.status_code == 200
        assert "HTTP_X_REAL_IP" not in response.wsgi_request.META
        assert "REMOTE_ADDR" not in response.wsgi_request.META
    assert lookup(client, peer="192.0.2.8", HTTP_X_REAL_IP=PEER).status_code == 429
    assert lookup(client, peer="192.0.2.8", HTTP_X_REAL_IP="198.51.100.19").status_code == 200


@pytest.mark.parametrize("peer,header", [("192.0.2.9", PEER), ("192.0.2.8", ""),
    ("192.0.2.8", "198.51.100.18, 203.0.113.1"), ("192.0.2.8", "example.test"),
    ("192.0.2.8", "fe80::1%eth0")])
def test_proxy_mode_refuses_untrusted_peer_or_nonliteral_source(backend, settings, client, peer, header):
    settings.SCMS_HTTPS_MODE = "proxy"
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.ANONYMOUS_TRACKING_TRUSTED_PROXY_CIDRS = ["192.0.2.8/32"]
    assert lookup(client, peer=peer, HTTP_X_REAL_IP=header).status_code == 503
    assert backend[0].keys("scms:b13:source:*") == []


def test_direct_mode_ignores_forged_real_ip_header(backend, client):
    for index in range(10):
        assert lookup(client, HTTP_X_REAL_IP=f"203.0.113.{index+1}").status_code == 200
    assert lookup(client, HTTP_X_REAL_IP="203.0.113.99").status_code == 429


@pytest.mark.parametrize("setting,value", [("SCMS_HTTPS_MODE", ""),
    ("SECURE_SSL_REDIRECT", False), ("SESSION_COOKIE_SECURE", False),
    ("CSRF_COOKIE_SECURE", False)])
def test_tracking_requires_https_release_configuration(backend, settings, client, setting, value):
    setattr(settings, setting, value)
    assert [error.id for error in check_tracking_privacy(None)] == ["complaints.E003"]
    assert lookup(client).status_code == 503
    assert backend[0].keys("scms:b13:source:*") == []


@pytest.mark.parametrize("networks", [[], ["invalid"], ["0.0.0.0/0"], ["::/0"], "192.0.2.8/32"])
def test_proxy_mode_requires_explicit_restricted_ingress_networks(backend, settings, networks):
    settings.SCMS_HTTPS_MODE = "proxy"
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.ANONYMOUS_TRACKING_TRUSTED_PROXY_CIDRS = networks
    assert [error.id for error in check_tracking_privacy(None)] == ["complaints.E003"]


@pytest.mark.parametrize("attribute", ["session", "user", "_cached_user"])
def test_preloaded_identity_cannot_consume_tracking_allowance(backend, attribute):
    request = RequestFactory().post("/complaints/track/", secure=True, REMOTE_ADDR=PEER)
    setattr(request, attribute, {} if attribute == "session" else AnonymousUser())
    response = AnonymousPrivacyMiddleware(tracking_views.track_reference)(request)
    assert response.status_code == 503 and not request.anonymous_privacy_isolated
    assert backend[0].keys("scms:b13:source:*") == []


def test_restart_quarantine_does_not_repeat_cached_configuration_calls(backend):
    backend[0].delete(limits.EPOCH_KEY)
    for _ in range(2):
        with pytest.raises(limits.TrackingUnavailable):
            limits.consume_attempt(PEER)
    assert backend[0].config_get.call_count == 6 and backend[0].info.call_count == 3
    assert backend[0].keys("scms:b13:source:*") == []


@pytest.mark.parametrize("version", ["6.2.14", "", "unknown"])
def test_backend_requires_redis_7_flagged_script_support(backend, version):
    backend[2]["server"]["redis_version"] = version
    with pytest.raises(limits.TrackingUnavailable):
        limits.consume_attempt(PEER)
    assert not backend[0].keys("scms:b13:source:*")
