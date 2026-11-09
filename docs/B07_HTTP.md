# Authenticated complaint submission and evidence HTTP flow

Related to #12, #13, #14 and #15. This builds on PR #67's real aggregate service.
PR #67 is merged. This contribution incorporates Main through merge b632e55;
the pull request should now target Main and retain only the HTTP-flow changes.

## Routes and behavior

| Route | Methods | Access/behavior |
| --- | --- | --- |
| `/complaints/new/` | GET, POST | Active Complainants; login redirect otherwise, role refusal for Staff/Head/Admin |
| `/complaints/<complaint_id>/submitted/` | GET, HEAD | Current Complainant's linked accepted receipt only; another account or unlinked record gets 404 |
| `/complaints/evidence/<pk>/` | GET, HEAD | Fresh B04 permission on the attachment's own parent; missing/denied/anonymous requests get 404 |

Submission uses the real category/location adapters, B07 validators and B10
aggregate service. The complete evidence batch is read with getlist(). CSRF
middleware protects POST. Derived fields from POST cannot select actors, status,
department, identifiers or dates. The view is non-atomic under ATOMIC_REQUESTS so
B10 still owns its outermost transaction. A successful service return produces
a 303 redirect; the acknowledgement verifies a matching account/time/Complaint
receipt. An arbitrary allocated ID or Complaint without a receipt cannot create
an acceptance page. Acknowledgements and successful downloads use private/no-store.

The GET form creates a signed token containing a new 256-bit intake key and the
account ID. POST validates the signature and account, then passes only the raw
key to B10. The token stays in a hidden form field, never a URL or durable server
session record. It grants no complaint/evidence access. No expiry is imposed on
accepted retry keys independently of receipt retention. The application signing
key and any SECRET_KEY_FALLBACKS must be managed consistently with retry retention.

Validation errors preserve safe text and the original valid token. Files cannot
be repopulated by a browser: reselect the same files for a retry. The fingerprint
includes their bytes and persisted metadata. Accepted retries reach B10 before
active choice revalidation, so later reference/SLA changes do not create another
complaint or prevent replay of identical accepted data.

Malformed tokens return 400; changed accepted payloads and legacy-reconciliation
refusals return 409; routing/SLA/storage/database failures return 503 when handled.
Unexpected exceptions remain server errors and never become a success redirect.
Required failure rollback and file cleanup remain owned by B10/B09. Logs added by
this view contain only a generic failure message; POST parameters are marked
sensitive for Django error reports. Full privacy/logging acceptance still needs
cross-module/deployment checks, especially before anonymous intake.

## D01 release gate

Submission is disabled by default. `COMPLAINT_INTAKE_ENABLED=False` and an empty
`COMPLAINT_EMERGENCY_NOTICE` are supplied in .env.example. A disabled gate or blank
notice returns 503 before any submission can be accepted. No campus contact,
emergency number or policy is invented by this contribution.

After F1/F3 and the team confirm real categories, locations and the emergency
instructions, put that exact plain-text notice in COMPLAINT_EMERGENCY_NOTICE and
set COMPLAINT_INTAKE_ENABLED=True in the authorized environment, then restart the
application and perform release verification. This flag is an operational gate,
not proof that supplied information was approved. Tests enable it only with
explicitly synthetic configuration and a visibly labelled synthetic notice.
Previously accepted records remain accessible through their authorized routes
when new intake is disabled.

The enabling value is case-sensitive: only the exact string `True` enables
intake; `true`, `1`, an unset value or `False` leave it disabled. E03 must pass
both `COMPLAINT_INTAKE_ENABLED` and the confirmed, nonblank
`COMPLAINT_EMERGENCY_NOTICE` into the Docker/Jenkins application environment.
Setting them only in a developer's shell does not configure a deployed container.

## Upload request boundary (Q02/E03 deployment requirement)

The HTTP view does not cap the total request body before multipart parsing.
Django can spool uploads larger than `FILE_UPLOAD_MAX_MEMORY_SIZE` into temporary
files; `DATA_UPLOAD_MAX_MEMORY_SIZE` excludes uploaded-file bytes. B09's maximum
file count, per-file byte limit and content checks apply after receipt, so they
do not prevent an oversized or many-file request from consuming ingress and
temporary-disk resources.

Before enabling deployed intake, Q02/E03 must configure and verify a total
request-body limit at the reverse proxy, before requests reach Django. Align
the limit with the confirmed D02 per-file limit, the complete three-file batch
and a bounded allowance for fields/multipart overhead. Verify a valid maximum
batch succeeds and an over-limit body is rejected with 413 without reaching
the application. Django's memory thresholds are not a substitute for that limit.
No reverse-proxy/deployment configuration exists in this contribution; the
deployment limit and its verification remain an explicit release prerequisite.

## Validation and remaining scope

Run `python -m pytest complaints/test_http_intake.py --no-cov`, system checks and
migration drift checks. Generate full-suite evidence from a clean source commit
under `docs/evidence/b07-http/`, after committing the Main merge and review edits.
The original evidence commit fe91b3e directly follows source commit
f3113003ea10f3cddaa02493da4a521f60fe4392, matching its recorded `source_revision`;
that original 842-test run remains in Git history. Refresh the current reports
from the updated clean source and commit those reports separately.
Verification with Main merged passed all 855 tests with no skips, including the
35 HTTP cases; all module coverage gates and Django system/migration checks
passed. The extra tests come from the merged CI-wrapper and B10 review updates.
Tests exercise actual
HTTP, storage and DB paths, CSRF, required fields, escaping,
token/account scope, conflict/replay, configuration failures, history rollback,
attachment GET/HEAD permissions, current membership and ATOMIC_REQUESTS.

This does not complete #12-#15 acceptance: D01/D02 confirmation, F4 event naming,
resolution-evidence integration, durable staging/orphan reconciliation,
notification delivery, PostgreSQL and deployed crash/restart/persistence and
performance checks remain. Anonymous intake, one-time references, privacy and
restricted tracking remain separate work under #16-#18.
