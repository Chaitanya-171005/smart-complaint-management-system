# B11 anonymous intake and one-time reference

Owner: Atul (F2). Related to #16 and #17. Builds on merged PR #69 and targets Main. This implements
submission, not the separate B13 tracking/feedback routes.

## HTTP contract

`GET /anonymous/new/` opens a no-login form. `POST` submits it with normal
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

### Routes aligned with SAD section 8

The canonical intake route is `/anonymous/new/` (GET and POST), named
`complaints:anonymous_submit`. The namespace is retained for existing named links;
the URL matches the SAD. The old `/complaints/anonymous/` path is not an alias or
redirect and accepts no submission. Login links and forms use the named route.
The first-position privacy middleware isolates the canonical path, including
its slashless form before CommonMiddleware handling. B13 uses the SAD's
`/anonymous/track/` on its dependent branch; the authenticated complaint routes
remain under `/complaints/`.

### HTTPS and trusted reverse-proxy configuration

Local authenticated HTTP development keeps anonymous intake disabled. For
anonymous release, explicitly select `DJANGO_HTTPS_MODE=direct` for TLS delivered
directly to the application, or `proxy` for a verified TLS-terminating ingress.
Both modes also require these exact settings:

```dotenv
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=300
ANONYMOUS_TRANSPORT_VERIFIED=False
```

The HSTS value above is a short rollout example, not campus policy. E03/Q02 must
choose and verify the actual duration, forward all these variables into Docker,
and test the running ingress before setting `ANONYMOUS_TRANSPORT_VERIFIED=True`.
This separate attestation defaults to False; topology/cookie flags alone cannot
make `anonymous_transport_ready()` return True. Do not attest a laptop unit test
as deployed transport acceptance.

Proxy mode sets `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")`;
direct/blank modes never trust that client header. Only choose proxy mode after
E03/Q02 (#27/#28) verify that the ingress strips incoming forwarded-protocol
values, sets its own value, preserves the public Host, and blocks direct backend
access. Never trust arbitrary client-supplied X-Forwarded-Proto. For example, a
controlled nginx upstream sets `Host $http_host` and `X-Forwarded-Proto $scheme`.
The actual TLS certificates, listener and network restrictions belong to E03.

The release predicate and complaints.E002 check require an explicit valid mode,
its matching proxy-header setting, SSL redirection, secure session/CSRF cookies,
positive HSTS, the explicit deployment attestation and SecurityMiddleware.
An unconfigured HTTPS deployment therefore cannot be attested merely by turning on the intake/privacy flags. Static checks cannot
prove the external proxy is trustworthy; deployment tests must verify header
spoofing, plain HTTP redirection, secure cookies, same-origin CSRF and successful
HTTPS intake through the actual ingress before enabling release.

Invalid fields/files return 400 with safe entered values and the same token.
Changed content after acceptance returns 409, clears the unusable form token,
disables resubmission and tells the user to reload/start a new form. Required-operation failures return
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

Operation tokens intentionally have no separate time expiry while receipt
retention is undefined: a late same-operation retry can still acknowledge the
original result without duplicating acceptance or redisplaying its reference.
They are not read/ownership credentials and cannot recover a reference. A future
expiry/retention policy must preserve a clear, safe retry contract; no arbitrary
campus retention policy is assumed here. Public-intake abuse limiting remains
optional hardening; B13's required tracking limit is separate.

## Cross-module output acceptance

`complainant_label` and `anonymous_summary` define the authorized output contract;
they do not by themselves enforce future F3/F4 views, messages or reports.
F3 integration work must cover queue/allocation (#23) and escalation (#26).
F4 must cover notices/email (#36/#37), department reports (#39) and coordinate
campus report/CSV consumers with their F1 owner (#8). Dedicated privacy follow-up
tickets must be linked in PR #71 before re-review; #16/#17 stay open for actual
owner-reviewed output/deployment acceptance.

An explicit cross-branch regression lives in
`integration_checks/anonymous_escalation.py`. In a checkout containing both
#71 and unmerged B18/#70, run:

```sh
python -m pytest integration_checks/anonymous_escalation.py --no-cov -q
```

It creates a real anonymous intake, performs B18 escalation and calls a safe
Head-notice hook using the real projection helpers and Django locmem email.
It asserts no reporter account, no reporter email and no raw/digested reference
in the Head payload/message. That injected hook verifies compatibility; it does
not replace F4's pending persistent notice/outbox implementation. The file is
explicitly invoked instead of auto-collected while B18 is unmerged; missing B18
is an error, never a skip/pass. F3/F4 must integrate and extend this check for
their real consumers before privacy release.

## Verification

Tests exercise real database/private-file/HTTP paths with explicitly synthetic
campus data: anonymous and signed-in callers, CSRF/cross-origin refusal, input/file
boundaries, cryptographic generation, one-time display, identical/changed retries,
concurrent duplicate submission, reference collision, actual rollback/cleanup,
commit/storage/history failures, metadata removal and account/evidence isolation.
The existing authenticated intake tests also run after the shared-code refactor.

Original verification passed 921 tests with no skips (855 baseline plus 66
anonymous/privacy cases). That evidence describes the earlier source commit.
Review verification passed 936 tests with no skips, including 81 anonymous/privacy
cases (the original 66 plus 15 HTTPS/proxy and preloaded-identity regressions). All
four module coverage gates, Django system checks and migration checks passed.
The explicit anonymous-escalation check also passed against B18/#70 source
`b0cfe10392828ca974cdc56d7694278b48c9a4d4` combined with #71 and these review fixes.
The route follow-up passed 947 tests with no skips, including 92 anonymous/privacy
cases. These add SAD route/login-link checks, session-lifetime CSRF cookies,
positive HSTS and transport attestation refusal, and near-limit JPEG acceptance
and whole-batch refusal. All module gates, system and migration checks passed.
Fresh clean-source evidence must be generated after committing the fixes, using
the command below. SQLite and the injected-notice compatibility check do not
establish PostgreSQL, live F4 or deployed privacy/logging acceptance.

Commit source, verify a clean tree, then run:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python scripts/run_tests.py --evidence-dir docs/evidence/b11-b12-route-review
```

Commit fresh evidence separately. The run metadata must identify that clean source
revision with both exit codes zero. Do not rewrite previous evidence directories.
Release requires the B12 checklist, D01/D02 confirmation and module-owner review.
