# Local queue/assignment remediation — measured pass, overall Q04 pending

The first retest in the explicitly approved 19 November 09:35–11:00 IST window
passed. Execution was **10:34:55–10:35:27 IST**, source
`a434eaa47f6e96f001c5d188f544cae137b1029d`, image
`sha256:6069cff926a5d048bf85a3cde7b893c3f379b3412fc7301aad75e8173f2765a6`.
No further load ran: stop-after-first-pass was honored. Containers are stopped;
volumes, reservations, raw samples and app/database logs are retained.

| Measured scenario | Samples | p50 ms | p95 ms | Max ms | Throughput/s | Request errors | Target ≤1,500ms |
|---|---:|---:|---:|---:|---:|---:|---|
| Queue |500|428.651|**471.597**|489.506|114.584|0|PASS|
| Assignment |500|537.939|**620.158**|659.589|46.458|0|PASS|

Fifty distinct department Heads each performed one warmup and ten measured
operations per scenario. Real PostgreSQL checks verified50 warmup assignments,
history and notification events **before** measuring, then all550 final graphs.
All assignment targets are unique, assigned to the same Staff as previous runs;
there were zero failed assignments. 1,100 raw samples include warmup. The closed
loop uses a50-worker barrier without think time. Assignment POST timing excludes
its fresh CSRF preparation request; wall throughput includes preparation. See
`report.json` for exact resources, network, source/image hashes and thresholds.

## Correction and validation

The first source batched52 notification and52 email INSERTs into one per table
(114→13 total statements in a single-action probe), preserving all eligible
recipients, atomic failure rollback and replay. These query counts are not load
timings. Current allocation uses FOR NO KEY UPDATE for its Head, FOR SHARE for
the referenced Staff, and the existing FOR UPDATE complaint lock. Staff readers
can overlap; role/department/active changes and deletion remain fenced. Raw SQL
identifiers come from quoted model metadata; prepared PK values are parameters.
Current authorization is read on every action, including reused connections.

The **isolated Q04 Compose setup only** explicitly uses four Gunicorn sync
workers, one thread each, with60-second PostgreSQL connection reuse and health
checks. Defaults remain unchanged without the opt-in. This comparison changes
code, worker count and connections; it cannot attribute improvement to batching
alone. PostgreSQL17.6;650 synthetic complaints,50 Heads,50 Complainants,two Staff;
seed1811; loopback HTTP without TLS or network shaping. Local5,000,000 bytes is
Atul's proposed D02 interpretation pending team confirmation. Release/privacy/
transport/limiter and coverage gates are unchanged and closed as recorded.

At a434eaa: **159 focused PostgreSQL passes**, followed by **26 overlapping
security/configuration passes** (includes the final added identifier case).
Hosted CI: **2,035 SQLite +2,035 PostgreSQL passes**,13 additional mandatory real
PostgreSQL concurrency cases,14 browser cases and9 Redis/TLS cases; coverage
gates pass. Actual logs are in `shared-run/`. Counts overlap and are not summed.
The concurrent-reader reproduction failed before the shared-reference fix.

## Retained unsuccessful runs

| Run / source | Actual result | Evidence |
|---|---|---|
|18 Nov20:45–20:48 /7d12 predecessor|Queue p952,895.659ms; assignment7,147.723ms; both FAIL|Original PR101 local packet|
|19 Nov00:15 /6fe48dc|Warmup:50 queue success,6 assignment success,44 HTTP500; stopped; **zero measured operations**|`failed-warmup-20261119/`|
|19 Nov09:00 /c39e492|Queue p951,504.823ms; assignment3,832.628ms; both FAIL; zero errors,550 correct graphs|`queue-assignment-lockfix-20261119/`|

The warmup failure exposed a real FK/row-lock cycle, reproduced with SQLSTATE40P01
before correction. Initial no-key locks removed deadlocks but Staff serialization
and cold connection overhead remained. The later shared Staff lock and explicit
bounded connection reuse were validated with fresh targets in the successful run.
Previous data, errors and measurements remain unchanged; queue1,504.823ms was
never rounded into a pass. `lock-fix/` retains before/after tests. Cold/warm single
request profiles in `diagnostics/` are diagnostic, never Q04 measurements.

## Scope limits

This is **local deployment evidence for queue/assignment only**, not official
combined Q04, production deployment, final Q05 or final Main acceptance. Other
intake/tracking/escalation/reporting/upload/pagination scenarios remain pending
appropriate approved data, policies and target readiness. PR105 needs genuine
F1/F3/F4/deployment review and team-authorized integration. Main was not merged.
See `REPRODUCE.md` for exact commands and the stop conditions.
