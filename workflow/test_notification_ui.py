"""B28 TC-11/13: recipient isolation, read state, headers and minimal payloads."""
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from workflow.history_service import record_history
from workflow.models import Notification, NotificationEvent
from workflow.notifications import mark_notification_read, unread_count

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def notices(complaint_factory, user_factory):
    complaint = complaint_factory()
    head = user_factory(role='HEAD', department=complaint.department)
    for _ in range(3):
        record_history(complaint.complaint_id, 'ESCALATED','SYSTEM', 'ASSIGNED','ASSIGNED')
    return complaint, complaint.submitted_by, head


def listing():
    return reverse('workflow:notifications')


def reading(notice):
    return reverse('workflow:notification_read', args=[notice.pk])


def test_newest_first_ties_pagination_and_get_never_mutates(notices, client):
    complaint, owner, _ = notices
    client.force_login(owner)
    own = Notification.objects.filter(recipient=owner)
    own.update(created_at=timezone.now())
    expected = list(own.order_by('-created_at','-pk').values_list('pk',flat=True))
    before = list(Notification.objects.values())
    response = client.get(listing())
    assert response.status_code == 200
    assert [n.pk for n in response.context['page']] == expected
    assert b'3 unread' in response.content
    assert b'Complainant: Anonymous' not in response.content
    assert 'no-store' in response.headers['Cache-Control']
    assert client.head(listing()).status_code == 200
    assert client.get(reading(own.first())).status_code == 405
    assert client.head(reading(own.first())).status_code == 405
    assert list(Notification.objects.values()) == before
    assert client.get(listing(), {'page':'bad'}).status_code == 200


def test_csrf_post_read_and_header_count_are_consistent_and_idempotent(notices):
    _, owner, head = notices
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    client.get(listing())
    notice = Notification.objects.filter(recipient=owner).first()
    assert client.post(reading(notice)).status_code == 403
    assert unread_count(owner) == 3
    with patch('workflow.email_delivery.send_mail') as send:
        response = client.post(reading(notice), {'csrfmiddlewaretoken':client.cookies['csrftoken'].value})
    assert response.status_code == 302 and response.url == listing()
    notice.refresh_from_db()
    first = notice.read_at
    assert first is not None and unread_count(owner) == 2 and unread_count(head) == 3
    assert b'2 unread' in client.get(listing()).content
    client.post(reading(notice), {'csrfmiddlewaretoken':client.cookies['csrftoken'].value})
    notice.refresh_from_db()
    assert notice.read_at == first
    assert b'Read' in client.get(listing()).content
    send.assert_not_called()


def test_recipient_only_even_if_both_can_read_complaint(notices, client):
    _, owner, head = notices
    notice = Notification.objects.filter(recipient=owner).first()
    client.force_login(head)
    before = list(Notification.objects.values())
    assert client.post(reading(notice)).status_code == 404
    with pytest.raises(Http404):
        mark_notification_read(head, notice.pk)
    assert list(Notification.objects.values()) == before
    assert set(n.recipient_id for n in client.get(listing()).context['page']) == {head.pk}


@pytest.mark.parametrize('kind', ['other','inactive','changed_department','revoked_role'])
def test_current_authority_controls_list_count_and_read(notices, client, user_factory, department_factory, kind):
    _, owner, head = notices
    user = head
    notice = Notification.objects.filter(recipient=head).first()
    if kind == 'other':
        user = user_factory()
    elif kind == 'inactive':
        type(head).objects.filter(pk=head.pk).update(is_active=False)
    elif kind == 'changed_department':
        type(head).objects.filter(pk=head.pk).update(department=department_factory())
    else:
        type(head).objects.filter(pk=head.pk).update(role='ADMIN', department=None)
    assert unread_count(user) == 0
    with pytest.raises(Http404):
        mark_notification_read(user, notice.pk)
    notice.refresh_from_db()
    assert notice.read_at is None
    if kind != 'inactive':
        client.force_login(user)
        assert len(client.get(listing()).context['page']) == 0
        assert client.post(reading(notice)).status_code == 404


def test_anonymous_and_missing_notice_denied(notices, client):
    _, owner, _ = notices
    notice = Notification.objects.first()
    assert client.get(listing()).status_code == 302
    assert client.post(reading(notice)).status_code == 302
    assert unread_count(AnonymousUser()) == unread_count(None) == 0
    with pytest.raises(Http404):
        mark_notification_read(None, notice.pk)
    client.force_login(owner)
    assert client.post(reverse('workflow:notification_read', args=[999999])).status_code == 404


def test_anonymous_notice_renders_only_minimal_projection(complaint_factory, user_factory, client):
    complaint = complaint_factory(anonymous=True, title='PRIVATE TITLE', description='PRIVATE BODY WITH SUFFICIENT LENGTH',
                                  resolution_remarks='PRIVATE RESOLUTION')
    head = user_factory(role='HEAD', department=complaint.department)
    history = record_history(complaint.complaint_id,'ESCALATED','SYSTEM','ASSIGNED','ASSIGNED',
                             remarks='PRIVATE HISTORY REASON')
    client.force_login(head)
    response = client.get(listing())
    body = response.content.decode()
    assert complaint.complaint_id in body
    assert 'Complainant: Anonymous' in body
    for private in ('PRIVATE TITLE','PRIVATE BODY','PRIVATE RESOLUTION','PRIVATE HISTORY REASON',
                    complaint.reference_digest,head.email,'storage_name','download_evidence'):
        assert private not in body
    notice = Notification.objects.get(event__history=history,recipient=head)
    assert client.post(reading(notice), {'reference':'a'*32}).status_code == 302
    assert NotificationEvent.objects.count() == 1


def test_pagination_and_home_header(notices, client):
    complaint, owner, _ = notices
    for _ in range(24):
        record_history(complaint.complaint_id,'ESCALATED','SYSTEM','ASSIGNED','ASSIGNED')
    client.force_login(owner)
    first = client.get(listing())
    assert len(first.context['page']) == 25
    assert len(client.get(listing(), {'page':2}).context['page']) == 2
    response = client.get(reverse('accounts:home'), follow=True)
    assert response.status_code == 200 and b'27 unread' in response.content


def test_read_update_rolls_back_with_callers_transaction(notices):
    from django.db import transaction
    _, owner, _ = notices
    notice = Notification.objects.filter(recipient=owner).first()
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            mark_notification_read(owner, notice.pk)
            raise RuntimeError('synthetic failure')
    notice.refresh_from_db()
    assert notice.read_at is None and unread_count(owner) == 3
