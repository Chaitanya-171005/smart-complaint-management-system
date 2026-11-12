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

Domain fixtures also live in root conftest.py:

| Fixture | Contract |
| --- | --- |
| `category_factory(**fields)` | Unique synthetic B17 category, validated before saving |
| `location_factory(**fields)` | Unique synthetic F1 location with canonical code |
| `routing_rule_factory(**fields)` | Category route in the shared `department` by default; supply `category=None` and a location code for a location-only route |
| `sla_factory(**fields)` | Category-specific synthetic 120-minute LOW SLA; seeded global SLAs remain unchanged |
| `routing_configuration` | Dictionary containing one related `department`, `category`, `location`, `rule`, `sla` and default `policy` |
| `complaint_factory(...)` | Valid persisted ASSIGNED Complaint with an allocated ID, using the merged schema |

`routing_configuration` temporarily sets the default escalation policy to its
synthetic department, 120-minute interval and maximum level 2. Pytest rolls back
these changes after each test. These values are fixture data, not campus defaults.
The policy is validated before either creating or updating its database row.
The SLA duration and escalation interval are independent settings.
Request fixtures explicitly; they do not seed configuration for unrelated tests.

Complaint factories accept `category_record` and `location_record` to reuse real
reference rows. Other keyword overrides are Complaint model fields. For example:

```python
def test_owner_record(complaint_factory, complainant_user, routing_configuration):
    config = routing_configuration
    complaint = complaint_factory(
        submitted_by=complainant_user,
        category_record=config["category"],
        location_record=config["location"],
    )
    assert complaint.submitted_by_id == complainant_user.pk
```

The default Complaint is synthetic, with status `ASSIGNED`, a department,
`unrouted=True`, an empty rule key and a due time two hours after submission.
This represents a fallback-assigned record. The factory does not perform B14/B16
routing or SLA calculation, write initial history, or create an intake receipt. Those services require their
own integration tests. `anonymous=True` invokes the real reference-generation
method and retains only the digest; it does not return or preserve the raw
reference. Reference-display tests must exercise the intake service directly.
The factory validates and saves inside one transaction; invalid overrides roll
back its new references, user and ID reservation. Construct models directly when
a test intentionally needs invalid rows.

test_fixtures.py builds every shared fixture and checks roles, department
relationships, password handling, overrides and uniqueness. Two independent
parameterized cases create the same unique values after asserting their
absence, verifying test database cleanup without relying on execution order.

test_domain_fixtures.py checks real reference relationships, overrides, uniqueness,
seed preservation, rollback, anonymous identity and isolation. The Complaint
schema is merged, so Complaint fixture cases run directly with no dependency
skip guard. A missing model is a test failure. Policy-validation failures are
checked for both new and existing policies without persisting invalid changes.
Run `python -m pytest test_fixtures.py test_domain_fixtures.py --no-cov -q`.

All values are synthetic, not confirmed campus policy. scms_admin_user has
the application ADMIN role, not Django superuser access. Only tests requesting
the shared user factory temporarily use the fast salted MD5 test hasher;
production settings and unrelated tests retain their own password settings.
Each module owner maintains their functional tests.

## Test runtime diagnostics

To include the ten slowest test phases in the normal evidence output, run:

    PYTEST_ADDOPTS="--durations=10" python scripts/run_tests.py --evidence-dir docs/evidence/e02-domain-fixtures

Keep the normal coverage options and password settings for this comparison.
The earlier 135-second result was recorded on the contributor's macOS machine;
it is an observed run time, not an application performance benchmark. Compare
setup, call and teardown timings before attributing the difference to hardware,
Python version, password hashing or other local conditions. Do not change
production password hashing or skip tests to shorten a report.

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

B07 validation and B17 configuration are merged. Read the actual coverage report
for the current source rather than reusing an earlier placeholder result. A
passing coverage gate does not establish completed features: the production HTTP
submission flow and complete intake integration still require acceptance tests.
Do not lower thresholds or add dummy branches.

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

`complaints/test_tracking.py` exercises B13's restricted HTTP/DB/history lookup
and runs the production rolling-window Lua in fakeredis with Lua support.
The emulator is a development-only dependency; deployment Redis, TLS, source
address and logging acceptance remain separate. See [B13_TRACKING.md](B13_TRACKING.md).

base-commit.txt records this PR's verified merge base, not the current branch head.
The initial base was confirmed as 8766bf27d4744a0f0221c97742305dc9b59455ea.

## Remaining scope

See [CI_TEST_HANDOFF.md](CI_TEST_HANDOFF.md) for the shared pipeline check command,
artifact contract and E03/E04 ownership. Real pipeline execution is still required.

Reference/configuration and Complaint fixtures use the merged application models.
Full module acceptance, continued tests for new features and Jenkins/GitHub
Actions integration remain pending. Issue #19 stays open.
