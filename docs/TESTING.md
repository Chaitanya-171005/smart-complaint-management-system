# Testing — E02

Owner: Atul Suresh — PES1UG24CS098. Related issue: #19.

## Setup and run

Follow [SETUP.md](SETUP.md) for the virtual environment and local .env.
Install dependencies from the repository root:

    python -m pip install -r requirements.txt -r requirements-dev.txt

pytest, pytest-django and pytest-cov are pinned in requirements-dev.txt.
The shared .coveragerc supplies source modules and branch measurement;
pytest.ini supplies the reporting options.

One command runs tests, checks coverage, and records sanitized evidence in ignored
build/evidence/, preserving committed evidence:

    python scripts/run_tests.py

To deliberately refresh committed evidence, select its directory explicitly:

    python scripts/run_tests.py --evidence-dir docs/evidence/e02
    python scripts/run_tests.py --evidence-dir docs/evidence/b07

Run only the command for the contribution you are recording. The runner directs
all three output files to that directory; it has no legacy EVIDENCE writes.

To run only the tests without the module gate:

    python -m pytest

To recheck an existing coverage.json:

    python scripts/coverage_summary.py

The runner returns the test failure code first, or the coverage gate code
when the tests pass. A green pytest result does not imply a green coverage gate.

## Shared fixtures and isolation

Root conftest.py provides department_factory, department, user_factory,
complainant_user, staff_user, head_user and scms_admin_user. Factories accept
field overrides. Role fixtures use accounts.models.User.Role constants.

test_fixtures.py builds every shared fixture and checks roles, department
relationships, password handling, overrides and uniqueness. Two independent
parameterized cases create the same unique values after asserting their
absence, verifying test database cleanup without relying on execution order.

All values are synthetic, not confirmed campus policy. scms_admin_user has
the application ADMIN role, not Django superuser access. Only tests requesting
the shared user factory temporarily use the fast salted MD5 test hasher;
production settings and unrelated tests retain their own password settings.
Each module owner maintains their functional tests.

## Coverage gate

Application test files, fixture definitions, migrations and package initializers
are excluded. The script reports line and branch coverage separately for F1-F4.

Each module must have at least 70% line coverage and 60% branch coverage.
Modules with fewer than 10 executable statements are marked PLACEHOLDER.
This is a reporting heuristic, not proof of completed functionality.
Missing modules, placeholders, absent branch data and under-target modules
fail the gate (exit 1). Missing or invalid coverage reports produce a clear
error (exit 2). Only all-module success returns 0.

test_coverage_summary.py exercises threshold boundaries, failure codes,
placeholders, missing/invalid reports, missing branch data and safe import.

B07 adds real complaint form validation; routing remains a placeholder on this
branch until B17 integrates. The gate therefore remains FAIL despite passing
tests. Even when all modules pass later, coverage is not feature acceptance:
the Complaint model, HTTP view and full intake flow still need implementation
and acceptance tests. Do not lower thresholds or add dummy branches.

## Evidence

scripts/run_tests.py writes pytest.txt, coverage-summary.txt and run.json under
build/evidence/ by default, or --evidence-dir when explicitly supplied.
Repository, virtual environment and home
paths are replaced with explicit placeholders; test results are preserved.
run.json records execution time, source revision, pre-run working_tree_dirty,
working_tree_status and actual exit codes. source_revision is HEAD before the
run; when the tree is dirty, the additional local changes listed were tested too.
The flag is captured before generated output is written. Original E02 execution
evidence is retained; its results describe that earlier source state.
To publish reproducible final evidence, commit source changes first and verify
git status --short is empty before invoking the runner with --evidence-dir.
Then check working_tree_dirty is false in run.json and commit only the generated
evidence. That evidence-only commit points back to the tested clean source commit;
it does not claim its own output files existed at test start.
coverage.json and .coverage are generated files excluded by .gitignore.

test_run_tests.py verifies output-directory isolation, stale-report removal,
failure exit codes, dirty/unknown source metadata, ignored default output and
actual subprocess path sanitization.

base-commit.txt records this PR's verified merge base, not the current branch head.
The initial base was confirmed as 8766bf27d4744a0f0221c97742305dc9b59455ea.

## Remaining scope

Complaint/configuration fixtures depend on the shared models. Full module
coverage acceptance and Jenkins/GitHub Actions integration remain pending.
Issue #19 stays open.
