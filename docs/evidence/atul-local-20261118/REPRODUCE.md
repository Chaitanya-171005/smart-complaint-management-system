# Reproduction and provenance

Tested code: `7d12ea429349f1c70bc8d3d5d2fff7ac0b0eb620`.
Use fresh isolated checkouts and disposable data, leaving the developer checkout
alone. Python 3.14; install `requirements.txt`, `requirements-dev.txt` and
`playwright==1.58.0`, then `python -m playwright install chromium`.
`python-packages.txt` records the actual installed versions. Activate the venv
in PATH: subprocess health checks invoke `python` by name.

## Sanitizer negative control and fixed checks

On the pre-fix revision `5b8e685d516f5b689e70d0d4944385d2d78d0589`, apply only
the test additions from `7d12ea4` to `test_run_tests.py`. The new cases fail while
the original 11 pass. Then use the complete fixed revision for:

```sh
DJANGO_SECRET_KEY=synthetic-atul-check-only python -m pytest \
  test_run_tests.py test_ci_checks.py test_q04_environment.py test_q04_load.py \
  --no-cov -q --junitxml=build/evidence/focused.xml
```

The HTTP harness needs permission to bind disposable loopback sockets.

## Full, PostgreSQL and browser checks

The exact commands, environment overrides, source and exit codes are retained in
each stage's `command.json` and `result.json`. Locations are sanitized as `<repo>`,
`<pg-repo>`, `<browser-repo>`, `<q05-repo>`, `<venv>` and `<home>`.
Replace them with isolated absolute paths. Never run SQLite suites concurrently
in the same checkout: the project has a fixed test database filename.

The retained driver in `../final-main-f2-20261117/reproduce.py` was used with
`SCMS_VERIFY_ROOT`, `SCMS_VERIFY_OUTPUT`, `SCMS_VERIFY_PYTHON` and, for PostgreSQL,
`SCMS_VERIFY_PG_PORT=55449`. Stages were `full-sqlite`, `full-pg`, `focused-pg`,
`browser` and `q05-pg`. Each requires a new output folder. Full stages invoke
`sh scripts/ci_checks.sh`, not a shortened test selection, with
`SCMS_CI_DATABASE_ISOLATED=1` and `SCMS_CI_REQUIRE_F4=1`.

The PostgreSQL container was created with:

```sh
docker run -d --name scms-atul-pg-20261118 \
  -e POSTGRES_DB=scms_integration -e POSTGRES_USER=scms_integration \
  -e POSTGRES_PASSWORD=synthetic-integration-only \
  -p 127.0.0.1:55449:5432 postgres:17.6
```

That name is historical; use a new task-owned name/port for a fresh reproduction.
Do not point at an application/shared database. Before `q05-pg`, the archived
component harnesses were materialized in a separate clone using
`../final-main-f2-20261117/prepare_q05.py`. Its recorded hashes match the retained
sources. Only the documented macOS closed-port fixture adaptation was applied.

## Local queue/assignment benchmark

The recorded authorization expired at 21:30 IST on 18 November 2026. **Obtain a
new explicit window before any new load.** The harness rejects out-of-window
requests. Do not reuse consumed targets, clear reservations, extend sessions,
change release gates or overwrite old results to obtain a pass.

Create a new isolated environment shortly before running so its real login
sessions remain valid:

```sh
python scripts/q04_env.py up --environment NEW_UNIQUE_NAME \
  --port NEW_LOOPBACK_PORT --complaints 650 --random-seed 1811
```

Use a valid lowercase environment name and an unused port. The command prints
the private state directory. Keep settings/actors there private (0600).
The actual retest command used the clean browser checkout at the tested SHA:

```sh
python run_queue_assignment_retest.py \
  --repo /private/tmp/scms-atul-browser-20261118 \
  --state /Users/mac/.scms-q04/ab4bebddbbca/environments/atul-20261118-retest \
  --output /private/tmp/scms-atul-20261118/build/evidence/atul-20261118/queue-assignment-retest \
  --window-start 2026-11-18T19:30:00+05:30 \
  --window-end 2026-11-18T21:30:00+05:30
```

Those historical locations and times describe the actual execution, not a new
authorization. Substitute freshly provisioned paths and newly approved boundaries
only after approval. Run the harness from this packet or pass its absolute path.
The first failed run used `run_queue_assignment_initial.py`; its file hash exactly
matches the first report. The retest adds an offline unexpired-session precheck.

The harness imports the tested `ActorClient`, `check_case` and `summarize` from
`scripts/q04_load.py`. It reserves targets exclusively, checks code/image hashes,
validates all 550 targets and active Heads, performs both warmups, then blocks
measurement until independent PostgreSQL history/assignee verification succeeds.
It retains warmups and measured samples, stops new operations on request errors,
and bounds each request by the remaining authorization time. A performance
threshold failure is reported as a failed target, never a successful Q04 run.

## Image persistence

Only after HTTP load stops, against the same task-owned project:

```sh
python run_persistence.py --repo /absolute/clean/source \
  --state /absolute/private/environment \
  --output /absolute/new/evidence/persistence \
  --probe /absolute/evidence/persistence_probe.py
```

It creates a restricted private retry key, accepts a synthetic graph through the
real service, restarts app/database, verifies replay, replaces both containers
without rebuilding or deleting volumes, and verifies replay/hashes again.
Its private key and state must never be published. No deployment gate is enabled.
