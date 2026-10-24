import logging
import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from accounts.models import LoginThrottle, SecurityEvent

User = get_user_model()
LOGIN = "/accounts/login/"
PASSWORD = "Campus123"
GENERIC = "Invalid email or password."
LOCKED = "Too many failed sign-in attempts"
T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fast_hasher(settings):
    # Salted but cheap, so the many logins in these tests run quickly.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@contextmanager
def at(moment):
    with mock.patch("django.utils.timezone.now", return_value=moment):
        yield


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="asha@pes.edu", password=PASSWORD, full_name="Asha")


def post(client, email="asha@pes.edu", password=PASSWORD, **extra):
    return client.post(LOGIN, {"email": email, "password": password}, **extra)


def fail(client, n, email="asha@pes.edu"):
    return [post(client, email, "WrongPass1") for _ in range(n)]


def logged_in(client):
    return "_auth_user_id" in client.session


# --- success and role landing -------------------------------------------------


@pytest.mark.django_db
def test_login_page_renders(client):
    r = client.get(LOGIN)
    assert r.status_code == 200
    assert b"csrfmiddlewaretoken" in r.content


@pytest.mark.django_db
def test_valid_login_creates_session_and_lands_on_role_page(client, user):
    r = post(client)
    assert r.status_code == 302 and r.url == "/accounts/landing/complainant/"
    assert logged_in(client)
    assert client.get(r.url).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role,url",
    [
        ("COMPLAINANT", "/accounts/landing/complainant/"),
        ("STAFF", "/accounts/landing/staff/"),
        ("HEAD", "/accounts/landing/head/"),
        ("ADMIN", "/accounts/landing/admin/"),
    ],
)
def test_each_role_lands_on_its_own_page(client, role, url):
    User.objects.create_user(email="r@pes.edu", password=PASSWORD, full_name="R", role=role)
    r = post(client, "r@pes.edu")
    assert r.url == url
    assert client.get(url).status_code == 200


@pytest.mark.django_db
def test_landing_uses_current_role(client, user):
    post(client)
    c2 = Client()  # no logout yet (B03), so log in again from a fresh client
    User.objects.filter(pk=user.pk).update(role="ADMIN")
    assert post(c2).url == "/accounts/landing/admin/"


@pytest.mark.django_db
def test_wrong_role_landing_redirects_to_own_page(client, user):
    post(client)
    r = client.get("/accounts/landing/admin/")
    assert r.status_code == 302 and r.url == "/accounts/landing/complainant/"


@pytest.mark.django_db
def test_landing_requires_login(client):
    r = client.get("/accounts/landing/complainant/")
    assert r.status_code == 302 and r.url.startswith("/accounts/login/")
    assert client.get("/accounts/home/").status_code == 302


@pytest.mark.django_db
def test_email_login_is_case_insensitive(client, user):
    assert post(client, "ASHA@PES.EDU").status_code == 302
    assert logged_in(client)


@pytest.mark.django_db
def test_authenticated_user_visiting_login_is_redirected(client, user):
    post(client)
    assert client.get(LOGIN).status_code == 302


@pytest.mark.django_db
def test_next_parameter_is_ignored(client, user):
    r = post(client, QUERY_STRING="next=https://evil.example/")
    assert r.url == "/accounts/landing/complainant/"


# --- generic failures ---------------------------------------------------------


@pytest.mark.django_db
def test_wrong_password_and_unknown_email_look_identical(client, user):
    wrong = post(client, password="WrongPass1")
    c2 = Client()
    unknown = post(c2, "nobody@pes.edu", "WrongPass1")
    assert wrong.status_code == unknown.status_code == 200
    assert GENERIC.encode() in wrong.content and GENERIC.encode() in unknown.content
    assert not logged_in(client) and not logged_in(c2)


@pytest.mark.django_db
def test_inactive_user_cannot_log_in(client, user):
    User.objects.filter(pk=user.pk).update(is_active=False)
    r = post(client)
    assert r.status_code == 200 and GENERIC.encode() in r.content
    assert not logged_in(client)


@pytest.mark.django_db
def test_missing_fields_give_generic_error(client):
    r = client.post(LOGIN, {"email": "asha@pes.edu"})
    assert r.status_code == 200 and GENERIC.encode() in r.content


@pytest.mark.django_db
def test_csrf_enforced_on_login(user):
    c = Client(enforce_csrf_checks=True)
    assert post(c).status_code == 403
    assert not logged_in(c)


# --- lockout ------------------------------------------------------------------


@pytest.mark.django_db
def test_fifth_failure_locks_and_correct_password_is_then_refused(client, user):
    with at(T0):
        results = fail(client, 5)
        assert all(GENERIC.encode() in r.content for r in results[:4])
        assert LOCKED.encode() in results[4].content
        r = post(client)  # correct password during lockout
    assert r.status_code == 200 and LOCKED.encode() in r.content
    assert not logged_in(client)


@pytest.mark.django_db
def test_four_failures_do_not_lock(client, user):
    with at(T0):
        fail(client, 4)
        r = post(client)
    assert r.status_code == 302 and logged_in(client)


@pytest.mark.django_db
def test_success_resets_the_failure_count(client, user):
    with at(T0):
        fail(client, 4)
        post(client)
        assert not LoginThrottle.objects.filter(email="asha@pes.edu").exists()
    c2 = Client()
    with at(T0 + timedelta(minutes=1)):
        results = fail(c2, 4)
        assert all(GENERIC.encode() in r.content for r in results)
        assert post(c2).status_code == 302


@pytest.mark.django_db
def test_lockout_expires_after_default_15_minutes(client, user):
    with at(T0):
        fail(client, 5)
    with at(T0 + timedelta(minutes=14, seconds=59)):
        assert LOCKED.encode() in post(client).content
        assert not logged_in(client)
    with at(T0 + timedelta(minutes=15)):
        r = post(client)
    assert r.status_code == 302 and logged_in(client)


@pytest.mark.django_db
def test_failures_outside_the_window_do_not_accumulate(client, user):
    with at(T0):
        fail(client, 4)
    with at(T0 + timedelta(minutes=16)):
        r = fail(client, 1)[0]
        assert GENERIC.encode() in r.content
        assert post(client).status_code == 302


@pytest.mark.django_db
def test_failures_inside_the_window_accumulate(client, user):
    with at(T0):
        fail(client, 3)
    with at(T0 + timedelta(minutes=14)):
        results = fail(client, 2)
    assert LOCKED.encode() in results[1].content


@pytest.mark.django_db
def test_lockout_duration_is_configurable(client, user, settings):
    settings.LOGIN_LOCKOUT_MINUTES = 2
    with at(T0):
        fail(client, 5)
    with at(T0 + timedelta(minutes=1)):
        assert LOCKED.encode() in post(client).content
    with at(T0 + timedelta(minutes=2)):
        assert post(client).status_code == 302


@pytest.mark.django_db
def test_threshold_and_window_are_configurable(client, user, settings):
    settings.LOGIN_MAX_FAILURES = 3
    with at(T0):
        results = fail(client, 3)
    assert LOCKED.encode() in results[2].content


@pytest.mark.django_db
def test_lockout_for_unknown_email_looks_the_same(client, user):
    c2 = Client()
    with at(T0):
        known = fail(client, 5)[4]
        unknown = fail(c2, 5, email="ghost@pes.edu")[4]
        known_after = post(client)
        unknown_after = post(c2, "ghost@pes.edu")
    assert LOCKED.encode() in known.content and LOCKED.encode() in unknown.content
    err = lambda b: re.search(rb'<p class="error"[^>]*>(.*?)</p>', b).group(1)
    assert err(known_after.content) == err(unknown_after.content)
    assert known_after.status_code == unknown_after.status_code


@pytest.mark.django_db
def test_lockout_is_per_account(client, user):
    other = User.objects.create_user(email="b@pes.edu", password=PASSWORD, full_name="B")
    with at(T0):
        fail(client, 5)
        c2 = Client()
        assert post(c2, other.email).status_code == 302


# --- security events and secrets ---------------------------------------------


@pytest.mark.django_db
def test_auth_events_are_recorded(client, user):
    with at(T0):
        fail(client, 5)
        post(client)  # blocked
    types = list(SecurityEvent.objects.order_by("id").values_list("event_type", flat=True))
    assert types.count("LOGIN_FAILURE") == 5
    assert types.count("LOGIN_LOCKOUT") == 1
    assert types.count("LOGIN_BLOCKED") == 1
    with at(T0 + timedelta(minutes=15)):
        post(client)
    ok = SecurityEvent.objects.get(event_type="LOGIN_SUCCESS")
    assert ok.user_id == user.pk and ok.identifier == "asha@pes.edu"


@pytest.mark.django_db
def test_no_password_or_session_secret_in_events_responses_or_logs(client, user, caplog):
    with caplog.at_level(logging.DEBUG):
        bad = post(client, password="Secret99x")
        ok = post(client, password=PASSWORD)
    for body in (bad.content, ok.content):
        assert b"Secret99x" not in body and PASSWORD.encode() not in body
    dump = " ".join(
        f"{e.event_type} {e.identifier} {e.detail}" for e in SecurityEvent.objects.all()
    )
    session_key = client.session.session_key
    for text in (dump, caplog.text):
        assert "Secret99x" not in text and PASSWORD not in text
        assert session_key not in text


# --- concurrent login vs lockout (race fix) -------------------------------------


@pytest.mark.django_db
def test_lockout_started_after_the_check_is_not_erased_by_a_successful_login(client, user):
    """Request A passes the is_locked() check, then request B's failures lock the
    account, then A's correct password succeeds. A must not erase B's lockout."""
    from accounts import services

    real_authenticate = services.authenticate

    def authenticate_while_other_request_locks(*args, **kwargs):
        # Interleaving: after A's is_locked() check and before A's success path,
        # another request records enough failures to start the lockout.
        for _ in range(5):
            services.register_failure("asha@pes.edu", services.timezone.now())
        return real_authenticate(*args, **kwargs)

    with at(T0):
        with mock.patch.object(services, "authenticate", authenticate_while_other_request_locks):
            r = post(client)  # correct password
        assert LOCKED in r.content.decode()
        assert not logged_in(client)
        assert LoginThrottle.objects.get(email="asha@pes.edu").locked_until > T0
        # The lockout still holds on the next request, even with the right password.
        r2 = post(client)
        assert LOCKED in r2.content.decode() and not logged_in(client)
    assert not SecurityEvent.objects.filter(event_type=SecurityEvent.EventType.LOGIN_SUCCESS).exists()
    assert SecurityEvent.objects.filter(event_type=SecurityEvent.EventType.LOGIN_BLOCKED).exists()


@pytest.mark.django_db
def test_successful_login_still_clears_earlier_failures(client, user):
    with at(T0):
        fail(client, 3)
        assert LoginThrottle.objects.get(email="asha@pes.edu").failure_count == 3
        assert post(client).status_code == 302 and logged_in(client)
        assert not LoginThrottle.objects.filter(email="asha@pes.edu").exists()


@pytest.mark.django_db
def test_clear_failures_keeps_an_active_lockout_and_removes_an_expired_one(user):
    from accounts import services

    LoginThrottle.objects.create(
        email="asha@pes.edu", locked_until=T0 + timedelta(minutes=5)
    )
    assert services.clear_failures("asha@pes.edu", T0) is False
    assert LoginThrottle.objects.filter(email="asha@pes.edu").exists()
    assert services.clear_failures("asha@pes.edu", T0 + timedelta(minutes=6)) is True
    assert not LoginThrottle.objects.filter(email="asha@pes.edu").exists()


@pytest.mark.django_db
def test_failure_during_an_active_lockout_does_not_change_it(user):
    from accounts import services

    until = T0 + timedelta(minutes=10)
    LoginThrottle.objects.create(email="asha@pes.edu", locked_until=until, failure_count=0)
    assert services.register_failure("asha@pes.edu", T0) is False
    t = LoginThrottle.objects.get(email="asha@pes.edu")
    assert t.locked_until == until and t.failure_count == 0
