"""B10 guard tests with real DB writes and explicitly synthetic operation adapters.

The adapters do not stand in for completed Complaint/routing acceptance. Optional
B09 tests exercise the actual private storage when that contribution is present.
"""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, connection, connections, transaction
from django.db.transaction import TransactionManagementError

from accounts.models import Department, SecurityEvent, User
from complaints import intake
from complaints.models import ComplaintIdSequence, IntakeReceipt
from workflow.history_service import record_history
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db(transaction=True)
FIELDS = {"category": "synthetic-category", "location": "SYNTHETIC.LOCATION",
          "title": "Synthetic complaint", "description": "Synthetic test description only.",
          "priority": "MEDIUM"}


@pytest.fixture
def args(complainant_user):
    return {"user": complainant_user, "key": intake.new_intake_key(),
            "payload_digest": intake.submission_digest(fields=FIELDS)}


def synthetic_operation(context):
    """Real independent DB writes used to test the guard's transaction boundary."""
    Department.objects.create(name=context.complaint_id)
    record_history(context.complaint_id, ComplaintHistory.EventType.SUBMITTED,
                   ComplaintHistory.ActorKind.COMPLAINANT, new_state="SUBMITTED")


def test_key_entropy_and_format():
    keys = {intake.new_intake_key() for _ in range(100)}
    assert len(keys) == 100
    assert all(intake.HEX_DIGEST.fullmatch(key) for key in keys)


def test_digest_is_canonical_and_contains_file_content():
    digest = intake.submission_digest(fields=FIELDS)
    assert digest == intake.submission_digest(fields=dict(reversed(list(FIELDS.items()))))
    assert digest != intake.submission_digest(fields={**FIELDS, "title": "Changed title"})
    first, second = hashlib.sha256(b"first").hexdigest(), hashlib.sha256(b"second").hexdigest()
    assert digest != intake.submission_digest(fields=FIELDS, evidence_sha256=[first])
    assert intake.submission_digest(fields=FIELDS, evidence_sha256=[first, second]) != intake.submission_digest(
        fields=FIELDS, evidence_sha256=[second, first]
    )


@pytest.mark.parametrize("fields,hashes", [(None, []), ({}, ["not-a-hash"]), ({}, [None])])
def test_bad_digest_inputs_refused(fields, hashes):
    with pytest.raises(ValueError):
        intake.submission_digest(fields=fields, evidence_sha256=hashes)


def test_success_commits_before_return_and_stores_no_raw_key(args):
    result = intake.execute_intake(**args, operation=synthetic_operation)
    assert not connection.in_atomic_block
    assert not result.replayed
    receipt = IntakeReceipt.objects.get()
    assert receipt.complaint_id == result.complaint_id
    assert receipt.submitted_at == result.submitted_at
    assert receipt.key_digest == hashlib.sha256(args["key"].encode()).hexdigest()
    assert receipt.key_digest != args["key"]
    assert Department.objects.filter(name=result.complaint_id).count() == 1
    assert ComplaintHistory.objects.filter(complaint_ref=result.complaint_id).count() == 1
    assert ComplaintIdSequence.objects.get().last_value == 1


def test_timeout_after_commit_replays_without_repeating_work_or_mail(args):
    notices = []
    first = intake.execute_intake(**args, operation=synthetic_operation, after_commit=notices.append)
    # Simulate loss of the HTTP response AFTER commit. A new connection/request
    # submits the identical key and digest; no knowledge of the result is needed.
    connection.close()
    replay = intake.execute_intake(**args, operation=lambda _: pytest.fail("operation repeated"),
                                   after_commit=lambda _: pytest.fail("notice repeated"))
    assert replay.replayed and replay.complaint_id == first.complaint_id
    assert replay.submitted_at == first.submitted_at
    assert len(notices) == 1
    assert IntakeReceipt.objects.count() == ComplaintHistory.objects.count() == 1
    assert ComplaintIdSequence.objects.get().last_value == 1


def test_changed_payload_with_old_key_refused(args):
    intake.execute_intake(**args, operation=synthetic_operation)
    args["payload_digest"] = intake.submission_digest(fields={**FIELDS, "title": "Changed"})
    with pytest.raises(intake.IdempotencyConflict):
        intake.execute_intake(**args, operation=lambda _: pytest.fail("reused conflicting key"))
    assert IntakeReceipt.objects.count() == 1
    assert ComplaintIdSequence.objects.get().last_value == 1


def test_same_key_is_scoped_to_account(args, user_factory):
    first = intake.execute_intake(**args, operation=synthetic_operation)
    second = intake.execute_intake(**{**args, "user": user_factory()}, operation=synthetic_operation)
    assert second.complaint_id != first.complaint_id
    assert not second.replayed
    assert IntakeReceipt.objects.count() == 2


@pytest.mark.parametrize("failure", [RuntimeError("routing failed"), OSError("storage failed"),
                                   IntegrityError("history failed"), PermissionDenied()])
def test_required_failure_rolls_back_every_write_and_identifier(args, failure):
    observed = []

    def fail(context):
        observed.append(context.complaint_id)
        synthetic_operation(context)
        raise failure

    with pytest.raises(type(failure)):
        intake.execute_intake(**args, operation=fail,
                              after_commit=lambda _: pytest.fail("notice before commit"))
    assert not IntakeReceipt.objects.exists()
    assert not ComplaintIdSequence.objects.exists()
    assert not ComplaintHistory.objects.exists()
    assert not Department.objects.filter(name=observed[0]).exists()
    result = intake.execute_intake(**args, operation=synthetic_operation)
    assert result.complaint_id == observed[0]  # failed reservation was never accepted
    assert not result.replayed


def test_receipt_write_failure_also_rolls_back_operation(args, monkeypatch):
    def fail(**_):
        raise IntegrityError("synthetic receipt failure")

    monkeypatch.setattr(IntakeReceipt.objects, "create", fail)
    with pytest.raises(IntegrityError):
        intake.execute_intake(**args, operation=synthetic_operation)
    assert not ComplaintHistory.objects.exists()
    assert not ComplaintIdSequence.objects.exists()


def test_commit_failure_never_returns_acceptance(args, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(connection, "commit", lambda: (_ for _ in ()).throw(OperationalError("commit failed")))
        with pytest.raises(OperationalError, match="commit failed"):
            intake.execute_intake(**args, operation=synthetic_operation)
    assert not IntakeReceipt.objects.exists()
    assert not ComplaintHistory.objects.exists()
    assert not ComplaintIdSequence.objects.exists()


def test_mail_failure_does_not_reverse_commit_or_escape_as_intake_failure(args, caplog):
    def broken_mail(result):
        assert not connection.in_atomic_block
        assert IntakeReceipt.objects.filter(complaint_id=result.complaint_id).exists()
        raise RuntimeError("synthetic mail failure")

    result = intake.execute_intake(**args, operation=synthetic_operation, after_commit=broken_mail)
    assert IntakeReceipt.objects.filter(complaint_id=result.complaint_id).exists()
    assert "synthetic mail failure" in caplog.text
    assert intake.execute_intake(**args, operation=synthetic_operation).replayed


@pytest.mark.parametrize("kind", ["anonymous", "none", "admin", "inactive", "removed"])
def test_permission_checked_fresh_before_processing_or_replay(args, kind):
    user = args["user"]
    intake.execute_intake(**args, operation=synthetic_operation)
    if kind == "anonymous":
        user = AnonymousUser()
    elif kind == "none":
        user = None
    elif kind == "admin":
        User.objects.filter(pk=user.pk).update(role=User.Role.ADMIN)
    elif kind == "inactive":
        User.objects.filter(pk=user.pk).update(is_active=False)
    else:
        # A request may carry an instance whose pk no longer resolves.
        user.pk += 1_000_000
    with pytest.raises(PermissionDenied):
        intake.execute_intake(**{**args, "user": user}, operation=lambda _: pytest.fail("unauthorized operation"),
                              staging=lambda: pytest.fail("unauthorized staging"))
    assert IntakeReceipt.objects.count() == 1
    assert SecurityEvent.objects.filter(event_type=SecurityEvent.EventType.AUTHORIZATION_REFUSED).exists()


def test_permission_rechecked_after_staging_and_refusal_audit_survives(args):
    @contextmanager
    def stage():
        User.objects.filter(pk=args["user"].pk).update(is_active=False)
        yield ()

    with pytest.raises(PermissionDenied):
        intake.execute_intake(**args, staging=stage, operation=lambda _: pytest.fail("stale permission"))
    assert not IntakeReceipt.objects.exists()
    assert SecurityEvent.objects.filter(event_type=SecurityEvent.EventType.AUTHORIZATION_REFUSED).exists()


@pytest.mark.parametrize("key", [None, "", "x" * 64, "a" * 63, "a" * 65, "A" * 64])
def test_invalid_request_key_refused_without_allocating(args, key):
    with pytest.raises(ValidationError):
        intake.execute_intake(**{**args, "key": key}, operation=synthetic_operation)
    assert not ComplaintIdSequence.objects.exists()


def test_missing_trusted_adapter_refused(args):
    with pytest.raises(TypeError):
        intake.execute_intake(**args, operation=None)
    assert not IntakeReceipt.objects.exists()


def test_invalid_payload_digest_refused(args):
    with pytest.raises(ValueError):
        intake.execute_intake(**{**args, "payload_digest": "untrusted-digest"}, operation=synthetic_operation)


def test_nested_transaction_refused(args):
    with transaction.atomic():
        with pytest.raises(TransactionManagementError, match="outermost"):
            intake.execute_intake(**args, operation=synthetic_operation)
    assert not IntakeReceipt.objects.exists()


def test_timestamp_is_server_controlled_and_replay_keeps_original(args, monkeypatch):
    first_time = datetime(2026, 12, 31, 12, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(intake.timezone, "now", lambda: first_time)
    first = intake.execute_intake(**args, operation=synthetic_operation)
    monkeypatch.setattr(intake.timezone, "now", lambda: first_time.replace(year=2027))
    replay = intake.execute_intake(**args, operation=synthetic_operation)
    assert replay.submitted_at == first_time == first.submitted_at
    assert replay.complaint_id.startswith("SCMS-2026-")


@pytest.mark.parametrize("shared_key", [True, False])
def test_eight_concurrent_connections_no_duplicate_work_or_identifier(args, shared_key):
    workers = 8
    barrier = threading.Barrier(workers)
    keys = [args["key"] if shared_key else intake.new_intake_key() for _ in range(workers)]

    def submit(index):
        close_old_connections()
        try:
            barrier.wait(timeout=15)
            return intake.execute_intake(**{**args, "key": keys[index]}, operation=synthetic_operation)
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(submit, range(workers)))  # exceptions are failures; no retries
    expected = 1 if shared_key else workers
    assert len({result.complaint_id for result in results}) == expected
    assert sum(not result.replayed for result in results) == expected
    assert IntakeReceipt.objects.count() == ComplaintHistory.objects.count() == expected
    assert ComplaintIdSequence.objects.get().last_value == expected


def test_database_constraints_reject_duplicate_keys(args):
    intake.execute_intake(**args, operation=synthetic_operation)
    receipt = IntakeReceipt.objects.get()
    values = {field: getattr(receipt, field) for field in
              ("user", "key_digest", "payload_digest", "submitted_at")}
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            IntakeReceipt.objects.create(**values, complaint_id="SCMS-2026-999999")


@pytest.mark.parametrize("mode", ["success-replay", "operation-failure", "commit-failure"])
def test_real_b09_storage_contract_when_available(args, settings, tmp_path, monkeypatch, mode):
    evidence = pytest.importorskip("complaints.evidence", reason="B09 PR #58 is not merged; storage integration pending.")
    from io import BytesIO
    from PIL import Image
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private"
    stream = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(stream, format="PNG")

    def stage():
        return evidence.staged_evidence([SimpleUploadedFile("synthetic.png", stream.getvalue())])

    def operation(context):
        assert len(context.evidence) == 1
        assert (settings.PRIVATE_EVIDENCE_ROOT / context.evidence[0].storage_name).exists()
        synthetic_operation(context)
        if mode == "operation-failure":
            raise RuntimeError("synthetic routing failure")

    if mode == "success-replay":
        first = intake.execute_intake(**args, staging=stage, operation=operation)
        originals = set(settings.PRIVATE_EVIDENCE_ROOT.iterdir())
        replay = intake.execute_intake(**args, staging=stage, operation=lambda _: pytest.fail("repeated"))
        assert replay.replayed and replay.complaint_id == first.complaint_id
        assert set(settings.PRIVATE_EVIDENCE_ROOT.iterdir()) == originals
    else:
        with monkeypatch.context() as patch:
            if mode == "commit-failure":
                patch.setattr(connection, "commit", lambda: (_ for _ in ()).throw(OperationalError("commit failed")))
            with pytest.raises((RuntimeError, OperationalError)):
                intake.execute_intake(**args, staging=stage, operation=operation)
        assert not list(settings.PRIVATE_EVIDENCE_ROOT.iterdir())
        assert not IntakeReceipt.objects.exists()
        assert not ComplaintIdSequence.objects.exists()
