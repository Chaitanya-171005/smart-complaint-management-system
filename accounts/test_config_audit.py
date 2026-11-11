"""B29 / REQ-ADM-04 / TC-12 / VM-02: one consistent, read-only configuration audit across F1 and F3."""

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import get_resolver

from accounts import reference_services as ref
from accounts import user_admin_services as users
from accounts.config_audit import ENTITY_TYPES, REDACTED, record_change
from accounts.models import ConfigAuditEvent, Department, Location, SecurityEvent, User

pytestmark = pytest.mark.django_db

AUDIT_URL = "/accounts/admin-config/audit/"


@pytest.fixture
def admin(scms_admin_user):
    return scms_admin_user


def login(user):
    client = Client()
    client.force_login(user)
    return client


def new_events(before):
    return list(ConfigAuditEvent.objects.order_by("id")[before:])


# --- completeness: every F1 configuration operation leaves exactly one record --------------------


def test_every_f1_configuration_operation_is_audited_exactly_once(admin, user_factory):
    person = user_factory()
    steps = []

    def step(label, entity, action, operation):
        before = ConfigAuditEvent.objects.count()
        result = operation()
        events = new_events(before)
        assert len(events) == 1, label
        event = events[0]
        assert (event.entity_type, event.action) == (entity, action), label
        assert event.actor == admin and event.actor_identifier == admin.email, label
        assert event.created_at is not None and event.entity_id, label
        steps.append(label)
        return result, event

    dept, created = step("create department", "Department", "CREATE",
                         lambda: ref.create_department(admin, "Synthetic Audit Dept"))
    assert created.old_values == {} and created.new_values["name"] == "Synthetic Audit Dept"
    _, renamed = step("rename department", "Department", "UPDATE",
                      lambda: ref.rename_department(admin, dept, "Synthetic Audit Dept 2"))
    assert renamed.old_values["name"] == "Synthetic Audit Dept"
    assert renamed.new_values["name"] == "Synthetic Audit Dept 2"
    step("deactivate department", "Department", "DEACTIVATE", lambda: ref.set_department_active(admin, dept, False))
    step("reactivate department", "Department", "REACTIVATE", lambda: ref.set_department_active(admin, dept, True))

    loc, _ = step("create location", "Location", "CREATE",
                  lambda: ref.create_location(admin, code="aud-1", block="Block A", floor="1", room_area="Room 1"))
    _, edited = step("edit location", "Location", "UPDATE",
                     lambda: ref.update_location(admin, loc, block="Block B", floor="2", room_area="Room 2"))
    assert edited.old_values["block"] == "Block A" and edited.new_values["block"] == "Block B"
    step("deactivate location", "Location", "DEACTIVATE", lambda: ref.set_location_active(admin, loc, False))
    step("reactivate location", "Location", "REACTIVATE", lambda: ref.set_location_active(admin, loc, True))

    _, role_change = step("change role and membership", "User", "UPDATE",
                          lambda: users.set_role_and_membership(admin, person, role="STAFF", department=dept))
    assert role_change.old_values == {"role": "COMPLAINANT", "department": None}
    assert role_change.new_values == {"role": "STAFF", "department": dept.pk}
    assert len(steps) == 9


def test_role_and_membership_changes_are_also_security_events(admin, user_factory, department_factory):
    person = user_factory()
    users.set_role_and_membership(admin, person, role="STAFF", department=department_factory())
    assert ConfigAuditEvent.objects.filter(entity_type="User").count() == 1
    assert SecurityEvent.objects.filter(event_type="ROLE_CHANGED", user=admin).count() == 1


def test_refused_or_failed_operations_leave_no_configuration_audit_record(admin, staff_user, user_factory):
    before = ConfigAuditEvent.objects.count()
    with pytest.raises(Exception):
        ref.create_department(staff_user, "Not Allowed")
    with pytest.raises(ValidationError):
        ref.create_department(admin, "")
    with pytest.raises(ValidationError):
        users.set_role_and_membership(admin, admin, role="COMPLAINANT", department=None)
    with pytest.raises(ValidationError):
        ref.create_location(admin, code="bad code", block="B", floor="1", room_area="R")
    assert ConfigAuditEvent.objects.count() == before


# --- the shared contract for F1 and F3 -------------------------------------------------------------


def test_the_contract_names_the_f1_and_f3_entities():
    assert {"Department", "Location", "User"} <= set(ENTITY_TYPES)
    assert {"Category", "RoutingRule", "SLAConfiguration", "EscalationPolicy"} <= set(ENTITY_TYPES)


@pytest.mark.parametrize("entity", sorted(ENTITY_TYPES))
def test_any_contract_entity_can_be_recorded_and_read_back(admin, entity):
    record_change(actor=admin, entity_type=entity, entity_id=7, action="UPDATE",
                  old={"duration_minutes": 60}, new={"duration_minutes": 120})
    event = ConfigAuditEvent.objects.get(entity_type=entity)
    assert (event.entity_id, event.old_values, event.new_values) == ("7", {"duration_minutes": 60}, {"duration_minutes": 120})
    page = login(admin).get(AUDIT_URL).content.decode()
    assert f"{entity} #7" in page and "duration_minutes: 120" in page


@pytest.mark.parametrize(
    "kwargs",
    [
        {"entity_type": "complaint", "action": "UPDATE"},
        {"entity_type": "Department", "action": "DELETE"},
        {"entity_type": "", "action": "CREATE"},
    ],
)
def test_unknown_entities_and_actions_are_programming_errors(admin, kwargs):
    with pytest.raises(ValueError):
        record_change(actor=admin, entity_id=1, **kwargs)
    assert not ConfigAuditEvent.objects.exists()


def test_a_change_needs_a_saved_acting_user():
    from django.contrib.auth.models import AnonymousUser

    for actor in (None, AnonymousUser(), User(email="x@example.test")):
        with pytest.raises(ValueError):
            record_change(actor=actor, entity_type="Department", entity_id=1, action="CREATE")
    assert not ConfigAuditEvent.objects.exists()


def test_every_f3_operation_records_exactly_one_shared_audit_event(admin, department_factory):
    from routing import services as routing
    from routing.models import EscalationPolicy, Priority

    dept = department_factory()
    other = department_factory()
    Location.objects.create(code="AUD-F3", block="Block F", room_area="Room 3")
    seen = []

    def step(label, entity, action, operation):
        before = ConfigAuditEvent.objects.count()
        result = operation()
        events = new_events(before)
        assert len(events) == 1, f"{label}: expected one audit event, got {len(events)}"
        event = events[0]
        assert (event.entity_type, event.action) == (entity, action), label
        assert event.entity_type in ENTITY_TYPES and event.actor == admin and event.created_at, label
        seen.append(label)
        return result

    category = step("create category", "Category", "CREATE", lambda: routing.create_category(admin, name="Synthetic F3 Cat"))
    step("update category", "Category", "UPDATE",
         lambda: routing.update_category(admin, category, minimum_priority=Priority.HIGH))
    rule = step("create rule", "RoutingRule", "CREATE",
                lambda: routing.create_routing_rule(admin, category=category, location_code="aud-f3",
                                                    department=dept, precedence=10))
    step("update rule", "RoutingRule", "UPDATE", lambda: routing.update_routing_rule(admin, rule, precedence=20))
    step("deactivate rule", "RoutingRule", "DEACTIVATE", lambda: routing.deactivate_routing_rule(admin, rule))
    sla = step("set SLA (create)", "SLAConfiguration", "CREATE",
               lambda: routing.set_sla_configuration(admin, priority=Priority.LOW, duration_minutes=600,
                                                     category=category))
    step("set SLA (update)", "SLAConfiguration", "UPDATE",
         lambda: routing.set_sla_configuration(admin, priority=Priority.LOW, duration_minutes=900, category=category))
    step("deactivate SLA", "SLAConfiguration", "DEACTIVATE", lambda: routing.deactivate_sla_configuration(admin, sla))
    EscalationPolicy.objects.all().delete()
    policy = step("create escalation policy", "EscalationPolicy", "CREATE",
                  lambda: routing.create_escalation_policy(admin, default_department=dept,
                                                           interval_minutes=1440, maximum_level=3))
    step("update escalation policy", "EscalationPolicy", "UPDATE",
         lambda: routing.update_escalation_policy(admin, policy, default_department=other, interval_minutes=720))
    step("deactivate category", "Category", "DEACTIVATE", lambda: routing.deactivate_category(admin, category))
    step("reactivate category", "Category", "REACTIVATE", lambda: routing.reactivate_category(admin, category))
    assert len(seen) == 12


def test_legacy_lowercase_entity_rows_still_appear_under_the_class_name_filter(admin):
    # The table is append-only, so an older database can hold lowercase names. The raw insert
    # below stands in for such a row.
    ConfigAuditEvent.objects.bulk_create([
        ConfigAuditEvent(actor=admin, actor_identifier=admin.email, entity_type="department",
                         entity_id="1", action="CREATE", new_values={"name": "Legacy"}),
    ])
    record_change(actor=admin, entity_type="Department", entity_id=2, action="CREATE", new={"name": "Current"})
    page = login(admin).get(AUDIT_URL, {"entity_type": "Department"}).content.decode()
    assert "name: Legacy" in page and "name: Current" in page


@pytest.mark.parametrize("bad", ["text", ["a"], 5, ("a", 1)])
def test_old_and_new_values_must_be_dicts_or_none(admin, bad):
    for field in ("old", "new"):
        with pytest.raises(ValueError):
            record_change(actor=admin, entity_type="Department", entity_id=1, action="UPDATE", **{field: bad})
    assert not ConfigAuditEvent.objects.exists()


def test_the_audit_table_has_a_caption_and_column_headers(admin):
    page = login(admin).get(AUDIT_URL).content.decode()
    assert "<caption>" in page and page.count('scope="col"') == 6


# --- sensitive values never reach the audit -------------------------------------------------------


def test_credentials_and_tokens_are_redacted_at_any_depth(admin):
    record_change(
        actor=admin, entity_type="User", entity_id=1, action="UPDATE",
        old={"password": "hunter2", "profile": {"api_token": "t0k", "note": "ok"}},
        new={"history": [{"session_key": "abc"}], "tracking_reference": "REF-1", "role": "STAFF"},
    )
    event = ConfigAuditEvent.objects.get()
    dump = str(event.old_values) + str(event.new_values)
    for secret in ("hunter2", "t0k", "abc", "REF-1"):
        assert secret not in dump
    assert event.old_values["password"] == REDACTED and event.new_values["role"] == "STAFF"


def test_secrets_embedded_in_ordinary_values_are_scrubbed_at_any_depth(admin):
    import hashlib
    import secrets

    reference = secrets.token_hex(16)
    digest = hashlib.sha256(reference.encode()).hexdigest()
    session_key = "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"

    class Odd:
        def __str__(self):
            return f"odd object holding {reference}"

    record_change(
        actor=admin, entity_type="Category", entity_id=1, action="UPDATE",
        old={"description": f"see {reference} for details", "name": "Lift",
             "items": [{"note": "password=hunter2"}, ["plain", f"digest {digest}"]]},
        new={"meta": {"deep": {"text": session_key, "ok": "short text"}},
             "weird": Odd(), f"{reference}": "value", "count": 3, "flag": True, "none": None},
    )
    event = ConfigAuditEvent.objects.get()
    dump = str(event.old_values) + str(event.new_values)
    for secret in (reference, digest, session_key, "hunter2"):
        assert secret not in dump
    assert event.old_values["name"] == "Lift" and event.old_values["description"].startswith("see ")
    assert event.new_values["meta"]["deep"]["ok"] == "short text"
    assert event.new_values["count"] == 3 and event.new_values["flag"] is True and event.new_values["none"] is None
    page = login(admin).get(AUDIT_URL).content.decode()
    for secret in (reference, digest, session_key, "hunter2"):
        assert secret not in page


def test_ordinary_names_and_codes_are_not_mangled(admin):
    record_change(actor=admin, entity_type="Location", entity_id=2, action="CREATE",
                  new={"code": "HOSTEL-BLOCK-A-ROOM-101", "block": "Block A", "room_area": "Room 101"})
    assert ConfigAuditEvent.objects.get().new_values == {
        "code": "HOSTEL-BLOCK-A-ROOM-101", "block": "Block A", "room_area": "Room 101"}


def test_user_role_audit_carries_no_credentials(admin, user_factory, department_factory):
    person = user_factory()
    users.set_role_and_membership(admin, person, role="STAFF", department=department_factory())
    event = ConfigAuditEvent.objects.get(entity_type="User")
    assert set(event.old_values) | set(event.new_values) == {"role", "department"}
    assert person.password not in str(event.old_values) + str(event.new_values)


# --- distinct from complaint history, and no mutable interface -------------------------------------


def test_configuration_audit_is_a_separate_store_from_complaint_history():
    from workflow.models import ComplaintHistory

    assert ConfigAuditEvent._meta.db_table != ComplaintHistory._meta.db_table
    assert ConfigAuditEvent._meta.app_label != ComplaintHistory._meta.app_label
    related = {f.related_model for f in ConfigAuditEvent._meta.get_fields() if f.is_relation}
    assert ComplaintHistory not in related


def test_audit_records_cannot_be_edited_or_deleted(admin):
    event = record_change(actor=admin, entity_type="Department", entity_id=1, action="CREATE", new={"name": "X"})
    event.new_values = {"name": "Tampered"}
    with pytest.raises(ValidationError):
        event.save()
    with pytest.raises(ValidationError):
        event.delete()
    with pytest.raises(ValidationError):
        ConfigAuditEvent.objects.filter(pk=event.pk).update(action="UPDATE")
    with pytest.raises(ValidationError):
        ConfigAuditEvent.objects.all().delete()
    event.refresh_from_db()
    assert event.new_values == {"name": "X"}


def test_the_only_audit_route_is_a_read_only_screen():
    audit_routes = [p for p in get_resolver("accounts.urls").url_patterns if "audit" in str(p.pattern)]
    assert [str(p.pattern) for p in audit_routes] == ["admin-config/audit/"]
    from django.contrib import admin as django_admin

    assert ConfigAuditEvent not in django_admin.site._registry


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_audit_screen_rejects_every_change_method(admin, method):
    event = record_change(actor=admin, entity_type="Department", entity_id=1, action="CREATE", new={"name": "X"})
    response = getattr(login(admin), method)(AUDIT_URL, {"action": "UPDATE"})
    assert response.status_code == 405
    event.refresh_from_db()
    assert ConfigAuditEvent.objects.count() == 1 and event.action == "CREATE"


# --- the screen -------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["complainant_user", "staff_user", "head_user"])
def test_only_the_administrator_can_read_the_audit_log(request, admin, who):
    record_change(actor=admin, entity_type="Department", entity_id=1, action="CREATE", new={"name": "X"})
    assert login(request.getfixturevalue(who)).get(AUDIT_URL).status_code == 403
    anonymous = Client().get(AUDIT_URL)
    assert anonymous.status_code == 302 and "/accounts/login/" in anonymous["Location"]


def test_screen_lists_changes_newest_first_with_actor_and_values(admin):
    record_change(actor=admin, entity_type="Department", entity_id=1, action="CREATE", new={"name": "First"})
    record_change(actor=admin, entity_type="Location", entity_id=2, action="UPDATE",
                  old={"block": "Old"}, new={"block": "New"})
    page = login(admin).get(AUDIT_URL).content.decode()
    assert admin.email in page and "block: Old" in page and "block: New" in page
    assert page.index("Location #2") < page.index("Department #1")


def test_screen_filters_by_entity_action_actor_and_date(admin):
    record_change(actor=admin, entity_type="Department", entity_id=1, action="CREATE", new={"name": "D"})
    record_change(actor=admin, entity_type="Location", entity_id=2, action="DEACTIVATE", old={"active": True}, new={"active": False})
    client = login(admin)
    by_entity = client.get(AUDIT_URL, {"entity_type": "Location"}).content.decode()
    assert "Location #2" in by_entity and "Department #1" not in by_entity
    by_action = client.get(AUDIT_URL, {"action": "CREATE"}).content.decode()
    assert "Department #1" in by_action and "Location #2" not in by_action
    assert "Department #1" in client.get(AUDIT_URL, {"actor": admin.email[:8]}).content.decode()
    assert "No configuration changes recorded" in client.get(AUDIT_URL, {"actor": "nobody@example.test"}).content.decode()
    assert "Department #1" in client.get(AUDIT_URL, {"date_from": "2000-01-01", "date_to": "2999-12-31"}).content.decode()
    assert "No configuration changes recorded" in client.get(AUDIT_URL, {"date_to": "2000-01-01"}).content.decode()


def test_invalid_filters_are_rejected_not_ignored(admin):
    response = login(admin).get(AUDIT_URL, {"entity_type": "complaint", "date_from": "not-a-date"})
    assert response.status_code == 400


def test_screen_pages_and_keeps_filters(admin):
    for i in range(55):
        record_change(actor=admin, entity_type="Department", entity_id=i, action="CREATE", new={"name": f"D{i}"})
    client = login(admin)
    first = client.get(AUDIT_URL, {"entity_type": "Department"}).content.decode()
    assert "Page 1 of 2" in first and "entity_type=Department&amp;page=2" in first
    assert "Page 2 of 2" in client.get(AUDIT_URL, {"entity_type": "Department", "page": 2}).content.decode()


def test_user_text_is_escaped_on_the_screen(admin):
    record_change(actor=admin, entity_type="Department", entity_id=1, action="CREATE",
                  new={"name": "<script>alert(1)</script>"})
    page = login(admin).get(AUDIT_URL).content.decode()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_admin_home_links_to_the_audit_log(admin):
    assert AUDIT_URL in login(admin).get("/accounts/landing/admin/").content.decode()
