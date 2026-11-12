"""Q03 / REQ-SEC-08 / TC-01, TC-12, TC-13, VM-02: one safe, consistent security-event policy."""

import secrets

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client

from accounts import reference_services as ref
from accounts import user_admin_services as users
from accounts.config_audit import record_change
from accounts.models import ConfigAuditEvent, SecurityEvent, User
from accounts.permissions import can_manage_configuration, require_permission
from accounts.security_log import REDACTED, record_event, scrub
from accounts.services import attempt_login as _attempt_login

pytestmark = pytest.mark.django_db

PASSWORD = "SyntheticSecret-Pw-93461"


def attempt_login(email, password):
    from django.contrib.sessions.middleware import SessionMiddleware
    from django.test import RequestFactory

    request = RequestFactory().post("/accounts/login/")
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    return _attempt_login(request, email, password)


@pytest.fixture
def admin(scms_admin_user):
    return scms_admin_user


def events(kind):
    return SecurityEvent.objects.filter(event_type=kind)


def every_stored_text():
    """All text that either audit store holds, for sweeping for secrets."""
    rows = [str(list(SecurityEvent.objects.values()))]
    rows.append(str(list(ConfigAuditEvent.objects.values("old_values", "new_values", "actor_identifier"))))
    return " ".join(rows)


# --- required events carry actor, action, target and time ------------------------------------


def test_every_required_event_type_exists_in_the_policy():
    required = {"LOGIN_SUCCESS", "LOGIN_FAILURE", "LOGIN_LOCKOUT", "AUTHORIZATION_REFUSED",
                "ROLE_CHANGED", "MASTER_DATA_CHANGED"}
    assert required <= set(SecurityEvent.EventType.values)


def test_authentication_events_are_recorded(user_factory):
    person = user_factory(password=PASSWORD)
    assert attempt_login(person.email, PASSWORD).status == "ok"
    assert events("LOGIN_SUCCESS").filter(user=person, identifier=person.email).count() == 1
    attempt_login(person.email, "wrong-" + PASSWORD)
    failure = events("LOGIN_FAILURE").get()
    assert failure.user == person and failure.identifier == person.email and failure.created_at


def test_lockout_is_recorded_and_blocks_are_recorded(user_factory):
    person = user_factory(password=PASSWORD)
    for _ in range(12):
        attempt_login(person.email, "wrong-" + PASSWORD)
    assert events("LOGIN_LOCKOUT").exists() or events("LOGIN_BLOCKED").exists()
    assert events("LOGIN_FAILURE").count() >= 1


def test_authorization_refusal_records_actor_action_target_time(staff_user, admin):
    with pytest.raises(PermissionDenied):
        require_permission(can_manage_configuration, staff_user)
    with pytest.raises(PermissionDenied):
        ref.create_department(staff_user, "Not Allowed")
    refusal = events("AUTHORIZATION_REFUSED").filter(user=staff_user).first()
    assert refusal.identifier == staff_user.email and refusal.detail and refusal.created_at


def test_refusal_against_an_object_names_the_target(staff_user, department_factory):
    from accounts.permissions import authorize_or_404

    dept = department_factory()
    with pytest.raises(Exception):
        authorize_or_404(lambda user, obj: False, staff_user, dept)
    assert events("AUTHORIZATION_REFUSED").filter(target=f"Department#{dept.pk}").exists()


def test_role_change_records_actor_action_target_time(admin, user_factory, department_factory):
    person = user_factory()
    users.set_role_and_membership(admin, person, role="STAFF", department=department_factory())
    event = events("ROLE_CHANGED").get()
    assert event.user == admin and event.identifier == admin.email
    assert event.target == f"User#{person.pk}" and "STAFF" in event.detail and event.created_at


def test_master_data_changes_in_f1_and_f3_record_one_consistent_event(admin):
    from routing import services as routing

    dept = ref.create_department(admin, "Synthetic Q03 Dept")
    ref.create_location(admin, code="q03-1", block="Block A", floor="1", room_area="Room 1")
    category = routing.create_category(admin, name="Synthetic Q03 Category")
    recorded = list(events("MASTER_DATA_CHANGED").order_by("id"))
    assert [e.target.split("#")[0] for e in recorded] == ["Department", "Location", "Category"]
    assert recorded[0].target == f"Department#{dept.pk}" and recorded[2].target == f"Category#{category.pk}"
    assert all(e.user == admin and e.identifier == admin.email and e.detail == "CREATE" and e.created_at
               for e in recorded)


def test_a_rolled_back_master_data_change_leaves_no_security_event(admin):
    before = SecurityEvent.objects.filter(event_type="MASTER_DATA_CHANGED").count()
    with pytest.raises(ValidationError):
        ref.create_department(admin, "")
    assert SecurityEvent.objects.filter(event_type="MASTER_DATA_CHANGED").count() == before


# --- redaction ------------------------------------------------------------------------------------


def test_scrub_removes_references_session_keys_digests_and_assignments():
    reference = secrets.token_hex(16)
    session_key = "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
    digest = "f" * 64
    text = f"ref {reference} sess {session_key} digest {digest} password=hunter2 token: abc"
    cleaned = scrub(text)
    for secret in (reference, session_key, digest, "hunter2", "abc"):
        assert secret not in cleaned
    assert REDACTED in cleaned


def test_scrub_leaves_normal_text_alone():
    text = "role COMPLAINANT->STAFF, department None->4"
    assert scrub(text) == text and scrub("") == "" and scrub(None) == ""


def test_secrets_passed_to_record_event_by_mistake_are_not_stored():
    reference = secrets.token_hex(16)
    record_event("AUTHORIZATION_REFUSED", identifier=reference, target=f"Complaint#{reference}",
                 detail=f"lookup {reference} password={PASSWORD}")
    stored = SecurityEvent.objects.get()
    for text in (stored.identifier, stored.target, stored.detail):
        assert reference not in text and PASSWORD not in text


@pytest.mark.parametrize(
    "typed",
    [
        "{ref}@example.test",
        "{key}@example.test",
        "{digest}@example.test",
        "password=hunter2@example.test",
        "person@example.test?token=abc123",
        "person@example.test session_key={key}",
    ],
)
def test_untrusted_email_shaped_identifiers_are_scrubbed_too(typed):
    import hashlib

    ref = secrets.token_hex(16)
    key = "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
    digest = hashlib.sha256(ref.encode()).hexdigest()
    text = typed.format(ref=ref, key=key, digest=digest)
    record_event("LOGIN_FAILURE", identifier=text)
    stored = SecurityEvent.objects.get().identifier
    for secret in (ref, key, digest, "hunter2", "abc123"):
        assert secret not in stored
    assert REDACTED in stored


def test_an_ordinary_typed_email_is_kept():
    record_event("LOGIN_FAILURE", identifier="ordinary.person@example.test")
    assert SecurityEvent.objects.get().identifier == "ordinary.person@example.test"


def test_a_secret_typed_into_the_login_form_never_reaches_the_log():
    reference = secrets.token_hex(16)
    attempt_login(f"{reference}@example.test", "irrelevant")
    attempt_login(f"password={PASSWORD}@example.test", "irrelevant")
    stored = every_stored_text()
    assert reference not in stored and PASSWORD not in stored
    assert events("LOGIN_FAILURE").count() == 2


def test_an_identifier_matching_another_users_email_is_not_trusted(user_factory):
    person = user_factory()
    other = user_factory()
    record_event("LOGIN_FAILURE", user=other, identifier=person.email)
    stored = SecurityEvent.objects.get().identifier
    assert stored != person.email and REDACTED in stored  # fixture emails carry a 32-hex token


def test_an_email_identifier_is_kept_as_is(user_factory):
    person = user_factory()
    record_event("LOGIN_FAILURE", user=person, identifier=person.email)
    assert SecurityEvent.objects.get().identifier == person.email


def test_no_scenario_leaves_a_password_or_session_key_in_either_store(admin, user_factory, department_factory):
    person = user_factory(password=PASSWORD)
    attempt_login(person.email, PASSWORD)
    attempt_login(person.email, "wrong-" + PASSWORD)
    users.set_role_and_membership(admin, person, role="STAFF", department=department_factory())
    record_change(actor=admin, entity_type="User", entity_id=person.pk, action="UPDATE",
                  old={"password": PASSWORD}, new={"profile": {"session_key": "k" * 32}})
    client = Client()
    client.force_login(person)
    client.get("/accounts/admin-config/users/")  # a refused request
    stored = every_stored_text()
    assert PASSWORD not in stored and person.password not in stored
    assert client.session.session_key not in stored
    assert "k" * 32 not in stored


# --- anonymous privacy --------------------------------------------------------------------------


def test_an_anonymous_refusal_records_no_actor_and_no_identity():
    from accounts.permissions import authorize_or_404

    from types import SimpleNamespace

    with pytest.raises(Exception):
        authorize_or_404(lambda user, obj: False, AnonymousUser(), SimpleNamespace(pk=3))
    event = events("AUTHORIZATION_REFUSED").get()
    assert event.user is None and event.identifier == ""


def test_anonymous_complaint_references_never_reach_the_log():
    # A reference is 32 lowercase hex characters (complaints.references); even if a caller
    # passed one by mistake it must not be stored, so no event can link to an anonymous reporter.
    from complaints.references import hash_reference

    reference = secrets.token_hex(16)
    digest = hash_reference(reference)
    record_event("AUTHORIZATION_REFUSED", target="Complaint#1", detail=f"track {reference} / {digest}")
    stored = every_stored_text()
    assert reference not in stored and digest not in stored


# --- the log cannot be altered ----------------------------------------------------------------------


def test_security_events_are_append_only(user_factory):
    event = record_event("LOGIN_FAILURE", user=user_factory(), identifier="x@example.test")
    event.detail = "tampered"
    with pytest.raises(ValidationError):
        event.save()
    with pytest.raises(ValidationError):
        event.delete()
    with pytest.raises(ValidationError):
        SecurityEvent.objects.filter(pk=event.pk).update(detail="tampered")
    with pytest.raises(ValidationError):
        SecurityEvent.objects.all().delete()
    event.refresh_from_db()
    assert event.detail == ""


def test_an_unknown_event_type_is_a_programming_error():
    with pytest.raises(ValueError):
        record_event("SOMETHING_ELSE")
    assert not SecurityEvent.objects.exists()


# --- one consistent format --------------------------------------------------------------------------


def test_every_event_written_by_the_scenarios_has_the_common_fields(admin, user_factory, department_factory):
    person = user_factory(password=PASSWORD)
    attempt_login(person.email, PASSWORD)
    attempt_login(person.email, "nope")
    ref.create_department(admin, "Synthetic Format Dept")
    users.set_role_and_membership(admin, person, role="STAFF", department=department_factory())
    with pytest.raises(PermissionDenied):
        require_permission(can_manage_configuration, person)
    assert SecurityEvent.objects.count() >= 5
    for event in SecurityEvent.objects.all():
        assert event.event_type in SecurityEvent.EventType.values
        assert event.created_at is not None
        assert len(event.identifier) <= 254 and len(event.target) <= 100 and len(event.detail) <= 255
        if event.event_type in ("ROLE_CHANGED", "MASTER_DATA_CHANGED"):
            assert event.user is not None and "#" in event.target
