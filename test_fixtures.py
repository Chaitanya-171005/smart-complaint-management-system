"""Verify shared fixture contracts, uniqueness and database isolation (E02/VM-04)."""

import pytest

from accounts.models import Department, User


def test_department_fixture(department):
    assert department.pk is not None
    assert department.active is True
    assert department.name.startswith("Synthetic Department ")


@pytest.mark.parametrize(
    "fixture_name,role,has_department",
    [
        ("complainant_user", User.Role.COMPLAINANT, False),
        ("staff_user", User.Role.STAFF, True),
        ("head_user", User.Role.HEAD, True),
        ("scms_admin_user", User.Role.ADMIN, False),
    ],
)
def test_named_user_fixtures(request, fixture_name, role, has_department):
    user = request.getfixturevalue(fixture_name)
    assert user.pk is not None
    assert user.role == role
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.check_password("SyntheticTest123!")
    assert user.password != "SyntheticTest123!"
    if has_department:
        assert user.department_id == request.getfixturevalue("department").pk
    else:
        assert user.department_id is None


def test_role_fixtures_share_department(staff_user, head_user, department):
    assert staff_user.department_id == head_user.department_id == department.pk
    assert staff_user.pk != head_user.pk
    assert staff_user.email != head_user.email


def test_repeated_factory_calls_are_unique(user_factory, department_factory):
    users = [user_factory() for _ in range(3)]
    departments = [department_factory() for _ in range(3)]
    assert len({user.email for user in users}) == 3
    assert len({user.pk for user in users}) == 3
    assert len({department.name for department in departments}) == 3
    assert len({department.pk for department in departments}) == 3
    assert all(user.role == User.Role.COMPLAINANT for user in users)
    assert all(user.department_id is None for user in users)


def test_factory_overrides(user_factory, department_factory):
    department = department_factory(name="Synthetic Closed Department", active=False)
    user = user_factory(
        email="override@example.test",
        full_name="Synthetic Resolver",
        password="OverridePassword123!",
        role=User.Role.STAFF,
        department=department,
    )
    assert department.name == "Synthetic Closed Department"
    assert department.active is False
    assert user.email == "override@example.test"
    assert user.full_name == "Synthetic Resolver"
    assert user.role == User.Role.STAFF
    assert user.department_id == department.pk
    assert user.check_password("OverridePassword123!")


@pytest.mark.parametrize("case", [1, 2])
def test_fixture_database_isolation(case, user_factory, department_factory):
    # Each case starts without the previous case's rows, then creates the same
    # unique values. This verifies rollback without relying on execution order.
    email = "fixture-isolation@example.test"
    name = "Synthetic Isolation Department"
    assert not User.objects.filter(email=email).exists()
    assert not Department.objects.filter(name=name).exists()
    user_factory(email=email, department=department_factory(name=name))
    assert User.objects.filter(email=email).count() == 1
    assert Department.objects.filter(name=name).count() == 1
