# Testing — E02

Owner: Atul Suresh — PES1UG24CS098. Related issue: #19.

## Setup and run

Follow [SETUP.md](SETUP.md) for the virtual environment and local .env.
Install dependencies from the repository root:

    python -m pip install -r requirements.txt -r requirements-dev.txt

pytest, pytest-django and pytest-cov are pinned in requirements-dev.txt.
The shared .coveragerc supplies source modules and branch measurement;
pytest.ini supplies the reporting options.

One command runs tests, checks coverage, and records sanitized evidence:

    python scripts/run_tests.py

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

complaints and routing are currently placeholders. The strict coverage gate
therefore remains FAIL even when all executed tests pass. Do not lower the
thresholds, add dummy branches, or call the final E02 acceptance complete.

## Evidence

scripts/run_tests.py regenerates docs/evidence/e02/pytest.txt,
coverage-summary.txt and run.json. Repository, virtual environment and home
paths are replaced with explicit placeholders; test results are preserved.
run.json records execution time, source revision and actual exit codes.
coverage.json and .coverage are generated files excluded by .gitignore.

base-commit.txt records this PR's verified merge base, not the current branch head.
The initial base was confirmed as 8766bf27d4744a0f0221c97742305dc9b59455ea.

## Remaining scope

Complaint/configuration fixtures depend on the shared models. Full module
coverage acceptance and Jenkins/GitHub Actions integration remain pending.
Issue #19 stays open.
