"""Real Chromium submission checks; run explicitly, never skip missing browsers.

The disposable loopback TLS proxy exercises the actual Django live server and
secure cookies/CSRF. Its test-only gate overrides are not deployment approval.
"""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import threading
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from complaints.models import AnonymousIntakeReceipt, Complaint, IntakeReceipt

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(scope="session")
def chromium():
    with sync_playwright() as runtime:
        options = {"headless": True}
        if os.environ.get("SCMS_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["SCMS_CHROMIUM_EXECUTABLE"]
        browser = runtime.chromium.launch(**options)
        if os.environ.get("SCMS_BROWSER_EVIDENCE_DIR"):
            folder = Path(os.environ["SCMS_BROWSER_EVIDENCE_DIR"])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "browser.json").write_text(json.dumps({
                "engine": "Chromium", "version": browser.version,
                "viewport": {"width": 320, "height": 740},
                "scope": "synthetic loopback TLS; not deployed acceptance",
            }, indent=2) + "\n")
        yield browser
        browser.close()


@pytest.fixture(scope="session")
def tls_context(tmp_path_factory):
    folder = tmp_path_factory.mktemp("synthetic-browser-tls")
    openssl = shutil.which("openssl")
    assert openssl, "Install openssl to create the disposable loopback certificate."
    subprocess.run([
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(folder / "key.pem"), "-out", str(folder / "cert.pem"),
        "-days", "1", "-subj", "/CN=localhost",
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(folder / "cert.pem", folder / "key.pem")
    return context


@pytest.fixture
def browser_site(settings, routing_configuration, complainant_user, live_server,
                 tls_context, tmp_path):
    # Keep reference labels short: this test isolates description validation,
    # rather than claiming acceptance of every possible campus label/layout.
    category, location = routing_configuration["category"], routing_configuration["location"]
    category.name = "Synthetic lights"
    category.save(update_fields=["name"])
    location.block, location.floor, location.room_area = "Test", "1", "Room"
    location.save(update_fields=["block", "floor", "room_area"])
    settings.DEBUG = False
    settings.COMPLAINT_INTAKE_ENABLED = True
    settings.COMPLAINT_EMERGENCY_NOTICE = "SYNTHETIC browser regression only."
    settings.ANONYMOUS_INTAKE_ENABLED = True
    settings.ANONYMOUS_PRIVACY_READY = True
    settings.ANONYMOUS_TRANSPORT_VERIFIED = True
    settings.SCMS_HTTPS_MODE = "proxy"
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_HSTS_SECONDS = 300
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    settings.CSRF_USE_SESSIONS = False
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private"
    upstream = urlsplit(live_server.url)

    class Proxy(BaseHTTPRequestHandler):
        def forward(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in {"connection", "transfer-encoding"}}
            headers["X-Forwarded-Proto"] = "https"
            connection = http.client.HTTPConnection(upstream.hostname, upstream.port, timeout=15)
            try:
                connection.request(self.command, self.path, body, headers)
                response = connection.getresponse()
                payload = response.read()
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in {"connection", "transfer-encoding", "content-length"}:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            finally:
                connection.close()

        do_GET = forward
        do_POST = forward

        def log_message(self, *args):
            pass  # Synthetic credentials and one-response references stay private.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    origin = f"https://localhost:{server.server_port}"
    settings.CSRF_TRUSTED_ORIGINS = [origin]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield origin, routing_configuration, complainant_user
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.mark.parametrize("anonymous", [False, True], ids=["authenticated", "anonymous"])
@pytest.mark.parametrize("description", [
    "Bad", "x" * 19 + "\u200b", "x" * 19 + "\u0301", "  " + "x" * 19 + "  ",
], ids=["short", "invisible-padding", "combining-padding", "outer-whitespace"])
def test_normal_submit_shows_accessible_inline_error_at_320(
        chromium, browser_site, anonymous, description):
    origin, config, user = browser_site
    context = chromium.new_context(ignore_https_errors=True, viewport={"width": 320, "height": 740})
    try:
        page = context.new_page()
        if not anonymous:
            page.goto(origin + "/accounts/login/")
            page.get_by_label("Email").fill(user.email)
            page.get_by_label("Password").fill("SyntheticTest123!")
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(page).to_have_url(origin + "/accounts/landing/complainant/")
        path = "/anonymous/new/" if anonymous else "/complaints/new/"
        assert page.goto(origin + path).status == 200
        page.locator("#id_category").select_option(str(config["category"].pk))
        page.locator("#id_location").select_option(config["location"].code)
        page.get_by_label("Title").fill("Synthetic browser complaint")
        field = page.get_by_label("Description")
        field.fill(description)
        token = page.locator('[name="request_token"]').input_value()
        assert field.evaluate("el => el.validity.valid"), "Native validation must allow this POST."
        button = page.get_by_role("button", name="Submit anonymously" if anonymous else "Submit complaint", exact=True)
        with page.expect_response(lambda r: r.request.method == "POST" and urlsplit(r.url).path == path) as pending:
            button.click()
        assert pending.value.status == 400
        error = page.locator("#id_description_error")
        expect(error.locator("li")).to_have_count(1)
        expect(error).to_contain_text("Enter at least 20 characters")
        expect(field).to_have_attribute("aria-invalid", "true")
        described_by = field.get_attribute("aria-describedby").split()
        assert {"id_description_error", "id_description_helptext"}.issubset(described_by)
        for target in (field, error):
            target.scroll_into_view_if_needed()
            expect(target).to_be_visible()
            box = target.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= 320
        assert page.evaluate("document.documentElement.scrollWidth") == 320
        assert page.locator('[name="request_token"]').input_value() == token
        assert page.get_by_label("Title").input_value() == "Synthetic browser complaint"
        assert Complaint.objects.count() == IntakeReceipt.objects.count() == AnonymousIntakeReceipt.objects.count() == 0
        expect(page.locator("#id_description_helptext")).to_contain_text("Interior spaces count")
        if description == "Bad" and os.environ.get("SCMS_BROWSER_EVIDENCE_DIR"):
            folder = Path(os.environ["SCMS_BROWSER_EVIDENCE_DIR"])
            folder.mkdir(parents=True, exist_ok=True)
            field.scroll_into_view_if_needed()
            page.screenshot(path=str(folder / ("anonymous-320.png" if anonymous else "authenticated-320.png")), full_page=True)
        # Exactly 20 characters, including an interior Unicode space; outer
        # whitespace is stripped. Real CSRF and the same request token are used.
        corrected = "\u0905" * 9 + "\u00a0" + "\u0915" * 10
        field.fill("  " + corrected + "  ")
        with page.expect_response(lambda r: r.request.method == "POST" and urlsplit(r.url).path == path) as pending:
            button.click()
        assert pending.value.status == (200 if anonymous else 303)
        expect(page.get_by_role("heading", level=1)).to_have_text(
            "Anonymous complaint accepted" if anonymous else "Your complaint was submitted")
        complaint = Complaint.objects.get()
        assert complaint.description == corrected
        assert complaint.submitted_by_id == (None if anonymous else user.pk)
        assert (AnonymousIntakeReceipt.objects.count(), IntakeReceipt.objects.count()) == (
            (1, 0) if anonymous else (0, 1))
    finally:
        context.close()
