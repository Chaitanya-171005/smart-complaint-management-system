# B11 anonymous intake and one-time reference

Owner: Atul (F2). Related to #16 and #17. Builds on PR #69; keep the PR based on
that branch until #69 merges, then update and retarget to Main. This implements
submission, not the separate B13 tracking/feedback routes.

## HTTP contract

`GET /complaints/anonymous/` opens a no-login form. `POST` submits it with normal
CSRF protection, a signed random operation token and the complete evidence batch.
HTTPS is required. The login page links to the anonymous route. Session cookies,
account authentication, identity headers and query parameters are isolated by
privacy middleware before Django session/auth middleware. A signed-in visitor
can use it without attaching or refreshing their account session.

Both intake flags, the privacy-readiness flag and a nonblank confirmed emergency
notice must be configured. DEBUG must be False, CSRF must use cookies and the
privacy middleware must run first. Missing prerequisites return 503 without
acceptance. `manage.py check --deploy` reports complaints.E002 if anonymous
intake is enabled with incomplete application configuration.

Invalid fields/files return 400 with safe entered values and the same token.
Changed content after acceptance returns 409. Required-operation failures return
a generic 503; unexpected view errors return a generic 500. None claim success
or expose stack traces, SQL, file paths, reference values or private diagnostics.

## Transaction and retry contract

`submit_anonymous_complaint(key=..., data=..., files=...)` accepts no account,
request, source key, email or IP argument. It reuses B07 input rules, B09 content
validation/private storage and B14/B16 routing/SLA through the same required
persistence routine as authenticated intake. Anonymous files are sanitized
before hashing/staging; see B12_PRIVACY.md for the visible-content limitation.

The outermost durable transaction reserves the ID, checks the operation receipt,
locks active master data, routes, creates the anonymous Complaint/Attachment
graph, records ANONYMOUS/SUBMITTED followed by SYSTEM/ASSIGNED history and creates
the receipt. Required errors roll back all these writes and unwind staged files.
The result is returned only after the outer commit succeeds. This is ordinary
exception cleanup, not a claim of atomic filesystem recovery after process crash.

The per-year identifier sequence serializes same-year writers before receipt
lookup. A unique receipt key prevents two accepted graphs for one operation,
including races across a year boundary; a conflicting cross-year transaction
may receive a generic retryable failure before a subsequent retry sees the
committed receipt. No retry loop masks database/lock errors.

The anonymous receipt stores only a hash of the random form-operation key, a
canonical payload hash, a complaint relation and creation time. It is not a
tracking credential or a rate-limit/source key. No pending receipt is committed.
The payload includes indicated priority, normalized input and ordered sanitized
file bytes/metadata. Retrying an accepted operation after reference/SLA changes
returns the original complaint ID, creates no new graph/files and does not advance
the ID counter. Retrying with changed persisted input is a conflict.

## Reference issuance and delivery

The existing model helper uses `secrets.token_hex(16)` to generate 128 random
bits encoded as exactly 32 lowercase hex characters, distinct from the complaint
ID. Only its SHA-256 digest is persisted using the shared B13 hashing contract.
Reference uniqueness and digest format are database constrained.

The raw reference exists only in the new operation's transient result and its
direct POST response. The result's repr omits it. No GET/redirect URL, database
column, session, cookie, history, log, notification or receipt retains a raw copy.
The success page prominently warns the user to save it and that it cannot be
recovered or shown again if lost. Responses use private/no-store, no-referrer,
noindex/noarchive and a restrictive CSP with no external resources/scripts.

Only the first successful commit can emit the raw reference. Refresh/replay or
a concurrent second submission acknowledges the same ID without that reference.
A lost response can therefore mean a lost reference; there is deliberately no
recovery endpoint or retry-based recovery. Starting a new form is a separate
operation; users are told to retry the retained form to avoid duplicates.

## Verification

Tests exercise real database/private-file/HTTP paths with explicitly synthetic
campus data: anonymous and signed-in callers, CSRF/cross-origin refusal, input/file
boundaries, cryptographic generation, one-time display, identical/changed retries,
concurrent duplicate submission, reference collision, actual rollback/cleanup,
commit/storage/history failures, metadata removal and account/evidence isolation.
The existing authenticated intake tests also run after the shared-code refactor.

Development verification passed 921 tests with no skips (855 baseline plus 66
anonymous/privacy cases), all module coverage gates, and Django system/migration
consistency checks. This execution uses SQLite; no PostgreSQL or deployed
privacy/logging acceptance is inferred from it.

Commit source, verify a clean tree, then run:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python scripts/run_tests.py --evidence-dir docs/evidence/b11-b12-anonymous
```

Commit fresh evidence separately. The run metadata must identify that clean source
revision with both exit codes zero. Do not rewrite previous evidence directories.
Release requires the B12 checklist, D01/D02 confirmation and module-owner review.
