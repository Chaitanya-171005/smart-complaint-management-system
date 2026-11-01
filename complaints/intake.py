"""B10 authenticated retry/transaction guard; actual intake adapters are pending.

Only trusted application code may supply operation/after_commit callbacks.
There is deliberately no view that acknowledges an unimplemented Complaint.
"""

import hashlib
import json
import re
import secrets
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections, transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from accounts.models import User
from accounts.permissions import can_submit_complaint, require_permission

from .identifiers import allocate_complaint_id
from .models import IntakeReceipt

HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class IdempotencyConflict(ValidationError):
    """A previously accepted request key was reused with different content."""


@dataclass(frozen=True)
class IntakeContext:
    user: User
    complaint_id: str
    submitted_at: datetime
    evidence: tuple


@dataclass(frozen=True)
class IntakeResult:
    complaint_id: str
    submitted_at: datetime
    replayed: bool


def new_intake_key():
    """Server-created key for one authenticated form operation, not a login token."""
    return secrets.token_hex(32)


def submission_digest(*, fields, evidence_sha256=()):
    """Hash server-canonical JSON values and ordered hashes of verified file bytes.

    fields must contain ALL submission-affecting validated values, using stable
    category/location keys. Never pass an untrusted digest from POST. File order
    is significant; filenames/MIME/stage must also be in fields if persisted.
    """
    hashes = tuple(evidence_sha256)
    if not isinstance(fields, dict) or any(
        not isinstance(value, str) or not HEX_DIGEST.fullmatch(value) for value in hashes
    ):
        raise ValueError("Use canonical field values and SHA-256 hashes of validated evidence.")
    encoded = json.dumps({"fields": fields, "evidence_sha256": hashes},
                         sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _ReplayResult(Exception):
    """Internal signal: unwind a newly staged batch without discarding the receipt."""

    def __init__(self, result):
        self.result = result


def execute_intake(*, user, key, payload_digest, operation, staging=None, after_commit=None):
    """Run a trusted required-operation adapter once per (account, request key).

    operation(IntakeContext) must persist the real Complaint plus required
    routing/history/attachment metadata in this SAME default DB transaction,
    and raise on any failure. It must not commit, send mail or publish acceptance.
    The guard cannot infer whether an arbitrary callback implemented that contract.

    Own the OUTERMOST transaction: the result is returned only after commit.
    Optional staging() returns B09's cleanup context manager. Its descriptors
    are context.evidence. It encloses the transaction and is unwound on replay
    too, so re-uploaded retry bytes cannot become orphaned duplicate files.
    """
    if connections["default"].in_atomic_block:
        raise TransactionManagementError("execute_intake must own the outermost transaction.")
    if (not callable(operation)
            or (staging is not None and not callable(staging))
            or (after_commit is not None and not callable(after_commit))):
        raise TypeError("Trusted intake operation and optional notification callbacks are required.")
    # Refuse unauthenticated callers before looking up any receipt. Use the
    # shared check for its generic refusal and audit event.
    if user is None or not user.is_authenticated or user.pk is None:
        require_permission(can_submit_complaint, user)
    if not isinstance(key, str) or not HEX_DIGEST.fullmatch(key):
        raise ValidationError("Use the server-issued intake request key.", code="request_key")
    if not isinstance(payload_digest, str) or not HEX_DIGEST.fullmatch(payload_digest):
        raise ValueError("payload_digest must be a server-computed SHA-256 digest.")
    key_digest = hashlib.sha256(key.encode("ascii")).hexdigest()
    current_user = User.objects.filter(pk=user.pk).first()
    require_permission(can_submit_complaint, current_user)  # before file processing
    try:
        with staging() if staging is not None else nullcontext(()) as staged:
            with transaction.atomic(durable=True):
                # Serialize intake for an account, including concurrent first use
                # of a key. SQLite's configured IMMEDIATE transaction serializes
                # writers; row-locking databases lock this account instead.
                current_user = User.objects.select_for_update().filter(pk=user.pk).first()
                if not can_submit_complaint(current_user):
                    raise PermissionDenied
                receipt = IntakeReceipt.objects.filter(user=current_user, key_digest=key_digest).first()
                if receipt is not None:
                    if receipt.payload_digest != payload_digest:
                        raise IdempotencyConflict(
                            "This request key was already used with different submission data.",
                            code="idempotency_conflict",
                        )
                    result = IntakeResult(receipt.complaint_id, receipt.submitted_at, True)
                else:
                    submitted_at = timezone.now()
                    complaint_id = allocate_complaint_id(submitted_at=submitted_at)
                    context = IntakeContext(current_user, complaint_id, submitted_at, tuple(staged))
                    operation(context)
                    # No PENDING receipt is committed. The receipt, ID reservation
                    # and all callback writes either commit together or roll back.
                    IntakeReceipt.objects.create(
                        user=current_user, key_digest=key_digest, payload_digest=payload_digest,
                        complaint_id=complaint_id, submitted_at=submitted_at,
                    )
                    result = IntakeResult(complaint_id, submitted_at, False)
                    if after_commit is not None:
                        # A mail failure is logged by Django and cannot reverse
                        # the business commit. Replays do not resend the callback.
                        transaction.on_commit(lambda: after_commit(result), robust=True)
            if result.replayed:
                # B09 sees an exception and removes only THIS attempt's staged
                # files; the already committed receipt and originals survive.
                raise _ReplayResult(result)
    except _ReplayResult as replay:
        return replay.result
    except PermissionDenied:
        # Log outside the rolled-back transaction so the refusal is retained.
        # If operation itself refused, propagate that exception unchanged.
        require_permission(can_submit_complaint, current_user)
        raise
    return result
