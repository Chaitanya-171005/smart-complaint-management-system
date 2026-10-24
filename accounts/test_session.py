import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()
LOGIN = "/accounts/login/"
LOGOUT = "/accounts/logout/"
HOME = "/accounts/landing/complainant/"
PASSWORD = "Campus123"
# Based on the real clock: sessions are also checked against real time outside at().
T0 = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture(autouse=True)
def fast_hasher(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@contextmanager
def at(moment):
    with mock.patch("django.utils.timezone.now", return_value=moment):
        yield


@pytest.fixture
def user(db):
    return User.objects.create_user(email="asha@pes.edu", password=PASSWORD, full_name="Asha")


def signed_in_client():
    c = Client()
    r = c.post(LOGIN, {"email": "asha@pes.edu", "password": PASSWORD})
    assert r.status_code == 302
    return c


def is_logged_in(client):
    return "_auth_user_id" in client.session


def needs_login(response):
    return response.status_code == 302 and response.url.startswith(LOGIN)


# --- logout -------------------------------------------------------------------


@pytest.mark.django_db
def test_logout_invalidates_session_and_requires_new_login(user):
    c = signed_in_client()
    assert c.get(HOME).status_code == 200
    r = c.post(LOGOUT)
    assert r.status_code == 302 and r.url == LOGIN
    assert not is_logged_in(c)
    assert needs_login(c.get(HOME))


@pytest.mark.django_db
def test_old_session_cookie_cannot_be_reused_after_logout(user):
    c = signed_in_client()
    old_cookie = c.cookies["sessionid"].value
    c.post(LOGOUT)
    thief = Client()
    thief.cookies["sessionid"] = old_cookie
    assert needs_login(thief.get(HOME))


@pytest.mark.django_db
def test_can_log_in_again_after_logout(user):
    c = signed_in_client()
    c.post(LOGOUT)
    assert c.post(LOGIN, {"email": "asha@pes.edu", "password": PASSWORD}).status_code == 302
    assert c.get(HOME).status_code == 200


@pytest.mark.django_db
def test_logout_does_not_work_on_get(user):
    c = signed_in_client()
    assert c.get(LOGOUT).status_code == 405
    assert is_logged_in(c)


@pytest.mark.django_db
def test_logout_requires_csrf_token(user):
    c = Client(enforce_csrf_checks=True)
    # Sign in the normal way, then try a logout without a CSRF token.
    plain = signed_in_client()
    c.cookies["sessionid"] = plain.cookies["sessionid"].value
    assert c.post(LOGOUT).status_code == 403
    assert needs_login(Client().get(HOME)) and plain.get(HOME).status_code == 200


@pytest.mark.django_db
def test_logout_when_not_signed_in_is_harmless():
    r = Client().post(LOGOUT)
    assert r.status_code == 302 and r.url == LOGIN


@pytest.mark.django_db
def test_landing_page_has_a_post_logout_form_with_csrf(user):
    c = signed_in_client()
    html = c.get(HOME).content.decode()
    assert f'action="{LOGOUT}"' in html and 'method="post"' in html
    assert "csrfmiddlewaretoken" in html


# --- idle expiry --------------------------------------------------------------


@pytest.mark.django_db
def test_idle_timeout_defaults_to_30_minutes(settings):
    assert settings.SESSION_IDLE_TIMEOUT_MINUTES == 30
    assert settings.SESSION_COOKIE_AGE == 30 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST is True


@pytest.mark.django_db
def test_session_is_valid_just_before_the_idle_boundary(user):
    with at(T0):
        c = signed_in_client()
    with at(T0 + timedelta(minutes=29, seconds=59)):
        assert c.get(HOME).status_code == 200


@pytest.mark.django_db
def test_session_expires_at_the_idle_boundary(user):
    with at(T0):
        c = signed_in_client()
    with at(T0 + timedelta(minutes=30)):
        assert needs_login(c.get(HOME))
        assert not is_logged_in(c)


@pytest.mark.django_db
def test_session_expired_well_after_the_boundary(user):
    with at(T0):
        c = signed_in_client()
    with at(T0 + timedelta(hours=3)):
        assert needs_login(c.get(HOME))


@pytest.mark.django_db
def test_activity_before_expiry_extends_the_session(user):
    with at(T0):
        c = signed_in_client()
    with at(T0 + timedelta(minutes=20)):
        assert c.get(HOME).status_code == 200
    with at(T0 + timedelta(minutes=45)):  # 25 min idle, 45 min since login
        assert c.get(HOME).status_code == 200
    with at(T0 + timedelta(minutes=75)):  # 30 min idle again
        assert needs_login(c.get(HOME))


@pytest.mark.django_db
def test_idle_timeout_is_configurable(user, settings):
    settings.SESSION_COOKIE_AGE = 5 * 60
    with at(T0):
        c = signed_in_client()
    with at(T0 + timedelta(minutes=4, seconds=59)):
        assert c.get(HOME).status_code == 200
    with at(T0 + timedelta(minutes=10)):
        assert needs_login(c.get(HOME))


@pytest.mark.django_db
def test_expired_session_cannot_do_protected_actions_or_reuse_old_cookie(user):
    with at(T0):
        c = signed_in_client()
        old_cookie = c.cookies["sessionid"].value
    with at(T0 + timedelta(minutes=31)):
        for path in (HOME, "/accounts/home/", "/accounts/landing/admin/"):
            assert needs_login(c.get(path))
        stale = Client()
        stale.cookies["sessionid"] = old_cookie
        assert needs_login(stale.get(HOME))


@pytest.mark.django_db
def test_login_works_again_after_expiry(user):
    with at(T0):
        c = signed_in_client()
    with at(T0 + timedelta(minutes=31)):
        assert needs_login(c.get(HOME))
        assert c.post(LOGIN, {"email": "asha@pes.edu", "password": PASSWORD}).status_code == 302
        assert c.get(HOME).status_code == 200


@pytest.mark.django_db
def test_expiry_handling_does_not_expose_session_secrets(user, caplog):
    with at(T0):
        c = signed_in_client()
        key = c.cookies["sessionid"].value
    with caplog.at_level(logging.DEBUG), at(T0 + timedelta(minutes=31)):
        r = c.get(HOME)
        follow = c.get(r.url)
    assert key not in r.url
    assert key.encode() not in r.content and key.encode() not in follow.content
    assert key not in caplog.text
    assert key not in str(r.headers.get("Location", ""))


@pytest.mark.django_db
def test_session_cookie_is_httponly_and_samesite(user):
    c = signed_in_client()
    cookie = c.cookies["sessionid"]
    assert cookie["httponly"]
    assert cookie["samesite"] == "Lax"
