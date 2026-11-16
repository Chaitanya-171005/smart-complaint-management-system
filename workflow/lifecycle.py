"""B20 shared account-action policy and conflict-safe state mutation boundary.

No HTTP action, resolution/evidence flow, reference feedback or scheduler is
introduced here. Those features must validate their own data before using the
shared locked mutation primitive; they cannot bypass the account service gates.
"""

import json
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Max
from django.http import Http404
from django.utils.crypto import constant_time_compare, salted_hmac

from accounts.models import User
from accounts.permissions import (
    can_confirm_resolution, can_progress_complaint, can_reject_complaint,
    can_resolve_complaint, can_submit_complaint, can_view_complaint,
    authorize_or_404, has_role, require_permission,
)
from complaints.models import Complaint
from workflow.history_service import record_history
from workflow.models import ComplaintHistory

State = Complaint.Status
Role = User.Role
TERMINAL_STATES = frozenset({State.CLOSED, State.REJECTED})
MAX_REASON_LENGTH = 2000  # Technical input bound; not B24's feedback minimum.


class LifecycleError(ValidationError):
    pass


class ModifiedRecord(LifecycleError):
    def __init__(self):
        super().__init__("The complaint has changed. Refresh before trying again.", code="modified_record")


class FeatureRequired(LifecycleError):
    def __init__(self, feature):
        super().__init__(f"This transition requires the {feature} action service.", code="feature_required")


@dataclass(frozen=True)
class TransitionRule:
    roles: tuple
    permission: object
    feature: str | None = None
    external_actors: tuple = ()


# SRS §4.3: every unlisted pair is denied, including every terminal exit/self-loop.
# External actors are documented policy entries, never booleans that authorize a
# request. Dedicated F2/B23/B24/B25 services must establish those capabilities.
TRANSITIONS = MappingProxyType({
    (State.SUBMITTED, State.ASSIGNED): TransitionRule((), None, "F2 routing", ("SYSTEM_ROUTING",)),
    (State.SUBMITTED, State.REJECTED): TransitionRule((Role.ADMIN, Role.HEAD), can_reject_complaint),
    (State.ASSIGNED, State.IN_PROGRESS): TransitionRule((Role.STAFF, Role.HEAD), can_progress_complaint),
    (State.ASSIGNED, State.REJECTED): TransitionRule((Role.STAFF, Role.HEAD), can_reject_complaint),
    (State.IN_PROGRESS, State.RESOLVED): TransitionRule((Role.STAFF,), can_resolve_complaint, "B22"),
    (State.RESOLVED, State.CLOSED): TransitionRule((Role.COMPLAINANT,), can_confirm_resolution, "B23/B25",
                                                ("ANONYMOUS_REFERENCE", "AUTO_CLOSE")),
    (State.RESOLVED, State.REOPENED): TransitionRule((Role.COMPLAINANT,), can_confirm_resolution, "B24",
                                                  ("ANONYMOUS_REFERENCE",)),
    (State.REOPENED, State.IN_PROGRESS): TransitionRule((Role.STAFF, Role.HEAD), can_progress_complaint),
})


@dataclass(frozen=True)
class TransitionResult:
    complaint_id: str
    previous_state: str
    new_state: str
    history_id: int
    revision: str


class _Denied(Exception):
    def __init__(self, actor, complaint, conceal=False):
        self.actor, self.complaint, self.conceal = actor, complaint, conceal


def _lifecycle_refused(actor, complaint):
    return False


def _report_denial(denial):
    # F1 logs only a static action and internal object ID, after this service's
    # rollback. An outer caller transaction still controls its audit commit.
    try:
        require_permission(_lifecycle_refused, denial.actor, denial.complaint)
    except PermissionDenied:
        if denial.conceal:
            raise Http404 from None
        raise


def _current_actor(actor):
    if actor is None or not getattr(actor, "is_authenticated", False):
        return None
    return User.objects.filter(pk=actor.pk).select_for_update().first()


def _locked_complaint(complaint_id):
    complaint = Complaint.objects.filter(complaint_id=complaint_id).select_for_update().first()
    if complaint is None:
        raise Http404
    return complaint


def _require_scope(actor, complaint, target_state):
    # An Admin's narrow SUBMITTED rejection is an action permission, not content
    # read access. Results/revision contain no complaint text or reporter data.
    admin_rejection = (target_state == State.REJECTED and complaint.status == State.SUBMITTED
                       and has_role(actor, Role.ADMIN) and can_reject_complaint(actor, complaint))
    if not (can_view_complaint(actor, complaint) or admin_rejection):
        raise _Denied(actor, complaint, conceal=True)


def _authorize(actor, complaint, target_state):
    _require_scope(actor, complaint, target_state)
    if not isinstance(target_state, str) or target_state not in State.values:
        raise LifecycleError("Choose a valid state.", code="invalid_transition")
    rule = TRANSITIONS.get((complaint.status, target_state))
    if complaint.status in TERMINAL_STATES or rule is None:
        raise LifecycleError("This state transition is not permitted.", code="invalid_transition")
    if not (has_role(actor, *rule.roles) and rule.permission is not None
            and rule.permission(actor, complaint)):
        raise _Denied(actor, complaint)
    return rule


def _revision(complaint):
    # Keyed digest: version metadata never exposes anonymous digests, personal
    # data or the complaint body. Count plus maximum PK also detects a history
    # append whose ID was reserved earlier but committed later than another row.
    row = Complaint.objects.filter(pk=complaint.pk).values().get()
    history = ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).aggregate(
        count=Count("pk"), latest=Max("pk"))
    # str(datetime) preserves full microseconds; DjangoJSONEncoder truncates
    # them, which would miss sub-millisecond due/resolution timestamp changes.
    value = json.dumps({"complaint": row, "history": history}, default=str,
                       sort_keys=True, separators=(",", ":"))
    return salted_hmac("workflow.lifecycle.v1", value, algorithm="sha256").hexdigest()


def get_transition_revision(*, actor, complaint_id, target_state):
    """Capture an authorized opaque precondition for a particular account action."""
    try:
        with transaction.atomic():
            complaint = _locked_complaint(complaint_id)
            current = _current_actor(actor)
            _authorize(current, complaint, target_state)
            return _revision(complaint)
    except _Denied as denial:
        _report_denial(denial)


def _clean_reason(reason, target_state):
    if not isinstance(reason, str) or len(reason.strip()) > MAX_REASON_LENGTH:
        raise LifecycleError("Supply a valid reason of at most 2000 characters.", code="invalid_reason")
    reason = reason.strip()
    if target_state == State.REJECTED and not reason:
        raise LifecycleError("A rejection reason is required.", code="reason_required")
    return reason


def _apply_locked_transition(complaint, actor, target_state, reason):
    """Trusted shared writer: caller owns lock, stale/auth and feature validation.

    Future B22-B25 wrappers must validate evidence/ratings/reopen/expiry and
    persist their metadata inside the SAME transaction before calling this.
    No user-supplied callback, update dictionary or anonymous/system flag exists.
    """
    _authorize(actor, complaint, target_state)
    return _persist_locked_transition(complaint, actor, target_state, reason)


def _persist_locked_transition(complaint, actor, target_state, reason):
    """Internal writer after account or scheduler validation under the row lock.

    None means SYSTEM only here; public account actions still deny it.
    """
    previous = complaint.status
    complaint.status = target_state
    complaint.save(update_fields=["status"])
    event_type = (ComplaintHistory.EventType.RESOLVED if target_state == State.RESOLVED
                  else ComplaintHistory.EventType.STATUS_CHANGED)
    # PR #68 owns the optional account field/API; do not duplicate its schema.
    account = {"actor": actor} if actor is not None and any(field.name == "actor" for field in ComplaintHistory._meta.fields) else {}
    history = record_history(complaint.complaint_id, event_type, actor.role if actor else "SYSTEM",
                             previous_state=previous, new_state=target_state, remarks=reason, **account)
    return TransitionResult(complaint.complaint_id, previous, target_state, history.pk, _revision(complaint))


@contextmanager
def _account_transition(*, actor, complaint_id, target_state, expected_revision):
    """Shared checked transaction for reviewed B22-B24 account-action wrappers.

    The wrapper must implement its feature-specific validation before invoking
    the trusted writer. This context alone never changes state or adds history.
    """
    try:
        with transaction.atomic():
            complaint = _locked_complaint(complaint_id)
            current = _current_actor(actor)
            _require_scope(current, complaint, target_state)
            if (not isinstance(expected_revision, str)
                    or len(expected_revision) != 64
                    or not constant_time_compare(expected_revision, _revision(complaint))):
                raise ModifiedRecord()
            rule = _authorize(current, complaint, target_state)
            yield complaint, current, rule
    except _Denied as denial:
        _report_denial(denial)


def transition_complaint(*, actor, complaint_id, target_state, expected_revision, reason=""):
    """Apply B20's start/reject transitions; later feature mutations fail closed."""
    with _account_transition(actor=actor, complaint_id=complaint_id,
                             target_state=target_state, expected_revision=expected_revision) as context:
        complaint, current, rule = context
        if rule.feature is not None:
            raise FeatureRequired(rule.feature)
        return _apply_locked_transition(complaint, current, target_state,
                                        _clean_reason(reason, target_state))


def validate_owner_edit(*, actor, complaint_id):
    """Guard for a future owner-edit service; does not edit or return content.

    Call inside the edit's outer transaction so the row lock covers that write.
    No edit endpoint is introduced. F2 intake/retry remains a separate operation.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Owner edits must own a transaction before validation.")
    complaint = _locked_complaint(complaint_id)
    current = _current_actor(actor)
    authorize_or_404(_can_owner_edit, current, complaint)
    if complaint.status != State.SUBMITTED:
        raise LifecycleError("Owner edits are closed after SUBMITTED.", code="owner_edit_closed")


def _can_owner_edit(actor, complaint):
    return can_submit_complaint(actor) and actor.pk == complaint.submitted_by_id
