"""Exercise the coverage CLI's real exit codes and failure diagnostics."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "scripts" / "coverage_summary.py"
MODULES = ("accounts", "complaints", "routing", "workflow")


def make_report(lines=80, branches=8):
    return {
        "meta": {"branch_coverage": True},
        "files": {
            f"{module}/services.py": {
                "summary": {
                    "num_statements": 100, "covered_lines": lines,
                    "num_branches": 10, "covered_branches": branches,
                }
            }
            for module in MODULES
        },
    }


def execute(tmp_path, report):
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        cwd=tmp_path, capture_output=True, text=True,
    )


def test_gate_passes_at_exact_targets(tmp_path):
    result = execute(tmp_path, make_report(lines=70, branches=6))
    assert result.returncode == 0
    assert "Coverage gate: PASS" in result.stdout
    assert "70.00%" in result.stdout and "60.00%" in result.stdout


@pytest.mark.parametrize("lines,branches", [(69, 10), (100, 5)])
def test_one_under_target_module_fails_gate(tmp_path, lines, branches):
    report = make_report()
    summary = report["files"]["workflow/services.py"]["summary"]
    summary.update(covered_lines=lines, covered_branches=branches)
    result = execute(tmp_path, report)
    assert result.returncode == 1
    assert "Coverage gate: FAIL" in result.stdout


def test_placeholder_is_not_reported_as_pass(tmp_path):
    report = make_report()
    report["files"]["complaints/services.py"]["summary"] = {
        "num_statements": 6, "covered_lines": 5,
        "num_branches": 0, "covered_branches": 0,
    }
    result = execute(tmp_path, report)
    assert result.returncode == 1
    assert "PLACEHOLDER" in result.stdout
    assert "N/A" in result.stdout


def test_missing_module_fails_gate(tmp_path):
    report = make_report()
    del report["files"]["routing/services.py"]
    result = execute(tmp_path, report)
    assert result.returncode == 1
    assert "NO DATA" in result.stdout


def test_no_branches_does_not_claim_branch_target(tmp_path):
    report = make_report()
    report["files"]["accounts/services.py"]["summary"].update(
        num_branches=0, covered_branches=0
    )
    result = execute(tmp_path, report)
    assert result.returncode == 1
    assert "NO BRANCH DATA" in result.stdout


def test_missing_report_has_clear_error(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "missing" in result.stderr
    assert "Traceback" not in result.stderr


def test_malformed_json_has_clear_error(tmp_path):
    path = tmp_path / "coverage.json"
    path.write_text("{broken", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "invalid coverage report" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "change",
    [
        lambda report: report["meta"].update(branch_coverage=False),
        lambda report: report["files"]["accounts/services.py"]["summary"].pop("num_branches"),
        lambda report: report["files"]["accounts/services.py"]["summary"].update(covered_lines=101),
        lambda report: report["files"]["accounts/services.py"]["summary"].update(num_statements=-1),
    ],
)
def test_invalid_report_fails_closed(tmp_path, change):
    report = make_report()
    change(report)
    result = execute(tmp_path, report)
    assert result.returncode == 2
    assert "invalid coverage report" in result.stderr
    assert "Traceback" not in result.stderr


def test_import_does_not_read_report_or_exit(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "import runpy,sys; runpy.run_path(sys.argv[1])", str(SCRIPT)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert result.stdout == "" and result.stderr == ""


def test_windows_separators_are_supported(tmp_path):
    report = make_report()
    report["files"] = {name.replace("/", "\\"): value for name, value in report["files"].items()}
    assert execute(tmp_path, report).returncode == 0
