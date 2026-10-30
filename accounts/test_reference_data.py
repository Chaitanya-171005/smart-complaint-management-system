"""B05 / TC-12 / REQ-ADM-01: department and location administration."""

from unittest import mock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client

from accounts import reference_services as svc
from accounts.config_audit import REDACTED, record_change
from accounts.models import ConfigAuditEvent, Department, Location, SecurityEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(scms_admin_user):
    return scms_admin_user


@pytest.fixture
def location(admin):
    return svc.create_location(admin, code="syn-a-101", block="Block A", floor="1", room_area="Room 101")


def audit(entity_type=None):
    qs = ConfigAuditEvent.objects.order_by("id")
    return qs.filter(entity_type=entity_type) if entity_type else qs


# --- departments: create, edit, deactivate ---------------------------------------------


def test_admin_creates_a_department_and_it_is_audited(admin):
    dept = svc.create_department(admin, "  Synthetic Maintenance ")
    assert dept.name == "Synthetic Maintenance" and dept.active is True
    event = audit("department").get()
    assert event.actor == admin and event.actor_identifier == admin.email
    assert event.action == "CREATE" and event.entity_id == str(dept.pk)
    assert event.old_values == {} and event.new_values == {"name": "Synthetic Maintenance", "active": True}
    assert event.created_at is not None


@pytest.mark.parametrize("name,ok", [("d" * 50, True), ("d" * 51, False), ("", False), ("   ", False), ("a\nb", False)])
def test_department_name_boundaries(admin, name, ok):
    if ok:
        assert svc.create_department(admin, name).name == name
    else:
        with pytest.raises(ValidationError):
            svc.create_department(admin, name)
        assert Department.objects.count() == 0 and audit().count() == 0


def test_department_names_are_unique_ignoring_case(admin):
    svc.create_department(admin, "Synthetic IT")
    with pytest.raises(ValidationError):
        svc.create_department(admin, "synthetic it")
    assert Department.objects.count() == 1 and audit().count() == 1


def test_rename_records_old_and_new_values(admin):
    dept = svc.create_department(admin, "Synthetic Old")
    svc.rename_department(admin, dept, "Synthetic New")
    dept.refresh_from_db()
    assert dept.name == "Synthetic New"
    event = audit("department").last()
    assert event.action == "UPDATE"
    assert event.old_values["name"] == "Synthetic Old" and event.new_values["name"] == "Synthetic New"


def test_rename_to_an_existing_name_is_refused_and_changes_nothing(admin):
    svc.create_department(admin, "Synthetic A")
    b = svc.create_department(admin, "Synthetic B")
    before = audit().count()
    with pytest.raises(ValidationError):
        svc.rename_department(admin, b, "SYNTHETIC a")
    b.refresh_from_db()
    assert b.name == "Synthetic B" and audit().count() == before


def test_unchanged_rename_is_not_audited(admin):
    dept = svc.create_department(admin, "Synthetic Same")
    before = audit().count()
    svc.rename_department(admin, dept, "Synthetic Same")
    assert audit().count() == before


def test_deactivate_and_reactivate_a_department(admin):
    dept = svc.create_department(admin, "Synthetic Cycle")
    svc.set_department_active(admin, dept, False)
    dept.refresh_from_db()
    assert dept.active is False
    svc.set_department_active(admin, dept, True)
    dept.refresh_from_db()
    assert dept.active is True
    assert [e.action for e in audit("department")] == ["CREATE", "DEACTIVATE", "REACTIVATE"]
    svc.set_department_active(admin, dept, True)  # no change, no new record
    assert audit("department").count() == 3


def test_deactivation_keeps_existing_references(admin, user_factory):
    dept = svc.create_department(admin, "Synthetic Referenced")
    staff = user_factory(role="STAFF", department=dept)
    svc.set_department_active(admin, dept, False)
    staff.refresh_from_db()
    assert staff.department_id == dept.pk  # reference preserved
    assert dept in Department.objects.all()


def test_new_operations_choose_active_values_only(admin):
    live = svc.create_department(admin, "Synthetic Live")
    retired = svc.create_department(admin, "Synthetic Retired")
    svc.set_department_active(admin, retired, False)
    assert list(svc.active_departments()) == [live]
    loc_live = svc.create_location(admin, code="L1", block="B", floor="", room_area="R1")
    loc_old = svc.create_location(admin, code="L2", block="B", floor="", room_area="R2")
    svc.set_location_active(admin, loc_old, False)
    assert list(svc.active_locations()) == [loc_live]


# --- referenced data cannot be removed -----------------------------------------------------


def test_departments_and_locations_cannot_be_deleted(admin, location, user_factory):
    dept = svc.create_department(admin, "Synthetic Keep")
    user_factory(role="STAFF", department=dept)
    for action in (
        dept.delete,
        Department.objects.all().delete,
        Department.objects.filter(pk=dept.pk).delete,
        location.delete,
        Location.objects.all().delete,
    ):
        with pytest.raises(ValidationError):
            action()
    assert Department.objects.filter(pk=dept.pk).exists()
    assert Location.objects.filter(pk=location.pk).exists()


# --- locations --------------------------------------------------------------------------------


def test_create_location_normalizes_the_code_and_audits(admin):
    loc = svc.create_location(admin, code="  blk-a-101 ", block="Block A", floor="1", room_area="Room 101")
    assert loc.code == "BLK-A-101" and loc.label == "Block A / 1 / Room 101" and loc.active
    event = audit("location").get()
    assert event.action == "CREATE" and event.new_values["code"] == "BLK-A-101"


@pytest.mark.parametrize(
    "field,limit",
    [("code", 100), ("block", 20), ("floor", 10), ("room_area", 30)],
)
def test_location_limits_match_srs_b2(admin, field, limit):
    base = {"code": "C1", "block": "B", "floor": "1", "room_area": "R"}
    svc.create_location(admin, **{**base, field: "x" * limit})
    Location.objects.all()._raw_delete(Location.objects.db)  # test cleanup only
    with pytest.raises(ValidationError):
        svc.create_location(admin, **{**base, field: "x" * (limit + 1)})


@pytest.mark.parametrize("field", ["code", "block", "room_area"])
def test_location_required_fields(admin, field):
    values = {"code": "C1", "block": "B", "floor": "", "room_area": "R"}
    values[field] = "  "
    with pytest.raises(ValidationError):
        svc.create_location(admin, **values)
    assert Location.objects.count() == 0


def test_floor_is_optional(admin):
    assert svc.create_location(admin, code="C1", block="B", floor="", room_area="R").floor == ""


def test_duplicate_code_and_duplicate_place_are_refused(admin, location):
    with pytest.raises(ValidationError):
        svc.create_location(admin, code="SYN-A-101", block="Other", floor="", room_area="Other")
    with pytest.raises(ValidationError):
        svc.create_location(admin, code="NEW", block="block a", floor="1", room_area="ROOM 101")
    assert Location.objects.count() == 1


def test_update_location_keeps_the_stable_code(admin, location):
    svc.update_location(admin, location, block="Block A", floor="2", room_area="Room 101 renamed")
    location.refresh_from_db()
    assert location.code == "SYN-A-101" and location.floor == "2"
    event = audit("location").last()
    assert event.action == "UPDATE"
    assert event.old_values["floor"] == "1" and event.new_values["floor"] == "2"
    assert event.old_values["code"] == event.new_values["code"] == "SYN-A-101"


def test_update_to_an_existing_place_is_refused(admin, location):
    other = svc.create_location(admin, code="O1", block="Block B", floor="", room_area="Hall")
    with pytest.raises(ValidationError):
        svc.update_location(admin, other, block="block a", floor="1", room_area="room 101")
    other.refresh_from_db()
    assert other.block == "Block B"


def test_deactivate_location_preserves_it(admin, location):
    svc.set_location_active(admin, location, False)
    location.refresh_from_db()
    assert location.active is False and Location.objects.filter(pk=location.pk).exists()
    assert audit("location").last().action == "DEACTIVATE"


# --- unauthorized changes are refused ---------------------------------------------------------


@pytest.fixture
def seeded(admin):
    return svc.create_department(admin, "Synthetic Seed"), svc.create_location(
        admin, code="SEED", block="B", floor="", room_area="R"
    )


def attempts(dept, loc):
    return [
        lambda u: svc.create_department(u, "Synthetic Intruder"),
        lambda u: svc.rename_department(u, dept, "Synthetic Hacked"),
        lambda u: svc.set_department_active(u, dept, False),
        lambda u: svc.create_location(u, code="X", block="B", floor="", room_area="Z"),
        lambda u: svc.update_location(u, loc, block="B", floor="", room_area="Hacked"),
        lambda u: svc.set_location_active(u, loc, False),
    ]


@pytest.mark.parametrize("who", ["complainant_user", "staff_user", "head_user"])
def test_non_admin_roles_cannot_change_reference_data(request, seeded, who):
    dept, loc = seeded
    user = request.getfixturevalue(who)
    audit_before, depts, locs = audit().count(), list(Department.objects.values()), list(Location.objects.values())
    for attempt in attempts(dept, loc):
        with pytest.raises(PermissionDenied):
            attempt(user)
    assert audit().count() == audit_before
    assert list(Department.objects.values()) == depts and list(Location.objects.values()) == locs
    # each refusal is logged and the log survives the refusal
    assert SecurityEvent.objects.filter(
        event_type=SecurityEvent.EventType.AUTHORIZATION_REFUSED, user=user
    ).count() == len(attempts(dept, loc))


def test_anonymous_cannot_change_reference_data(seeded):
    dept, loc = seeded
    for attempt in attempts(dept, loc):
        with pytest.raises(PermissionDenied):
            attempt(AnonymousUser())
    assert Department.objects.count() == 1


def test_demoted_admin_is_refused_on_the_next_call(admin, seeded):
    dept, _ = seeded
    type(admin).objects.filter(pk=admin.pk).update(role="STAFF")
    fresh = type(admin).objects.get(pk=admin.pk)
    with pytest.raises(PermissionDenied):
        svc.set_department_active(fresh, dept, False)


# --- audit: complete, atomic, safe, append-only -------------------------------------------


def test_change_and_audit_record_succeed_or_fail_together(admin):
    with mock.patch.object(svc, "record_change", side_effect=RuntimeError("audit down")):
        with pytest.raises(RuntimeError):
            svc.create_department(admin, "Synthetic Atomic")
    assert not Department.objects.filter(name="Synthetic Atomic").exists()
    dept = svc.create_department(admin, "Synthetic Atomic 2")
    with mock.patch.object(svc, "record_change", side_effect=RuntimeError("audit down")):
        with pytest.raises(RuntimeError):
            svc.set_department_active(admin, dept, False)
    dept.refresh_from_db()
    assert dept.active is True


def test_audit_records_cannot_be_edited_or_deleted(admin):
    svc.create_department(admin, "Synthetic Audited")
    event = audit().get()
    event.new_values = {"name": "tampered"}
    for action in (
        event.save,
        event.delete,
        lambda: ConfigAuditEvent.objects.update(entity_type="x"),
        ConfigAuditEvent.objects.all().delete,
    ):
        with pytest.raises(ValidationError):
            action()
    assert audit().get().new_values["name"] == "Synthetic Audited"


def test_sensitive_values_are_never_stored(admin):
    event = record_change(
        actor=admin, entity_type="user", entity_id=1, action="UPDATE",
        old={"role": "STAFF", "password": "Campus123", "session_key": "abc"},
        new={"role": "HEAD", "Password_Hash": "pbkdf2$x", "tracking_reference": "REF-1"},
    )
    event.refresh_from_db()
    assert event.old_values == {"role": "STAFF", "password": REDACTED, "session_key": REDACTED}
    assert event.new_values == {"role": "HEAD", "Password_Hash": REDACTED, "tracking_reference": REDACTED}
    assert "Campus123" not in str(event.old_values)


def test_audit_survives_actor_deletion_of_account_row(admin):
    # actor is SET_NULL, the identifier snapshot keeps the trail readable.
    svc.create_department(admin, "Synthetic Trail")
    email = admin.email
    type(admin).objects.filter(pk=admin.pk).delete()
    event = audit().get()
    assert event.actor is None and event.actor_identifier == email


# --- screens ---------------------------------------------------------------------------------


@pytest.fixture
def client_for(db):
    def make(user=None, **kwargs):
        c = Client(**kwargs)
        if user is not None:
            c.force_login(user)
        return c

    return make


LIST_URLS = ["/accounts/admin-config/departments/", "/accounts/admin-config/locations/"]


@pytest.mark.parametrize("url", LIST_URLS)
def test_admin_sees_the_screens(client_for, admin, url):
    r = client_for(admin).get(url)
    assert r.status_code == 200


@pytest.mark.parametrize("url", LIST_URLS)
def test_anonymous_is_sent_to_login(client_for, url):
    r = client_for().get(url)
    assert r.status_code == 302 and "/accounts/login/" in r["Location"]


@pytest.mark.parametrize("who", ["complainant_user", "staff_user", "head_user"])
@pytest.mark.parametrize("url", LIST_URLS)
def test_other_roles_get_403_on_get_and_post(request, client_for, seeded, who, url):
    user = request.getfixturevalue(who)
    c = client_for(user)
    dept_count, loc_count = Department.objects.count(), Location.objects.count()
    assert c.get(url).status_code == 403
    assert c.post(url, {"name": "Intruder", "code": "X", "block": "B", "room_area": "R"}).status_code == 403
    dept, loc = seeded
    assert c.post(f"/accounts/admin-config/departments/{dept.pk}/active/", {"active": "false"}).status_code == 403
    assert c.post(f"/accounts/admin-config/locations/{loc.pk}/edit/", {"block": "B", "room_area": "X"}).status_code == 403
    dept.refresh_from_db()
    assert dept.active
    assert (Department.objects.count(), Location.objects.count()) == (dept_count, loc_count)


def test_admin_creates_edits_and_toggles_through_the_screens(client_for, admin):
    c = client_for(admin)
    assert c.post(LIST_URLS[0], {"name": "Synthetic Screens"}).status_code == 302
    dept = Department.objects.get(name="Synthetic Screens")
    assert c.post(f"/accounts/admin-config/departments/{dept.pk}/edit/", {"name": "Synthetic Renamed"}).status_code == 302
    assert c.post(f"/accounts/admin-config/departments/{dept.pk}/active/", {"active": "false"}).status_code == 302
    dept.refresh_from_db()
    assert dept.name == "Synthetic Renamed" and dept.active is False
    r = c.post(LIST_URLS[1], {"code": "scr-1", "block": "B", "floor": "", "room_area": "R"})
    assert r.status_code == 302 and Location.objects.get().code == "SCR-1"
    assert "Synthetic Renamed" in c.get(LIST_URLS[0]).content.decode()


def test_screens_show_validation_errors_and_change_nothing(client_for, admin):
    svc.create_department(admin, "Synthetic Dup")
    c = client_for(admin)
    r = c.post(LIST_URLS[0], {"name": "synthetic dup"})
    assert r.status_code == 400 and "already exists" in r.content.decode()
    r = c.post(LIST_URLS[0], {"name": "x" * 51})
    assert r.status_code == 400
    assert Department.objects.count() == 1


def test_toggle_requires_post_a_valid_value_and_csrf(client_for, admin, seeded):
    dept, _ = seeded
    url = f"/accounts/admin-config/departments/{dept.pk}/active/"
    assert client_for(admin).get(url).status_code == 405
    assert client_for(admin).post(url, {"active": "maybe"}).status_code == 404
    assert client_for(admin, enforce_csrf_checks=True).post(url, {"active": "false"}).status_code == 403
    dept.refresh_from_db()
    assert dept.active is True


def test_role_change_applies_on_the_next_request(client_for, admin):
    c = client_for(admin)
    assert c.get(LIST_URLS[0]).status_code == 200
    type(admin).objects.filter(pk=admin.pk).update(role="COMPLAINANT")
    assert c.get(LIST_URLS[0]).status_code == 403


def test_admin_home_links_to_the_screens(client_for, admin):
    body = client_for(admin).get("/accounts/landing/admin/").content.decode()
    assert "/accounts/admin-config/departments/" in body and "/accounts/admin-config/locations/" in body


def test_escapes_names_on_the_screen(client_for, admin):
    svc.create_department(admin, "<b>Synthetic</b>")
    body = client_for(admin).get(LIST_URLS[0]).content.decode()
    assert "&lt;b&gt;Synthetic&lt;/b&gt;" in body and "<b>Synthetic</b>" not in body


def test_admin_edits_and_toggles_a_location_through_the_screens(client_for, admin, location):
    c = client_for(admin)
    r = c.post(f"/accounts/admin-config/locations/{location.pk}/edit/",
               {"block": "Block A", "floor": "2", "room_area": "Room 101"})
    assert r.status_code == 302
    r = c.post(f"/accounts/admin-config/locations/{location.pk}/active/", {"active": "false"})
    assert r.status_code == 302
    location.refresh_from_db()
    assert location.floor == "2" and location.active is False and location.code == "SYN-A-101"
    page = c.get(f"/accounts/admin-config/locations/{location.pk}/edit/")
    assert page.status_code == 200 and "Edit location: SYN-A-101" in page.content.decode()


def test_edit_screens_show_errors_and_unknown_records_are_404(client_for, admin, location):
    other = svc.create_location(admin, code="O2", block="Block B", floor="", room_area="Hall")
    c = client_for(admin)
    r = c.post(f"/accounts/admin-config/locations/{other.pk}/edit/",
               {"block": "Block A", "floor": "1", "room_area": "Room 101"})
    assert r.status_code == 400 and "already exists" in r.content.decode()
    other.refresh_from_db()
    assert other.block == "Block B"
    assert c.get("/accounts/admin-config/departments/99999/edit/").status_code == 404
    assert c.post("/accounts/admin-config/locations/99999/active/", {"active": "true"}).status_code == 404
    dept = svc.create_department(admin, "Synthetic Edit Errors")
    r = c.post(f"/accounts/admin-config/departments/{dept.pk}/edit/", {"name": ""})
    assert r.status_code == 400
    r = c.get(f"/accounts/admin-config/departments/{dept.pk}/edit/")
    assert r.status_code == 200 and "Synthetic Edit Errors" in r.content.decode()
