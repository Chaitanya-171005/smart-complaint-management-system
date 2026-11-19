# Reproduce the recorded source and focused checks

Use a disposable checkout at `a434eaa47f6e96f001c5d188f544cae137b1029d`,
Python3.14 with requirements-dev.txt installed, a synthetic DJANGO_SECRET_KEY,
and an isolated PostgreSQL17 database. Set DJANGO_DATABASE_URL to its disposable
connection URL. Do not run against shared data. Actual hosted source runs:

- Unified SQLite/PostgreSQL/coverage: Actions44454131707.
- Browser: Actions44454131714.
- Redis/TLS: Actions44454131711.

```sh
python -m pytest integration_checks/allocation_concurrency_pg.py \
  scms/test_database_settings.py --no-cov -q --junitxml=security.xml
SCMS_CI_DATABASE_ISOLATED=1 SCMS_CI_REQUIRE_F4=1 \
  sh scripts/ci_checks.sh build/evidence/NEW-UNIQUE-RUN
```

The26-case focused subset includes13 mandatory real-PostgreSQL lock/concurrency
cases and13 database configuration cases. A non-PostgreSQL backend is rejected
for the concurrency subset. The canonical CI invokes its separate PG step after
full regression, without weakening coverage thresholds. Check the recorded CI
command in `shared-run/ci-unified-a434eaa.txt` for its exact environment setup.
The159-case broader focused run preceded the final added SQL-identifier case;
its subsequent26-case security rerun includes that case. Suites overlap.

## Recorded benchmark command — historical authorization only

This command actually ran on19 November10:34:55–10:35:27 IST. Its authorization
ended11:00 IST; do not reuse that window or consumed targets. A future load run
requires a newly approved timezone-qualified window, target and resource profile.
The successful run ended further load under its stop-after-first-pass condition.

Create a new isolated `scripts.q04_env` environment only after such approval,
record source/image equality, and use a new private state root. Configure650
synthetic complaints, seed1811,50 distinct real Head sessions and550 distinct
unassigned targets. The published `q04/compose.yml` specifies four sync workers,
one thread each,60-second DB connections with health checks. Do not change gates,
limiter, Staff-target distribution or dataset to obtain passing timings.

The retained harness is `harness/run_shared_20261119.py.txt`; copy it to a private
working directory as `run_shared_20261119.py` and record its hash. Actual argument
shape (set absolute task paths; credentials stay private):

```sh
python run_shared_20261119.py \
  --repo "$SCMS_SOURCE" --state "$SCMS_PRIVATE_STATE" \
  --output "$SCMS_NEW_EVIDENCE" \
  --window-start 2026-11-19T09:35:00+05:30 \
  --window-end 2026-11-19T11:00:00+05:30
```

Baseline probes enforce50 active department Heads/sessions, fresh targets, closed
release gates, local5,000,000-byte interpretation,60-second connections and health
checks. Warmup must execute50 real assignments with matching immutable history
and notification events before measuring. Each Head then performs ten measured
queue requests and ten assignment POSTs. Verify all550 final graphs. The first
unexpected failure or window expiry stops execution; targets are permanently
reserved rather than reset. Retain all1,100 raw samples, exact p50/p95/max,
throughput, errors, source/image/configuration and app/PostgreSQL logs.

Reported p95 uses `scripts.q04_load.summarize` (nearest-rank from sorted samples).
CSRF preparation GETs are excluded from the POST timer but included in assignment
wall throughput. This is closed-loop50-concurrent-user local evidence only.
Warmup samples, SQL counts, CI wall time and single-request profiles never replace
measured response samples. Previous failed runs remain retained and labelled.
