"""F1 refuses to deactivate a department or location that F3 routing still depends on.

F3 owns what "in use" means (routing.services.department_in_use / location_in_use); F1 must call it
(docs/REFERENCE_DATA.md). Without it an Administrator could deactivate the default department and
break fallback routing.
"""

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from accounts import reference_services as svc
from accounts.models import ConfigAuditEvent, Department, Location
from routing.services import (
    create_escalation_policy,
    create_routing_rule,
    deactivate_routing_rule,
    update_escalation_policy,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(scms_admin_user):
    return scms_admin_user


def audit_count():
    return ConfigAuditEvent.objects.count()


def make_default_policy(admin, department):
    return create_escalation_policy(admin, default_department=department, interval_minutes=1440, maximum_level=3)


# --- departments ---------------------------------------------------------------------------------


def test_default_department_cannot_be_deactivated(admin, department_factory):
    default = department_factory()
    make_default_policy(admin, default)
    before = audit_count()

    with pytest.raises(ValidationError, match="default for escalation"):
        svc.set_department_active(admin, default, False)

    default.refresh_from_db()
    assert default.active is True
    assert audit_count() == before  # a refused change leaves no audit record


def test_default_can_be_deactivated_after_choosing_another_default(admin, department_factory):
    first, second = department_factory(), department_factory()
    policy = make_default_policy(admin, first)
    update_escalation_policy(admin, policy, default_department=second)

    svc.set_department_active(admin, first, False)

    first.refresh_from_db()
    assert first.active is False
    assert ConfigAuditEvent.objects.filter(entity_type="Department", action="DEACTIVATE").count() == 1


def test_department_with_an_active_rule_cannot_be_deactivated_until_the_rule_is(
    admin, department_factory, category_factory
):
    department = department_factory()
    rule = create_routing_rule(admin, category=category_factory(), department=department)

    with pytest.raises(ValidationError):
        svc.set_department_active(admin, department, False)

    deactivate_routing_rule(admin, rule)
    svc.set_department_active(admin, department, False)
    department.refresh_from_db()
    assert department.active is False


def test_unused_department_and_reactivation_are_unaffected(admin, department_factory):
    unused = department_factory()
    svc.set_department_active(admin, unused, False)
    svc.set_department_active(admin, unused, True)
    unused.refresh_from_db()
    assert unused.active is True


# --- locations -----------------------------------------------------------------------------------


def test_location_with_an_active_rule_cannot_be_deactivated(admin, department_factory, category_factory, location_factory):
    location = location_factory()
    rule = create_routing_rule(
        admin, category=category_factory(), location_code=location.code, department=department_factory()
    )
    before = audit_count()

    with pytest.raises(ValidationError, match="active routing rules"):
        svc.set_location_active(admin, location, False)
    location.refresh_from_db()
    assert location.active is True and audit_count() == before

    deactivate_routing_rule(admin, rule)
    svc.set_location_active(admin, location, False)
    location.refresh_from_db()
    assert location.active is False


def test_unused_location_can_still_be_deactivated(admin, location_factory):
    location = location_factory()
    svc.set_location_active(admin, location, False)
    location.refresh_from_db()
    assert location.active is False


# --- what the Administrator sees ------------------------------------------------------------------


def test_screen_explains_the_refusal_and_changes_nothing(admin, department_factory):
    default = department_factory()
    make_default_policy(admin, default)
    client = Client()
    client.force_login(admin)

    response = client.post(f"/accounts/admin-config/departments/{default.pk}/active/", {"active": "false"})

    assert response.status_code == 409
    assert b"default for escalation" in response.content
    default.refresh_from_db()
    assert default.active is True


def test_location_screen_explains_the_refusal(admin, department_factory, category_factory, location_factory):
    location = location_factory()
    create_routing_rule(admin, category=category_factory(), location_code=location.code, department=department_factory())
    client = Client()
    client.force_login(admin)

    response = client.post(f"/accounts/admin-config/locations/{location.pk}/active/", {"active": "false"})

    assert response.status_code == 409
    assert b"active routing rules" in response.content
    location.refresh_from_db()
    assert location.active is True
