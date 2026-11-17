"""B22 forms/actions: real CSRF, permissions, uploads and private downloads."""

from unittest.mock import patch

import pytest
from django.db import connection
from django.test import Client
from django.urls import reverse

from complaints.models import Attachment, Complaint
from workflow.models import ComplaintHistory
from workflow.test_resolution_integration import REMARKS, capture, case, files_on_disk, upload

pytestmark = pytest.mark.django_db(transaction=True)


def route(case, name='resolve'):
    return reverse('workflow:' + name, args=[case[0].complaint_id])


def form_data(client, case, name='resolve'):
    response = client.get(route(case, name))
    assert response.status_code == 200
    return {'revision':response.context['form'].initial['revision'], 'remarks':REMARKS,
            'csrfmiddlewaretoken':client.cookies['csrftoken'].value}


def test_real_csrf_resolution_post_redirect_and_protected_evidence(case, settings):
    complaint, staff, _ = case
    client = Client(enforce_csrf_checks=True)
    client.force_login(staff)
    before = capture(case, settings)
    data = form_data(client, case)
    assert capture(case, settings) == before
    assert client.post(route(case), {'revision':data['revision'], 'remarks':REMARKS}).status_code == 403
    assert capture(case, settings) == before
    response = client.post(route(case), {**data, 'evidence':[upload('PNG'), upload('PDF')]})
    assert response.status_code == 302 and response.url == route(case, 'work_status')
    result = client.get(response.url)
    assert result.status_code == 200 and b'Resolved' in result.content
    assert 'no-store' in result.headers['Cache-Control']
    attachment = Attachment.objects.first()
    download = reverse('complaints:download_evidence', args=[attachment.pk])
    assert download.encode() in result.content
    proof = client.get(download)
    assert proof.status_code == 200 and 'attachment;' in proof.headers['Content-Disposition']
    assert b''.join(proof.streaming_content) == files_on_disk(settings)[attachment.storage_name]
    proof.close()
    assert client.post(route(case), {**data, 'evidence':upload()}).status_code == 409
    assert Attachment.objects.count() == 2 and ComplaintHistory.objects.count() == 1
    complaint.refresh_from_db()
    assert complaint.status == 'RESOLVED' and complaint.closed_at is None


def test_progress_then_resolution_works_with_atomic_requests(case, monkeypatch):
    complaint, staff, _ = case
    complaint.status = 'ASSIGNED'
    complaint.save(update_fields=['status'])
    monkeypatch.setitem(connection.settings_dict, 'ATOMIC_REQUESTS', True)
    client = Client(enforce_csrf_checks=True)
    client.force_login(staff)
    data = form_data(client, case, 'progress')
    assert client.post(route(case, 'progress'), data).status_code == 302
    status = client.get(route(case, 'work_status'))
    assert route(case).encode() in status.content
    data = form_data(client, case)
    assert client.post(route(case), {**data, 'evidence':upload()}).status_code == 302
    assert list(ComplaintHistory.objects.values_list('new_state', flat=True)) == ['IN_PROGRESS', 'RESOLVED']


@pytest.mark.parametrize('kind', ['head', 'owner', 'admin', 'unassigned', 'cross'])
def test_resolution_form_denies_ineligible_actors(case, user_factory, department_factory, kind):
    complaint, _, head = case
    if kind == 'head':
        actor = head
    elif kind == 'owner':
        actor = complaint.submitted_by
    elif kind == 'admin':
        actor = user_factory(role='ADMIN')
    else:
        actor = user_factory(role='STAFF', department=department_factory() if kind == 'cross' else complaint.department)
    client = Client()
    client.force_login(actor)
    assert client.get(route(case)).status_code in (403, 404)
    assert client.post(route(case), {'revision':'a'*64, 'remarks':REMARKS, 'evidence':upload()}).status_code in (403, 404)
    assert not Attachment.objects.exists() and not ComplaintHistory.objects.exists()


@pytest.mark.parametrize('bad', ['state', 'uploader', 'storage_key', 'unknown_file', 'invalid_evidence', 'short'])
def test_form_rejects_tampering_and_invalid_evidence_without_mutation(case, settings, bad):
    client = Client(enforce_csrf_checks=True)
    client.force_login(case[1])
    data = form_data(client, case)
    if bad == 'state':
        data['status'] = 'CLOSED'
    elif bad == 'uploader':
        data['uploaded_by'] = case[0].submitted_by_id
    elif bad == 'storage_key':
        data['storage_name'] = '../private'
    elif bad == 'unknown_file':
        data['other_file'] = upload()
    elif bad == 'invalid_evidence':
        data['evidence'] = upload('PNG', 'mismatch.pdf')
    else:
        data['remarks'] = 'x' * 19
    before = capture(case, settings)
    assert client.post(route(case), data).status_code == 400
    assert capture(case, settings) == before


def test_remarks_are_escaped_and_status_is_read_only(case, settings):
    client = Client()
    client.force_login(case[1])
    data = form_data(client, case)
    data['remarks'] = '<script>alert(1)</script> The reported fault has been repaired.'
    assert client.post(route(case), data).status_code == 302
    before = capture(case, settings)
    response = client.get(route(case, 'work_status'))
    assert b'<script>' not in response.content and b'&lt;script&gt;' in response.content
    assert client.head(route(case, 'work_status')).status_code == 200
    assert client.post(route(case, 'work_status')).status_code == 405
    assert capture(case, settings) == before
    assert client.get(route(case)).status_code == 409


def test_download_and_status_do_not_accept_anonymous_references_or_other_owners(case, user_factory):
    from workflow.resolution_service import resolve_complaint
    from workflow.test_resolution_integration import arguments

    resolve_complaint(**arguments(case), files=[upload()])
    attachment = Attachment.objects.get()
    url = reverse('complaints:download_evidence', args=[attachment.pk])
    anonymous = Client()
    assert anonymous.get(url + '?reference=' + 'a'*32).status_code == 404
    assert anonymous.get(route(case, 'work_status')).status_code == 302
    client = Client()
    client.force_login(user_factory())
    assert client.get(url).status_code == 404
    assert client.get(route(case, 'work_status')).status_code == 404
    client.force_login(case[0].submitted_by)
    assert client.get(route(case, 'work_status')).status_code == 200
    response = client.get(url)
    assert response.status_code == 200
    response.close()


def test_unexpected_storage_error_is_sanitized_in_http_and_logs(case, settings, caplog):
    client = Client()
    client.force_login(case[1])
    data = form_data(client, case)
    before = capture(case, settings)
    with patch('complaints.evidence.PrivateEvidenceStorage._save', side_effect=OSError('SECRET SOURCE REFERENCE')):
        response = client.post(route(case), {**data, 'evidence':upload()})
    assert response.status_code == 503
    assert b'SECRET' not in response.content and 'SECRET' not in caplog.text
    assert capture(case, settings) == before


def test_stale_http_revision_is_conflict_without_upload_parse(case, settings):
    client = Client()
    client.force_login(case[1])
    data = form_data(client, case)
    Complaint.objects.filter(pk=case[0].pk).update(is_escalated=True, escalation_level=1)
    before = capture(case, settings)
    with patch('workflow.resolution_service.validate_evidence') as validate:
        assert client.post(route(case), {**data, 'evidence':upload()}).status_code == 409
    validate.assert_not_called()
    assert capture(case, settings) == before


def test_http_role_revocation_after_staging_is_denied_and_cleaned(case, settings):
    from contextlib import contextmanager
    from accounts.models import User
    from complaints.evidence import staged_evidence

    client = Client()
    client.force_login(case[1])
    data = form_data(client, case)
    before = capture(case, settings)
    @contextmanager
    def staged(*files, **kwargs):
        with staged_evidence(*files, **kwargs) as stored:
            User.objects.filter(pk=case[1].pk).update(is_active=False)
            yield stored
    with patch('workflow.resolution_service.staged_evidence', staged):
        assert client.post(route(case), {**data, 'evidence':upload()}).status_code == 404
    assert capture(case, settings) == before
