"""Regression checks for evidence isolation and truthful test-run metadata."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import run_tests


@pytest.mark.parametrize("target", [None, "docs/evidence/b07"])
@pytest.mark.parametrize("test_code,gate_code,expected", [(0, 0, 0), (0, 1, 1), (3, 2, 3)])
def test_runner_preserves_old_evidence_and_propagates_failures(tmp_path, monkeypatch, target, test_code, gate_code, expected):
    old = tmp_path / "docs/evidence/e02/pytest.txt"
    old.parent.mkdir(parents=True)
    old.write_text("original E02 evidence")
    (tmp_path / "coverage.json").write_text("stale report")
    monkeypatch.setattr(run_tests, "ROOT", tmp_path)
    calls = []

    def run(command):
        calls.append(command)
        if command[:2] == ["git", "rev-parse"]:
            return 0, "test-source-revision\n"
        if command[:2] == ["git", "status"]:
            return 0, " M complaints/forms.py\n"
        if command[1:3] == ["-m", "pytest"]:
            assert not (tmp_path / "coverage.json").exists()
            return test_code, "actual test output\n"
        return gate_code, "actual gate output\n"

    monkeypatch.setattr(run_tests, "run", run)
    args = [] if target is None else ["--evidence-dir", target]
    assert run_tests.main(args) == expected
    destination = tmp_path / (target or "build/evidence")
    assert old.read_text() == "original E02 evidence"
    assert (destination / "pytest.txt").read_text() == "actual test output\n"
    assert (destination / "coverage-summary.txt").read_text() == "actual gate output\n"
    metadata = json.loads((destination / "run.json").read_text())
    assert metadata["source_revision"] == "test-source-revision"
    assert metadata["working_tree_dirty"] is True
    assert metadata["working_tree_status"] == [" M complaints/forms.py"]
    assert metadata["pytest_exit_code"] == test_code
    assert metadata["coverage_gate_exit_code"] == gate_code
    assert len(calls) == 4


@pytest.mark.parametrize("status_code,status,dirty", [(0, "", False), (128, "fatal", None)])
def test_source_state_is_recorded_before_generated_files(tmp_path, monkeypatch, status_code, status, dirty):
    monkeypatch.setattr(run_tests, "ROOT", tmp_path)

    def run(command):
        if command[:2] == ["git", "rev-parse"]:
            return status_code, "HEAD\n"
        if command[:2] == ["git", "status"]:
            assert not (tmp_path / "build/evidence").exists()
            return status_code, status
        return 0, ""

    monkeypatch.setattr(run_tests, "run", run)
    assert run_tests.main([]) == 0
    metadata = json.loads((tmp_path / "build/evidence/run.json").read_text())
    assert metadata["working_tree_dirty"] is dirty
    assert metadata["source_revision"] == ("HEAD" if status_code == 0 else "unavailable")


def test_real_subprocess_output_is_sanitized():
    code, output = run_tests.run([
        sys.executable, "-c", "import os,sys;from pathlib import Path;print(os.getcwd());print(sys.prefix);print(Path.home())"
    ])
    assert code == 0
    assert output.splitlines() == ["<repo>", "<venv>", "<home>"]


def test_default_evidence_directory_is_ignored_by_git():
    result = subprocess.run(["git", "check-ignore", "build/evidence/run.json"],
                            cwd=Path(__file__).resolve().parent, capture_output=True, text=True)
    assert result.returncode == 0


def test_runner_help_documents_explicit_refresh():
    script = Path(__file__).resolve().parent / "scripts/run_tests.py"
    result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "build/evidence" in result.stdout
    assert "--evidence-dir" in result.stdout
