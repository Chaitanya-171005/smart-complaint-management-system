"""B06 / TC-02 / TC-12 / REQ-ADM-02: users, roles and department membership."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client

from accounts import reference_services as ref
from accounts import user_admin_services as svc
from accounts.models import ConfigAuditEvent, Department, SecurityEvent, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(scms_admin_user):
    return scms_admin_user


@pytest.fixture
def dept(admin):
    return ref.create_department(admin, "Synthetic Hostel")


@pytest.fixture
def other_dept(admin):
    return ref.create_department(admin, "Synthetic IT")


@pytest.fixture
def person(user_factory):
    return user_factory()


def snapshot():
    return list(User.objects.order_by("pk").values("pk", "role", "department_id", "is_active"))


def events(kind):
    return SecurityEvent.objects.filter(event_type=kind)


# --- authorized changes --------------------------------------------------------------------


def test_admin_makes_a_complainant_staff_in_a_department(admin, person, dept):
    svc.set_role_and_membership(admin, person, role="STAFF", department=dept)
    person.refresh_from_db()
    assert (person.role, person.department_id) == ("STAFF", dept.pk)


def test_staff_to_head_and_move_between_departments(admin, person, dept, other_dept):
    svc.set_role_and_membership(admin, person, role="STAFF", department=dept)
    svc.set_role_and_membership(admin, person, role="HEAD", department=other_dept)
    person.refresh_from_db()
    assert (person.role, person.department_id) == ("HEAD", other_dept.pk)


def test_removing_membership_means_a_role_without_a_department(admin, person, dept):
    svc.set_role_and_membership(admin, person, role="STAFF", department=dept)
    svc.set_role_and_membership(admin, person, role="COMPLAINANT", department=None)
    person.refresh_from_db()
    assert (person.role, person.department_id) == ("COMPLAINANT", None)


def test_department_can_be_passed_as_a_primary_key(admin, person, dept):
    svc.set_role_and_membership(admin, person, role="HEAD", department=dept.pk)
    person.refresh_from_db()
    assert person.department_id == dept.pk


def test_admin_can_promote_a_user_to_admin_without_a_department(admin, person):
    svc.set_role_and_membership(admin, person, role="ADMIN", department=None)
    person.refresh_from_db()
    assert person.role == "ADMIN" and person.department_id is None


def test_unchanged_request_changes_and_records_nothing(admin, person):
    before = ConfigAuditEvent.objects.count()
    svc.set_role_and_membership(admin, person, role="COMPLAINANT", department=None)
    assert ConfigAuditEvent.objects.count() == before and not events("ROLE_CHANGED").exists()


# --- audit and security events -------------------------------------------------------------


def test_change_writes_an_audit_record_and_a_security_event(admin, person, dept):
    svc.set_role_and_membership(admin, person, role="STAFF", department=dept)
    audit = ConfigAuditEvent.objects.get(entity_type="user")
    assert audit.actor == admin and audit.entity_id == str(person.pk) and audit.action == "UPDATE"
    assert audit.old_values == {"role": "COMPLAINANT", "department": None}
    assert audit.new_values == {"role": "STAFF", "department": dept.pk}
    event = events("ROLE_CHANGED").get()
    assert event.user == admin and f"#{person.pk}" in event.detail and "STAFF" in event.detail


def test_records_contain_no_credentials(admin, person, dept):
    svc.set_role_and_membership(admin, person, role="STAFF", department=dept)
    blob = str(list(ConfigAuditEvent.objects.values())) + str(list(SecurityEvent.objects.values()))
    assert person.password not in blob and "Campus123" not in blob and "SyntheticTest123" not in blob


# --- safeguards: self change, last admin, department rules ---------------------------------------


def test_nobody_changes_their_own_role_or_membership(admin, dept):
    before = snapshot()
    for role, department in (("COMPLAINANT", None), ("STAFF", dept), ("ADMIN", None)):
        with pytest.raises(ValidationError, match="own role"):
            svc.set_role_and_membership(admin, admin, role=role, department=department)
    assert snapshot() == before
    assert events("ROLE_CHANGE_REFUSED").count() == 3


def test_the_last_active_admin_guard_refuses_removing_the_only_admin(admin):
    # Defence in depth: through the service the actor is always another active Admin, so the
    # guard is exercised directly for the case where no other active Administrator exists.
    with pytest.raises(svc._Refused, match="At least one"):
        svc._ensure_an_admin_remains(admin, admin, "COMPLAINANT")
    svc._ensure_an_admin_remains(admin, admin, "ADMIN")  # staying Admin is fine


def test_demoting_another_admin_is_allowed_while_one_remains(admin):
    other = User.objects.create_user(email="other-admin@example.test", password="x", full_name="O", role="ADMIN")
    svc.set_role_and_membership(admin, other, role="COMPLAINANT", department=None)
    assert User.objects.filter(role="ADMIN", is_active=True).count() == 1


def test_a_stale_admin_object_cannot_act_after_demotion(admin, person, dept):
    other = User.objects.create_user(email="other-admin@example.test", password="x", full_name="O", role="ADMIN")
    User.objects.filter(pk=admin.pk).update(role="COMPLAINANT")  # demoted elsewhere; `admin` is stale
    assert admin.role == "ADMIN"
    with pytest.raises(PermissionDenied):
        svc.set_role_and_membership(admin, other, role="COMPLAINANT", department=None)
    assert User.objects.get(pk=other.pk).role == "ADMIN"


@pytest.mark.parametrize(
    "role,department,message",
    [
        ("STAFF", None, "need a department"),
        ("HEAD", None, "need a department"),
        ("COMPLAINANT", "dept", "Only Staff"),
        ("ADMIN", "dept", "Only Staff"),
        ("SUPERUSER", None, "valid role"),
        ("", None, "valid role"),
    ],
)
def test_invalid_combinations_are_refused_and_change_nothing(admin, person, dept, role, department, message):
    before = snapshot()
    with pytest.raises(ValidationError, match=message):
        svc.set_role_and_membership(admin, person, role=role, department=dept if department else None)
    assert snapshot() == before
    assert events("ROLE_CHANGE_REFUSED").count() == 1 and not events("ROLE_CHANGED").exists()
    assert not ConfigAuditEvent.objects.filter(entity_type="user").exists()


def test_unknown_and_inactive_departments_cannot_be_assigned(admin, person, dept):
    with pytest.raises(ValidationError, match="valid department"):
        svc.set_role_and_membership(admin, person, role="STAFF", department=99999)
    ref.set_department_active(admin, dept, False)
    with pytest.raises(ValidationError, match="active department"):
        svc.set_role_and_membership(admin, person, role="STAFF", department=dept)
    person.refresh_from_db()
    assert person.role == "COMPLAINANT"


def test_existing_member_of_a_deactivated_department_keeps_it(admin, person, dept):
    svc.set_role_and_membership(admin, person, role="STAFF", department=dept)
    ref.set_department_active(admin, dept, False)
    svc.set_role_and_membership(admin, person, role="HEAD", department=dept)  # same department
    person.refresh_from_db()
    assert (person.role, person.department_id) == ("HEAD", dept.pk)


def test_audit_failure_rolls_the_change_back(admin, person, dept, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr(svc, "record_change", boom)
    with pytest.raises(RuntimeError):
        svc.set_role_and_membership(admin, person, role="STAFF", department=dept)
    person.refresh_from_db()
    assert person.role == "COMPLAINANT"


# --- unauthorized actors -------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["complainant_user", "staff_user", "head_user"])
def test_non_admins_cannot_change_roles(request, person, dept, who):
    actor = request.getfixturevalue(who)
    before = snapshot()
    with pytest.raises(PermissionDenied):
        svc.set_role_and_membership(actor, person, role="ADMIN", department=None)
    assert snapshot() == before
    assert events("AUTHORIZATION_REFUSED").filter(user=actor).count() == 1


def test_anonymous_cannot_change_roles(person):
    with pytest.raises(PermissionDenied):
        svc.set_role_and_membership(AnonymousUser(), person, role="ADMIN", department=None)
    assert User.objects.get(pk=person.pk).role == "COMPLAINANT"


# --- effect on the next request --------------------------------------------------------------------


def login(user):
    c = Client()
    c.force_login(user)
    return c


def test_promotion_takes_effect_on_the_next_request(admin, person, dept):
    c = login(person)
    assert c.get("/accounts/landing/staff/").status_code == 302  # complainant: bounced to own home
    svc.set_role_and_membership(admin, person, role="STAFF", department=dept)
    assert c.get("/accounts/landing/staff/").status_code == 200


def test_demotion_takes_effect_on_the_next_request(admin, person, dept):
    svc.set_role_and_membership(admin, person, role="STAFF", department=dept)
    c = login(person)
    assert c.get("/accounts/landing/staff/").status_code == 200
    svc.set_role_and_membership(admin, person, role="COMPLAINANT", department=None)
    assert c.get("/accounts/landing/staff/").status_code == 302


def test_a_demoted_admin_loses_the_admin_screens_at_once(admin):
    other = User.objects.create_user(email="other-admin@example.test", password="x", full_name="O", role="ADMIN")
    c = login(other)
    assert c.get("/accounts/admin-config/users/").status_code == 200
    svc.set_role_and_membership(admin, other, role="COMPLAINANT", department=None)
    assert c.get("/accounts/admin-config/users/").status_code == 403


# --- screens -------------------------------------------------------------------------------------


USERS = "/accounts/admin-config/users/"


def test_admin_sees_the_user_list_and_not_a_link_for_themselves(admin, person):
    body = login(admin).get(USERS).content.decode()
    assert person.email in body and f"/users/{person.pk}/edit/" in body
    assert f"/users/{admin.pk}/edit/" not in body and "(you)" in body


@pytest.mark.parametrize("who", ["complainant_user", "staff_user", "head_user"])
def test_other_roles_cannot_open_or_post_the_user_screens(request, person, who):
    c = login(request.getfixturevalue(who))
    assert c.get(USERS).status_code == 403
    assert c.get(f"{USERS}{person.pk}/edit/").status_code == 403
    assert c.post(f"{USERS}{person.pk}/edit/", {"role": "ADMIN"}).status_code == 403
    assert User.objects.get(pk=person.pk).role == "COMPLAINANT"


def test_anonymous_is_sent_to_login():
    r = Client().get(USERS)
    assert r.status_code == 302 and "/accounts/login/" in r["Location"]


def test_admin_changes_a_role_through_the_screen(admin, person, dept):
    c = login(admin)
    r = c.post(f"{USERS}{person.pk}/edit/", {"role": "STAFF", "department": dept.pk})
    assert r.status_code == 302
    person.refresh_from_db()
    assert (person.role, person.department_id) == ("STAFF", dept.pk)


def test_screen_shows_errors_and_changes_nothing(admin, person, dept):
    c = login(admin)
    r = c.post(f"{USERS}{person.pk}/edit/", {"role": "STAFF", "department": ""})
    assert r.status_code == 400 and "need a department" in r.content.decode()
    assert User.objects.get(pk=person.pk).role == "COMPLAINANT"
    r = c.post(f"{USERS}{admin.pk}/edit/", {"role": "COMPLAINANT", "department": ""})
    assert r.status_code == 400 and "own role" in r.content.decode()
    assert User.objects.get(pk=admin.pk).role == "ADMIN"


def test_screen_offers_only_active_departments_plus_the_current_one(admin, person, dept, other_dept):
    ref.set_department_active(admin, other_dept, False)
    page = login(admin).get(f"{USERS}{person.pk}/edit/").content.decode()
    assert dept.name in page and other_dept.name not in page


def test_screen_rejects_an_inactive_department_even_if_posted(admin, person, other_dept):
    ref.set_department_active(admin, other_dept, False)
    r = login(admin).post(f"{USERS}{person.pk}/edit/", {"role": "STAFF", "department": other_dept.pk})
    assert r.status_code == 400
    assert User.objects.get(pk=person.pk).role == "COMPLAINANT"


def test_unknown_user_is_404(admin):
    assert login(admin).get(f"{USERS}99999/edit/").status_code == 404


def test_post_needs_a_csrf_token(admin, person):
    c = Client(enforce_csrf_checks=True)
    c.force_login(admin)
    assert c.post(f"{USERS}{person.pk}/edit/", {"role": "ADMIN"}).status_code == 403
    assert User.objects.get(pk=person.pk).role == "COMPLAINANT"


def test_admin_home_links_to_the_user_screen(admin):
    assert USERS in login(admin).get("/accounts/landing/admin/").content.decode()
