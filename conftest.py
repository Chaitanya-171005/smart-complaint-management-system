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
