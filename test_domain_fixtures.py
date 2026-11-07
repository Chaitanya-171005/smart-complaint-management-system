"""E02 contracts for reusable real-model fixtures; all values are synthetic."""

import re

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError


@pytest.fixture
def real_complaint_factory(complaint_factory):
    try:
        apps.get_model("complaints", "Complaint")
    except LookupError:
        pytest.skip("Complaint fixture checks require the schema from PR #62.")
    return complaint_factory


def test_reference_factories_are_unique_and_keep_overrides(category_factory, location_factory):
    categories = [category_factory() for _ in range(3)]
    locations = [location_factory() for _ in range(3)]
    assert len({row.name for row in categories}) == 3
    assert len({row.code for row in locations}) == 3
    assert all(row.name.startswith("Synthetic Category ") for row in categories)
    assert all(row.code.startswith("TEST-") for row in locations)
    category = category_factory(name="Synthetic inactive category", active=False)
    location = location_factory(code="TEST-CLOSED", room_area="Closed room", active=False)
    assert not category.active and not location.active
    assert location.room_area == "Closed room"


def test_rule_factory_preserves_location_scope_and_department(routing_rule_factory, location_factory,
                                                             department_factory):
    location = location_factory()
    department = department_factory()
    rule = routing_rule_factory(category=None, location_code=location.code.lower(),
                                department=department, precedence=7)
    rule.refresh_from_db()
    assert rule.category_id is None
    assert rule.location_code == location.code
    assert rule.scope_key == f"0:{location.code}"
    assert rule.department_id == department.pk and rule.precedence == 7


def test_sla_factory_does_not_replace_seeded_global_policy(sla_factory):
    from routing.models import SLAConfiguration

    before = list(SLAConfiguration.objects.filter(category=None).values())
    rows = [sla_factory() for _ in range(2)]
    assert rows[0].category_id != rows[1].category_id
    assert all(row.scope_key == f"{row.category_id}:LOW" for row in rows)
    assert list(SLAConfiguration.objects.filter(category=None).values()) == before


def test_routing_configuration_is_one_consistent_graph(routing_configuration):
    config = routing_configuration
    assert config["rule"].category_id == config["sla"].category_id == config["category"].pk
    assert config["rule"].location_code == config["location"].code
    assert config["rule"].department_id == config["policy"].default_department_id == config["department"].pk
    assert config["policy"].key == "default"
    assert config["sla"].duration_minutes == config["policy"].interval_minutes == 120
    assert config["policy"].maximum_level == 2


@pytest.mark.parametrize("case", [1, 2])
def test_reference_factory_rows_do_not_leak_between_tests(case, category_factory, location_factory):
    from accounts.models import Location
    from routing.models import Category

    name, code = "Synthetic isolation category", "TEST-ISOLATION"
    assert not Category.objects.filter(name=name).exists()
    assert not Location.objects.filter(code=code).exists()
    category_factory(name=name)
    location_factory(code=code)
    assert Category.objects.filter(name=name).count() == 1
    assert Location.objects.filter(code=code).count() == 1


@pytest.mark.parametrize("anonymous", [False, True])
def test_complaint_factory_persists_valid_identity(real_complaint_factory, anonymous):
    complaint = real_complaint_factory(anonymous=anonymous)
    complaint.refresh_from_db()
    complaint.full_clean()
    assert re.fullmatch(r"SCMS-[0-9]{4}-[0-9]{6}", complaint.complaint_id)
    if anonymous:
        assert complaint.submitted_by_id is None
        assert re.fullmatch(r"[0-9a-f]{64}", complaint.reference_digest)
    else:
        assert complaint.submitted_by_id is not None
        assert complaint.reference_digest is None


def test_complaint_factory_preserves_explicit_graph(real_complaint_factory, routing_configuration,
                                                   user_factory, staff_user):
    config = routing_configuration
    owner = user_factory()
    complaint = real_complaint_factory(
        category_record=config["category"], location_record=config["location"],
        submitted_by=owner, department=config["department"], assignee=staff_user,
        priority="HIGH", status="ASSIGNED", unrouted=False,
        routing_rule_key=str(config["rule"].pk),
    )
    assert complaint.category_key == str(config["category"].pk)
    assert complaint.category == config["category"].name
    assert complaint.location_code == config["location"].code
    assert complaint.submitted_by_id == owner.pk
    assert complaint.department_id == staff_user.department_id
    assert complaint.assignee_id == staff_user.pk
    assert complaint.priority == "HIGH" and complaint.status == "ASSIGNED"
    assert complaint.routing_rule_key == str(config["rule"].pk)


def test_repeated_complaint_factory_calls_reserve_unique_ids(real_complaint_factory):
    from complaints.models import ComplaintIdSequence

    rows = [real_complaint_factory(anonymous=True) for _ in range(3)]
    assert len({row.pk for row in rows}) == 3
    assert len({row.complaint_id for row in rows}) == 3
    assert len({row.reference_digest for row in rows}) == 3
    year = int(rows[0].complaint_id.split("-")[1])
    assert ComplaintIdSequence.objects.get(year=year).last_value == 3


def test_failed_complaint_fixture_rolls_back_its_graph_and_id(real_complaint_factory):
    from accounts.models import Location
    from complaints.models import Complaint, ComplaintIdSequence
    from routing.models import Category

    before = (Category.objects.count(), Location.objects.count(), Complaint.objects.count(),
              list(ComplaintIdSequence.objects.values_list("year", "last_value")))
    with pytest.raises(ValidationError):
        real_complaint_factory(rating=6)
    after = (Category.objects.count(), Location.objects.count(), Complaint.objects.count(),
             list(ComplaintIdSequence.objects.values_list("year", "last_value")))
    assert after == before


def test_anonymous_factory_refuses_an_account_link(real_complaint_factory, user_factory):
    with pytest.raises(ValidationError):
        real_complaint_factory(anonymous=True, submitted_by=user_factory())


@pytest.mark.parametrize("case", [1, 2])
def test_complaint_factory_database_isolation(case, real_complaint_factory):
    from complaints.models import Complaint

    identifier = "SCMS-2026-999998"
    assert not Complaint.objects.filter(complaint_id=identifier).exists()
    real_complaint_factory(complaint_id=identifier)
    assert Complaint.objects.filter(complaint_id=identifier).count() == 1
