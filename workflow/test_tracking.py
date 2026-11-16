"""Focused B19 owner-page acceptance tests using real Complaint records."""

import hashlib
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from complaints.evidence import PrivateEvidenceStorage
from complaints.models import Attachment, Complaint
from complaints.references import hash_reference
from workflow.history_service import record_history
from workflow.models import ComplaintHistory, Notification

pytestmark = pytest.mark.django_db(transaction=True)


def listing():
    return reverse('workflow:complaint_list')


def detail(complaint):
    return reverse('workflow:complaint_detail', args=[complaint.complaint_id])


def test_owner_list_filters_and_pagination_preserve_scope(client, user_factory, complaint_factory):
    owner = user_factory()
    matches = [complaint_factory(submitted_by=owner, category='Electrical', status='ASSIGNED') for _ in range(26)]
    complaint_factory(submitted_by=owner, category='Plumbing', status='RESOLVED')
    hidden = complaint_factory(category='OTHER-PRIVATE-CATEGORY', title='OTHER-PRIVATE-TITLE')
    anonymous = complaint_factory(anonymous=True, category='ANON-PRIVATE-CATEGORY', title='ANON-PRIVATE-TITLE')
    client.force_login(owner)
    query = {'status':'ASSIGNED', 'category':'Electrical', 'submitted_by':hidden.submitted_by_id}
    response = client.get(listing(), query)
    assert response.status_code == 200
    page = response.context['page']
    assert len(page) == 25 and page.paginator.count == 26
    assert list(page) == sorted(matches, key=lambda c:(c.submitted_at,c.pk), reverse=True)[:25]
    assert b'status=ASSIGNED' in response.content and b'category=Electrical' in response.content
    for secret in ('OTHER-PRIVATE', 'ANON-PRIVATE'):
        assert secret.encode() not in response.content
    assert hidden.complaint_id.encode() not in response.content and anonymous.complaint_id.encode() not in response.content
    last = client.get(listing(), {**query, 'page':2}).context['page']
    assert len(last) == 1 and last[0].pk == matches[0].pk
    assert 'no-store' in response.headers['Cache-Control'] and 'Cookie' in response.headers['Vary']
    assert client.get(listing(), {'category':'Plumbing'}).context['page'].paginator.count == 1
    assert client.get(listing(), {'status':'RESOLVED'}).context['page'].paginator.count == 1
    assert client.get(listing(), {'status':'UNKNOWN'}).context['page'].paginator.count == 0


@pytest.mark.parametrize('role', ['STAFF','HEAD','ADMIN'])
def test_tracking_requires_current_complainant_role(client, user_factory, complaint_factory, department, role):
    owner = user_factory(department=department)
    complaint = complaint_factory(submitted_by=owner, department=department)
    client.force_login(owner)
    User.objects.filter(pk=owner.pk).update(role=role)
    assert client.get(listing()).status_code == 403
    assert client.get(detail(complaint)).status_code == 403


def test_anonymous_requests_and_references_never_grant_full_access(client, user_factory, complaint_factory):
    complaint = complaint_factory(anonymous=True, title='SECRET-ANONYMOUS')
    reference = 'a'*32
    complaint.reference_digest = hash_reference(reference)
    complaint.save(update_fields=['reference_digest'])
    assert client.get(listing()).status_code == 302
    assert client.get(detail(complaint), {'reference':reference}).status_code == 302
    client.force_login(user_factory())
    response = client.get(listing(), {'reference':reference, 'complaint_id':complaint.complaint_id})
    assert response.context['page'].paginator.count == 0
    assert reference.encode() not in response.content and b'SECRET-ANONYMOUS' not in response.content
    assert client.get(detail(complaint), {'reference':reference}).status_code == 404
    assert client.get(reverse('workflow:complaint_detail', args=[reference])).status_code == 404


def test_direct_other_owner_and_missing_details_are_not_exposed(client, user_factory, complaint_factory):
    owner, other = user_factory(), user_factory()
    complaint = complaint_factory(submitted_by=other, title='SECRET-OTHER-RECORD')
    client.force_login(owner)
    response = client.get(detail(complaint))
    assert response.status_code == 404 and b'SECRET-OTHER-RECORD' not in response.content
    assert client.get(reverse('workflow:complaint_detail', args=['SCMS-2000-999999'])).status_code == 404


@pytest.mark.parametrize('stage', ['INTAKE','RESOLUTION'])
def test_detail_shows_chronological_history_and_protected_evidence(
        client, user_factory, complaint_factory, settings, tmp_path, stage):
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path/'private'
    owner = user_factory()
    now = timezone.now()
    complaint = complaint_factory(submitted_by=owner, status='RESOLVED', submitted_at=now-timedelta(minutes=10),
                                  title='<script>secret()</script>', description='Synthetic description of a faulty light.')
    with patch('django.utils.timezone.now', return_value=now-timedelta(minutes=1)):
        later = record_history(complaint.complaint_id, 'RESOLVED', 'STAFF', 'IN_PROGRESS','RESOLVED','LATER-REPAIR')
    with patch('django.utils.timezone.now', return_value=now-timedelta(minutes=5)):
        earlier = record_history(complaint.complaint_id, 'SUBMITTED','COMPLAINANT','','SUBMITTED','EARLIER-SUBMISSION')
    buffer = BytesIO()
    Image.new('RGB',(1,1),'blue').save(buffer,format='PNG')
    data = buffer.getvalue()
    name = PrivateEvidenceStorage().save(uuid4().hex+'.png',ContentFile(data))
    proof = Attachment.objects.create(complaint=complaint, storage_name=name, original_name='PRIVATE-ORIGINAL.png',
                                     content_type='image/png', size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                     stage=stage, uploaded_by=owner)
    client.force_login(owner)
    before = (Complaint.objects.values().get(), ComplaintHistory.objects.count(), Notification.objects.count())
    response = client.get(detail(complaint))
    assert response.status_code == 200
    assert list(response.context['history_page']) == [earlier,later]
    assert response.content.index(b'EARLIER-SUBMISSION') < response.content.index(b'LATER-REPAIR')
    assert b'<script>' not in response.content and b'&lt;script&gt;' in response.content
    assert b'PRIVATE-ORIGINAL' not in response.content and name.encode() not in response.content
    download = reverse('complaints:download_evidence',args=[proof.pk])
    assert download.encode() in response.content
    result = client.get(download)
    assert result.status_code == 200 and b''.join(result.streaming_content) == data
    result.close()
    assert client.head(detail(complaint)).status_code == 200
    assert client.post(detail(complaint)).status_code == 405
    assert client.post(listing()).status_code == 405
    assert (Complaint.objects.values().get(), ComplaintHistory.objects.count(), Notification.objects.count()) == before
    client.force_login(user_factory())
    assert client.get(download).status_code == 404
    client.logout()
    assert client.get(download, {'reference':'a'*32}).status_code == 404


def test_history_pages_use_chronological_tie_break_and_cap(client, user_factory, complaint_factory):
    owner = user_factory()
    complaint = complaint_factory(submitted_by=owner)
    now = timezone.now()
    with patch('django.utils.timezone.now', return_value=now):
        events = [record_history(complaint.complaint_id,'STATUS_CHANGED','SYSTEM') for _ in range(26)]
    client.force_login(owner)
    page = client.get(detail(complaint)).context['history_page']
    assert list(page) == events[:25]
    assert list(client.get(detail(complaint), {'history_page':2}).context['history_page']) == events[25:]


def test_empty_and_invalid_page_requests_are_safe(client, user_factory):
    client.force_login(user_factory())
    for page in ('invalid','-1','999999'):
        response = client.get(listing(), {'page':page})
        assert response.status_code == 200 and len(response.context['page']) == 0
