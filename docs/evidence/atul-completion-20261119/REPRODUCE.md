# Reproduce the verified branch checks

Use a new disposable checkout at runtime
`27d41850ecf2de3f77cd726de98a2eeae8b08cad` and copy this evidence packet from its
later evidence tip if needed. Set SCMS_SOURCE, SCMS_VENV and SCMS_PACKET to
absolute task-owned directories. Install requirements.txt, requirements-dev.txt
and Playwright1.58.0/Chromium. Use a synthetic DJANGO_SECRET_KEY and disposable
SQLite/PostgreSQL databases only. The repository fixes its SQLite test filename
per checkout; do not run suites there concurrently. Do not reuse existing private
state or consumed assignment targets.

## Canonical regression, migration and coverage

```sh
cd "$SCMS_SOURCE"
export DJANGO_SECRET_KEY=synthetic-isolated-verification-only
export SCMS_CI_DATABASE_ISOLATED=1 SCMS_CI_REQUIRE_F4=1
export SCMS_CI_PYTHON="$SCMS_VENV/bin/python"
export PATH="$SCMS_VENV/bin:$PATH"
sh scripts/ci_checks.sh build/evidence/NEW-UNIQUE-RUN
```

Repeat in a separate disposable PostgreSQL configuration using the actual hosted
workflow's DB environment. See `.github/workflows/evidence-recovery.yml` for its
explicit PG settings and mandatory separate13-case concurrency command. Hosted
source27d logs: `current/ci-unified.txt`, jobs recovery-tests and
postgresql-recovery;2,097 tests each and module coverage gates pass. The extra
real-PG subset refuses SQLite; a wrong backend is not a skip.

## Independent Q06, exact68 cases

```sh
mkdir -p build/evidence/q06/harness build/evidence/q06/browser
for file in "$SCMS_PACKET"/harness/*.py.txt; do
  filename=$(basename "$file" .txt)
  cp "$file" "build/evidence/q06/harness/$filename"
done
export Q06_OUTPUT="$SCMS_SOURCE/build/evidence/q06/browser"
export SCMS_BROWSER_EVIDENCE_DIR="$SCMS_SOURCE/build/evidence/q06/feedback"
"$SCMS_VENV/bin/python" -m pytest \
  build/evidence/q06/harness/test_q06_browser.py \
  build/evidence/q06/harness/test_q06_work_ui.py \
  build/evidence/q06/harness/test_q06_keyboard.py \
  integration_checks/q06_four_screen_browser.py \
  integration_checks/reference_feedback_browser.py \
  --no-cov -q --junitxml=build/evidence/q06/junit.xml
```

The actual latest execution split this into60 independent cases and8 committed
four-screen/reference-feedback cases, retained under current/q06.txt and
current/q06-feedback.txt with separate XML. Ephemeral TLS and emulated Redis are
synthetic process fixtures. Their prerequisite settings do not modify deployed
configuration. Expected results:68 pass,0 fail/error/skip;4 primary screens at
both1280/320 widths. No unaided human acceptance is inferred.

For the actual automated demo, run only the retained q06_recorded_demo.py harness
with SCMS_DEMO_VIDEO_DIR set to a new absolute output directory and
SCMS_BROWSER_EVIDENCE_DIR set to a new screenshot directory. It produces2 passing
cases and real WebM files; these overlap the four-screen scenario. Do not reuse
the historical dates or call those clips sprint/human acceptance.

## Actual built browser and restart/replacement

The retained `harness/built_browser.py.txt` uses SCMS_VERIFY_ROOT,
SCMS_PRIVATE_STATE and SCMS_BROWSER_OUTPUT. Start a **new** task-owned Q04 stack
from the source with the published Compose settings, closed gates and local
proposed5,000,000-byte limit. Generate private synthetic real-login Head and
Complainant sessions through the application's CSRF login. Do not publish
settings.json, actors.json, cookies, retry keys, DBs or evidence storage. The
recorded14 browser cases run after real replacement and check assets200, role
refusals, private no-asset/no-script pages, page fit and JS exceptions at both
widths. See current/built-browser/results.json and current/source-image.json.

Copy run_persistence.py.txt and persistence_probe.py.txt to a task-owned working
folder and run the former with --repo, --state, --output and --probe absolute
paths. It invokes the real service with a private0600 retry key, keeps HTTP gates
closed, restarts only its recorded app/DB containers and recreates them without
resetting named volumes. It asserts unchanged graph counts/hash, PNG hash/mode,
mounts/image and idempotent replay at all three stages. This is service/persistence
evidence; no enabled HTTP intake, production SMTP or Jenkins is claimed.

## Process / SMTP / scheduler28 cases

Copy harness/q05/*.py.txt into a task-owned importable q05_checks package. Use a
new disposable PostgreSQL DB/user and set Q05_DB_NAME, Q05_DB_USER,
Q05_DB_PASSWORD, Q05_DB_HOST and Q05_DB_PORT to that test target. Set
DJANGO_SETTINGS_MODULE=q05_checks.settings and run:

```sh
"$SCMS_VENV/bin/python" -m pytest q05_checks --no-cov -q \
  --junitxml=build/evidence/q05-junit.xml
```

The adapted settings select actual PostgreSQL for process tests and create
isolated child connections; test SMTP servers are local controlled fixtures.
Actual latest result28 pass is retained with all harness sources and hashes.
This is not delivery-owner acceptance of production scheduler/SMTP.

## Local queue/assignment and remaining Q04

The actual passing bounded run used runtimea434eaa on the separate PR105 setup,
not the UI composition. Complete raw timings/logs and the guarded historical
command are in `../q04-fanout-candidate-20261118/REPRODUCE.md`. Its approved window
has ended and its stop-after-first-pass condition fired; do not repeat load under
that authorization. A future run needs fresh explicit approval/targets/settings.
OtherQ04 scenarios remain pending approved policy/data/target readiness. Release
gates, limiter budgets, source-bucket rules, thresholds and workload must remain.

## Evidence verification

`sha256.json` hashes every packet file except itself. Parse each XML/JSON and
compare counts to its recorded log, keeping historical source stages separate.
Private-value/local-path scans ran before publication; no credentials/private
state/database files are included. Text redaction does not imply filesystem
containment. Recheck any new packet files rather than reusing this scan verdict.
