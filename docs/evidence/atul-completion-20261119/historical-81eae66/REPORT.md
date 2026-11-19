# Atul completion audit and final-build handoff

This audit covers Atul's GitHub-assigned issues and the user's explicit review,
integration, test, Q06 and demonstration requests. It does not invent the
unavailable Library report's full R01–R19 ownership tables. The current inspected
Main remains `a479551c61beb2e2f6e04b93b167084bb7397dcc`; no Main merge was performed.

## Implementation and review work

| Work | Actual status / source | Remaining acceptance |
|---|---|---|
| PR #92 formal review | APPROVE already submitted at `43ff72a80eabcd79091e3c7e0f06107c004fb189`, review 5932745566 | Complete; no duplicate review |
| F2/F3/F4 Main integration | PR #98 merged; exact Main regression and F2 evidence retained | Future UI/report/deployment integration requires a new final-SHA check |
| Test-runner output redaction / PR #101 | Corrected head `9b91929901f0d3f5bbf422847c0047e3f109b229`; committed metadata check, redacted packets/manifests; 36 focused and 2,018 SQLite + 2,018 PostgreSQL CI pass | Chaitanya's independent re-review and team-authorized integration |
| PR #103 independent review | REQUEST_CHANGES at `68cd6fafe59c49b21d99a0b4ec889579883b2b84`, review 5961973349; 75 focused pass; Q06 57 pass / 9 fail | Incorporate reviewed corrections, preserve #94's admin report link |
| Q06 correction / PR #104 | Four actual visible screens, private inline CSS, errors/focus/403, Gunicorn static delivery; source `fcf053ccb7730e028461e7a1dec38fc0efaa9afc` | Genuine owner review, integration, final-Main/deployment verification |
| Notification candidate / PR #105 | Source `3ace587ca046080f30fa2a554362048237bcb100`, published `6fe48dc608f44aae9c8d03adc017633d32434a35`; 414 focused, 2,003 SQLite + 2,003 PostgreSQL CI pass | New authorized local measurement, F3/F4 review and integration |
| Combined preview | `81eae6675b75c242cf8dfd0a3691778c9a64fb81`; combines #101, #103/#104 and #105 without conflicts | Branch evidence only; reporting/security branches and final acceptance remain separate |

Review URLs:
- https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/92#pullrequestreview-5932745566
- https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/103#pullrequestreview-5961973349

The sanitizer performs output redaction. It is not general filesystem path
containment. None of these changes lowers a coverage target or opens an intake,
anonymous, transport, privacy or limiter release gate.

## Requirement and issue checklist

| Atul work | Requirement IDs from the actual issue | Verified implementation / evidence | Acceptance status |
|---|---|---|---|
| B07 #12 | REQ-CMP-01, NFR-SAFE-02, DOM-02 | Required/server validation, active references, length limits, safe correction, synthetic emergency notice; automated checks pass | OPEN: D01 campus references and emergency channels require confirmation |
| B08 #13 | REQ-CMP-02 | Unique immutable ID, account/time, SUBMITTED→ASSIGNED history, concurrent uniqueness, post-commit acknowledgement; merged integration tests/peer review | CLOSED with exact-Main evidence comment 6987101646 |
| B09 #14 | REQ-CMP-03, REQ-SEC-05, NFR-PERF-03 | Three-file/content/size validation, generated storage names, protected parent-scoped download, F4 reuse and reference denial; both candidate byte limits tested | OPEN: D02 team decision and final exact-limit/upload acceptance |
| B10 #15 | REQ-CMP-04, NFR-SAFE-01, NFR-QUAL-01 | Required-failure rollback, orphan cleanup, timeout/concurrent retry, email handoff; merged integration/recovery evidence | CLOSED with evidence comment 6987103209; final Q05 remains separate |
| B11 #16 | REQ-ANON-01, NFR-SAFE-02, DOM-02 | No-login intake, unguessable one-time reference/digest and loss warning, privacy gate | Already CLOSED; deployed release remains gated |
| B12 #17 | REQ-ANON-02, REQ-SEC-06, BR-03 | Restricted storage/views/queues/history/notices/logging, no complaint-linked source keys, new private UI no asset requests | OPEN: final integrated reporting/UI/security/deployment owner acceptance |
| B13 #18 | REQ-ANON-03, REQ-SEC-06 | Restricted fields, uniform no-match, complaint-ID denial, 10 attempts/10-minute limit, no evidence access | Already CLOSED; real deployed transport/limiter readiness separate |
| E02 #19 | NFR-QUAL-04 | Documented canonical runner, synthetic fixtures, explicit F4 integration and module line/branch gates | Already CLOSED; new runner correction awaits PR #101 review |
| Q04 #20 | NFR-PERF-01/02/03 | Reproducible runner, actual prior failed queue/action measurements and current remediation evidence | OPEN: measured retest and remaining scenarios, no assumed passes |
| Q05 #21 | NFR-SAFE-01, NFR-QUAL-01/05 | Process/overlap/SMTP/scheduler tests and actual local image restart/replacement preservation | OPEN: agreed final delivery SHA, deployment owner and quality-gate acceptance |
| Q06 support | NFR-QUAL-02, SRS §3.1, STP VM-03 | Four primary screens; automated desktop/320px workflow, validation, copy/fallback, keyboard, labels, focus, roles/refusals | Automated branch result separate from unavailable genuine first-time human acceptance |

D02 remains Atul's proposed **5,000,000 bytes for the local setup**, pending team
confirmation. It is not an SRS-mandated exact byte value. D01 remains provisional.
No campus emergency number, team approval, human assistance count, screen-reader
observation, production SMTP/Jenkins result or final acceptance is fabricated.

## Exact combined-preview validation

The source before the static correction, `44a12d0216ae6edc359f36394cc38c9ad6c87d71`,
passed 2,057 SQLite and 2,057 PostgreSQL tests, with all module gates. Its actual
Gunicorn build exposed CSS/JS 404s. This is a retained failed built-instance
observation, not a passing deployment result.

After correction at `81eae6675b75c242cf8dfd0a3691778c9a64fb81`:

- Full SQLite: **2,065 passed**, all module coverage gates pass. Warnings identify
  the deliberately uncollected local test static directory, not failed cases.
- Actual Docker/Gunicorn desktop/320px: **14 pass, 0 fail, 0 skip**. Public assets
  return 200, private pages make no asset requests, permission guidance and page
  fit pass. HTTP intake/anonymous routes remain gated. The full enabled first
  submission uses the separate isolated browser fixtures, not this gated build.
- Actual app/database restart and replacement: **LOCAL_PERSISTENCE_PASS**. One
  complaint, PNG file/hash, receipt/routing, two history/events and 52 notices +
  52 email jobs remain identical. Retries return the same complaint; file mode
  stays 0600. Neither complaint deletion nor gate changes enable recovery.
- Final combined PostgreSQL, complete browser checklist and process-recovery
  results are recorded in the actual attached run files as they complete. A
  pending or failed check is never counted as passing.

Suites overlap. Counts are never summed into a unique aggregate. Branch evidence
does not establish final Main acceptance. See REPRODUCE.md and source/CI metadata.

## Remaining coordinated Q04 measurements

| Measurement | Required conditions / owner inputs | Record and verify |
|---|---|---|
| Queue/assignment, 50 Heads | Newly authorized 19 Nov 00:15–01:15 IST, isolated four-worker candidate, fresh sessions and targets, gates closed | One warmup + ten measured each; verify actual 50 warmup assignments before measuring; p95 ≤1,500 ms; all 550 final history/events; raw samples/errors/throughput |
| Intake/list/detail, 50 Complainants | F1/F3 confirm D01 and authorized delivery build/intake readiness; F4 supplies real list/detail records per account | p95 ≤2,000 ms each; distinct fresh submissions, successful durable outcomes, exact data/resource/network settings |
| Valid reference tracking | Deployment owners provide approved HTTPS, memory-only limiter and 50 real permitted source buckets after NAT / IPv6 grouping | p95 ≤2,000 ms; one warmup + nine measured per source (10-attempt budget); positive permitted results, no fake forwarded headers or limiter reset |
| 5,000 escalation records | F3 supplies separate eligible overdue dataset and approved scheduler settings | Actual command elapsed ≤60 s; validate exactly-once work/history/outbox and rerun behavior; runner time is not deployment evidence |
| 12-month reporting | Tanmay/Anushka agree reporting rules and integrate the actual Head/admin report routes | Representative 12-month dataset, elapsed ≤5 s, correct totals/filter/CSV scope and authorization; 404/empty placeholder is not a pass |
| 5 MB at 2 Mbps | Team confirms D02 and test-network conditions; owner-approved shaper inside disposable network only | Actual complete transfer ≤30 s, byte count/content/hash and durable attachment; retain shaper/topology/retries/errors; no host/shared-network changes |
| Every applicable list | Each module owner inventories actual lists: complainant list, queue, notifications/history and integrated report/user lists where applicable | Exact record selectors; page 1 and full page 2, stable ordering/no duplicates; ≤25 records/page. Queue pages 1/2 were observed at 25; this does not accept every list |

The current isolated fixture reports intake/anonymous/tracking/feedback as
RELEASE_GATED and the absent report as ROUTE_UNAVAILABLE. Those are readiness
states, not successful timings. No gate is opened for a performance result.

## Review and delivery order

Chaitanya re-reviews #101; affected F1/F2/F3/F4 owners review #104/#105. The team
coordinates reviewed integration of #103/#104, notification changes and the
reporting/security dependencies. Preserve #94's administrator campus-report link.
Identify the delivery SHA after authorized merges, then rerun final functional,
privacy, evidence, recovery, browser, security and agreed performance checks on
that SHA. Keep production SMTP/scheduler/Jenkins and unavailable genuine human
acceptance explicit. Only then record final combined acceptance and the actual
demo recording/duration. This task does not merge Main or invent a sign-off.
