import logging
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounts import services

User = get_user_model()
URL = "/accounts/register/"


@pytest.fixture(autouse=True)
def fast_hasher(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


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
def test_password_stored_as_salted_hash_only(client, settings):
    # The real production hasher here, not the fast one the rest of the file uses.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
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


# --- SRS Appendix B-1 field limits (name 100, email 120, hostel block 20, room 10) ---------

LIMITS = [("full_name", 100), ("hostel_block", 20), ("hostel_room", 10)]


@pytest.mark.django_db
def test_model_field_limits_match_srs():
    f = User._meta.get_field
    assert f("full_name").max_length == 100
    assert f("email").max_length == 120
    assert f("hostel_block").max_length == 20
    assert f("hostel_room").max_length == 10
    assert f("user_type").max_length == 20 and f("role").max_length == 20


@pytest.mark.django_db
@pytest.mark.parametrize("field,limit", LIMITS)
def test_text_field_at_limit_accepted_and_over_limit_rejected(client, field, limit):
    base = valid(hostel_resident="on", hostel_block="A", hostel_room="1")
    at_limit = dict(base, **{field: "x" * limit})
    assert client.post(URL, at_limit).status_code == 302
    stored = User.objects.get(email="asha@pes.edu")
    assert len(getattr(stored, field)) == limit

    User.objects.all().delete()
    over = dict(base, **{field: "x" * (limit + 1)})
    r = client.post(URL, over)
    assert r.status_code == 200 and field in r.context["form"].errors
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_email_at_120_accepted_and_121_rejected(client):
    ok = "a" * 64 + "." + "b" * (120 - 64 - 1 - len("@pes.edu")) + "@pes.edu"
    assert len(ok) == 120
    assert client.post(URL, valid(email=ok)).status_code == 302
    assert User.objects.filter(email=ok).exists()

    User.objects.all().delete()
    too_long = ok[:-len("@pes.edu")] + "c@pes.edu"
    assert len(too_long) == 121
    r = client.post(URL, valid(email=too_long))
    assert r.status_code == 200 and "email" in r.context["form"].errors
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_database_rejects_overlong_values_not_only_the_form():
    # SQLite does not enforce VARCHAR length, so check the validators the model declares.
    from django.core.exceptions import ValidationError

    u = User(email="a@pes.edu", full_name="x" * 101, hostel_room="y" * 11)
    with pytest.raises(ValidationError) as e:
        u.full_clean(exclude=["password"])
    assert {"full_name", "hostel_room"} <= set(e.value.message_dict)


# --- uniqueness enforced by the database ------------------------------------------------


@pytest.mark.django_db
def test_database_has_unique_constraint_on_email():
    from django.db import connection

    with connection.cursor() as cur:
        constraints = connection.introspection.get_constraints(cur, User._meta.db_table)
    assert any(
        c["unique"] and c["columns"] == ["email"] for c in constraints.values()
    ), "plain unique index on email"
    assert "accounts_user_email_ci_unique" in constraints


@pytest.mark.django_db
def test_database_refuses_duplicate_email_bypassing_forms_and_services():
    from django.db import IntegrityError, connection, transaction

    User.objects.create_user(email="dup@pes.edu", password="Campus123", full_name="A")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(email="dup@pes.edu", full_name="B", password="x")])
    with pytest.raises(IntegrityError), transaction.atomic():  # differs only by case
        User.objects.bulk_create([User(email="DUP@pes.edu", full_name="C", password="x")])
    assert User.objects.count() == 1


# --- concurrent registration (acceptance criterion) -------------------------------------


@pytest.mark.django_db(transaction=True)
def test_many_simultaneous_registrations_create_exactly_one_account():
    import threading

    from django.db import connection

    workers = 12
    barrier = threading.Barrier(workers)
    results, errors = [], []

    def attempt(i):
        try:
            barrier.wait(timeout=10)  # all threads start together
            results.append(
                services.register_complainant(
                    full_name=f"Racer {i}",
                    email="Race@PES.edu",
                    password="Campus123",
                    user_type="STUDENT",
                )
            )
        except Exception as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert len(results) == workers
    assert results.count(True) == 1  # exactly one winner
    assert results.count(False) == workers - 1  # everyone else got the duplicate path
    assert User.objects.filter(email__iexact="race@pes.edu").count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_registrations_through_the_view_give_identical_responses():
    import threading

    from django.db import connection

    workers = 8
    barrier = threading.Barrier(workers)
    out, errors = [], []

    def attempt(i):
        try:
            c = Client()
            barrier.wait(timeout=10)
            r = c.post(URL, valid(email="view-race@pes.edu", full_name=f"Racer {i}"))
            out.append((r.status_code, r.url))
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert len(set(out)) == 1 and out[0][0] == 302  # same generic acknowledgement
    assert User.objects.filter(email="view-race@pes.edu").count() == 1


# --- duplicate vs unexpected IntegrityError ---------------------------------------------


@pytest.mark.django_db
def test_duplicate_collision_is_reported_as_duplicate_without_error_log(caplog):
    User.objects.create_user(email="race@pes.edu", password="Campus123", full_name="First")
    real_filter = User.objects.filter
    calls = {"n": 0}

    def first_check_misses(*a, **k):
        calls["n"] += 1
        qs = real_filter(*a, **k)
        if calls["n"] == 1:  # the pre-check "misses" the existing row (the race)
            m = mock.Mock()
            m.exists.return_value = False
            return m
        return qs

    with mock.patch.object(User.objects, "filter", side_effect=first_check_misses):
        with caplog.at_level(logging.ERROR):
            created = services.register_complainant(
                full_name="Second", email="race@pes.edu", password="Campus123", user_type="STUDENT"
            )
    assert created is False
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.django_db
def test_unexpected_integrity_error_is_not_treated_as_duplicate(caplog):
    from django.db import IntegrityError

    with mock.patch.object(
        User.objects, "create_user", side_effect=IntegrityError("NOT NULL constraint failed")
    ):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(services.RegistrationError):
                services.register_complainant(
                    full_name="Zed", email="zed@pes.edu", password="Campus123", user_type="STUDENT"
                )
    assert User.objects.count() == 0
    assert any("Unexpected integrity failure" in r.message for r in caplog.records)


@pytest.mark.django_db
def test_view_shows_generic_error_not_acknowledgement_on_unexpected_failure(client):
    from django.db import IntegrityError

    with mock.patch.object(
        User.objects, "create_user", side_effect=IntegrityError("secret detail: users.password")
    ):
        r = client.post(URL, valid())
    assert r.status_code == 500
    body = r.content.decode()
    assert "could not complete your registration" in body
    assert "secret detail" not in body and "IntegrityError" not in body
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_acknowledgement_mentions_password_reset_assistance_for_existing_users(client):
    # D06 interim: the wording points to assistance, no reset flow exists (docs/DECISIONS.md).
    r = client.get(client.post(URL, valid()).url)
    assert "password-reset assistance" in r.content.decode()
    from django.urls import NoReverseMatch

    for name in ("password_reset", "accounts:password_reset"):
        with pytest.raises(NoReverseMatch):
            reverse(name)
