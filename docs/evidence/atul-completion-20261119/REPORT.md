# Atul — implementation, verification and remaining acceptance

**Branch verdict: DEMO READY WITH LIMITATIONS.** Atul's identified local code
corrections, formal reviews, combined-preview checks, automated Q06 evidence,
bounded queue/assignment remediation and presentation/demo artifacts are finished.
Team policy decisions, genuine peer approval, reviewed integration, remaining
Q04 scenarios and final delivery acceptance remain open. They cannot be inferred
from local passes. No Main merge, production activation or human acceptance is
claimed. This is an evidence handoff, not a final sign-off.

Latest inspected Main: `b7db7848cbc15d8b67fbba508e57b9f31e16dc74` (includes PR96).
Tested combined runtime: `27d41850ecf2de3f77cd726de98a2eeae8b08cad`, joining
Main with PR101, PR103/104 and PR105. Subsequent changes only merge benchmark
records and add this packet; the runtime diff is unchanged. Current image/source
hashes for22 relevant files match. Work stayed in separate task-owned checkouts;
the original `atul-pr93` source and local changes are preserved.

The complete linked Library contributor report was not available in the task;
this audit uses the supplied ownership summary, actual assigned issues, SRS/STP,
repository evidence and explicit requests. It does not invent the full R01–R19
mapping or a team decision on unassigned subcategory ownership.

## Published work and formal reviews

| Work | Actual result | Remaining condition |
|---|---|---|
| PR92 F2/F3 review | Formal APPROVE at `43ff72a80eabcd79091e3c7e0f06107c004fb189` | Complete; do not duplicate |
| F2/F3/F4 integration / PR98 | Already merged; direct current-Main F2 subset622 pass | Later UI/report/deployment integration needs final-SHA recheck |
| PR101 sanitizer correction | Head `9b91929901f0d3f5bbf422847c0047e3f109b229`; raw paths replaced in committed metadata/Markdown, negative controls and refreshed manifests;36 focused,2,018 SQLite+2,018 PostgreSQL CI pass | Chaitanya independent re-review and reviewed integration |
| PR103 UI independent review | REQUEST CHANGES at `68cd6fafe59c49b21d99a0b4ec889579883b2b84`;75 focused pass;66 Chromium cases:57 pass,9 fail,0 error/skip | Parent head remains unchanged; incorporate reviewed corrections before approval |
| PR104 Q06/static corrections | Published head `9082bf32516e490a2f4e9c2b9bbb82d62ae2fe85`; runtime fcf053c CI2,046 each DB,16 browser,9 Redis/TLS, coverage pass | F1/F2/F3/F4 review, integration and final delivery verification |
| PR105 concurrency/performance | Tested runtime `a434eaa47f6e96f001c5d188f544cae137b1029d`; evidence tip `a850732` (benchmark records in85d7984; supported DB-variable correction follows); actual local queue/assignment PASS | Independent authorization/lock/outbox/deployment review and final acceptance |
| Combined preview | Runtime27d41850 and published integration/evidence branch; conflict-free joins and current Main guards preserved | Team-authorized reviewed integration; no Main merge performed |

Formal review URLs:

- [PR92 approval](https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/92#pullrequestreview-5932745566).
- [PR103 precise changes-requested review](https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/103#pullrequestreview-5961973349).

The sanitizer is **output redaction**, not general filesystem path containment.
PR104 fixes the original six-page route, privacy-CSP-blocked assets, missing error
IDs/focus/guidance and actual Gunicorn public CSS/JS404s. Private pages inline
fixed repository CSS with no automatic asset requests/scripts; public collected
static delivery refuses private-evidence-root overlap at startup. Registration
still uses a generic receipt with blank CSRF-protected login; gated existing
intake on Complainant home provides the four-page route. Existing acceptance,
authorization, idempotence and privacy controls remain.

PR105 batches required notification/outbox writes without ignoring conflicts,
corrects the observed FK/row-lock cycle, permits shared Staff-reference readers
while fencing authorization-changing updates, and adds mandatory real-PG
concurrency checks. Only the isolated Q04 setup opts into four sync workers and
60-second health-checked DB connections. Default session timeout, release gates,
privacy/transport/limiter guards and coverage targets stay unchanged.

## Exact latest combined-runtime validation

| Validation at27d41850 | Pass | Fail | Error | Skip | Evidence |
|---|---:|---:|---:|---:|---|
| Canonical SQLite regression + required F4 |2,097|0|0|0|`current/ci-unified.txt`, recovery-tests job; all coverage gates pass |
| Canonical PostgreSQL regression + required F4 |2,097|0|0|0|Same file, postgresql-recovery job; all coverage gates pass |
| Additional mandatory PostgreSQL concurrency |13|0|0|0|Same file; refuses non-PG backend |
| Hosted Chromium |16|0|0|0|`current/ci-browser.txt` |
| Real Redis/TLS subset |9|0|0|0|`current/ci-redis.txt`; also repeats full2,097-case regression |
| Independent Q06 browser checklist |60|0|0|0|`current/q06.txt`, `current/q06/junit.xml` |
| Four-screen / reference-feedback browser |8|0|0|0|`current/q06-feedback.txt`, `current/q06/feedback.xml` |
| Actual Docker/Gunicorn browser after replacement |14|0|0|0|`current/built-browser/results.json` |
| PostgreSQL process/SMTP/scheduler recovery |28|0|0|0|`current/q05/q05-shared.txt/.xml` |
| Automated recorded workflow (overlaps Q06) |2|0|0|0|`current/demo.txt`, `current/demo/junit.xml` |

Counts overlap; do not sum these suites into a unique total. Hosted source27d:
[unified44454931630](https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/44454931630),
[browser44454936029](https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/44454936029),
[Redis44454939471](https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/44454939471).
System and migration checks passed with canonical CI. Expected negative-test
constraint/lock-timeout database messages are present in passing hosted logs.
Native fixture warnings note an uncollected local static directory; actual built
public assets return200 and private pages make no asset requests.

Actual image `sha256:307e3ac2edd309d5dcef84c2754d587b0783369e3d7b6ec8e09ee1f31f808401`
is recorded in `current/source-image.json` and persistence identities. Twenty-two
runtime file hashes match. **LOCAL_PERSISTENCE_PASS** at27d covers real app/DB
restart and both-container replacement, preserving one complaint, PNG hash and
0600 mode, receipt/routing, two history/events and52 notices/email jobs. A real
service retry returns the same complaint with no duplicate graph. HTTP release
gates stay closed. This is not production SMTP, deployed scheduler or Jenkins
acceptance. See `current/persistence/report.json` for exact identities/mounts.

Direct Main b7db784 F2 checks: **622 pass,0 fail/error/skip**, retained under
`current/f2-main/`; this narrow current-Main result does not accept the unmerged UI.
Historical81eae66 evidence and earlier static failure stage remain separately
labelled in `historical-81eae66/`, with their original outcomes and provenance.

## Q06 checklist mapped to SRS and test plan

Sources: `docs/Team6_SRS.pdf` §3.1 p4, NFR-QUAL-02 p13;
`docs/Team6_STP.pdf` VM-03 p3. The tested primary pages are registration, generic
registration receipt/login, Complainant home/intake, and acknowledgement. Every
visible full-page step including acknowledgement counts: **4 desktop,4 at320px**.

| Requirement / requested observation | Actual automated result | Limit |
|---|---|---|
| NFR-QUAL-02: first registration/submission within4 primary screens | PASS, actual4 at both widths | The unaided first-time human part is PENDING |
| NFR-QUAL-02 / §3.1: refusals state problem and correction | PASS required/invalid fields, labels, adjacent errors, focus and safe403/503 guidance | No human comprehension study |
| NFR-QUAL-02:320px+, text statuses, copyable IDs | PASS desktop1280/320 layout, acknowledgement, clipboard native/rejected/unavailable fallback and manual reference copy | Chromium desktop emulation; no physical mobile/device acceptance |
| VM-03: validation/correction/confirmation | PASS normal/invalid registration, login/intake, appropriate non-secret value preservation and resubmission | Password/file re-entry is intentional |
| Keyboard, focus, labels and announcements | PASS exercised keyboard-only intake, labels, error-description targets, alert and focus checks | No live screen-reader or complete WCAG certification |
| Anonymous intake, reference tracking/feedback | PASS under isolated synthetic prerequisite fixtures; reference screenshots masked | Real deployed transport/privacy/limiter readiness remains gated |
| Navigation, role controls, permissions | PASS four roles, queue/home link crawl and corrective403; status stays403 | Report/security dependencies outside this composition remain separate |
| No overflow / JS exceptions | PASS exercised long labels/forms/refusals/queues and page-level width checks; zero uncaught JS exceptions | Bounded local nav/table scrolling is intentional; expected403/503 console responses distinct |
| Genuine first-time tester, assistance, observations | NOT RUN; explicitly unavailable per user | No tester, assistance count or feedback fabricated |
| Final Main delivery build | NOT RUN for this unmerged composition | Required after reviewed integration on actual delivery SHA |

No remaining failure occurs in this automated checklist. Critical original defects
are corrected in PR104 but **persist at unchanged PR103 alone**. Demonstrate the
reviewed corrected composition only after team integration/approval; the gated
Docker build does not offer enabled intake merely because fixture tests do.
Automated verdict remains **DEMO READY WITH LIMITATIONS**.

Actual synthetic workflow video clips at27d: desktop6.64 seconds,320px5.12 seconds,
under `current/demo/video/`. These are automated paths, not human completion
speeds or the required Sprint1 one-minute / Sprint2 two-minute team recordings.
An editable eight-slide evidence presentation is exported separately with this
packet. `DEMO.md` gives the factual script and build/gate prerequisites.

## Actual bounded Q04 outcome and retained failures

The first newly permitted retest ran **19Nov10:34:55–10:35:27 IST**, inside the
explicit09:35–11:00 window. It passed; no further load ran. Runtimea434eaa,
image`sha256:6069cff926a5d048bf85a3cde7b893c3f379b3412fc7301aad75e8173f2765a6`,
four sync workers/one thread,60-second health-checked DB connections,PostgreSQL17.6,
650 synthetic complaints/50 Heads/50 Complainants/two Staff,seed1811,loopback HTTP.
All550 unique assignment targets use the same Staff as the previous workload.

| Scenario | Measured | p50 ms | p95 ms | Throughput/s | Request errors | Target≤1,500ms |
|---|---:|---:|---:|---:|---:|---|
| Queue |500|428.651|471.597|114.584|0|PASS|
| Assignment |500|537.939|620.158|46.458|0|PASS|

Fifty real warmup assignments/history/events verified before measuring; all550
final graphs verified afterwards, zero failed assignments. All1,100 raw samples
include warmup. POST timers exclude fresh CSRF preparation; throughput includes
it. Containers are stopped; volumes/reservations/logs retained. No additional
load is permitted by that expired successful-run authorization.

Earlier failures remain:18Nov queuep952,895.659ms/action7,147.723ms;19Nov00:15
warmup6 assignment successes/44HTTP500s and zero measured operations;19Nov09:00
queuep951,504.823ms/action3,832.628ms, zero errors. They are not relabelled or
rounded into passes. The real deadlock was reproduced before lock correction.
Single-request SQL counts/profiles never substitute for load measurements.
See [complete raw run/reproduction packet](../q04-fanout-candidate-20261118/README.md).

**This passes the local queue/assignment scenario only.** Official overall Q04,
production sizing, other scenarios, final Q05 and final Main acceptance remain
pending. Local5,000,000-byte D02 is Atul's proposal pending team confirmation,
not an exact SRS-mandated byte value. Both5,000,000 and5,242,880 candidate limits
have validation coverage; do not silently promote the local proposal to policy.

## Atul requirement/issue acceptance status

| Work / issue | Requirement IDs from actual issue | Result / next condition |
|---|---|---|
| B07 #12 |REQ-CMP-01,NFR-SAFE-02,DOM-02|Implementation verified; OPEN pending campus-approved categories/locations/emergency channels(D01) |
| B08 #13 |REQ-CMP-02|CLOSED with merged-Main implementation evidence/comment6987101646 |
| B09 #14 |REQ-CMP-03,REQ-SEC-05,NFR-PERF-03|Implementation verified; OPEN pending D02 and final exact-limit/upload acceptance |
| B10 #15 |REQ-CMP-04,NFR-SAFE-01,NFR-QUAL-01|CLOSED with merged-Main atomic/retry/recovery evidence/comment6987103209; finalQ05 separate |
| B11 #16 |REQ-ANON-01,NFR-SAFE-02,DOM-02|Already CLOSED; deployment release readiness separate |
| B12 #17 |REQ-ANON-02,REQ-SEC-06,BR-03|Automated privacy checks pass; OPEN pending integrated reporting/security/deployment owner review |
| B13 #18 |REQ-ANON-03,REQ-SEC-06|Already CLOSED; deployed transport/limiter readiness separate |
| E02 #19 |NFR-QUAL-04|Already CLOSED; PR101 output correction still needs genuine peer review |
| Q04 #20 / defect#102 |NFR-PERF-01/02/03|Local queue/assignment now PASS; OPEN for reviewed integration, remaining scenarios and overall acceptance |
| Q05 #21 |NFR-SAFE-01,NFR-QUAL-01/05|Local process/image persistence PASS; OPEN pending actual final delivery SHA/deployment/owner acceptance |
| Q06 support |NFR-QUAL-02,§3.1,VM-03|68 automated cases PASS; human and final-delivery acceptance PENDING |

## Remaining Q04 coordination and owner inputs

| Measurement | Required approved conditions | Actual acceptance to record |
|---|---|---|
|50-user intake/list/detail |F1/F3 D01 and authorized delivery intake readiness; F4 actual records per account|p95≤2,000ms, durable distinct submissions/list/detail outcomes, timings/errors/resources |
|Valid reference tracking |Approved HTTPS/privacy/limiter configuration and50 real permitted source buckets after NAT/IPv6 grouping|p95≤2,000ms;1warmup+9measured each under10-attempt budget; no fake forwarded headers or limiter resets |
|5,000 eligible escalation records |F3 approved overdue dataset and scheduler settings|Actual elapsed≤60s, correct exactly-once history/outbox and rerun |
|Representative12-month Head/admin reporting |Tanmay/Anushka reporting decisions and actual integrated report routes|Elapsed≤5s, correct filters/totals/CSV scope/permissions;404/empty placeholder cannot pass |
|5MB upload at2Mbps |Team D02 plus approved shaping inside disposable network|Complete transfer≤30s, actual bytes/hash/durable attachment and network/retry/error logs |
|Every applicable list |Owners inventory queues, complainant records, notices/history and integrated reporting/admin lists|≤25/page, full page2, stable order/no duplicates; queue alone does not accept every list |

Coordination requests are already published on issues12,14,17,20,21. The latest
local result must be linked on20/102 without closing final acceptance. Chaitanya
owns reviewed merges/deployment/SMTP/scheduler/Jenkins; Tanmay/Anushka own pending
reporting decisions and final browser/traceability coordination. Genuine first-time
human Q06 is explicitly unavailable, not waived or replaced by automation.
Preserve PR94's admin campus-report link when its landing-template conflict is
resolved. The team must decide subcategory ownership from its UNASSIGNED state.

## Final delivery sequence

1. Independent owners review101,103/104 and105; coordinate reviewed integration
   without assuming author validation is approval. This task does not merge Main.
2. Confirm D01/D02 and reporting/security requirements with their owners, identify
   the actual delivery SHA and approved target. Retain current closed gates until
   their existing prerequisites are genuinely satisfied.
3. On that SHA, verify final F2/F3/F4 intake/validation/privacy/tracking/feedback,
   private evidence, recovery, browser and required regression/coverage/security.
   Run separately approved remaining Q04 measurements and record actual outcomes.
4. Deployment owners provide actual SMTP/scheduler/Jenkins/security and recovery
   evidence. Record genuine human Q06 when available; retain an explicit pending
   status until then. Complete team sprint recordings/freeze sign-off only with
   real evidence and team authorization.

See [reproduction](REPRODUCE.md), [demo script](DEMO.md),
[sendable teammate message](TEAMMATE_MESSAGE.md), `results.json` and `sha256.json`.
