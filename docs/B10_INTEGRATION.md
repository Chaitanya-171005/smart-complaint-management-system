# B10 authenticated aggregate integration

Related to #12, #13, #14 and #15. This contribution connects the merged helpers
to real persisted records. It does not close these issues or release an HTTP flow.

## Service boundary

Call `submit_authenticated_complaint(user=..., key=..., data=..., files=...)`
from `complaints.submission`, outside any existing database transaction.
`data` contains only category (positive Category primary-key string), location
(canonical Location code), title, description, indicated priority and optional
sub_category. `files` is the complete batch, not a single-file dictionary lookup.
The key is retained across retries of the same submission. The caller cannot
supply an identifier, digest, department, status, timestamps, uploader or callback.

The service authorizes the current account before parsing/storing files. It
normalizes user text and original filenames with NFC before validation and uses
B07's field validators and B09's verified bytes. It fingerprints all normalized
submission-affecting values, indicated priority, and ordered evidence bytes/name/
verified MIME/size/stage. Storage uses immutable byte snapshots of that input.
Current labels, routing policy and derived priority/deadline are not retry input.

The guard rechecks and locks the account. For a new operation, the service
rechecks active Category/Location rows within the transaction and calls B14's
`route_and_prioritize()` entry point. That entry point derives B16 priority/deadline
before recording routing. The adapter creates Complaint and INTAKE Attachment
metadata, and appends B21 SUBMITTED then ALLOCATED history with states SUBMITTED
then ASSIGNED. `RoutingOutcome.as_complaint_fields()` supplies department,
unrouted, the rule key, priority, due_at and ASSIGNED status, so the field mapping
has one owner. An INTAKE attachment's uploader is the authorized account.
F4 must independently authorize RESOLUTION writes and enforce its operation limit.

The ID reservation, aggregate, routing, history and linked retry receipt commit
together. Return is acknowledgement-eligible only after commit. New retries
return the original identifier/time and skip configuration derivation and writes;
their newly staged files are removed. Changed normalized inputs are refused.
Required failures, including database commit errors, roll back the graph and ID,
and B09 removes this attempt's new files. Existing accepted files remain intact.
Storage and rollback failures are not silently converted into successful intake.

`RoutingConfigurationError`, `SLAConfigurationError`, and
`ValidationError(code="inactive_reference")` propagate to the HTTP caller.
The future view must show a configuration/validation failure, preserve safe
input and the original request key, and never render an acknowledgement for
these errors. Idempotency conflicts and legacy reconciliation errors also remain
refusals; a generic exception handler must not convert them into success.

### F4 event decision still required

Automatic routing currently emits ALLOCATED with actor SYSTEM and the state
transition SUBMITTED to ASSIGNED. B15's Head-to-Staff allocation will also use
ALLOCATED with its own actor/state context. Before #15 closes, Tanmay/F4 must
confirm whether those contexts distinguish the events sufficiently or whether
automatic routing needs a separate event type. Track the shared contract with
#31 and #23. This follow-up preserves the current event; it does not claim that
F4 has confirmed the decision or introduce a new enum unilaterally.

B15 PR #68 proposes nullable `ComplaintHistory.actor` and `assignee` fields.
Once merged, automatic routing (actor_kind SYSTEM, no account actor or assignee)
can be distinguished from a Head's allocation (recorded Head and Staff assignee).
F4 should use that B15 contract when closing the event question in #31/#23;
the proposed fields do not by themselves constitute F4 confirmation.

## Additive migration and legacy receipts

0004 adds Attachment and a nullable `IntakeReceipt.accepted_complaint` relation
to Complaint.complaint_id, leaving the earlier 0003 migration unchanged. A DB
constraint requires the linked identifier to equal the retained receipt ID.
Backfill links only exact identifier, account and submission-time matches.
All unmatched rows are preserved. No counters or Complaint records are deleted,
and no migration rollback, fake migration state or database reset is required.

The production service opts into `require_complaint=True`. Unlinked or identity/
timestamp-mismatched receipts raise `IntakeReconciliationRequired`; do not issue
a new key automatically to bypass this condition. Resolve those rows through a
reviewed, data-preserving policy. Generic trusted guard callers keep their earlier
behavior and are not a production submission endpoint.

## Verification and remaining work

Run `python -m pytest complaints/test_submission.py complaints/test_intake.py
complaints/test_evidence.py complaints/test_models.py --no-cov` plus system and
migration consistency checks. Tests use synthetic configuration, real persistent
models/private files, required failure injection, migration backfill, concurrent
same-key requests and authorized downloads against an actual Attachment.

The authenticated page/POST, reference/error handling, post-commit acknowledgement
and protected GET/HEAD download endpoint are implemented in B07_HTTP.md. They
require review and confirmed D01 references/emergency information before release.
Keep the original request key on timeout; never present failed input as accepted.
The endpoint must be non-atomic if ATOMIC_REQUESTS is enabled.

Evidence storage now syncs bytes/directory entries before acceptance and holds a
writer lease through commit. The `reconcile_evidence` command provides primary-DB
integrity checks, reversible orphan quarantine, accepted-file restoration and an
explicit later purge. Cleanup failures remain retryable without deleting accepted
metadata. See B10_RECOVERY.md for the contract and subprocess crash tests.
This does not make filesystem/DB writes one hardware transaction. Notification
outbox/delivery, deployed PostgreSQL, container replacement and scheduled-work
recovery acceptance remain pending with F3/F4. D02 byte-limit confirmation and actual upload performance
acceptance remain open. Anonymous intake/privacy/tracking are separate follow-ups.
