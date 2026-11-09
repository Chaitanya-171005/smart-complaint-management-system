"""Shared synthetic fixtures; these are not confirmed campus data."""

from uuid import uuid4

import pytest

from accounts.models import User


@pytest.fixture
def department_factory(db):
    from accounts.models import Department

    def create_department(**overrides):
        values = {
            "name": f"Synthetic Department {uuid4().hex[:12]}",
            "active": True,
        }
        values.update(overrides)
        return Department.objects.create(**values)

    return create_department


@pytest.fixture
def department(department_factory):
    return department_factory()


@pytest.fixture
def fixture_password_hasher(settings):
    """Use a cheap salted hasher only in tests requesting shared user fixtures."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def user_factory(db, django_user_model, fixture_password_hasher):
    def create_user(**overrides):
        password = overrides.pop("password", "SyntheticTest123!")
        values = {
            "email": f"synthetic-{uuid4().hex}@example.test",
            "full_name": "Synthetic Test User",
            "role": User.Role.COMPLAINANT,
        }
        values.update(overrides)
        return django_user_model.objects.create_user(
            password=password, **values
        )

    return create_user


@pytest.fixture
def complainant_user(user_factory):
    return user_factory()


@pytest.fixture
def staff_user(user_factory, department):
    return user_factory(role=User.Role.STAFF, department=department)


@pytest.fixture
def head_user(user_factory, department):
    return user_factory(role=User.Role.HEAD, department=department)


@pytest.fixture
def scms_admin_user(user_factory):
    return user_factory(role=User.Role.ADMIN)


@pytest.fixture
def category_factory(db):
    from routing.models import Category

    def create_category(**overrides):
        values = {"name": f"Synthetic Category {uuid4().hex[:12]}"}
        values.update(overrides)
        category = Category(**values)
        category.full_clean()
        category.save()
        return category

    return create_category


@pytest.fixture
def location_factory(db):
    from accounts.models import Location

    def create_location(**overrides):
        suffix = uuid4().hex[:12].upper()
        values = {
            "code": f"TEST-{suffix}",
            "block": "Synthetic block", "floor": "1", "room_area": f"Synthetic {suffix}",
        }
        values.update(overrides)
        location = Location(**values)
        location.full_clean()
        location.save()
        return location

    return create_location


@pytest.fixture
def routing_rule_factory(db, category_factory, department):
    from routing.models import RoutingRule

    def create_rule(**overrides):
        values = {"department": department}
        if "category" not in overrides and "category_id" not in overrides:
            values["category"] = category_factory()
        values.update(overrides)
        rule = RoutingRule(**values)
        rule.full_clean(exclude=["scope_key"])
        rule.save()
        return rule

    return create_rule


@pytest.fixture
def sla_factory(db, category_factory):
    from routing.models import Priority, SLAConfiguration

    def create_sla(**overrides):
        # Category-specific defaults leave B17's seeded global SLAs untouched.
        values = {"priority": Priority.LOW, "duration_minutes": 120}
        if "category" not in overrides and "category_id" not in overrides:
            values["category"] = category_factory()
        values.update(overrides)
        sla = SLAConfiguration(**values)
        sla.full_clean(exclude=["scope_key"])
        sla.save()
        return sla

    return create_sla


@pytest.fixture
def routing_configuration(db, department, category_factory, location_factory,
                          routing_rule_factory, sla_factory):
    """One synthetic route/SLA/fallback graph, isolated by pytest's DB rollback."""
    from routing.models import EscalationPolicy

    category = category_factory()
    location = location_factory()
    rule = routing_rule_factory(category=category, location_code=location.code)
    sla = sla_factory(category=category)
    policy = EscalationPolicy.objects.filter(key="default").first()
    if policy is None:
        policy = EscalationPolicy(key="default")
    policy.default_department = department
    policy.interval_minutes = 120
    policy.maximum_level = 2
    policy.full_clean()
    policy.save()
    return {"department": department, "category": category, "location": location,
            "rule": rule, "sla": sla, "policy": policy}


@pytest.fixture
def complaint_factory(db, user_factory, department, category_factory, location_factory):
    """Persist valid synthetic Complaints in the merged application schema.

    category_record/location_record select references; other overrides name model
    fields. anonymous=True generates a digest and discards the raw reference.
    The two-hour due time is test data, not a routing/SLA policy implementation.
    """
    from datetime import timedelta

    from django.apps import apps
    from django.db import transaction
    from django.utils import timezone

    from complaints.identifiers import allocate_complaint_id

    def create_complaint(*, category_record=None, location_record=None,
                         anonymous=False, **overrides):
        model = apps.get_model("complaints", "Complaint")
        with transaction.atomic():
            category = category_record if category_record is not None else category_factory()
            location = location_record if location_record is not None else location_factory()
            submitted_at = overrides.get("submitted_at", timezone.now())
            values = {
                "category_key": str(category.pk), "category": category.name,
                "location_code": location.code, "block": location.block,
                "floor": location.floor, "room_area": location.room_area,
                "title": "Synthetic faulty light",
                "description": "The light in this synthetic test room does not turn on.",
                "priority": model.Priority.LOW, "department": department,
                "submitted_at": submitted_at, "due_at": submitted_at + timedelta(hours=2),
                "status": model.Status.ASSIGNED, "unrouted": True,
            }
            values.update(overrides)
            if "complaint_id" not in values:
                values["complaint_id"] = allocate_complaint_id(submitted_at=submitted_at)
            if "submitted_by" not in values and "submitted_by_id" not in values:
                values["submitted_by"] = None if anonymous else user_factory()
            complaint = model(**values)
            if anonymous and complaint.reference_digest is None:
                complaint.issue_anonymous_reference()
            complaint.full_clean()
            complaint.save()
            return complaint

    return create_complaint
