# Reproduce the isolated automated Q06 checklist

Use a new disposable checkout and venv. Set Q06_SOURCE, Q06_VENV, Q06_PACKET and
Q06_OUTPUT_ROOT to absolute directories you own; Q06_PACKET is this committed
packet. Check out the follow-up runtime source `2a40cbf34c1caff4242d729e4a0f2609ef5ad557`
or the final published follow-up head (whose CI must be checked separately).

```sh
cd "$Q06_SOURCE"
"$Q06_VENV/bin/python" -m pip install -r requirements.txt -r requirements-dev.txt playwright==1.58.0
"$Q06_VENV/bin/python" -m playwright install chromium
mkdir -p build/evidence/q06/harness "$Q06_OUTPUT_ROOT"
for file in "$Q06_PACKET"/harness/*.py.txt; do
  filename=$(basename "$file" .txt)
  cp "$file" "build/evidence/q06/harness/$filename"
done
export Q06_OUTPUT="$Q06_OUTPUT_ROOT/browser"
export SCMS_BROWSER_EVIDENCE_DIR="$Q06_OUTPUT_ROOT/feedback"
export DJANGO_SECRET_KEY=synthetic-q06-only
export DJANGO_DB_ENGINE=sqlite
export DJANGO_DB_PATH="$Q06_SOURCE/build/q06-app.sqlite3"
export PRIVATE_EVIDENCE_ROOT="$Q06_SOURCE/build/q06-private"
"$Q06_VENV/bin/python" -m pytest \
  build/evidence/q06/harness/test_q06_browser.py \
  build/evidence/q06/harness/test_q06_keyboard.py \
  build/evidence/q06/harness/test_q06_work_ui.py \
  integration_checks/reference_feedback_browser.py \
  integration_checks/q06_four_screen_browser.py \
  --create-db --no-cov -q --junitxml="$Q06_OUTPUT_ROOT/junit.xml" \
  > "$Q06_OUTPUT_ROOT/pytest.txt" 2>&1
```

Expected follow-up result: 68 passed, zero failed/errors/skipped. The fixture uses
an ephemeral loopback TLS proxy and an in-process Redis emulator. It enables
prerequisites only in the isolated test process and also checks closed gates.
No deployed env file or shared resource is used. The repository fixes its SQLite
test filename inside the checkout: do not run other suites there concurrently.

To reproduce baseline failures use exact PR #103 `68cd6fa` and the committed
`baseline-harness/*.py.txt` instead, omitting the new four-screen file from pytest; the follow-up harness
intentionally follows the new four-screen normal route. Baseline observed paths,
failures and counters are retained in before-pr103, rather than claimed on a
future head. Existing CI browser workflow runs the two new committed normal-flow
cases plus the existing browser regression suite on the published commit.

Required regression/coverage entry point on a disposable SQLite or PostgreSQL DB:
set DJANGO_SECRET_KEY to a synthetic value, SCMS_CI_DATABASE_ISOLATED=1,
SCMS_CI_REQUIRE_F4=1 and SCMS_CI_PYTHON to the venv Python, put that venv's bin on
PATH, then run `sh scripts/ci_checks.sh build/evidence/NEW-UNIQUE-RUN`.
Do not reuse an evidence directory or claim focused browser passes as full CI.
