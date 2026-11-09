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
rechecks active Category/Location rows within the transaction, records B14 routing,
derives B16 effective priority/deadline, creates Complaint and INTAKE Attachment
metadata, and appends B21 SUBMITTED then ALLOCATED history with states SUBMITTED
then ASSIGNED. It copies department, unrouted and str(decision.rule_id), or an
empty key for fallback. An INTAKE attachment's uploader is the authorized account.
F4 must independently authorize RESOLUTION writes and enforce its operation limit.

The ID reservation, aggregate, routing, history and linked retry receipt commit
together. Return is acknowledgement-eligible only after commit. New retries
return the original identifier/time and skip configuration derivation and writes;
their newly staged files are removed. Changed normalized inputs are refused.
Required failures, including database commit errors, roll back the graph and ID,
and B09 removes this attempt's new files. Existing accepted files remain intact.
Storage and rollback failures are not silently converted into successful intake.

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

Before closing the issues, implement and review the authenticated CSRF-protected
page/POST, reference-option/error handling, confirmed D01 emergency notice,
post-commit acknowledgement and GET/HEAD-only protected download endpoint.
Keep the original request key on timeout; never present failed input as accepted.
The endpoint must be non-atomic if ATOMIC_REQUESTS is enabled.

Ordinary exception cleanup does not make filesystem and DB commit atomic against
process crashes. Durable staging/orphan reconciliation, cleanup-failure recovery,
notification outbox/delivery, PostgreSQL and restart/container preservation tests
remain pending with F3/F4. D02 byte-limit confirmation and actual upload performance
acceptance remain open. Anonymous intake/privacy/tracking are separate follow-ups.
