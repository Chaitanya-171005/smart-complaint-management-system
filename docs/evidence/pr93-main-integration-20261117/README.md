# PR93 integration with merged Main — branch verification

This is evidence for the integration branch, not final Main acceptance. Main was
not modified by this work. After the integration is reviewed into PR #93 and #93
is merged, rerun the agreed checks on the resulting Main SHA and retain those
results separately. No production deployment, release activation, official Q04
performance, final Q05 acceptance or unaided Q06 acceptance is claimed here.

## Source and conflict resolution

- PR93 input: `524ef555d3fba18dd1575173e4bbcc81d51a49cd`.
- Main input, containing merged PR92: `b77e8b1ff05ebaea2a477c693fbdac1bfa1d5757`.
- Tested merge commit: `3ac81b60bd8a5df9da1009328444bfe33d2cacab`.
- Tested tree: `6b11b2edf27ba37d73c7a5c7db80aae1d673b5a8`.
- Branch: `codex/pr93-main-integration-20261117`; PR93 is the first merge parent.
- The sole conflict was `.env.docker.example`. Both PR93 feedback/reopen defaults
  and Main's console/SMTP configuration were retained. Other shared files merged
  automatically and were inspected, including settings, Compose and CI wiring.

`merge-invariants.json` records unchanged release-gate definitions and unchanged
privacy, intake, feedback, reference-disclosure-fix, recovery, routing and
allocation source blobs relative to their input revisions. All existing release
gates retain their disabled defaults. Synthetic test fixtures alone enable gates
temporarily; they do not attest deployed readiness.

No AGENTS.md was found in either input tree, repository subtrees or applicable
local parent directories. The available branch/review workflow, testing, CI
handoff, authorization/privacy contracts and prior PR93 review evidence were read.
The original `atul-pr93` checkout was left untouched; isolated clones held the work.

## Actual validation

Final canonical SQLite result: **2,001 passed**, zero failures/errors/skips; **96.91%** overall coverage. All four module gates passed (line/branch: accounts 98.62%/96.79%, complaints 98.22%/95.30%, routing 94.58%/86.06%, workflow 98.20%/95.60%).

`verification.json` contains exact case counts, zero-skip/failure checks, source
SHAs, exit codes and durations. Counts across different suites overlap.

- The canonical SQLite command `sh scripts/ci_checks.sh` ran with disposable
  storage and `SCMS_CI_REQUIRE_F4=1`. It includes syntax and synthetic Compose/deploy
  preflight, Django checks, migration drift, fresh migrations, the complete default
  suite plus explicit anonymous recovery/escalation and F3/F4 lifecycle,
  resolution, handoff and retired-route checks, followed by all module coverage
  gates. The final result and coverage are in `full-sqlite-venv/`.
- 621 focused PostgreSQL 17.6 cases passed with zero failures/errors/skips. They
  cover anonymous identity/reference privacy, tracking/feedback (including the P1
  case-variant regressions), department authorization, queue/allocation, escalation,
  real F4 outbox composition, SMTP retries, auto-close and evidence recovery.
- 28 additional PostgreSQL scheduler/SMTP/auto-close component cases passed after
  the portable refusal-fixture correction described below. These exercise actual
  worker processes, SIGKILL boundaries, competing transactions, loopback SMTP,
  durable retries and conservative handling of ambiguous acceptance.
- 14 real Chromium cases passed with zero failures/errors/skips, exercising normal
  intake validation plus confirmation, reopening, maximum-reopen Head review and
  tracking. Browser evidence covers 320px and 1280px layouts; the intake error
  cases use 320px. The loopback TLS proxy is real; reference-feedback browser
  cases use the existing emulated Redis fixture, not deployed Redis acceptance.
  The mobile anonymous-validation and reopened-tracking screenshots were also
  visually inspected.
- Both real image-health subprocess cases passed after virtualenv PATH correction;
  see `healthcheck-fixed.*` and their inclusion in the final canonical suite.

Mac runtime: Python 3.13.0, Django 6.1.2, Chromium 145.0.7632.6. PostgreSQL ran in
a dedicated loopback-only Docker container at version 17.6. Dependency versions
are retained in `dependencies.txt`. No deployed database, SMTP account or existing
Q04 application container was used or changed.

## Failed attempts and corrections

`failed-attempts.zip` retains actual logs, JUnit and commands, with inherited
environment credentials redacted and local paths normalized. Failed/interrupted
counts are not added to accepted results.

1. The initial browser and full SQLite commands were mistakenly launched from the
   same checkout. The project's fixed `test_db.sqlite3` path caused a collision,
   readonly errors and a generic anonymous 503. The affected full run was stopped;
   browser, SQLite and PostgreSQL checks were moved to separate clones. All 14
   isolated browser cases then passed. No application bypass was introduced.
2. A complete isolated SQLite attempt passed 1,999 tests and all module coverage
   gates but failed two image-health subprocess tests because the runner selected
   a virtualenv interpreter without adding its bin directory to PATH. The older
   supplemental full PostgreSQL attempt encountered the same two failures and was
   interrupted after 1,594 passing cases; it is not reported as a full PostgreSQL
   pass. The runner now activates the virtualenv in PATH. Both health cases passed
   in isolation and the canonical SQLite suite was rerun with the correction.
   Focused PostgreSQL results remain independent; hosted unified CI provides the
   full PostgreSQL branch check separately.
3. The historical SMTP recovery fixture assumed a bound, non-listening TCP socket
   would raise ConnectionRefusedError. On this Mac it produced TimeoutError, which
   the application correctly classified as ambiguous delivery rather than blindly
   retrying. Only the materialized test copy was adapted to close the reservation
   before connecting to the unused port. Actual refusal/retry and subsequent worker
   resumption then passed, as did all 28 component cases. The exact patch, original
   and adapted hashes, and diagnostic exception-type log are retained. Historical
   archived payloads and the application's timeout/retry policy were not edited.

## Reproduction

Install the repository requirements in an activated virtualenv, plus
`playwright==1.58.0`, and install its Chromium runtime. Docker Compose and openssl
must be available. Use synthetic data and an isolated clone. Run sequentially in
one clone, or use a different clone per concurrent suite: SQLite TEST.NAME is fixed
within each checkout.

Copy `reproduce.py` and `prepare_q05.py` outside the checkout before switching to
the tested source commit if exact-source reproduction is required. The published
evidence commit adds documentation/logs only. Example, with `$HARNESS` naming that
external directory and `$CANDIDATE` a disposable clone:

```sh
cd "$CANDIDATE"
git switch --detach 3ac81b60bd8a5df9da1009328444bfe33d2cacab
export SCMS_VERIFY_ROOT="$CANDIDATE"
export SCMS_VERIFY_PYTHON="$VIRTUAL_ENV/bin/python"
export SCMS_VERIFY_OUTPUT="$CANDIDATE/build/evidence/reproduction-new"
python "$HARNESS/reproduce.py" full-sqlite
python "$HARNESS/reproduce.py" browser

docker run --detach --rm --name scms-pr93-reproduce-pg \
  --publish 127.0.0.1:55439:5432 \
  --env POSTGRES_DB=scms_integration --env POSTGRES_USER=scms_integration \
  --env POSTGRES_PASSWORD=synthetic-integration-only postgres:17.6
# Wait until pg_isready succeeds before running the checks.
docker exec scms-pr93-reproduce-pg pg_isready -U scms_integration
python "$HARNESS/reproduce.py" focused-pg
# Optional canonical full PostgreSQL branch regression:
python "$HARNESS/reproduce.py" full-pg

docker exec scms-pr93-reproduce-pg createdb -U scms_integration scms_q05_integration
python "$HARNESS/prepare_q05.py" "$CANDIDATE"
python "$HARNESS/reproduce.py" q05-portable-pg
docker stop scms-pr93-reproduce-pg
```

Use a fresh output directory for each reproduction. The runner refuses reused
stage directories and the canonical wrapper refuses stale evidence destinations.
`SCMS_VERIFY_PG_PORT` can select a different matching disposable host port.
Separate checkout paths can be supplied through `SCMS_VERIFY_PG_ROOT`,
`SCMS_VERIFY_BROWSER_ROOT` and `SCMS_VERIFY_Q05_ROOT`. `command.json` files retain
the actual executed argv and synthetic environment overrides, with normalized
paths. `prepare_q05.py` refuses a reused harness directory and asserts the exact
archived fixture before adapting it.

## Remaining review and acceptance

Chaitanya must review the integration into #93 and the existing CI/P1 corrections.
This evidence does not dismiss existing changes-requested reviews. The inherited
default-department deactivation safeguard remains a separate F1/F3 follow-up.
Abandoned RUNNING scheduler audit-row supervision, deployed ingress/log redaction,
SMTP mailbox acceptance, official Q04 performance and final combined Main acceptance
remain separate. After #93 merges, fetch that Main revision, verify the merge result,
run the canonical SQLite/PostgreSQL, browser and real Redis/TLS jobs on it, and
record fresh source-specific evidence before final Main acceptance.
