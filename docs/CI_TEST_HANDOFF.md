# E02 test and coverage handoff

Related issues: #19 (Atul), #27 (Chaitanya, Jenkins/deployment), and #40
(Tanmay, GitHub Actions/repository workflow).

## Run the agreed checks

Use a clean checkout and the project's virtual environment. Install both
requirements files, then supply an ephemeral test-only Django secret through
`DJANGO_SECRET_KEY`. Never use production credentials or a production database.
Follow SETUP.md for supported local configuration and Python requirements.

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
sh scripts/ci_checks.sh
```

The entry point works from any working directory. It runs, in order:

1. Django system checks.
2. Migration-drift checks (`makemigrations --check --dry-run`).
3. The existing test/evidence runner, including the separate module coverage gate.

Any failing stage returns nonzero and stops the sequence. A successful pytest
run does not override a failed coverage gate. The wrapper preserves the existing
runner and its failure handling; it does not lower thresholds or change hashers.

The default creates a unique ignored directory under `build/evidence/ci/`.
An optional first argument selects a different **new** evidence directory.
Existing destinations are refused to avoid publishing stale results. Set
`SCMS_CI_PYTHON` to a Python executable path if the environment does not expose
its activated interpreter as `python`.

## Integrate and retain evidence

Both pipeline owners should call this same entry point after installing the
dependencies. Give each job/build a separate workspace and evidence directory.
Capture the job console, and archive `pytest.txt`, `coverage-summary.txt`, and
`run.json` from that run. Collect diagnostic artifacts after failures too, when
they exist, while preserving the failed job status. Early system/migration
failures are reported in the console and never reuse earlier test artifacts.

Record the checked-out revision and actual job URL. For final evidence, require
`working_tree_dirty=false`, the expected `source_revision`, and both exit codes
equal to zero in `run.json`. Skips must remain visible and be explained.

Chaitanya owns Jenkins build/deployment and must make deployment depend on all
required checks succeeding. Tanmay owns the corresponding Actions triggers and
job wiring. Actions does not replace Jenkins. The current Django database
settings use SQLite; PostgreSQL deployment/test configuration remains part of
E03 and must be verified there rather than inferred from a SQLite result.

## Acceptance still required from the pipeline owners

- Retain one genuine successful job showing checks, tests and the coverage gate.
- Retain a controlled failed job proving a required failure prevents deployment.
- Review test/coverage integration with Atul and link the job evidence in #19,
  #27 and #40. Do not claim a CI service was exercised from a local run alone.

For a safe failure check in an isolated test job, `EVIDENCE_MAX_BYTES=0` causes
the existing Django system check to refuse the configuration. Do not apply this
setting to a running deployment. Final persistence, security/static checks and
PostgreSQL/container acceptance remain owned by E03 and its related tasks.
