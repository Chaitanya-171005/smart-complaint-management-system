"""#96 under real concurrency: a deactivation racing a routing change never leaves routing broken.

Each case races F1's deactivation against the F3 change that depends on the same record, many times,
and checks the invariant afterwards. The invariant must hold whichever side wins. These run on SQLite
(writers serialize) and PostgreSQL (row locks); the PostgreSQL run is the meaningful one.
"""

from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from accounts import reference_services as svc
from accounts.models import Department, Location
from routing.models import EscalationPolicy, RoutingRule
from routing.services import create_escalation_policy, create_routing_rule, update_escalation_policy

pytestmark = pytest.mark.django_db(transaction=True)
ROUNDS = 25
# A refusal is the expected loser; anything else (deadlock, integrity error) is a defect.
EXPECTED_REFUSALS = ("ValidationError", "ConfigurationError")


def race(*jobs):
    barrier = Barrier(len(jobs))
    outcomes = [None] * len(jobs)

    def runner(index, job):
        close_old_connections()
        try:
            barrier.wait(timeout=15)
            job()
            outcomes[index] = "ok"
        except Exception as exc:  # noqa: BLE001 - recorded and judged by the caller
            outcomes[index] = exc
        finally:
            connection.close()

    from threading import Thread

    threads = [Thread(target=runner, args=(i, job)) for i, job in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    for outcome in outcomes:
        assert outcome == "ok" or type(outcome).__name__ in EXPECTED_REFUSALS, repr(outcome)
    return outcomes


@pytest.fixture
def admin(scms_admin_user):
    return scms_admin_user


def test_deactivating_a_department_while_a_rule_is_created_for_it(admin, department_factory, category_factory):
    for _ in range(ROUNDS):
        department, category = department_factory(), category_factory()
        race(
            lambda: svc.set_department_active(admin, department, False),
            lambda: create_routing_rule(admin, category=category, department=department),
        )
        department.refresh_from_db()
        has_active_rule = RoutingRule.objects.filter(department=department, active=True).exists()
        assert not (not department.active and has_active_rule), "active rule on a deactivated department"


def test_deactivating_a_department_while_it_becomes_the_default(admin, department_factory):
    for _ in range(ROUNDS):
        current, candidate = department_factory(), department_factory()
        EscalationPolicy.objects.all().delete()
        policy = create_escalation_policy(admin, default_department=current, interval_minutes=1440, maximum_level=3)
        race(
            lambda: svc.set_department_active(admin, candidate, False),
            lambda: update_escalation_policy(admin, policy, default_department=candidate),
        )
        policy.refresh_from_db()
        assert policy.default_department.active, "default department was left inactive"


def test_deactivating_a_location_while_a_rule_is_created_for_it(admin, department_factory, category_factory, location_factory):
    department = department_factory()
    for _ in range(ROUNDS):
        location, category = location_factory(), category_factory()
        race(
            lambda: svc.set_location_active(admin, location, False),
            lambda: create_routing_rule(admin, category=category, location_code=location.code, department=department),
        )
        location.refresh_from_db()
        has_active_rule = RoutingRule.objects.filter(location_code=location.code, active=True).exists()
        assert not (not location.active and has_active_rule), "active rule on a deactivated location"
