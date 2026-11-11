"""Private local-filesystem reconciliation against primary Attachment metadata.

No complaint, receipt, account or reference data is modified. Recovery never
prints file names, source data, credentials or exception messages.
"""

import hashlib
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import connections

QUARANTINE = ".recovery-quarantine"


class EvidenceRecoveryUnavailable(Exception):
    """A sanitized operational refusal; no private paths or database details."""


@contextmanager
def evidence_lease(*, exclusive=False, create_root=True):
    """A shared writer lease spans staging through DB commit and error cleanup.

    Recovery takes a nonblocking exclusive lease. All writers must use the same
    private directory and staged_evidence contract on a flock-capable filesystem.
    Directory descriptors avoid a persistent lock file or identifying journal.
    With create_root=False, an absent directory yields None without creating it;
    callers must not scan that path without a lease if it appears concurrently.
    """
    import fcntl
    root = Path(settings.PRIVATE_EVIDENCE_ROOT)
    if create_root:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        if create_root:
            raise
        yield None
        return
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB if exclusive else fcntl.LOCK_SH)
        except BlockingIOError:
            raise EvidenceRecoveryUnavailable("Evidence writers or another recovery are active; retry later.") from None
        yield root
    finally:
        os.close(descriptor)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _files(directory):
    from .evidence import STORAGE_KEY
    found, ignored = {}, 0
    if not directory.exists():
        return found, ignored
    for path in directory.iterdir():
        if STORAGE_KEY.fullmatch(path.name):
            if not stat.S_ISREG(path.lstat().st_mode):
                raise EvidenceRecoveryUnavailable("A generated evidence entry is not a regular file; no changes made.")
            found[path.name] = path
        elif path.name != QUARANTINE:
            ignored += 1
    return found, ignored


def _matches(path, row):
    # Open without following symlinks. Accepted files are immutable while all
    # participating writers/recovery commands hold the directory lease.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_size != row["size"]
                or not 0 < row["size"] <= 5 * 1024 * 1024):
            return False
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return digest == row["sha256"]


@dataclass(frozen=True)
class RecoveryReport:
    referenced: int = 0
    orphaned: int = 0
    quarantined: int = 0
    restorable: int = 0
    purgeable: int = 0
    ignored: int = 0
    applied: bool = False


def reconcile_evidence(*, apply=False, purge_quarantine=False):
    """Dry-run by default; apply quarantines, restores and optionally purges.

    All referenced files are checked before any mutation. Missing/corrupt
    accepted evidence, unsafe entries or unavailable metadata abort the run.
    Quarantine moves are reversible; purging requires explicit opt-in and a
    fresh primary-DB reference check under the exclusive lease on EVERY run.
    """
    from .evidence import STORAGE_KEY
    from .models import Attachment
    if connections["default"].in_atomic_block:
        raise EvidenceRecoveryUnavailable("Recovery requires an outermost primary-database view.")
    if purge_quarantine and not apply:
        raise EvidenceRecoveryUnavailable("Purging requires explicit apply mode.")
    try:
        with evidence_lease(exclusive=True, create_root=apply) as root:
            # Query the primary database before classifying or moving any file.
            rows = list(Attachment.objects.using("default").values("storage_name", "size", "sha256"))
            if any(not STORAGE_KEY.fullmatch(row["storage_name"]) for row in rows):
                raise EvidenceRecoveryUnavailable("Invalid attachment metadata; no changes made.")
            if root is None:
                if rows:
                    raise EvidenceRecoveryUnavailable("Accepted evidence is missing or corrupt; no changes made.")
                return RecoveryReport()
            accepted = {row["storage_name"]: row for row in rows}
            quarantine = root / QUARANTINE
            if quarantine.is_symlink() or (quarantine.exists() and not quarantine.is_dir()):
                raise EvidenceRecoveryUnavailable("Unsafe recovery directory; no changes made.")
            active, ignored = _files(root)
            retained, extra = _files(quarantine)
            restore = []
            for name, row in accepted.items():
                if name in active:
                    if not _matches(active[name], row):
                        raise EvidenceRecoveryUnavailable("Accepted evidence failed integrity verification; no changes made.")
                elif name in retained and _matches(retained[name], row):
                    restore.append(name)
                else:
                    raise EvidenceRecoveryUnavailable("Accepted evidence is missing or corrupt; no changes made.")
            orphaned = sorted(set(active) - set(accepted))
            purgeable = sorted(set(retained) - set(accepted))
            if any(name in retained for name in orphaned):
                raise EvidenceRecoveryUnavailable("Conflicting recovery copies require investigation; no changes made.")
            report = RecoveryReport(len(accepted), len(orphaned), len(retained), len(restore),
                                    len(purgeable), ignored + extra, apply)
            if apply:
                if orphaned:
                    quarantine.mkdir(mode=0o700, exist_ok=True)
                    sync_directory(root)
                for name in restore:
                    os.rename(quarantine / name, root / name)
                for name in orphaned:
                    os.rename(root / name, quarantine / name)
                if purge_quarantine:
                    # Only items already quarantined BEFORE this run are purged.
                    # Newly discovered orphans always get a reversible first pass.
                    for name in purgeable:
                        (quarantine / name).unlink()
                if quarantine.exists():
                    sync_directory(quarantine)
                sync_directory(root)
            return report
    except EvidenceRecoveryUnavailable:
        raise
    except Exception:
        # DB and OSError messages can contain credentials, file paths or input.
        # Partial quarantine moves remain discoverable and retryable next run.
        raise EvidenceRecoveryUnavailable("Evidence recovery could not complete; retain the files and retry safely.") from None
