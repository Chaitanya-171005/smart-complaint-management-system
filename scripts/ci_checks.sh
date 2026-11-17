#!/bin/sh
# Shared E02 check entry point for the E03/E04 pipeline owners.
set -eu

if [ "$#" -gt 1 ]; then
    printf '%s\n' 'Usage: sh scripts/ci_checks.sh [new-evidence-directory]' >&2
    exit 2
fi

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_dir"
ci_python=${SCMS_CI_PYTHON:-python}
evidence_dir=${1:-build/evidence/ci/$(date -u +%Y%m%dT%H%M%SZ)-$$}

if [ -e "$evidence_dir" ]; then
    printf '%s\n' 'Use a new evidence directory so an earlier result cannot be reused.' >&2
    exit 2
fi

if [ -z "${DJANGO_SECRET_KEY:-}" ]; then
    printf '%s\n' 'Export DJANGO_SECRET_KEY with a test-only value before running CI checks.' >&2
    exit 2
fi

if [ "${SCMS_CI_DATABASE_ISOLATED:-}" != 1 ]; then
    printf '%s\n' 'Set SCMS_CI_DATABASE_ISOLATED=1 only for a disposable CI database.' >&2
    exit 2
fi

"$ci_python" scripts/ci_environment.py
"$ci_python" manage.py check
"$ci_python" manage.py makemigrations --check --dry-run
"$ci_python" manage.py migrate --noinput
"$ci_python" manage.py migrate --check
"$ci_python" scripts/run_tests.py --evidence-dir "$evidence_dir"
