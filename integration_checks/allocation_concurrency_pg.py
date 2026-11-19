"""Real PostgreSQL lock compatibility: small deterministic reproductions, not Q04 load."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from django.db import connection, connections, transaction, OperationalError
from django.db.models.query import QuerySet
import pytest
from accounts.models import User
from routing.allocation import allocate_complaint, StaleAllocation
from workflow.models import ComplaintHistory, NotificationEvent, Notification, EmailDelivery

pytestmark=pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def requires_real_postgresql():
    assert connection.vendor=='postgresql','This required check must run against real isolated PostgreSQL.'


def worker_call(head,staff,complaint):
    connections.close_all()
    try:
        with transaction.atomic():
            with connection.cursor() as c:c.execute("SET LOCAL lock_timeout = '5s'")
            allocate_complaint(actor=head,complaint_id=complaint.complaint_id,assignee=staff,expected_assignee_id=None)
        return 'committed'
    except StaleAllocation:
        return 'modified_record'
    except OperationalError as error:
        return getattr(error.__cause__,'sqlstate','OperationalError')
    finally:
        connections.close_all()


def test_two_heads_same_staff_keep_all_notification_foreign_keys_without_deadlock(user_factory,department,complaint_factory,monkeypatch):
    heads=[user_factory(role='HEAD',department=department) for _ in range(2)]
    staff=user_factory(role='STAFF',department=department)
    complaints=[complaint_factory(department=department) for _ in heads]
    barrier=Barrier(2);original=QuerySet.first;head_ids={h.pk for h in heads}
    def synchronized_first(qs):
        obj=original(qs)
        if qs.model is User and qs.query.select_for_update and obj and obj.pk in head_ids:
            barrier.wait(timeout=10)
        return obj
    monkeypatch.setattr(QuerySet,'first',synchronized_first)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker_call,h,staff,c) for h,c in zip(heads,complaints)]
        outcomes=[f.result(timeout=20) for f in futures]
    print('two_head_outcomes',outcomes)
    assert outcomes==['committed','committed']
    for head,complaint in zip(heads,complaints):
        complaint.refresh_from_db();assert complaint.assignee_id==staff.pk
        history=ComplaintHistory.objects.get(complaint_ref=complaint.complaint_id)
        assert history.actor_id==head.pk and history.assignee_id==staff.pk
        event=NotificationEvent.objects.get(history=history)
        expected={h.pk for h in heads}|{staff.pk,complaint.submitted_by_id}
        assert set(Notification.objects.filter(event=event).values_list('recipient_id',flat=True))==expected
        assert set(EmailDelivery.objects.filter(notice__event=event).values_list('notice__recipient_id',flat=True))==expected


@pytest.mark.parametrize('who,field,value',[('head','role','STAFF'),('head','is_active',False),('staff','role','COMPLAINANT'),('staff','is_active',False),('head','department_id','OTHER'),('staff','department_id','OTHER')])
def test_authorization_changes_still_block_until_allocation_commits(user_factory,department,complaint_factory,department_factory,monkeypatch,who,field,value):
    import routing.allocation as module
    if value=='OTHER':value=department_factory().pk
    head=user_factory(role='HEAD',department=department);staff=user_factory(role='STAFF',department=department)
    complaint=complaint_factory(department=department)
    locked=Event();release=Event();original=module.record_history
    def paused_history(*args,**kwargs):
        locked.set()
        assert release.wait(timeout=10)
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'record_history',paused_history)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(worker_call,head,staff,complaint)
        try:
            assert locked.wait(timeout=10)
            with pytest.raises(OperationalError) as caught:
                with transaction.atomic():
                    with connection.cursor() as c:c.execute("SET LOCAL lock_timeout = '200ms'")
                    User.objects.filter(pk=(head if who=='head' else staff).pk).update(**{field:value})
            assert caught.value.__cause__.sqlstate=='55P03'
        finally:
            release.set()
        assert future.result(timeout=15)=='committed'
    head.refresh_from_db();staff.refresh_from_db();complaint.refresh_from_db()
    assert head.role=='HEAD' and head.is_active and staff.role=='STAFF' and staff.is_active
    assert complaint.assignee_id==staff.pk
    assert head.department_id==staff.department_id==department.pk


def test_two_heads_same_complaint_commit_only_one_assignment(user_factory,department,complaint_factory,monkeypatch):
    heads=[user_factory(role='HEAD',department=department) for _ in range(2)]
    staff=user_factory(role='STAFF',department=department)
    complaint=complaint_factory(department=department)
    barrier=Barrier(2);original=QuerySet.first;head_ids={h.pk for h in heads}
    def synchronized_first(qs):
        obj=original(qs)
        if qs.model is User and qs.query.select_for_update and obj and obj.pk in head_ids:
            barrier.wait(timeout=10)
        return obj
    monkeypatch.setattr(QuerySet,'first',synchronized_first)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker_call,h,staff,complaint) for h in heads]
        outcomes=[f.result(timeout=20) for f in futures]
    assert sorted(outcomes)==['committed','modified_record']
    complaint.refresh_from_db();assert complaint.assignee_id==staff.pk
    history=ComplaintHistory.objects.get(complaint_ref=complaint.complaint_id)
    assert history.actor_id in head_ids and history.assignee_id==staff.pk
    event=NotificationEvent.objects.get(history=history)
    assert event.notices.count()==EmailDelivery.objects.filter(notice__event=event).count()==4


def test_independent_assignments_can_hold_the_same_staff_reference_concurrently(user_factory,department,complaint_factory,monkeypatch):
    import routing.allocation as module
    heads=[user_factory(role='HEAD',department=department) for _ in range(2)]
    staff=user_factory(role='STAFF',department=department)
    complaints=[complaint_factory(department=department) for _ in heads]
    original=module._lock_assignment_target;barrier=Barrier(2)
    def synchronized_reference(target_id):
        target=original(target_id)
        barrier.wait(timeout=3)
        return target
    monkeypatch.setattr(module,'_lock_assignment_target',synchronized_reference)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker_call,h,staff,c) for h,c in zip(heads,complaints)]
        outcomes=[f.result(timeout=15) for f in futures]
    assert outcomes==['committed','committed']
    for complaint in complaints:
        complaint.refresh_from_db();assert complaint.assignee_id==staff.pk
        history=ComplaintHistory.objects.get(complaint_ref=complaint.complaint_id)
        assert history.assignee_id==staff.pk
        assert NotificationEvent.objects.get(history=history).notices.count()==4


@pytest.mark.parametrize('change',['role','department','active'])
def test_reused_wsgi_connection_still_refreshes_authorization(client,user_factory,department,department_factory,complaint_factory,change):
    head=user_factory(role='HEAD',department=department)
    complaint=complaint_factory(department=department)
    age=connection.settings_dict.get('CONN_MAX_AGE',0)
    checks=connection.settings_dict.get('CONN_HEALTH_CHECKS',False)
    connection.close();connection.settings_dict.update(CONN_MAX_AGE=60,CONN_HEALTH_CHECKS=True)
    try:
        client.force_login(head)
        first=client.get('/routing/queue/');assert first.status_code==200
        assert complaint.complaint_id.encode() in first.content
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_backend_pid()');before=cursor.fetchone()[0]
        fields={'role':'COMPLAINANT'} if change=='role' else ({'department_id':department_factory().pk} if change=='department' else {'is_active':False})
        User.objects.filter(pk=head.pk).update(**fields)
        second=client.get('/routing/queue/')
        assert second.status_code=={'role':403,'department':200,'active':302}[change]
        assert complaint.complaint_id.encode() not in second.content
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_backend_pid()');after=cursor.fetchone()[0]
        assert before==after  # Same live connection, newly read authorization.
    finally:
        connection.close();connection.settings_dict.update(CONN_MAX_AGE=age,CONN_HEALTH_CHECKS=checks)


def test_staff_reference_rejects_sql_text_and_preserves_the_original_graph(user_factory,department,complaint_factory):
    head=user_factory(role='HEAD',department=department);staff=user_factory(role='STAFF',department=department)
    complaint=complaint_factory(department=department)
    with pytest.raises(ValueError):
        allocate_complaint(actor=head,complaint_id=complaint.complaint_id,assignee='1 OR 1=1 --',expected_assignee_id=None)
    complaint.refresh_from_db();assert complaint.assignee_id is None
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()
    assert worker_call(head,staff,complaint)=='committed'
