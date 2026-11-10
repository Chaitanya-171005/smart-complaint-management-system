"""B10/Q05 real-file recovery, primary-DB checks and abrupt process-death tests."""

import base64
import hashlib
import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from PIL import Image

from complaints import evidence
from complaints.evidence_recovery import (
    QUARANTINE, EvidenceRecoveryUnavailable, evidence_lease, reconcile_evidence,
)
from complaints.models import Attachment, Complaint, IntakeReceipt

pytestmark = pytest.mark.django_db(transaction=True)


def png():
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def root(settings, tmp_path):
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private"
    return settings.PRIVATE_EVIDENCE_ROOT


def orphan(root, character="a", data=None):
    root.mkdir(mode=0o700, exist_ok=True)
    path = root / (character * 32 + ".png")
    path.write_bytes(png() if data is None else data)
    path.chmod(0o600)
    return path


def metadata(complaint, path, **overrides):
    data = path.read_bytes()
    return Attachment.objects.create(complaint=complaint, storage_name=path.name,
        original_name="synthetic.png", content_type="image/png", size=len(data),
        sha256=hashlib.sha256(data).hexdigest(), stage="INTAKE", **overrides)


def test_dry_run_reports_orphans_without_moving_or_deleting(root):
    path = orphan(root)
    before = path.read_bytes()
    result = reconcile_evidence()
    assert result.orphaned == 1 and not result.applied
    assert path.read_bytes() == before and not (root / QUARANTINE).exists()


def test_apply_quarantines_then_explicit_second_run_can_purge(root):
    path = orphan(root)
    first = reconcile_evidence(apply=True, purge_quarantine=True)
    assert first.orphaned == 1 and first.purgeable == 0
    retained = root / QUARANTINE / path.name
    assert not path.exists() and retained.read_bytes() == png()
    assert retained.stat().st_mode & 0o777 == 0o600
    assert (root / QUARANTINE).stat().st_mode & 0o777 == 0o700
    second = reconcile_evidence(apply=True, purge_quarantine=True)
    assert second.purgeable == 1 and not retained.exists()
    assert reconcile_evidence(apply=True).orphaned == 0


def test_purge_requires_apply(root):
    with pytest.raises(EvidenceRecoveryUnavailable, match="explicit apply"):
        reconcile_evidence(purge_quarantine=True)


def test_accepted_intake_and_resolution_evidence_are_preserved(root, complaint_factory):
    complaint = complaint_factory()
    first, second, extra = orphan(root, "a"), orphan(root, "b"), orphan(root, "c")
    metadata(complaint, first)
    attachment = metadata(complaint, second)
    Attachment.objects.filter(pk=attachment.pk).update(stage="RESOLUTION")
    database_before = list(Attachment.objects.values())
    result = reconcile_evidence(apply=True)
    assert result.referenced == 2 and result.orphaned == 1
    assert first.exists() and second.exists() and not extra.exists()
    assert list(Attachment.objects.values()) == database_before
    assert Complaint.objects.filter(pk=complaint.pk).exists()


def test_accepted_quarantined_file_is_restored_not_purged(root, complaint_factory):
    path = orphan(root)
    reconcile_evidence(apply=True)
    retained = root / QUARANTINE / path.name
    metadata(complaint_factory(), retained)
    preview = reconcile_evidence()
    assert preview.restorable == 1 and preview.purgeable == 0
    reconcile_evidence(apply=True, purge_quarantine=True)
    assert path.read_bytes() == png() and not retained.exists()


@pytest.mark.parametrize("broken", ["missing", "size", "sha256"])
def test_invalid_accepted_evidence_prevents_all_mutation(root, complaint_factory, broken):
    path, extra = orphan(root), orphan(root, "b")
    attachment = metadata(complaint_factory(), path)
    if broken == "missing":
        path.unlink()
    elif broken == "size":
        path.write_bytes(b"truncated")
    else:
        Attachment.objects.filter(pk=attachment.pk).update(sha256="b" * 64)
    with pytest.raises(EvidenceRecoveryUnavailable, match="missing|integrity"):
        reconcile_evidence(apply=True, purge_quarantine=True)
    assert extra.exists() and not (root / QUARANTINE).exists()
    assert Attachment.objects.filter(pk=attachment.pk).exists()


def test_unavailable_primary_metadata_never_quarantines_any_file(root):
    path = orphan(root)
    with patch.object(Attachment.objects, "using", side_effect=RuntimeError("private-db-password")):
        with pytest.raises(EvidenceRecoveryUnavailable) as error:
            reconcile_evidence(apply=True)
    assert "private-db-password" not in str(error.value) and path.exists()


def test_unknown_names_are_preserved_and_not_reported_verbatim(root):
    root.mkdir()
    private = root / "private-person@example.test.txt"
    private.write_text("synthetic private data")
    result = reconcile_evidence(apply=True)
    assert result.ignored == 1 and private.read_text() == "synthetic private data"
    assert "private-person" not in str(asdict(result))


@pytest.mark.parametrize("location", ["root", "quarantine"])
def test_generated_symlinks_are_not_followed_or_removed(root, tmp_path, location):
    outside = tmp_path / "outside.png"
    outside.write_bytes(png())
    parent = root if location == "root" else root / QUARANTINE
    parent.mkdir(parents=True)
    link = parent / ("a" * 32 + ".png")
    link.symlink_to(outside)
    with pytest.raises(EvidenceRecoveryUnavailable, match="regular file"):
        reconcile_evidence(apply=True, purge_quarantine=True)
    assert link.is_symlink() and outside.read_bytes() == png()


def test_quarantine_symlink_is_rejected(root, tmp_path):
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / QUARANTINE).symlink_to(outside, target_is_directory=True)
    with pytest.raises(EvidenceRecoveryUnavailable, match="Unsafe"):
        reconcile_evidence(apply=True)
    assert not list(outside.iterdir())


def test_existing_quarantine_name_cannot_be_overwritten(root):
    path = orphan(root)
    quarantine = root / QUARANTINE
    quarantine.mkdir()
    (quarantine / path.name).write_bytes(b"other retained bytes")
    with pytest.raises(EvidenceRecoveryUnavailable, match="Conflicting"):
        reconcile_evidence(apply=True, purge_quarantine=True)
    assert path.read_bytes() == png()
    assert (quarantine / path.name).read_bytes() == b"other retained bytes"


def test_writer_lease_prevents_recovery_until_intake_exits(root):
    with evidence.staged_evidence([ContentFile(png(), name="synthetic.png")]):
        with pytest.raises(EvidenceRecoveryUnavailable, match="active"):
            reconcile_evidence(apply=True)
    assert reconcile_evidence(apply=True).orphaned == 1


def test_overlapping_recovery_cannot_take_exclusive_lease(root):
    with evidence_lease(exclusive=True):
        with pytest.raises(EvidenceRecoveryUnavailable, match="active"):
            reconcile_evidence()


def test_recovery_refuses_an_existing_database_transaction(root):
    with transaction.atomic():
        with pytest.raises(EvidenceRecoveryUnavailable, match="outermost"):
            reconcile_evidence(apply=True)


def test_bytes_and_directory_are_synced_before_staging_returns(root, monkeypatch):
    calls = []
    original = os.fsync
    def sync(descriptor):
        calls.append(os.fstat(descriptor).st_mode)
        original(descriptor)
    monkeypatch.setattr(os, "fsync", sync)
    with evidence.staged_evidence([ContentFile(png(), name="synthetic.png")]):
        import stat
        assert any(stat.S_ISREG(mode) for mode in calls)
        assert any(stat.S_ISDIR(mode) for mode in calls)


def test_post_commit_exception_preserves_accepted_attachment(root, complaint_factory):
    complaint = complaint_factory()
    with pytest.raises(RuntimeError, match="after commit"):
        with evidence.staged_evidence([ContentFile(png(), name="synthetic.png")]) as stored:
            with transaction.atomic(durable=True):
                metadata(complaint, root / stored[0].storage_name)
            raise RuntimeError("synthetic callback failed after commit")
    assert reconcile_evidence().referenced == 1
    assert Attachment.objects.count() == 1


def test_unknown_database_state_defers_cleanup_and_preserves_original_error(root, caplog):
    with patch.object(Attachment.objects, "using", side_effect=RuntimeError("private-db-password")):
        with pytest.raises(RuntimeError, match="original required operation"):
            with evidence.staged_evidence([ContentFile(png(), name="synthetic.png")]):
                raise RuntimeError("original required operation")
    assert "private-db-password" not in caplog.text
    assert "deferred to recovery" in caplog.text
    assert reconcile_evidence().orphaned == 1


@pytest.mark.parametrize("anonymous", [False, True])
def test_failed_cleanup_is_retryable_and_does_not_log_private_exception(root, monkeypatch, caplog, anonymous):
    monkeypatch.setattr(evidence.PrivateEvidenceStorage, "delete", lambda *args: (_ for _ in ()).throw(OSError("private-content@example.test")))
    with pytest.raises(RuntimeError, match="original required operation"):
        with evidence.staged_evidence([ContentFile(png(), name="synthetic.png")], anonymous=anonymous):
            raise RuntimeError("original required operation")
    assert "private-content" not in caplog.text
    assert reconcile_evidence(apply=True).orphaned == 1


def test_interrupted_move_can_be_retried_without_losing_files(root, monkeypatch):
    orphan(root, "a")
    orphan(root, "b")
    original = os.rename
    count = 0
    def fail_second(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("synthetic interruption")
        original(*args)
    with monkeypatch.context() as context:
        context.setattr(os, "rename", fail_second)
        with pytest.raises(EvidenceRecoveryUnavailable):
            reconcile_evidence(apply=True)
    result = reconcile_evidence(apply=True)
    assert result.orphaned == 1 and result.quarantined == 1
    assert len(list((root / QUARANTINE).iterdir())) == 2


def test_command_reports_only_counts_and_fails_nonzero_on_integrity_error(root, complaint_factory):
    path = orphan(root)
    output = StringIO()
    call_command("reconcile_evidence", stdout=output)
    assert "mode=dry-run" in output.getvalue() and "orphans=1" in output.getvalue()
    assert path.name not in output.getvalue()
    metadata(complaint_factory(), path)
    path.unlink()
    with pytest.raises(CommandError, match="missing"):
        call_command("reconcile_evidence", apply=True)


CHILD = r'''
import base64, json, os, signal
from contextlib import contextmanager
import django
django.setup()
from django.core.files.base import ContentFile
from accounts.models import User
from complaints import evidence, intake, submission
mode = os.environ["SCMS_CRASH_POINT"]
original = evidence.staged_evidence
@contextmanager
def staged(files):
    with original(files) as batch:
        if mode == "before": os.kill(os.getpid(), signal.SIGKILL)
        yield batch
        if mode == "after": os.kill(os.getpid(), signal.SIGKILL)
submission.staged_evidence = staged
if mode == "during":
    create = intake.IntakeReceipt.objects.create
    def interrupted_create(**kwargs):
        result = create(**kwargs)
        os.kill(os.getpid(), signal.SIGKILL)
        return result
    intake.IntakeReceipt.objects.create = interrupted_create
submission.submit_authenticated_complaint(
    user=User.objects.get(pk=int(os.environ["SCMS_TEST_USER"])),
    key="a"*64, data=json.loads(os.environ["SCMS_TEST_FIELDS"]),
    files=[ContentFile(base64.b64decode(os.environ["SCMS_TEST_PNG"]), name="synthetic.png")],
)
raise SystemExit("Crash point was not reached")
'''


@pytest.mark.parametrize("point", ["before", "during", "after"])
def test_sigkill_intake_recovery_keeps_only_committed_graph(root, complainant_user, routing_configuration, point):
    config = routing_configuration
    data = {"category": str(config["category"].pk), "location": config["location"].code,
        "title": "Synthetic crash check", "description": "Synthetic description for interrupted intake.", "priority": "LOW"}
    environment = os.environ.copy()
    environment.update(DJANGO_SETTINGS_MODULE="scms.settings", DJANGO_SECRET_KEY="synthetic-child-test-only",
        DJANGO_DB_PATH=str(connection.settings_dict["NAME"]), PRIVATE_EVIDENCE_ROOT=str(root),
        SCMS_CRASH_POINT=point, SCMS_TEST_USER=str(complainant_user.pk), SCMS_TEST_FIELDS=json.dumps(data),
        SCMS_TEST_PNG=base64.b64encode(png()).decode())
    result = subprocess.run([sys.executable, "-c", CHILD], env=environment,
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
    assert result.returncode == -signal.SIGKILL, result.stderr
    report = reconcile_evidence(apply=True)
    if point == "after":
        assert report.referenced == 1 and report.orphaned == 0
        assert Complaint.objects.count() == IntakeReceipt.objects.count() == Attachment.objects.count() == 1
        attachment = Attachment.objects.get()
        assert (root / attachment.storage_name).read_bytes() == png()
    else:
        assert report.referenced == 0 and report.orphaned == 1
        assert not Complaint.objects.exists() and not IntakeReceipt.objects.exists() and not Attachment.objects.exists()
        assert len(list((root / QUARANTINE).iterdir())) == 1
    # A restarted app retries the SAME operation key, without resetting data.
    from complaints.submission import submit_authenticated_complaint
    retried = submit_authenticated_complaint(user=complainant_user, key="a" * 64,
        data=data, files=[ContentFile(png(), name="synthetic.png")])
    assert retried.replayed is (point == "after")
    assert Complaint.objects.count() == IntakeReceipt.objects.count() == Attachment.objects.count() == 1
    # Same command is safe on a second run, with no record deletions/reset.
    assert reconcile_evidence(apply=True).orphaned == 0


def test_file_sync_failure_never_yields_staged_acceptance(root, monkeypatch):
    def failed_sync(descriptor):
        raise OSError("synthetic fsync failure")
    with monkeypatch.context() as context:
        context.setattr(os, "fsync", failed_sync)
        with pytest.raises(OSError, match="fsync failure"):
            with evidence.staged_evidence([ContentFile(png(), name="synthetic.png")]):
                pytest.fail("Unsynced file was yielded")
    assert not list(root.iterdir())


def test_private_storage_root_symlink_is_refused(tmp_path, settings):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "private"
    root.symlink_to(outside, target_is_directory=True)
    settings.PRIVATE_EVIDENCE_ROOT = root
    with pytest.raises(EvidenceRecoveryUnavailable):
        reconcile_evidence(apply=True)
    assert not list(outside.iterdir())


def test_live_writer_in_another_process_prevents_recovery(root):
    import select
    child = r"""
import django, sys
django.setup()
from django.core.files.base import ContentFile
from complaints.evidence import staged_evidence
from complaints.test_evidence_recovery import png
with staged_evidence([ContentFile(png(), name="synthetic.png")]):
    print("ready", flush=True)
    sys.stdin.readline()
"""
    environment = os.environ.copy()
    environment.update(DJANGO_SETTINGS_MODULE="scms.settings", DJANGO_SECRET_KEY="synthetic-child-test-only",
                       PRIVATE_EVIDENCE_ROOT=str(root))
    process = subprocess.Popen([sys.executable, "-c", child], env=environment,
        cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 5)
        assert ready and process.stdout.readline().strip() == "ready"
        with pytest.raises(EvidenceRecoveryUnavailable, match="active"):
            reconcile_evidence(apply=True)
        assert not (root / QUARANTINE).exists()
    finally:
        process.communicate("finish\n", timeout=5)
    assert process.returncode == 0
    assert reconcile_evidence(apply=True).orphaned == 1
