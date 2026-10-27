"""Shared synthetic fixtures; these are not confirmed campus data."""

from uuid import uuid4

import pytest


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
def user_factory(db, django_user_model):
    def create_user(**overrides):
        password = overrides.pop("password", "SyntheticTest123!")
        values = {
            "email": f"synthetic-{uuid4().hex}@example.test",
            "full_name": "Synthetic Test User",
            "role": "COMPLAINANT",
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
    return user_factory(role="STAFF", department=department)


@pytest.fixture
def head_user(user_factory, department):
    return user_factory(role="HEAD", department=department)


@pytest.fixture
def scms_admin_user(user_factory):
    return user_factory(role="ADMIN")
