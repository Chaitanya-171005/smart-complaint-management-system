# Atul — verified local work, 18 November 2026

This packet is **branch/local deployment evidence**, not final Main acceptance,
production approval, an overall Q04 pass, or genuine first-time Q06 acceptance.
The contributor Library URL did not render its report in either browser. Scope
therefore follows the Atul responsibilities pasted by the user; Tables A–D and
the full R01–R19 mapping have not been certified from that inaccessible file.

## Revisions and integration

- Current Main inspected: `a479551c61beb2e2f6e04b93b167084bb7397dcc`.
- PR #101 started at `5b8e685d516f5b689e70d0d4944385d2d78d0589`.
- Tested code: `7d12ea429349f1c70bc8d3d5d2fff7ac0b0eb620`.
  It includes #101 and the sanitizer fix, and already contains current Main.
- The existing developer checkout was preserved. No Main merge was performed.
  PR #101 is updated for Chaitanya's genuine peer review; it is not self-approved.
- PR #92's formal approval already exists, tied to
  `43ff72a80eabcd79091e3c7e0f06107c004fb189`:
  https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/92#pullrequestreview-5932745566

## Sanitizer and regression evidence

The sanitizer performs **output redaction**, not filesystem path containment.
Review follow-up redacts saved metadata/reproduction path spellings as well as
process output. Historical source SHAs and numeric results are preserved;
`sha256.json` describes the redacted files. The new
`scripts/check_evidence_redaction.py` and regression tests check both review
packets, including JSON metadata, Markdown reproduction instructions and logs.

The previous sanitizer resolved `sys.prefix` before replacement and could leave
its configured symlink spelling in shared output. Repository/home aliases could
also be missed. The fix retains both configured and resolved spellings and
continues replacing the longest paths first. Two new regression cases failed
before the fix (`sanitizer-before.txt`: 2 failed, 11 passed).

| Actual validation on 7d12ea4 | Result |
| --- | --- |
| Runner, shell wrapper, Q04 environment and HTTP harness | 99 passed |
| Required SQLite system/migration/full regression + F4 integrations | 2,009 passed; coverage gate PASS |
| Required PostgreSQL system/migration/full regression + F4 integrations | 2,009 passed; coverage gate PASS |
| Focused PostgreSQL F2/F3/F4 privacy/routing/authorization/assignment/feedback | 621 passed |
| PostgreSQL process, SMTP failure, scheduler and auto-close recovery | 28 passed |
| Actual Chromium desktop/320px regression | 14 passed |
| Hosted SQLite job 134856101764 | PASS, 2,009 tests |
| Hosted PostgreSQL job 134856102140 | PASS, 2,009 tests |

Suites overlap; these counts are not added into a unique-test total. Full-run
metadata records clean source, both exit codes zero and F4 required. The first
focused attempt hit the sandbox's loopback socket restriction (86 passed,
13 errors); `focused.txt` is retained, followed by the successful permitted
`focused-retry.txt`. Those infrastructure errors are not silently discarded.

| Module | SQLite line / branch | PostgreSQL line / branch |
| --- | --- | --- |
| accounts | 98.62% / 96.79% | 98.62% / 96.79% |
| complaints | 98.18% / 95.30% | 98.18% / 95.58% |
| routing | 94.44% / 86.06% | 94.44% / 86.06% |
| workflow | 98.19% / 95.60% | 98.19% / 95.60% |

Required gates remain line >=70% and branch >=60% per module.
Hosted run: https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/44320000265

## Authorized local queue/assignment measurement — FAILED latency targets

Atul authorized only a new isolated local Docker/PostgreSQL queue/assignment
benchmark on **18 November 2026, 19:30–21:30 IST**. The clock was checked before
each run and the harness refused requests outside that window. There were no
load requests after the final run ended at **20:48:25 IST**.

- First run, 20:39:36–20:39:44 IST: stopped during queue warmup. All 50 responses
  were HTTP 302 login redirects; the original 30-minute sessions had expired.
  No assignment or measurement phase ran. Raw warmup samples, expiry diagnostic
  and the exact matching-hash initial harness are retained in `queue-assignment/`.
- Retest, **20:45:57–20:48:25 IST**: a separate fresh environment and sessions;
  the application timeout was unchanged. Before measurements, PostgreSQL verified
  50 successful warmup assignments, their expected Head and assignee, exactly 50
  assignment-history events and 50 notification events. All 550 targets were
  checked, including the still-unassigned measurement targets.

| Measured scenario | Samples | p50 | p95 | Maximum | Throughput | Request errors | Result (p95 <=1,500 ms) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Queue GET | 500 | 2,432.440 ms | 2,895.659 ms | 3,010.418 ms | 19.910 ops/s | 0 | FAIL |
| Assignment POST | 500 | 4,922.253 ms | 7,147.723 ms | 7,467.474 ms | 5.139 ops/s | 0 | FAIL |

Each scenario used 50 distinct active department Heads, one warmup plus ten
measured operations per Head, a barrier start and closed-loop requests without
think time. Each assignment had a unique initially unassigned target. Fresh
CSRF form preparation is outside the POST latency timer and inside wall-time
throughput. p50/p95 use nearest rank. No failure timings are filtered out.

All 500 measured assignments succeeded. Final PostgreSQL verification found
**550 assigned targets, 550 correct Head/assignee history events and 550
notification events**, with one per target and no failed/missing assignments.
All 1,100 warmup/measured samples are retained in
`queue-assignment-retest/samples.jsonl` and `report.json`.
Performance remains failed despite correct business outcomes.

The measured image is
`sha256:edb272296f2efe8003a71659401a7e88f91fecd41766abeb3c80bddce597b5d9`.
Source/image SHA256 matched for 13 inspected runtime/helper files. PostgreSQL
17.6, max_connections=100; Gunicorn's default sync worker command; Docker engine
16 CPUs and 8,320,905,216 bytes RAM; no per-container CPU/memory cap. Dataset:
650 synthetic complaints, 50 Heads, 50 Complainants, two Staff, seed 1811, with
550 reserved targets. Local HTTP loopback and a private Docker database network;
no TLS or network shaping in this scenario. Two unrelated background containers
were observed on the Docker engine before load; they were neither accessed nor
stopped. This was not a dedicated or production-representative host.

Only the task-owned project was targeted. The failed first environment and both
run reservations were preserved. No limiter allowance was reset or gate enabled.

## Recovery and persistence

`persistence/report.json` records actual app/database restart and replacement of
both containers while retaining their named volumes and image IDs. Through the
real authenticated service, the probe accepted a complaint with PNG evidence,
receipt, routing decision, two history/events and 52 notices/email-outbox rows.
After restart and after replacement, retry returned the original complaint.
The entire graph hash, evidence hash, counts and 0600 file permissions matched.
No complaints were deleted to recover. The 28 PostgreSQL component checks also
passed, including actual process interruption and SMTP/scheduler behavior.

The image probe used the internal service while HTTP intake remained disabled;
it does not establish public intake activation, production SMTP/scheduler/Jenkins
acceptance or final Main recovery sign-off. Those require the agreed delivery
revision and deployment owners' acceptance.

## D02 and remaining acceptance

Atul specified **5,000,000 bytes for this local setup only**, explicitly as his
proposal pending team confirmation, not an exact byte count mandated by the SRS.
It matches the existing provisional default. `docs/DECISIONS.md` records this
scope. No conflicting approved D02 decision was found in the inspected sources.
Final B09 exact-limit acceptance and #14 remain open pending the team decision.

- #101: current Main composition verified on a separate branch; genuine peer
  review and the reviewed merge remain pending. Main was not merged by this work.
- Q04: queue/assignment latency FAIL. Owner remediation and a newly authorized
  retest are required. Intake/list/detail/tracking, 5,000-record escalation,
  actual 12-month reporting, shaped upload and other applicable pagination remain
  pending. Release-gated 503s and unavailable report routes are not timed passes.
- Q05: local component and image persistence checks PASS; final delivery-build
  deployment/recovery acceptance remains a coordinated owner gate.
- Q06: 14 automated browser checks PASS, but genuine first-time observation,
  assistance/screen-count recording and human acceptance remain pending with
  Tanmay. Earlier assisted six-screen evidence is not relabelled as unaided.
- Other members' security, reporting, UI, lock, SMTP/scheduler and Jenkins work,
  and the unassigned subcategory implementation, are not declared complete here.

See `REPRODUCE.md`, `demo-script.md`, actual command/result metadata and
`sha256.json`. Private settings, cookies and the persistence retry key are excluded.
