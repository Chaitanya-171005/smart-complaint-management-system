import pytest
from django.urls import reverse
from django.test import Client
from accounts.models import User
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db


def test_queue_and_assignment(client, head_user, staff_user, department, complaint_factory):
    complaint = complaint_factory(department=department)
    client.force_login(head_user)
    response = client.get(reverse('routing:queue'))
    assert response.status_code == 200
    assert complaint.complaint_id in response.content.decode()
    url = reverse('assign_complaint', args=[complaint.complaint_id])
    assert client.get(url).status_code == 405
    assert client.post(url, {'assignee': staff_user.pk, 'expected_assignee': ''}).status_code == 302
    complaint.refresh_from_db()
    assert complaint.assignee == staff_user
    assert ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id, event_type='ALLOCATED').count() == 1
    assert client.post(url, {'assignee': staff_user.pk, 'expected_assignee': ''}).status_code == 400
    assert ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).count() == 1


def test_assignment_csrf(head_user, staff_user, department, complaint_factory):
    complaint = complaint_factory(department=department)
    client = Client(enforce_csrf_checks=True)
    client.force_login(head_user)
    assert client.post(reverse('assign_complaint', args=[complaint.complaint_id]), {'assignee': staff_user.pk}).status_code == 403


@pytest.mark.parametrize('role', [User.Role.STAFF, User.Role.COMPLAINANT, User.Role.ADMIN])
def test_assignment_forbidden_roles(client, user_factory, department, staff_user, complaint_factory, role):
    user = user_factory(role=role, department=department if role == User.Role.STAFF else None)
    complaint = complaint_factory(department=department)
    client.force_login(user)
    assert client.post(reverse('assign_complaint', args=[complaint.complaint_id]), {'assignee': staff_user.pk}).status_code == 403
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()


def test_reassignment_history(client, head_user, staff_user, department, user_factory, complaint_factory):
    other = user_factory(role=User.Role.STAFF, department=department)
    complaint = complaint_factory(department=department)
    client.force_login(head_user)
    url = reverse('assign_complaint', args=[complaint.complaint_id])
    assert client.post(url, {'assignee': staff_user.pk}).status_code == 302
    assert client.post(url, {'assignee': other.pk, 'expected_assignee': staff_user.pk, 'reason': '  coverage  '}).status_code == 302
    events = list(ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).order_by('pk'))
    assert [(e.event_type, e.actor, e.assignee, e.remarks) for e in events] == [
        ('ALLOCATED', head_user, staff_user, ''), ('REASSIGNED', head_user, other, 'coverage')]
    complaint.refresh_from_db()
    assert complaint.assignee == other


@pytest.mark.parametrize('reason,same', [('', False), ('   ', False), ('x' * 501, False), ('reason', True)])
def test_reassignment_failures(client, head_user, staff_user, department, user_factory, complaint_factory, reason, same):
    other = user_factory(role=User.Role.STAFF, department=department)
    complaint = complaint_factory(department=department, assignee=staff_user)
    client.force_login(head_user)
    response = client.post(reverse('assign_complaint', args=[complaint.complaint_id]), {
        'assignee': staff_user.pk if same else other.pk, 'expected_assignee': staff_user.pk, 'reason': reason})
    assert response.status_code == 400
    complaint.refresh_from_db()
    assert complaint.assignee == staff_user
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()


@pytest.mark.parametrize('target', ['', 'invalid', '-1', '99999999'])
def test_invalid_assignee_http(client, head_user, department, complaint_factory, target):
    complaint = complaint_factory(department=department)
    client.force_login(head_user)
    assert client.post(reverse('assign_complaint', args=[complaint.complaint_id]), {'assignee': target}).status_code in (400, 403)
    complaint.refresh_from_db()
    assert complaint.assignee is None
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()


@pytest.mark.parametrize('kind', ['inactive', 'cross'])
def test_ineligible_staff_http(client, head_user, department, department_factory, user_factory, complaint_factory, kind):
    target = user_factory(role=User.Role.STAFF, department=department_factory() if kind == 'cross' else department, is_active=kind != 'inactive')
    complaint = complaint_factory(department=department)
    client.force_login(head_user)
    assert client.post(reverse('assign_complaint', args=[complaint.complaint_id]), {'assignee': target.pk}).status_code == 403
    complaint.refresh_from_db()
    assert complaint.assignee is None
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()


@pytest.mark.parametrize('status', ['SUBMITTED', 'RESOLVED', 'CLOSED', 'REJECTED'])
def test_invalid_status_http(client, head_user, staff_user, department, complaint_factory, status):
    complaint = complaint_factory(department=department, status=status)
    client.force_login(head_user)
    assert client.post(reverse('assign_complaint', args=[complaint.complaint_id]), {'assignee': staff_user.pk}).status_code == 400
    complaint.refresh_from_db()
    assert complaint.assignee is None
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()


def test_anonymous_and_cross_department_http(client, head_user, staff_user, department_factory, complaint_factory):
    complaint = complaint_factory(department=department_factory())
    url = reverse('assign_complaint', args=[complaint.complaint_id])
    assert client.get(reverse('routing:queue')).status_code == 302
    assert client.post(url, {'assignee': staff_user.pk}).status_code == 302
    client.force_login(head_user)
    assert client.post(url, {'assignee': staff_user.pk}).status_code == 404
    assert complaint.complaint_id not in client.get(reverse('routing:queue')).content.decode()
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()


def test_http_history_failure_rolls_back(client, head_user, staff_user, department, complaint_factory, monkeypatch):
    complaint = complaint_factory(department=department)
    client.force_login(head_user)
    def fail(*args, **kwargs):
        raise RuntimeError('history failure')
    monkeypatch.setattr('routing.allocation.record_history', fail)
    with pytest.raises(RuntimeError, match='history failure'):
        client.post(reverse('assign_complaint', args=[complaint.complaint_id]), {'assignee': staff_user.pk})
    complaint.refresh_from_db()
    assert complaint.assignee is None
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('reassignment', [False, True])
def test_competing_http_assignments(head_user, staff_user, department, user_factory, complaint_factory, reassignment):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    other = user_factory(role=User.Role.STAFF, department=department)
    original = user_factory(role=User.Role.STAFF, department=department) if reassignment else None
    complaint = complaint_factory(department=department, assignee=original)
    url = reverse('assign_complaint', args=[complaint.complaint_id])
    barrier = Barrier(2)
    def submit(target):
        close_old_connections()
        client = Client()
        client.force_login(head_user)
        barrier.wait(timeout=10)
        try:
            return client.post(url, {'assignee': target, 'expected_assignee': original.pk if original else '', 'reason': 'coverage' if original else ''}).status_code
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [staff_user.pk, other.pk]))
    assert sorted(results) == [302, 400]
    complaint.refresh_from_db()
    event = ComplaintHistory.objects.get(complaint_ref=complaint.complaint_id)
    assert event.event_type == ('REASSIGNED' if reassignment else 'ALLOCATED')
    assert event.actor_id == head_user.pk
    assert event.assignee_id == complaint.assignee_id
    assert complaint.assignee_id in (staff_user.pk, other.pk)
    assert event.remarks == ('coverage' if reassignment else '')


@pytest.mark.parametrize('role', [User.Role.COMPLAINANT, User.Role.ADMIN])
def test_queue_forbidden_roles(client, user_factory, role):
    client.force_login(user_factory(role=role))
    assert client.get(reverse('routing:queue')).status_code == 403


def test_staff_queue_and_pagination(client, staff_user, department, department_factory, complaint_factory):
    complaints = [complaint_factory(department=department) for _ in range(26)]
    other = complaint_factory(department=department_factory())
    client.force_login(staff_user)
    first = client.get(reverse('routing:queue'))
    second = client.get(reverse('routing:queue'), {'page': 2})
    assert first.status_code == second.status_code == 200
    assert len(first.context['page']) == 25 and len(second.context['page']) == 1
    assert set(first.context['page'].object_list) | set(second.context['page'].object_list) == set(complaints)
    assert other.complaint_id not in first.content.decode()
    assert b'<form' not in first.content


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('kind', ['cross_complaint', 'inactive_staff', 'cross_staff', 'missing_staff', 'staff_actor'])
def test_http_denial_preserves_security_event(client, head_user, staff_user, department,
                                               department_factory, user_factory, complaint_factory, kind):
    from accounts.models import SecurityEvent
    complaint = complaint_factory(department=department_factory() if kind == 'cross_complaint' else department,
                                  assignee=staff_user)
    actor = staff_user if kind == 'staff_actor' else head_user
    if kind == 'inactive_staff':
        target = user_factory(role=User.Role.STAFF, department=department, is_active=False).pk
    elif kind == 'cross_staff':
        target = user_factory(role=User.Role.STAFF, department=department_factory()).pk
    elif kind == 'missing_staff':
        target = 99999999
    else:
        target = staff_user.pk
    client.force_login(actor)
    before = SecurityEvent.objects.count()
    response = client.post(reverse('assign_complaint', args=[complaint.complaint_id]),
                           {'assignee': target, 'expected_assignee': staff_user.pk, 'reason': 'coverage'})
    assert response.status_code == (404 if kind == 'cross_complaint' else 403)
    complaint.refresh_from_db()
    assert complaint.assignee_id == staff_user.pk
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()
    events = SecurityEvent.objects.order_by('pk')[before:]
    assert len(events) == 1
    assert events[0].event_type == SecurityEvent.EventType.AUTHORIZATION_REFUSED
    assert events[0].user_id == actor.pk
