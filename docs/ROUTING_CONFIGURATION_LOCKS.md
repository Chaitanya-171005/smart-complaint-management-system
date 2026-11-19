# Routing configuration transaction lock

Base: Main `b7db7848cbc15d8b67fbba508e57b9f31e16dc74` (includes PR #96).
This fixes inherited configuration lock cycles while preserving PR #96's F1 guards.

## Root cause and change

Routing creation locks category -> department -> location. A location-changing
update locks rule -> location -> category -> department. A location-only creator
holding department D and an updater holding location L can each wait for the
other, without conflicting routing scopes. SLA set takes category -> SLA, while
SLA deactivation takes SLA -> category. Atomic rollback prevents partial writes,
but a deadlock abort escapes the configuration view as an unexpected DB error.

All F1 reference-data, F3 routing/SLA/policy and F1 user-role configuration writes
now acquire the same PostgreSQL transaction advisory lock, `(0x53434D53, 1)`,
immediately after entering `atomic()` and before row locks. The existing row
locks, validation, uniqueness constraints, precedence and audit writes remain.
The transaction-wide order is configuration lock -> existing row locks ->
mutation/audit -> deferred FK checks -> commit/release. Nested calls can reacquire
the same lock. Rollback releases it automatically; there is no session lock,
migration, persistent lock row, or Python process-local mutex.

Audit actor/security-event FKs reference User; rules/SLA/policy reference
Category/Department. PostgreSQL FK checks can acquire additional parent key-share
locks, including at commit for deferred constraints. User-role changes acquire
User row locks and can check Department FKs, so they join the same configuration
lock before their User locks. Read-only configuration/queue/intake requests do
not acquire the advisory lock. Normal complaint workflow is not serialized.

Tradeoff: configuration writes queue behind each other; no throughput claim is
made for concurrent bulk administration. Callers must enter these services
before acquiring other row locks in an enclosing transaction. Direct ORM writes
and arbitrary externally locked transactions are outside this service contract.
Do not use a new session-level advisory lock or acquire this lock after row locks.

## PostgreSQL regressions

`routing/test_configuration_lock.py` coordinates two real database backends.
The first is held at an actual row-lock or post-audit-write boundary; the
coordinator confirms the second backend waits for the first using
`pg_blocking_pids()` before releasing it. This avoids probabilistic sleeps as
proof of ordering. Finite lock/statement timeouts fail stalled workers.

Four scenarios cover routing create/update, a genuine HTTP update (no 500),
category/SLA set/deactivation, and concurrent post-write audit failure/rollback.
They check exceptions, final state, audit counts and old/new audit values.
`SCMS_LOCK_TEST_ROUNDS` defaults to 3 and supports 100 repetitions per scenario.
The opt-in negative control disables only the new routing lock in the test and
requires the original cycle to produce PostgreSQL SQLSTATE `40P01` and exactly
one committed operation/audit. It must run only against a disposable test DB.
SQLite skips these five tests explicitly; its writer serialization is not proof.
No rule-reactivation endpoint is added; existing update refresh behavior remains.

## Mac verification commands

Run from the isolated integration checkout, not the UI or Main worktree. The
existing verification environment is shown below.

```sh
cd /tmp/scms-routing-lock-order-final-20261119
source /tmp/scms-lock-order-venv/bin/activate
export DJANGO_SECRET_KEY=synthetic-lock-order-verification-only
export DJANGO_DB_ENGINE=postgresql
export DJANGO_DB_HOST=127.0.0.1
export DJANGO_DB_PORT=57440
export DJANGO_DB_USER=scms_review
export DJANGO_DB_PASSWORD=scms_review_local_only
export DJANGO_DB_NAME="scms_lock_$(python -c 'import uuid; print(uuid.uuid4().hex[:12])')"
python - <<'PY'
import os
import psycopg
from psycopg import sql
with psycopg.connect(host=os.environ['DJANGO_DB_HOST'], port=os.environ['DJANGO_DB_PORT'],
    dbname='scms_review', user=os.environ['DJANGO_DB_USER'],
    password=os.environ['DJANGO_DB_PASSWORD'], autocommit=True) as conn:
    print(conn.execute('SELECT version()').fetchone()[0])
    conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(os.environ['DJANGO_DB_NAME'])))
PY
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py migrate --check
SCMS_LOCK_TEST_ROUNDS=100 python -m pytest routing/test_configuration_lock.py --no-cov -q
SCMS_LOCK_NEGATIVE_CONTROL=1 python -m pytest routing/test_configuration_lock.py::test_postgresql_original_routing_cycle_negative_control --no-cov -q
SCMS_CI_DATABASE_ISOLATED=1 sh scripts/ci_checks.sh "build/evidence/lock-order-$(date +%Y%m%d%H%M%S)"
```

Django creates and destroys a separate `test_<DJANGO_DB_NAME>` database; do not
pass `--reuse-db` or agree to delete an existing database. The UUID base database
is task-owned and remains available for inspection. No existing containers or
volumes need modification. Confirm the container's published port before use.
Repeat the test commands in `/tmp/scms-routing-lock-order-pr96-compat` to verify
the merged tree with #96; use a new UUID database there as well.

## Earlier results from the restricted review environment

Python 3.14.6, Django 6.1.3, pytest 9.1.1; SQLite in task-owned checkouts.

- Focused routing/reference/user/audit tests: 191 passed, 4 PostgreSQL scenarios
  skipped, 2 subtests passed (before adding the opt-in negative-control test).
- Full suite attempt: 1,984 passed, 4 PostgreSQL skips, 6 failures and 13 setup
  errors. All 19 unsuccessful cases were denied loopback socket binding in
  Docker-health, SMTP relay or load-harness tests. No success is claimed for them.
- Final available-suite run, including the negative control: 1,984 passed,
  5 PostgreSQL skips, 19 socket-dependent cases deselected; no failures.
- Coverage gates: accounts 98.41% line / 96.40% branch; complaints 98.18% /
  95.30%; routing 94.45% / 86.06%; workflow 98.19% / 95.60%. All gates pass.
- Django check: zero issues. Migration drift: none. Fresh migrations and
  migrate --check: pass. git diff --check: pass.
- Earlier Git merge-tree of Main + #96: conflict-free tree
  `990ca26e01a4c94168ebbbbd8f17388bd9d96b47`. The fix applied without conflicts.
  Compatibility-focused run: 169 passed, 4 PostgreSQL skips, 2 subtests passed.
  Final compatibility guard/lock tests: 22 passed, 5 PostgreSQL skips.
- Direct psycopg to the dedicated PostgreSQL endpoint 127.0.0.1:50311 was denied
  with Operation not permitted before authentication. Zero PostgreSQL scenarios
  or negative-control deadlocks were executed here; they remain unverified.

## Final verification after PR #96 merged

The integrated tree uses Main `b7db7848cbc15d8b67fbba508e57b9f31e16dc74` and
preserves PR #96. The final combined source tree is
`bd474045ff6d27fbba538158cb35c3f8a21a546f`.

- Task 7 focused SQLite tests: 388 passed.
- Task 7 PostgreSQL concurrency: 6 passed, 1 expected skip.
- Original-deadlock negative control: 1 passed; PostgreSQL reported SQLSTATE
  `40P01` as expected.
- PR #96 exact-head PostgreSQL and SQLite CI: 2,025 passed in each database;
  coverage gates passed.
- Combined PR #96 and Task 7 SQLite tests: 142 passed, 5 PostgreSQL-only tests
  skipped, 2 subtests passed.
- Combined PostgreSQL compatibility tests: 30 passed, 1 expected skip.
- Django system and migration checks passed; no migration changes were needed.

F1 reference-data guards and F3 routing/SLA/policy writers acquire the shared
transaction advisory lock before row locks. The combined PostgreSQL verification
covered their interaction. The final branch contains only the six Task 7 files;
PR #96 remains in Main unchanged.
