# E03 local security and pipeline validation

Source HEAD tested: `b2b2b1fcafccc5b473e5433db0705d539528b0cc`.
The worktree was dirty; see `run.json` for the pre-run status of all source
changes tested. This is not clean-source evidence.

## Security scans

- Bandit 1.9.4, Python 3.14.6: the exact scoped command in `bandit.txt`
  passed with exit code 0 and no findings. Severity and confidence defaults
  remain unchanged.
- Before the two precise B105 annotations, the unfiltered five-package scan
  found 1,407 low findings: 1,405 in test modules and two B105 matches on
  public Django signing salts. Both values are only `salt=` namespace inputs
  to `django.core.signing.dumps/loads`; Django's `SECRET_KEY` provides
  signature integrity. Only those two assignments carry `# nosec B105`.
- A separate broader diagnostic of test utilities found 67 findings: 65 in
  `integration_checks/` and test-only `scripts/q04_load.py` (46 B101, 3 B404,
  8 B603, 2 B405, 4 B607, 2 B314), plus two B404/B603 hits in
  `scripts/run_tests.py`. The two B314 hits are XML parsing of locally
  generated JUnit reports in PostgreSQL integration harnesses. The integration
  harnesses and Q04 load tool are outside runtime application/CI source; the
  CI runner findings are narrowly annotated as fixed, no-shell subprocess use.
  Archived `docs/evidence/` helpers are also outside runtime and CI source.
  These boundaries do not exclude production modules, and no application code
  finding remained in the final scan.
- The Dockerfile uses `COPY . /app`; `.dockerignore` now excludes test modules,
  `conftest.py`, `integration_checks/`, and `scripts/q04_load.py`. Those are
  test tooling rather than runtime dependencies. Every remaining Python file
  copied into the image falls under the Bandit scan's explicit source roots.
- The CI runner's `subprocess` import/call has narrow B404/B603 annotations:
  it executes only fixed, repository-controlled Python argv without a shell.

## Tests and coverage

- Focused E03 checks: 15 passed; command and exit code are in
  `focused-tests.txt`.
- Full suite: 1,170 passed, zero failures/errors/skips; details are in
  `pytest.txt`.
- Overall coverage: 96.14%. All module line and branch gates passed; the exact
  report is in `coverage-summary.txt`. `run.json` records both test and gate
  exit codes as 0.
- The first sandboxed full-suite attempt had 13 Q04 loopback socket setup
  errors because local binds were denied. The complete suite was rerun with
  loopback permission and passed without skips; `pytest.txt` records that
  successful run.

## pip-audit and execution limits

`pip-audit -r requirements.txt -r requirements-dev.txt` passed with no known
vulnerabilities and exit code 0; see `pip-audit.txt`.

Jenkins Declarative syntax and an actual Jenkins build remain unverified:
there is no local Jenkins/Groovy linter, and Jenkins/Docker daemon execution
was unavailable. Repository tests inspect pipeline structure but do not run
Jenkins. This evidence does not claim a Jenkins execution or production
deployment. Q02 transport/privacy verification remains an external prerequisite.
