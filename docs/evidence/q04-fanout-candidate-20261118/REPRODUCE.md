# Focused reproduction and next authorized measurement

Use a new disposable checkout at `3ace587ca046080f30fa2a554362048237bcb100` (or
published candidate head), a fresh test venv and synthetic DJANGO_SECRET_KEY.
Do not run against a shared DB. The existing pytest SQLite filename is fixed
inside the checkout; do not run suites there concurrently.

```sh
python -m pytest workflow/test_notification_fanout.py workflow/test_notifications.py \
  workflow/test_reference_feedback.py workflow/test_reopening.py \
  workflow/test_resolution_integration.py workflow/test_lifecycle.py \
  workflow/test_confirmation.py workflow/test_autoclose.py \
  integration_checks/lifecycle_f3.py --no-cov -q -s --junitxml=after.xml
```

Expected: 414 passing focused cases. The two new fanout cases print actual SQL
statement counts and assert recipient/job equality, pending states, replay
idempotence and two bulk INSERTs for the tested 3/50-Head cardinalities. Existing
failure-injection cases assert required insert failures roll back the business
graph. Reproduce the pre-fix failure by applying only the new fanout test to
Main a479551; do not weaken the assertion.

Required CI: `SCMS_CI_DATABASE_ISOLATED=1 SCMS_CI_REQUIRE_F4=1` plus synthetic
DJANGO_SECRET_KEY and a new disposable SQLite/PostgreSQL configuration; invoke
`sh scripts/ci_checks.sh build/evidence/NEW-UNIQUE-RUN` with the test venv on PATH.
Hosted SQLite/PostgreSQL regression/coverage results must match the published SHA.

For a new benchmark: first obtain the exact timezone-qualified window and target
approval, unpause Docker, build a **new** isolated q04_env environment, and record
its source tree, image digest, four worker processes, DB version, resource caps
and release guards. Do not alter existing retained benchmark environments. Use
650 synthetic complaints, seed 1811, 50 fresh real Head sessions and 550 distinct
unassigned targets. The retained `run_queue_assignment_retest.py` in the PR #101
packet performs one warmup and ten measured queue/assignment operations per Head,
checks actual warmup assignment/history/event correctness before measurement,
and stops on unexpected failures/window expiry. Its --help gives explicit source,
private-state, output and approved boundary arguments.

Before publishing: verify all final 550 assignments, immutable Head/assignee
history and event rows; retain every raw sample, p50/p95/max, throughput, errors,
failed assignments and Docker/PostgreSQL logs. Keep credentials/private state out
of evidence. Only a real new measurement can assess p95 <=1,500 ms. This candidate
has not run it. Do not substitute SQL counts or CI wall time for Q04 timings.
