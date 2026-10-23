import logging
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounts import services

User = get_user_model()
URL = "/accounts/register/"


def valid(**over):
    data = {
        "full_name": "Asha Rao",
        "email": "asha@pes.edu",
        "password": "Campus123",
        "user_type": "STUDENT",
    }
    data.update(over)
    return data


@pytest.fixture
def client():
    return Client()


@pytest.mark.django_db
def test_form_renders(client):
    r = client.get(URL)
    assert r.status_code == 200
    assert b"csrfmiddlewaretoken" in r.content


@pytest.mark.django_db
def test_valid_registration_creates_complainant(client):
    r = client.post(URL, valid())
    assert r.status_code == 302
    assert r.url == reverse("accounts:register_done")
    u = User.objects.get(email="asha@pes.edu")
    assert u.role == "COMPLAINANT"
    assert u.full_name == "Asha Rao"
    assert u.department is None


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["ADMIN", "HEAD", "STAFF", "admin"])
def test_role_injection_ignored(client, role):
    client.post(URL, valid(role=role, is_superuser="on", is_staff="on"))
    u = User.objects.get(email="asha@pes.edu")
    assert u.role == "COMPLAINANT"
    assert not u.is_superuser and not u.is_staff


@pytest.mark.django_db
def test_duplicate_email_gets_same_response_and_no_second_account(client):
    first = client.post(URL, valid())
    second = client.post(URL, valid(full_name="Someone Else", password="Another123"))
    assert (first.status_code, first.url) == (second.status_code, second.url)
    assert User.objects.count() == 1
    assert User.objects.get().full_name == "Asha Rao"  # original untouched
    page1 = client.get(first.url).content
    page2 = client.get(second.url).content
    assert page1 == page2


@pytest.mark.django_db
def test_duplicate_email_is_case_insensitive(client):
    client.post(URL, valid(email="Asha@PES.edu"))
    client.post(URL, valid(email="asha@pes.edu"))
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_concurrent_duplicate_handled_by_db_constraint():
    # Simulate the race: the pre-check sees no user, the insert then collides.
    User.objects.create_user(email="race@pes.edu", password="Campus123", full_name="First")
    with mock.patch.object(User.objects, "filter") as f:
        f.return_value.exists.return_value = False
        created = services.register_complainant(
            full_name="Second", email="race@pes.edu", password="Campus123", user_type="STUDENT"
        )
    assert created is False
    assert User.objects.filter(email="race@pes.edu").count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "password",
    ["Short1", "abcdefgh", "12345678", "", "abc 1"],
)
def test_bad_passwords_rejected_and_no_account(client, password):
    r = client.post(URL, valid(password=password))
    assert r.status_code == 200
    assert User.objects.count() == 0
    assert "password" in r.context["form"].errors


@pytest.mark.django_db
def test_eight_char_password_with_letter_and_digit_accepted(client):
    client.post(URL, valid(password="abcdefg1"))
    assert User.objects.filter(email="asha@pes.edu").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("missing", ["full_name", "email", "password", "user_type"])
def test_required_fields(client, missing):
    data = valid()
    data.pop(missing)
    r = client.post(URL, data)
    assert r.status_code == 200
    assert missing in r.context["form"].errors
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_invalid_email_and_user_type_rejected(client):
    assert client.post(URL, valid(email="not-an-email")).status_code == 200
    assert client.post(URL, valid(user_type="ALIEN")).status_code == 200
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_hostel_resident_requires_block_and_room(client):
    r = client.post(URL, valid(hostel_resident="on"))
    assert r.status_code == 200
    errors = r.context["form"].errors
    assert "hostel_block" in errors and "hostel_room" in errors
    assert User.objects.count() == 0

    client.post(URL, valid(hostel_resident="on", hostel_block="A", hostel_room="101"))
    u = User.objects.get()
    assert (u.hostel_block, u.hostel_room) == ("A", "101")


@pytest.mark.django_db
def test_non_resident_hostel_fields_not_stored(client):
    client.post(URL, valid(hostel_block="A", hostel_room="101"))
    u = User.objects.get()
    assert (u.hostel_block, u.hostel_room) == ("", "")


@pytest.mark.django_db
def test_password_stored_as_salted_hash_only(client):
    client.post(URL, valid())
    u = User.objects.get()
    assert u.password != "Campus123"
    assert u.password.startswith(("pbkdf2_sha256$", "argon2", "bcrypt", "scrypt"))
    assert "Campus123" not in u.password
    assert u.check_password("Campus123")
    client.post(URL, valid(email="b@pes.edu"))
    assert User.objects.get(email="b@pes.edu").password != u.password  # unique salts


@pytest.mark.django_db
def test_plaintext_password_never_in_response_or_logs(client, caplog):
    with caplog.at_level(logging.DEBUG):
        ok = client.post(URL, valid(password="Campus123"), follow=True)
        bad = client.post(URL, valid(email="c@pes.edu", password="Secret99x", user_type="ALIEN"))
    for body in (ok.content, bad.content):
        assert b"Campus123" not in body and b"Secret99x" not in body
    assert "Campus123" not in caplog.text and "Secret99x" not in caplog.text


@pytest.mark.django_db
def test_csrf_enforced():
    c = Client(enforce_csrf_checks=True)
    r = c.post(URL, valid())
    assert r.status_code == 403
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_get_does_not_create_accounts(client):
    client.get(URL, valid())
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_invalid_submission_preserves_safe_fields_but_not_password(client):
    r = client.post(URL, valid(password="Zq9x"))  # too short, distinctive string
    assert b"asha@pes.edu" in r.content
    assert b"Zq9x" not in r.content
