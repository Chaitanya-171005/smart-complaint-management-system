"""Q01 cross-module security checks (REQ-SEC-01/02/03/05/06, BR-03; TC-02, TC-04, TC-05, TC-13, VM-02).

These checks walk the real URL configuration, so a route added later by any module is covered
without editing this file:

* A route that answers a signed-out GET with 200 must be on PUBLIC_ROUTES, a reviewed list. A new
  public page therefore fails here until someone decides it is meant to be public.
* Every route refuses a POST that has no CSRF token, and no view is csrf_exempt.
* Administrator-only screens refuse every other role on the server, whatever the UI shows.
* Application code and templates contain no unescaped output or raw SQL, except reviewed entries.
* SCMS roles cannot reach the Django admin site.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import get_resolver

pytestmark = pytest.mark.django_db

# Reviewed public routes: sign-in/registration pages and anonymous complaint intake. Anything else that
# a signed-out visitor can open is a defect or a conscious change to this list.
PUBLIC_ROUTES = {
    "register", "register_done", "login", "logout", "home", "anonymous_submit",
}
# Route names that exist only to be reached by one role and must refuse the others.
ADMIN_ONLY_PREFIX = "admin_"
ADMIN_ONLY_NAMES = {"configuration"}
HEAD_ONLY_NAMES = {"assign_complaint"}

APP_ROOT = Path(settings.BASE_DIR)
# Reviewed exceptions to the unsafe-pattern scan: (relative path, pattern). Keep this list short.
UNSAFE_ALLOWED = set()
UNSAFE_PATTERNS = {
    "mark_safe": re.compile(r"\bmark_safe\b"),
    "|safe filter": re.compile(r"\|\s*safe\b"),
    "autoescape off": re.compile(r"autoescape\s+off"),
    "raw SQL (.raw)": re.compile(r"\.raw\("),
    "raw SQL (.extra)": re.compile(r"\.extra\("),
    "raw SQL (RawSQL)": re.compile(r"\bRawSQL\b"),
    "raw SQL (cursor)": re.compile(r"\bconnection\.cursor\(|\bconnections\[[^\]]+\]\.cursor\("),
    "csrf_exempt": re.compile(r"\bcsrf_exempt\b"),
}


def _routes():
    """(route text, URL pattern) for every plain route outside the Django admin site."""

    def walk(patterns, prefix=""):
        for pattern in patterns:
            text = prefix + str(pattern.pattern)
            if hasattr(pattern, "url_patterns"):
                yield from walk(pattern.url_patterns, text)
            else:
                yield text, pattern

    for text, pattern in walk(get_resolver().url_patterns):
        if text.startswith("admin/") or "(?P" in text or text.startswith("^"):
            continue
        yield text, pattern


def _path(route):
    route = re.sub(r"<int:[^>]+>", "1", route)
    route = re.sub(r"<(?:str|path|slug):[^>]+>", "SCMS-2026-000001", route)
    return "/" + route


ROUTES = sorted(_routes(), key=lambda item: item[0])
IDS = [route for route, _ in ROUTES]


def test_the_route_walk_finds_the_application_routes():
    assert len(ROUTES) >= 25
    names = {pattern.name for _, pattern in ROUTES}
    assert {"login", "admin_audit", "queue", "download_evidence"} <= names


# --- authentication (REQ-SEC-01/02) ---------------------------------------------------------------


@pytest.mark.parametrize("route, pattern", ROUTES, ids=IDS)
def test_signed_out_visitors_only_reach_reviewed_public_routes(route, pattern):
    response = Client().get(_path(route))
    if pattern.name in PUBLIC_ROUTES:
        return
    assert response.status_code != 200, f"{route} answered a signed-out GET; add it to PUBLIC_ROUTES if intended"
    if response.status_code == 302:
        assert "login" in response["Location"], f"{route} redirected somewhere other than sign-in"


# --- CSRF (REQ-SEC-03) ----------------------------------------------------------------------------


def test_csrf_middleware_is_enabled():
    assert "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE


@pytest.mark.parametrize("route, pattern", ROUTES, ids=IDS)
def test_no_view_is_csrf_exempt(route, pattern):
    assert not getattr(pattern.callback, "csrf_exempt", False), f"{route} is csrf_exempt"


@pytest.mark.parametrize("route, pattern", ROUTES, ids=IDS)
def test_post_without_a_csrf_token_is_refused_signed_out_and_signed_in(route, pattern, scms_admin_user):
    signed_out = Client(enforce_csrf_checks=True)
    signed_in = Client(enforce_csrf_checks=True)
    signed_in.force_login(scms_admin_user)
    for client in (signed_out, signed_in):
        assert client.post(_path(route), {"active": "false", "role": "ADMIN"}).status_code == 403


# --- server-side authorization (REQ-SEC-02, BR-03) -------------------------------------------------


def _names(predicate):
    return [(route, pattern) for route, pattern in ROUTES if pattern.name and predicate(pattern.name)]


ADMIN_ROUTES = _names(lambda name: name.startswith(ADMIN_ONLY_PREFIX) or name in ADMIN_ONLY_NAMES)
HEAD_ROUTES = _names(lambda name: name in HEAD_ONLY_NAMES)


def test_the_authorization_lists_match_real_routes():
    assert len(ADMIN_ROUTES) >= 10
    assert {pattern.name for _, pattern in HEAD_ROUTES} == HEAD_ONLY_NAMES


@pytest.mark.parametrize("route, pattern", ADMIN_ROUTES, ids=[r for r, _ in ADMIN_ROUTES])
@pytest.mark.parametrize("fixture", ["complainant_user", "staff_user", "head_user"])
def test_administrator_screens_refuse_every_other_role_on_get_and_post(request, fixture, route, pattern):
    client = Client()
    client.force_login(request.getfixturevalue(fixture))
    assert client.get(_path(route)).status_code in (403, 404)
    assert client.post(_path(route), {"active": "false"}).status_code in (403, 404, 405)


@pytest.mark.parametrize("route, pattern", HEAD_ROUTES, ids=[r for r, _ in HEAD_ROUTES])
@pytest.mark.parametrize("fixture", ["complainant_user", "staff_user", "scms_admin_user"])
def test_head_only_actions_refuse_other_roles(request, fixture, route, pattern):
    client = Client()
    client.force_login(request.getfixturevalue(fixture))
    assert client.post(_path(route), {"assignee": "1"}).status_code in (403, 404, 405)


@pytest.mark.parametrize("fixture", ["complainant_user", "staff_user", "head_user", "scms_admin_user"])
def test_scms_roles_cannot_use_the_django_admin_site(request, fixture):
    """No SCMS role is Django staff, so the admin site cannot widen what the SRS allows."""
    user = request.getfixturevalue(fixture)
    assert user.is_staff is False and user.is_superuser is False
    client = Client()
    client.force_login(user)
    response = client.get("/admin/workflow/complainthistory/")
    assert response.status_code == 302 and "/admin/login/" in response["Location"]


def test_modified_object_ids_do_not_reveal_other_users_files(complainant_user, user_factory, complaint_factory):
    """Direct evidence URL with someone else's id behaves like a missing file (REQ-SEC-02)."""
    from complaints.models import Attachment

    other = user_factory()
    complaint = complaint_factory(submitted_by=other)
    attachment = Attachment.objects.create(
        complaint=complaint, storage_name="a" * 32 + ".pdf", original_name="x.pdf", content_type="application/pdf",
        size=1, sha256="0" * 64, stage=Attachment.Stage.INTAKE, uploaded_by=other,
    )
    client = Client()
    client.force_login(complainant_user)
    assert client.get(f"/complaints/evidence/{attachment.pk}/").status_code == 404
    assert client.get("/complaints/evidence/999999/").status_code == 404


# --- output escaping, ORM use and anonymous privacy (REQ-SEC-05/06) ----------------------------------

SKIPPED_PARTS = {"migrations", "scripts", "integration_checks", "docs", "build", "node_modules", ".git"}


def _source_files():
    for path in APP_ROOT.rglob("*"):
        relative = path.relative_to(APP_ROOT)
        if (path.suffix not in {".py", ".html", ".txt"} or SKIPPED_PARTS & set(relative.parts)
                or path.name.startswith("test_") or path.name in {"tests.py", "conftest.py"}):
            continue
        yield relative, path


def test_application_code_has_no_unescaped_output_raw_sql_or_csrf_exemptions():
    found = []
    for relative, path in _source_files():
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in UNSAFE_PATTERNS.items():
            if pattern.search(text) and (str(relative), label) not in UNSAFE_ALLOWED:
                found.append(f"{relative}: {label}")
    assert not found, "Review these, then fix them or list them in UNSAFE_ALLOWED with a reason: " + "; ".join(found)


def test_unsafe_scan_actually_detects_a_violation():
    sample = "from django.utils.safestring import mark_safe\nx = mark_safe(user_text)\n"
    assert any(pattern.search(sample) for pattern in UNSAFE_PATTERNS.values())


def test_session_cookie_is_not_readable_by_scripts():
    assert settings.SESSION_COOKIE_HTTPONLY is True
