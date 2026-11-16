"""B22 real ORM/storage/lifecycle integration, including accepted-byte safety."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO
from threading import Barrier
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from django.http import Http404
from django.utils import timezone
from PIL import Image
from pypdf import PdfWriter

from accounts.models import User
from complaints.evidence import PrivateEvidenceStorage, staged_evidence
from complaints.models import Attachment, Complaint
from workflow.lifecycle import ModifiedRecord, _revision, get_transition_revision
from workflow.models import ComplaintHistory, EmailDelivery, Notification, NotificationEvent
from workflow.resolution_service import progress_complaint, resolve_complaint

pytestmark = pytest.mark.django_db(transaction=True)
REMARKS = 'The reported light has been inspected and repaired.'


def upload(kind='PNG', name=None):
    data = BytesIO()
    if kind == 'PDF':
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.write(data)
        extension = 'pdf'
    else:
        Image.new('RGB', (3, 3), 'blue').save(data, format=kind)
        extension = 'jpg' if kind == 'JPEG' else 'png'
    return SimpleUploadedFile(name or 'synthetic.' + extension, data.getvalue(), content_type='text/plain')


@pytest.fixture
def case(complaint_factory, user_factory, settings, tmp_path):
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / 'private'
    complaint = complaint_factory(status='IN_PROGRESS')
    staff = user_factory(role='STAFF', department=complaint.department)
    head = user_factory(role='HEAD', department=complaint.department)
    complaint.assignee = staff
    complaint.save(update_fields=['assignee'])
    return complaint, staff, head


def arguments(case):
    complaint, staff, _ = case
    return dict(actor=staff, complaint_id=complaint.complaint_id, remarks=REMARKS,
                expected_revision=get_transition_revision(actor=staff, complaint_id=complaint.complaint_id,
                                                          target_state='RESOLVED'))


def files_on_disk(settings):
    return {p.name: p.read_bytes() for p in settings.PRIVATE_EVIDENCE_ROOT.glob('*') if p.is_file()}


def capture(case, settings):
    complaint, _, _ = case
    return (Complaint.objects.filter(pk=complaint.pk).values().get(),
            *[list(model.objects.order_by('pk').values()) for model in (
                Attachment, ComplaintHistory, NotificationEvent, Notification, EmailDelivery)],
            files_on_disk(settings))


@pytest.mark.parametrize('count', [0, 1, 3])
def test_resolution_persists_proof_history_and_durable_notices(case, settings, count):
    complaint, staff, head = case
    before = Complaint.objects.filter(pk=complaint.pk).values().get()
    now = timezone.now()
    evidence = [upload(kind) for kind in ('PNG', 'JPEG', 'PDF')[:count]]
    expected = [f.read() for f in evidence]
    for f in evidence:
        f.seek(0)
    args = arguments(case)
    result = resolve_complaint(**args, files=evidence)
    complaint.refresh_from_db()
    assert result.new_state == complaint.status == 'RESOLVED'
    assert complaint.resolution_remarks == REMARKS and now <= complaint.resolved_at <= timezone.now()
    assert complaint.closed_at is None and complaint.rating is None
    after = Complaint.objects.filter(pk=complaint.pk).values().get()
    changed = {'status', 'resolution_remarks', 'resolved_at'}
    assert {k:v for k,v in before.items() if k not in changed} == {k:v for k,v in after.items() if k not in changed}
    rows = list(Attachment.objects.order_by('pk'))
    assert len(rows) == count
    for item, data, mime in zip(rows, expected, ('image/png', 'image/jpeg', 'application/pdf')):
        assert item.stage == 'RESOLUTION' and item.complaint_id == complaint.pk and item.uploaded_by_id == staff.pk
        assert item.sha256 == hashlib.sha256(data).hexdigest() and item.size == len(data)
        assert item.content_type == mime
        assert files_on_disk(settings)[item.storage_name] == data
        with pytest.raises(NotImplementedError):
            PrivateEvidenceStorage().url(item.storage_name)
    history = ComplaintHistory.objects.get()
    assert (history.event_type, history.actor_kind, history.previous_state, history.new_state, history.remarks) == (
        'RESOLVED', 'STAFF', 'IN_PROGRESS', 'RESOLVED', REMARKS)
    if any(f.name == 'actor' for f in ComplaintHistory._meta.fields):
        assert history.actor_id == staff.pk
    event = NotificationEvent.objects.get(history=history)
    assert event.kind == 'RESOLVED'
    assert set(event.notices.values_list('recipient_id', flat=True)) == {staff.pk, head.pk, complaint.submitted_by_id}
    assert EmailDelivery.objects.count() == 3
    assert set(EmailDelivery.objects.values_list('status', flat=True)) == {'PENDING'}
    original = capture(case, settings)
    with patch('workflow.resolution_service.validate_evidence') as validate:
        with pytest.raises(ModifiedRecord):
            resolve_complaint(**args, files=[upload()])
    validate.assert_not_called()
    assert capture(case, settings) == original


@pytest.mark.parametrize('state', ['ASSIGNED', 'REOPENED'])
@pytest.mark.parametrize('role', ['STAFF', 'HEAD'])
def test_progress_is_a_real_start_action(case, state, role):
    complaint, staff, head = case
    complaint.status = state
    complaint.save(update_fields=['status'])
    actor = staff if role == 'STAFF' else head
    revision = get_transition_revision(actor=actor, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    progress_complaint(actor=actor, complaint_id=complaint.complaint_id, expected_revision=revision,
                       remarks='Inspection started')
    complaint.refresh_from_db()
    assert complaint.status == 'IN_PROGRESS' and complaint.resolved_at is None
    assert ComplaintHistory.objects.get().remarks == 'Inspection started'
    assert NotificationEvent.objects.get().kind == 'STARTED' and not EmailDelivery.objects.exists()
    with pytest.raises(ModifiedRecord):
        progress_complaint(actor=actor, complaint_id=complaint.complaint_id, expected_revision=revision)


@pytest.mark.parametrize('kind', ['head', 'admin', 'owner', 'unassigned', 'cross', 'inactive', 'anonymous', 'none'])
def test_ineligible_resolver_cannot_parse_or_store_evidence(case, settings, user_factory, department_factory, kind):
    complaint, staff, head = case
    args = arguments(case)
    if kind == 'head':
        actor = head
    elif kind == 'owner':
        actor = complaint.submitted_by
    elif kind == 'admin':
        actor = user_factory(role='ADMIN')
    elif kind == 'unassigned':
        actor = user_factory(role='STAFF', department=complaint.department)
    elif kind == 'cross':
        actor = user_factory(role='STAFF', department=department_factory())
    elif kind == 'inactive':
        actor = staff
        User.objects.filter(pk=staff.pk).update(is_active=False)
    else:
        actor = AnonymousUser() if kind == 'anonymous' else None
    before = capture(case, settings)
    with patch('workflow.resolution_service.validate_evidence') as validate:
        with pytest.raises((PermissionDenied, Http404)):
            resolve_complaint(**{**args, 'actor':actor}, files=[upload()])
    validate.assert_not_called()
    assert capture(case, settings) == before


@pytest.mark.parametrize('state', [s for s in Complaint.Status.values if s != 'IN_PROGRESS'])
def test_resolution_never_skips_state_or_closes_work(case, settings, state):
    complaint, staff, _ = case
    complaint.status = state
    complaint.save(update_fields=['status'])
    before = capture(case, settings)
    with pytest.raises(ValidationError):
        resolve_complaint(actor=staff, complaint_id=complaint.complaint_id, expected_revision=_revision(complaint),
                          remarks=REMARKS, files=[upload()])
    assert capture(case, settings) == before


@pytest.mark.parametrize('remarks', [None, 7, '', ' ' * 50, 'x' * 19, 'x' * 2001, 'x' * 25 + '\x00'])
def test_invalid_resolution_remarks_leave_everything_unchanged(case, settings, remarks):
    args = arguments(case)
    before = capture(case, settings)
    with patch('workflow.resolution_service.validate_evidence') as validate:
        with pytest.raises(ValidationError):
            resolve_complaint(**{**args, 'remarks':remarks}, files=[upload()])
    validate.assert_not_called()
    assert capture(case, settings) == before


@pytest.mark.parametrize('length', [20, 2000])
def test_resolution_remarks_boundaries(case, length):
    resolve_complaint(**{**arguments(case), 'remarks':'  ' + 'x' * length + '  '})
    assert Complaint.objects.get().resolution_remarks == 'x' * length


@pytest.mark.parametrize('bad', ['empty', 'damaged', 'mismatch', 'extension', 'four', 'oversize'])
def test_shared_evidence_controls_reject_complete_operation(case, settings, bad):
    args = arguments(case)
    if bad == 'four':
        files = [upload() for _ in range(4)]
    elif bad == 'oversize':
        f = upload()
        files = [SimpleUploadedFile('too-large.png', f.read() + b'x' * settings.EVIDENCE_MAX_BYTES)]
    elif bad == 'mismatch':
        files = [upload('PNG', name='wrong.pdf')]
    else:
        files = [SimpleUploadedFile('file.txt' if bad == 'extension' else 'file.png',
                                    b'' if bad == 'empty' else b'not a valid image')]
    before = capture(case, settings)
    with pytest.raises(ValidationError):
        resolve_complaint(**args, files=files)
    assert capture(case, settings) == before


@pytest.mark.parametrize('failure', ['history', 'notice', 'email_job', 'attachment', 'commit'])
def test_required_failure_rolls_back_files_and_all_database_records(case, settings, failure):
    args = arguments(case)
    before = capture(case, settings)
    if failure == 'commit':
        @contextmanager
        def staged(*files, **kwargs):
            with staged_evidence(*files, **kwargs) as stored:
                with patch.object(connection, 'commit', side_effect=DatabaseError('controlled commit')):
                    yield stored
        target, replacement = 'workflow.resolution_service.staged_evidence', staged
    else:
        target = {'history':'workflow.lifecycle.record_history',
                  'notice':'workflow.notifications.Notification.objects.create',
                  'email_job':'workflow.notifications.EmailDelivery.objects.create',
                  'attachment':'workflow.resolution_service.Attachment.objects.create'}[failure]
        replacement = None
    error = DatabaseError if failure == 'commit' else RuntimeError
    with pytest.raises(error):
        if replacement:
            with patch(target, replacement):
                resolve_complaint(**args, files=[upload()])
        else:
            with patch(target, side_effect=RuntimeError('controlled required failure')):
                resolve_complaint(**args, files=[upload()])
    assert capture(case, settings) == before


@pytest.mark.parametrize('change', ['assignment', 'inactive'])
def test_changes_during_staging_are_rechecked_and_files_cleaned(case, settings, change, user_factory):
    complaint, staff, _ = case
    args = arguments(case)
    @contextmanager
    def staged(*files, **kwargs):
        with staged_evidence(*files, **kwargs) as stored:
            if change == 'assignment':
                Complaint.objects.filter(pk=complaint.pk).update(assignee=user_factory(role='STAFF', department=complaint.department))
            else:
                User.objects.filter(pk=staff.pk).update(is_active=False)
            yield stored
    with patch('workflow.resolution_service.staged_evidence', staged):
        with pytest.raises(ModifiedRecord if change == 'assignment' else Http404):
            resolve_complaint(**args, files=[upload()])
    complaint.refresh_from_db()
    assert complaint.status == 'IN_PROGRESS' and complaint.resolved_at is None
    assert not Attachment.objects.exists() and not ComplaintHistory.objects.exists() and not files_on_disk(settings)


def test_resolution_refuses_outer_transaction_before_storage(case, settings):
    args = arguments(case)
    before = capture(case, settings)
    with transaction.atomic(), pytest.raises(TransactionManagementError):
        resolve_complaint(**args, files=[upload()])
    assert capture(case, settings) == before


def test_competing_resolutions_keep_one_proof_batch(case, settings):
    args = arguments(case)
    barrier = Barrier(2)
    def work(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                return resolve_complaint(**args, files=[upload(name=f'proof-{index}.png')]).new_state
            except ModifiedRecord:
                return 'STALE'
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, range(2)))
    assert sorted(results) == ['RESOLVED', 'STALE']
    assert Attachment.objects.count() == ComplaintHistory.objects.count() == NotificationEvent.objects.count() == 1
    assert set(files_on_disk(settings)) == set(Attachment.objects.values_list('storage_name', flat=True))
    assert EmailDelivery.objects.count() == 3


def test_postcommit_exception_cannot_delete_accepted_evidence(case, settings):
    args = arguments(case)
    original = Attachment.objects.create
    def create(**kwargs):
        row = original(**kwargs)
        def fail():
            raise RuntimeError('controlled callback after commit')
        transaction.on_commit(fail)
        return row
    with patch('workflow.resolution_service.Attachment.objects.create', side_effect=create):
        with pytest.raises(RuntimeError, match='after commit'):
            resolve_complaint(**args, files=[upload()])
    complaint = Complaint.objects.get()
    assert complaint.status == 'RESOLVED' and ComplaintHistory.objects.count() == NotificationEvent.objects.count() == 1
    attachment = Attachment.objects.get()
    assert hashlib.sha256(files_on_disk(settings)[attachment.storage_name]).hexdigest() == attachment.sha256
    with pytest.raises(ModifiedRecord):
        resolve_complaint(**args, files=[upload()])


def test_failed_cleanup_is_private_and_does_not_hide_operation_failure(case, settings, caplog):
    args = arguments(case)
    with patch('workflow.lifecycle.record_history', side_effect=RuntimeError('controlled operation')):
        with patch('complaints.evidence.PrivateEvidenceStorage.delete', side_effect=OSError('SECRET REF SOURCE')):
            with pytest.raises(RuntimeError, match='controlled operation'):
                resolve_complaint(**args, files=[upload()])
    assert 'recovery required' in caplog.text and 'SECRET' not in caplog.text
    assert not Attachment.objects.exists() and not ComplaintHistory.objects.exists()


def test_uncertain_database_cleanup_defers_without_disclosing_values(case, settings, caplog):
    args = arguments(case)
    with patch('workflow.lifecycle.record_history', side_effect=RuntimeError('controlled operation')):
        with patch('complaints.models.Attachment.objects.using', side_effect=DatabaseError('SECRET DB')):
            with pytest.raises(RuntimeError, match='controlled operation'):
                resolve_complaint(**args, files=[upload()])
    assert 'deferred to recovery' in caplog.text and 'SECRET' not in caplog.text
    assert len(files_on_disk(settings)) == 1 and not Attachment.objects.exists()


def test_existing_evidence_survives_failure_and_next_resolution(case, settings):
    complaint, staff, _ = case
    with staged_evidence([upload(name='previous.png')]) as stored:
        item = stored[0]
        previous = Attachment.objects.create(
            complaint=complaint, storage_name=item.storage_name, original_name=item.original_name,
            content_type=item.content_type, size=item.size, sha256=item.sha256,
            stage=Attachment.Stage.RESOLUTION, uploaded_by=staff)
    args = arguments(case)
    before = capture(case, settings)
    with patch('workflow.lifecycle.record_history', side_effect=RuntimeError('controlled')):
        with pytest.raises(RuntimeError):
            resolve_complaint(**args, files=[upload()])
    assert capture(case, settings) == before
    resolve_complaint(**args, files=[upload() for _ in range(3)])
    assert Attachment.objects.count() == 4  # Three new files; previous evidence is retained.
    assert files_on_disk(settings)[previous.storage_name] == before[-1][previous.storage_name]


def test_only_validated_immutable_bytes_reach_storage(case, settings):
    from complaints.evidence import validate_evidence

    file = upload()
    expected = file.read()
    file.seek(0)
    def validate(files):
        result = validate_evidence(files)
        file.file = BytesIO(b'changed after validation')
        return result
    with patch('workflow.resolution_service.validate_evidence', side_effect=validate):
        resolve_complaint(**arguments(case), files=[file])
    row = Attachment.objects.get()
    assert files_on_disk(settings)[row.storage_name] == expected


def test_anonymous_resolution_never_attributes_or_emails_reporter(complaint_factory, user_factory, settings, tmp_path):
    import json
    from django.core import mail
    from workflow.email_delivery import deliver_email

    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / 'private'
    settings.MAILERS = {'default':{'BACKEND':'django.core.mail.backends.locmem.EmailBackend'}}
    complaint = complaint_factory(anonymous=True, status='IN_PROGRESS', title='SECRET-REPORTER')
    staff = user_factory(role='STAFF', department=complaint.department)
    head = user_factory(role='HEAD', department=complaint.department)
    complaint.assignee = staff
    complaint.save(update_fields=['assignee'])
    args = arguments((complaint, staff, head))
    resolve_complaint(**args, files=[upload(name='SECRET-NAME.png')])
    complaint.refresh_from_db()
    assert complaint.submitted_by_id is None and Attachment.objects.get().uploaded_by_id == staff.pk
    assert set(Notification.objects.values_list('recipient_id', flat=True)) == {staff.pk, head.pk}
    for job in EmailDelivery.objects.all():
        assert deliver_email(job.pk) == 'SENT'
    serialized = json.dumps(list(NotificationEvent.objects.values()), default=str)
    serialized += ''.join(message.message().as_string() for message in mail.outbox)
    assert 'Anonymous' in serialized and 'SECRET' not in serialized
    assert complaint.reference_digest not in serialized and 'submitted_by' not in serialized
    assert len(mail.outbox) == 2 and {m.to[0] for m in mail.outbox} == {staff.email, head.email}


def test_email_failure_cannot_reverse_real_resolution_or_delete_proof(case, settings):
    import smtplib
    from workflow.email_delivery import deliver_email

    resolve_complaint(**arguments(case), files=[upload()])
    before = capture(case, settings)
    job = EmailDelivery.objects.first()
    with patch('workflow.email_delivery.send_mail', side_effect=smtplib.SMTPDataError(451, b'SECRET')):
        assert deliver_email(job.pk) == 'RETRY_WAIT'
    after = capture(case, settings)
    assert after[:5] == before[:5] and after[-1] == before[-1]
