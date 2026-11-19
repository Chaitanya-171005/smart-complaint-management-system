Current status, 19 November: the deadlock correction is verified, but the latest measured queue/assignment targets still FAIL. A shared Staff-reference / bounded WSGI connection-reuse candidate passes focused checks and awaits a separately authorized fresh retest. Prior failures remain retained below.

# Q04 remediation candidate — no new load result

Source `3ace587ca046080f30fa2a554362048237bcb100` is based on Main
`a479551c61beb2e2f6e04b93b167084bb7397dcc`, separate from the Q06/UI branch.
Related defect: #102. This candidate is proposed for genuine owner review; it
neither closes the defect nor proves the 1.5-second target.

An actual single-action SQL probe with 50 synthetic department Heads found 52
notification INSERTs plus 52 email-job INSERTs, 114 SQL statements total. The
same correctness probe after batching found one INSERT per table, 13 statements
total, with the exact same 52 eligible recipients, pending jobs, history/event
and idempotent replay. With three Heads the counts changed from 20 total / ten
INSERTs to 13 total / two INSERTs. These are **single-action query counts**, not a
50-concurrent-user load benchmark or timings.

The new regression fails twice before the fix and passes after it. Actual
focused result: **414 passed, zero failed/errors/skipped**, covering notification
channels/recipients, idempotence, privacy, permission changes, intake, resolution,
feedback, reopening, confirmation, auto-close, and transaction rollback. Existing
failure injections now target the actual bulk write points. No model save hooks
or signals existed for these outbox models. History still uses its validated
single-row writer; no history bulk-create restriction is bypassed.

Notification recipient authorization/projection and the atomic business
transaction/locks are unchanged. No conflicts are ignored. Failure of either
required table insert rolls back the assignment/history/event graph. Email IDs
are read back from the newly created event, so backend-specific bulk PK return
behavior is not required. SMTP remains deferred to its existing outbox worker.

The isolated **q04/compose.yml only** now requests four Gunicorn sync workers,
one thread each, instead of its previous implicit single worker. This is a
second, explicitly recorded resource change. Any future timing comparison must
state both code and worker changes, not attribute all improvement to batching.
No production Compose default, authorization, limiter, release gate or coverage
threshold was changed.

Preparation of the new task-owned Docker project stopped because Docker Desktop
is manually paused. `prepare-stack.txt` is the actual failed preparation log;
no candidate image or new concurrent load result exists yet. The earlier load
window expired at 21:30 IST on 18 November. A new explicit window is required;
elapsed time or silence is not consent. No previous measured failure is relabelled.

Last real authorized result remains queue p95 2,895.659 ms and assignment p95
7,147.723 ms, both failing <=1,500 ms. Preserve its original packet on PR #101.
Other Q04 scenarios and final Main/Q05/human acceptance remain separate pending
work. See REPRODUCE.md for actual focused commands and the guarded next run.

## Stopped real multiworker run and assignment lock correction

On 19 November, the authorized run at **00:15:34–00:16:11 IST** used
`6fe48dc608f44aae9c8d03adc017633d32434a35`, image
`sha256:e42ab60f663ae6863ae488daa0a6309a6045c8e0c661dab6ceab1bc57e010a94`,
four sync workers, PostgreSQL17.6 and 650 synthetic complaints. All50 Head
sessions passed baseline verification. Queue warmup returned50 successful
responses. Assignment warmup returned6 successful redirects and44 HTTP500s.
The harness stopped, with **zero measured operations**. Warmup timings are raw
evidence only and do not establish a passing p95. The complete100 warmup
samples, actual app/DB logs, image/resources and failure report are retained.
No run targets, reservations or data were reset or reused.

The PostgreSQL logs identify a real row-lock/foreign-key cycle: allocation
locks its Head and target Staff FOR UPDATE, while notification foreign keys
need KEY SHARE on other Heads locked by waiting assignments. A two-Head
PostgreSQL reproduction fails before correction (one failure, four existing
authorization-lock cases pass), with SQLSTATE40P01. This is a specific
concurrency failure missed by sequential correctness checks.

The correction uses FOR NO KEY UPDATE for the two account rows. Complaint
locking, current-state authorization and atomic assignment/history/outbox remain.
Role, department and active-status updates still block during allocation;
foreign-key references can proceed. The PostgreSQL-only regression is a required
CI step and refuses a non-PostgreSQL backend rather than reporting a skip.
Reference: https://www.postgresql.org/docs/17/explicit-locking.html

Actual post-correction focused result at
`bbec7401b87ad28bf90bc97a15a9ee965a5de7e7`: **142 passed, zero failures/errors/skips**,
including8 lock/concurrency cases, notification graph, HTTP/permissions and the
new Main deactivation guards. This source includes latest inspected Main
`b7db7848cbc15d8b67fbba508e57b9f31e16dc74` through an isolated branch merge.
A read-only post-stop check verifies all550 targets, exactly6 committed
assignments/history/events, and312 notices/email jobs. Failed attempts leave no
partial accepted assignment. Expired benchmark sessions are not reused.

The original warmup failure is retained after this code correction. A new
50-user run needs a new explicit window and fresh environment/targets. No new
measurement or overall Q04/final Main acceptance is claimed.

## Completed corrected run at 09:00 — latency still fails

Actual execution: **19 November 09:00:58–09:02:32 IST**, within the newly
authorized09:00–10:00 window, source `c39e492b3ea47ac8b520d2e412ce6ebba3e53aab`,
image `sha256:2df6260efb55de20ad297ec0386d5830de7e1cc6534e7a385cfeec3246e3e208`.
Four sync workers,650 complaints/50 Heads/two Staff, seed1811; the original
550 targets were fresh and distinct in this separate environment.

| Measured scenario | Samples | p50 ms | p95 ms | Max ms | Throughput/s | Request errors | Target≤1,500ms |
|---|---:|---:|---:|---:|---:|---:|---|
| Queue |500|1,222.474|**1,504.823**|1,594.485|39.614|0|FAIL|
| Assignment |500|2,551.462|**3,832.628**|4,481.594|9.737|0|FAIL|

The queue result is not rounded down to a pass. PostgreSQL verified50 real
warmup assignments/history/events before measurement and all550 target
assignments/history/events after measurement. No failed/missing assignments,
deadlocks or request errors occurred. All1,100 raw warmup/measured samples
and actual app/DB logs are retained. The six-assignment stopped environment
remains separate and unchanged. This single authorized run was not repeated.

## Further measured investigation and shared-reference candidate

A warmed single sequential post-run queue diagnostic observes8 queries and
10ms recorded SQL time (58.515ms instrumented elapsed). These diagnostic values
are not concurrent-user p95 evidence. No per-row query loop was found. The
Staff-reference FOR NO KEY UPDATE still serializes independent assignments
to the same Staff. A two-actor barrier test fails before its correction.

The PostgreSQL target reference now uses **FOR SHARE**, which permits concurrent
reference readers but blocks authorization-changing updates and deletion until
commit. The Head retains FOR NO KEY UPDATE; complaints retain FOR UPDATE.
Model-owned identifiers are quoted, the primary key is type-prepared, and its
value is bound as a SQL parameter. The supported SQLite fallback is unchanged.

The isolated WSGI Q04 setup also opts into60-second PostgreSQL connection reuse
with per-request health checks. The optional setting accepts0–300 seconds.
Absent that opt-in, production/default behavior remains unchanged. Session
timeout remains30 minutes and authorization is re-read on every request.
Actual tests confirm role, department and active-status changes on the **same
live PostgreSQL connection** take effect on the next request.

Focused current-tree validation: **159 passed**, followed by **26 passed** in
the expanded PostgreSQL/security/configuration subset (overlapping suites).
The13 real-PostgreSQL cases include simultaneous Staff-reference readers,
current authorization fences, same-complaint stale-action handling, durable
notification graphs and SQL-text identifier rejection. The final identifier
case was added after the159-case run and passes in the26-case rerun.

Configuration reference: https://docs.djangoproject.com/en/6.1/ref/databases/#persistent-connections
Raw parameter binding: https://docs.djangoproject.com/en/6.1/topics/db/sql/
Row-lock matrix: https://www.postgresql.org/docs/17/explicit-locking.html

The new shared-reference/reuse candidate has no new50-user result yet. Its
code and changed connection configuration require a new explicit authorization
before any additional concurrent run. All release/privacy/limiter gates and
coverage thresholds remain unchanged. Overall official Q04 and final Main
acceptance are still open.
