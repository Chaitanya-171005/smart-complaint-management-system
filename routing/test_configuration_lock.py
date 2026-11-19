"""Real PostgreSQL lock-graph regressions; SQLite cannot prove these contracts.

SCMS_LOCK_TEST_ROUNDS=100 repeats each scenario. No arbitrary sleep establishes
ordering: pg_blocking_pids confirms the second backend waits for the first.
Without the configuration lock, routing/SLA probes form the original row-lock
cycle after the first backend is released.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from django.test import Client
from django.urls import reverse

from accounts.configuration_lock import lock_configuration
from accounts.models import ConfigAuditEvent, Department
from routing import services as svc
from routing.models import Category, RoutingRule, SLAConfiguration


@pytest.mark.django_db(transaction=True)
def test_configuration_lock_requires_transaction():
    with pytest.raises(TransactionManagementError):
        lock_configuration()


@pytest.mark.django_db
def test_nested_configuration_lock_is_reentrant():
    with transaction.atomic():
        lock_configuration()
        with transaction.atomic():
            lock_configuration()


def run_blocked_pair(first, second, *, hold_model=None, rollback_audit=False):
    held, release = Event(), Event()
    pids = {}
    original_lock, original_audit = svc._lock, svc._audit

    def hold():
        held.set()
        assert release.wait(8), 'Coordinator did not release first writer'

    def row_lock(model, instance, label):
        result = original_lock(model, instance, label)
        if current_thread().name.endswith('_0') and model is hold_model:
            hold()
        return result

    def audit(*args, **kwargs):
        result = original_audit(*args, **kwargs)
        if rollback_audit and current_thread().name.endswith('_0'):
            hold()
            raise RuntimeError('synthetic audit failure after durable writes')
        return result

    def worker(index, operation):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
                cursor.execute('SELECT pg_backend_pid()')
                pids[index] = cursor.fetchone()[0]
            try:
                return operation()
            except Exception as exc:
                return exc
        finally:
            connection.close()

    with patch.object(svc, '_lock', row_lock), patch.object(svc, '_audit', audit):
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='config-race') as pool:
            a = pool.submit(worker, 0, first)
            b = None
            try:
                assert held.wait(5), 'First writer did not reach the held boundary'
                b = pool.submit(worker, 1, second)
                deadline = time.monotonic() + 3
                blocked = False
                while time.monotonic() < deadline:
                    if 1 in pids:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT pg_blocking_pids(%s)', [pids[1]])
                            blocked = pids[0] in cursor.fetchone()[0]
                        if blocked:
                            break
                    time.sleep(0.01)
                assert blocked, 'Second writer never waited for first writer'
            finally:
                release.set()
            return a.result(timeout=12), b.result(timeout=12)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('scenario', ['routing_service', 'routing_http', 'sla', 'audit_rollback'])
def test_postgresql_configuration_lock_graph(
        scenario, scms_admin_user, department_factory, category_factory, location_factory):
    if connection.vendor != 'postgresql':
        pytest.skip('Requires real PostgreSQL row/advisory locks')
    rounds = int(os.environ.get('SCMS_LOCK_TEST_ROUNDS', '3'))
    assert rounds > 0
    admin = scms_admin_user
    # Login outside the raced transaction; a genuine endpoint request checks 500s.
    client = Client()
    client.force_login(admin)
    for _ in range(rounds):
        department, category = department_factory(), category_factory()
        if scenario.startswith('routing') or scenario == 'audit_rollback':
            old_location, new_location = location_factory(), location_factory()
            rule = svc.create_routing_rule(admin, category=category,
                department=department, location_code=old_location.code)
            before = ConfigAuditEvent.objects.count()
            def create():
                return svc.create_routing_rule(admin, department=Department.objects.get(pk=department.pk),
                                               location_code=new_location.code)
            def update():
                if scenario == 'routing_http':
                    response = client.post(reverse('routing:configuration'), {
                        'action': 'update_rule', 'rule_id': rule.pk, 'category_id': category.pk,
                        'department_id': department.pk, 'location_code': new_location.code,
                        'precedence': 20})
                    assert response.status_code == 302
                    return response.status_code
                return svc.update_routing_rule(admin, RoutingRule.objects.get(pk=rule.pk),
                                               location_code=new_location.code, precedence=20)
            results = run_blocked_pair(create, update,
                hold_model=None if scenario == 'audit_rollback' else Department,
                rollback_audit=scenario == 'audit_rollback')
            if scenario == 'audit_rollback':
                assert isinstance(results[0], RuntimeError), results
                assert str(results[0]) == 'synthetic audit failure after durable writes'
                assert not RoutingRule.objects.filter(category=None, location_code=new_location.code).exists()
                assert ConfigAuditEvent.objects.count() == before + 1
            else:
                assert not isinstance(results[0], Exception), results
                assert RoutingRule.objects.filter(category=None, location_code=new_location.code, active=True).count() == 1
                assert ConfigAuditEvent.objects.count() == before + 2
            assert not isinstance(results[1], Exception), results
            rule.refresh_from_db()
            assert rule.location_code == new_location.code and rule.active and rule.precedence == 20
            event = ConfigAuditEvent.objects.filter(entity_type='RoutingRule', entity_id=str(rule.pk)).first()
            assert event.old_values['location_code'] == old_location.code
            assert event.new_values['location_code'] == new_location.code
        else:
            config = svc.set_sla_configuration(admin, category=category, priority='LOW', duration_minutes=60)
            before = ConfigAuditEvent.objects.count()
            def update_sla():
                return svc.set_sla_configuration(admin, category=Category.objects.get(pk=category.pk),
                                                 priority='LOW', duration_minutes=120)
            def deactivate_sla():
                return svc.deactivate_sla_configuration(admin, SLAConfiguration.objects.get(pk=config.pk))
            results = run_blocked_pair(update_sla, deactivate_sla, hold_model=Category)
            assert not any(isinstance(result, Exception) for result in results), results
            config.refresh_from_db()
            assert config.duration_minutes == 120 and not config.active
            assert ConfigAuditEvent.objects.count() == before + 2
            event = ConfigAuditEvent.objects.filter(entity_type='SLAConfiguration', entity_id=str(config.pk)).first()
            assert event.old_values['duration_minutes'] == 120
            assert event.new_values['active'] is False


@pytest.mark.django_db(transaction=True)
def test_postgresql_original_routing_cycle_negative_control(
        scms_admin_user, department_factory, category_factory, location_factory):
    if connection.vendor != 'postgresql':
        pytest.skip('Requires real PostgreSQL deadlock detection')
    if os.environ.get('SCMS_LOCK_NEGATIVE_CONTROL') != '1':
        pytest.skip('Opt in only on a disposable test database; intentionally forms old cycle')
    admin = scms_admin_user
    department, category = department_factory(), category_factory()
    old_location, new_location = location_factory(), location_factory()
    rule = svc.create_routing_rule(admin, category=category, department=department,
                                   location_code=old_location.code)
    before = ConfigAuditEvent.objects.count()
    with patch.object(svc, 'lock_configuration', lambda: None):
        results = run_blocked_pair(
            lambda: svc.create_routing_rule(admin, department=Department.objects.get(pk=department.pk),
                                           location_code=new_location.code),
            lambda: svc.update_routing_rule(admin, RoutingRule.objects.get(pk=rule.pk),
                                           location_code=new_location.code),
            hold_model=Department)
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1, results
    assert getattr(errors[0].__cause__, 'sqlstate', None) == '40P01', results
    # The losing transaction, including its audit records, must be rolled back.
    assert ConfigAuditEvent.objects.count() == before + 1
