"""B11 anonymous intake: one committed graph and one nonrecoverable reference."""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import connections, transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .evidence import staged_evidence
from .identifiers import allocate_complaint_id
from .intake import HEX_DIGEST, IdempotencyConflict, submission_digest
from .models import AnonymousIntakeReceipt
from .privacy import private_evidence
from .submission import _clean_fields, _persist_complaint


class AnonymousIntakeUnavailable(Exception):
    """Sanitized required-operation failure; never includes input or references."""


@dataclass(frozen=True)
class AnonymousContext:
    complaint_id: str
    submitted_at: datetime
    evidence: tuple


@dataclass(frozen=True)
class AnonymousResult:
    complaint_id: str
    submitted_at: datetime
    replayed: bool
    reference: str | None = field(default=None, repr=False)


class _AcceptedReplay(Exception):
    def __init__(self, result):
        self.result = result


@sensitive_variables()
def submit_anonymous_complaint(*, key, data, files=()):
    """No user/request/IP/session argument is accepted or looked up.

    The operation key is random form state, not a source/rate-limit key. Only
    its hash and a canonical payload hash are retained with the complaint.
    A replay never regenerates or reveals the first result's raw reference.
    """
    if connections["default"].in_atomic_block:
        raise TransactionManagementError("Anonymous intake must own its outermost transaction.")
    if not isinstance(key, str) or not HEX_DIGEST.fullmatch(key):
        raise ValidationError("Use the server-issued anonymous form.", code="request_key")
    fields = _clean_fields(data)
    validated = private_evidence(files)
    fingerprint = submission_digest(fields={**fields, "evidence": [
        {"name": item.original_name, "type": item.content_type, "size": len(item.data)}
        for item in validated
    ]}, evidence_sha256=[hashlib.sha256(item.data).hexdigest() for item in validated])
    key_digest = hashlib.sha256(key.encode("ascii")).hexdigest()
    try:
        with staged_evidence([
            ContentFile(item.data, name=item.original_name) for item in validated
        ], anonymous=True) as stored:
            with transaction.atomic(durable=True):
                now = timezone.now()
                # The yearly sequence serializes writers before the receipt read
                # on row-locking databases as well as SQLite IMMEDIATE. Replays
                # unwind this reservation and their newly staged files.
                identifier = allocate_complaint_id(submitted_at=now)
                receipt = AnonymousIntakeReceipt.objects.select_related("complaint").filter(
                    key_digest=key_digest,
                ).first()
                if receipt is not None:
                    if receipt.payload_digest != fingerprint:
                        raise IdempotencyConflict("This form was accepted with different details.",
                                                  code="idempotency_conflict")
                    complaint = receipt.complaint
                    if complaint.submitted_by_id is not None or not complaint.reference_digest:
                        raise AnonymousIntakeUnavailable("Anonymous intake needs reconciliation.")
                    raise _AcceptedReplay(AnonymousResult(
                        complaint.complaint_id, complaint.submitted_at, True,
                    ))
                context = AnonymousContext(identifier, now, tuple(stored))
                complaint, reference = _persist_complaint(context, fields, anonymous=True)
                AnonymousIntakeReceipt.objects.create(
                    key_digest=key_digest, payload_digest=fingerprint, complaint=complaint,
                )
                result = AnonymousResult(complaint.complaint_id, complaint.submitted_at, False, reference)
        # The outermost DB commit succeeded before a raw reference can escape.
        return result
    except _AcceptedReplay as replay:
        return replay.result
    except ValidationError:
        raise
    except Exception:
        # Do not expose storage/history/DB exception values (or their chains) to
        # HTTP, error email or an exception logger.
        raise AnonymousIntakeUnavailable("Anonymous intake could not complete.") from None
