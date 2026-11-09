"""Exercise the shell entry point in isolated checkouts, without real CI secrets."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SHELL = shutil.which("sh")
pytestmark = pytest.mark.skipif(SHELL is None, reason="The CI wrapper requires a POSIX shell.")


@pytest.fixture
def wrapper(tmp_path):
    root = tmp_path / "checkout with spaces"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "ci_checks.sh"
    script.write_bytes((Path(__file__).parent / "scripts/ci_checks.sh").read_bytes())
    outside = tmp_path / "caller"
    outside.mkdir()
    log = tmp_path / "invocations.jsonl"
    fake_script = tmp_path / "record_stages.py"
    fake_script.write_text('''import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with Path(os.environ["CI_TEST_LOG"]).open("a") as stream:
    stream.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\\n")
stage = args[1] if args[0] == "manage.py" else "runner"
if stage == os.environ.get("CI_TEST_FAIL_STAGE"):
    sys.exit(int(os.environ["CI_TEST_FAIL_CODE"]))
''')
    fake_interpreter = tmp_path / "fake interpreter"
    fake_interpreter.write_text('#!/bin/sh\nexec "$CI_TEST_REAL_PYTHON" "$CI_TEST_FAKE_SCRIPT" "$@"\n')
    fake_interpreter.chmod(0o700)
    environment = {
        **os.environ,
        "SCMS_CI_PYTHON": str(fake_interpreter),
        "DJANGO_SECRET_KEY": "synthetic-wrapper-test-only",
        "CI_TEST_REAL_PYTHON": sys.executable,
        "CI_TEST_FAKE_SCRIPT": str(fake_script),
        "CI_TEST_LOG": str(log),
    }
    environment.pop("CI_TEST_FAIL_STAGE", None)
    environment.pop("CI_TEST_FAIL_CODE", None)

    def run(*arguments, env=None):
        return subprocess.run(
            [SHELL, str(script), *map(str, arguments)], cwd=outside,
            env=environment if env is None else env,
            capture_output=True, text=True, timeout=15,
        )

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return root, outside, environment, run, calls


def test_extra_arguments_refused_without_running_stages(wrapper):
    _, _, _, run, calls = wrapper
    result = run("one", "two")
    assert result.returncode == 2
    assert "Usage: sh scripts/ci_checks.sh [new-evidence-directory]" in result.stderr
    assert calls() == []


@pytest.mark.parametrize("kind", ["directory", "file"])
def test_existing_destination_refused_without_running_stages(wrapper, kind):
    root, _, _, run, calls = wrapper
    existing = root / "existing evidence"
    if kind == "directory":
        existing.mkdir()
        preserved = existing / "prior.txt"
    else:
        preserved = existing
    preserved.write_text("previous evidence")
    result = run(existing)
    assert result.returncode == 2 and "Use a new evidence directory" in result.stderr
    assert calls() == []
    assert preserved.read_text() == "previous evidence"


def test_stages_run_in_order_with_exact_arguments(wrapper):
    root, _, _, run, calls = wrapper
    destination = root / "new evidence"
    result = run(destination)
    assert result.returncode == 0, result.stderr
    assert calls() == [
        {"cwd": str(root), "args": ["manage.py", "check"]},
        {"cwd": str(root), "args": ["manage.py", "makemigrations", "--check", "--dry-run"]},
        {"cwd": str(root), "args": ["scripts/run_tests.py", "--evidence-dir", str(destination)]},
    ]


@pytest.mark.parametrize("stage,exit_code,count", [("check", 7, 1), ("makemigrations", 11, 2), ("runner", 13, 3)])
def test_failure_stops_later_stages_and_preserves_exit_code(wrapper, stage, exit_code, count):
    root, _, environment, run, calls = wrapper
    result = run(root / "fresh", env={**environment, "CI_TEST_FAIL_STAGE": stage,
                                     "CI_TEST_FAIL_CODE": str(exit_code)})
    assert result.returncode == exit_code
    assert len(calls()) == count
    assert calls()[-1]["args"][0 if stage == "runner" else 1] == (
        "scripts/run_tests.py" if stage == "runner" else stage
    )


def test_relative_destination_is_relative_to_repository_not_caller(wrapper):
    root, outside, _, run, calls = wrapper
    relative = "evidence directory/new run"
    result = run(relative)
    assert result.returncode == 0, result.stderr
    runner = calls()[-1]
    destination = Path(runner["cwd"]) / runner["args"][-1]
    assert destination == root / relative
    assert destination != outside / relative


def test_default_destination_uses_unique_ignored_repository_paths(wrapper):
    root, _, _, run, calls = wrapper
    for _ in range(2):
        result = run()
        assert result.returncode == 0, result.stderr
    destinations = [item["args"][-1] for item in calls() if item["args"][0] == "scripts/run_tests.py"]
    assert len(set(destinations)) == 2
    assert all(path.startswith("build/evidence/ci/") for path in destinations)
    assert all(item["cwd"] == str(root) for item in calls())


@pytest.mark.parametrize("secret", [None, ""])
def test_missing_secret_has_clear_diagnostic_and_runs_no_stage(wrapper, secret):
    root, _, environment, run, calls = wrapper
    environment = dict(environment)
    if secret is None:
        environment.pop("DJANGO_SECRET_KEY", None)
    else:
        environment["DJANGO_SECRET_KEY"] = secret
    result = run(root / "fresh", env=environment)
    assert result.returncode == 2
    assert "Export DJANGO_SECRET_KEY with a test-only value" in result.stderr
    assert "Traceback" not in result.stderr and calls() == []
