# Testing — E02

Owner: Atul Suresh — PES1UG24CS098
Related issue: #19

## Run

Activate the project virtual environment and configure .env as described
in SETUP.md. Run these commands from the repository root:

    pytest -ra --cov=accounts --cov=complaints --cov=routing --cov=workflow --cov-branch --cov-report=term-missing --cov-report=json:coverage.json
    python scripts/coverage_summary.py

## Shared fixtures

Root conftest.py provides:

- department_factory and department
- user_factory and complainant_user
- staff_user and head_user sharing the department fixture
- scms_admin_user for the application ADMIN role

Factories accept field overrides. Fixtures use the isolated pytest
database and synthetic values, not confirmed campus policy.
scms_admin_user is an application administrator, not a Django superuser.

Each module owner maintains tests for their own functionality.

## Coverage

.coveragerc measures application code and excludes test files, fixture
definitions, migrations and package initializers.

Report line and branch coverage separately for F1-F4.
Required targets per module are at least 70% unit line coverage and
60% branch coverage.

High coverage of placeholder code does not demonstrate implemented features.
A module without executable branches has no measured branch percentage.
Skipped and unexecuted tests are not passing tests.

## Current scope

This contribution establishes user/department fixtures, coverage
configuration and module reporting.

Complaint and configuration fixtures remain pending their shared models.
Final module coverage and CI integration remain part of E02.
