"""Run tests and the coverage gate; write sanitized evidence to build/evidence.

Use --evidence-dir explicitly to refresh a committed evidence directory.
"""

import argparse
import json
import os
# The CI runner invokes a fixed argv list of repository-controlled commands.
import subprocess  # nosec B404
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = Path("build/evidence")
CURRENT_INTEGRATIONS = ("integration_checks/anonymous_escalation.py",
                        "integration_checks/anonymous_recovery.py")
F4_INTEGRATIONS = ("integration_checks/lifecycle_f3.py", "integration_checks/resolution_f3.py",
                   "integration_checks/f3_f4_handoff.py", "workflow/test_retired_anonymous_routes.py")


def integration_selection(root, require_f4=False):
    installed = (root / "workflow/notifications.py").is_file()
    enabled = installed or require_f4
    paths = list(CURRENT_INTEGRATIONS)
    if enabled:
        paths.extend(F4_INTEGRATIONS)
    state = "required" if enabled else "BLOCKED: F4 not installed; this run is not F4 acceptance"
    return paths, state


def pytest_command(integrations):
    # Pytest directory collection can otherwise discard explicitly supplied
    # nonstandard filenames when '.' is also requested. Include their patterns.
    patterns = "tests.py test_*.py " + " ".join(Path(p).name for p in integrations)
    return [sys.executable, "-m", "pytest", ".", *integrations, "-o", "python_files=" + patterns]


def sanitize(text):
    # Subprocesses may print either the configured spelling or the resolved
    # path (e.g. Homebrew's /opt symlink or a symlinked virtual environment).
    # Keep both; resolving alone leaves the configured path in shared evidence.
    paths = {}
    for root, replacement in (
        (ROOT, "<repo>"), (Path(sys.prefix), "<venv>"), (Path.home(), "<home>"),
    ):
        for spelling in (str(root), str(root.resolve())):
            paths.setdefault(spelling, replacement)
    # Replace nested venv/repo paths before their enclosing home directory.
    for path, replacement in sorted(paths.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(path, replacement)
    return text


def run(command):
    # Call sites pass fixed repository-controlled Python argv without a shell.
    result = subprocess.run(  # nosec B603
        command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    return result.returncode, sanitize(result.stdout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-dir", type=Path, default=DEFAULT_EVIDENCE,
        help="Output directory (default: ignored build/evidence); pass docs/evidence/<task> to refresh committed evidence.",
    )
    args = parser.parse_args(argv)
    flag = os.environ.get("SCMS_CI_REQUIRE_F4", "0")
    if flag not in {"0", "1"}:
        parser.error("SCMS_CI_REQUIRE_F4 must be 0 or 1")
    integrations, f4_state = integration_selection(ROOT, flag == "1")
    print("Explicit integration checks: " + ", ".join(integrations), flush=True)
    print("F4 dependency gate: " + f4_state, flush=True)
    evidence = args.evidence_dir
    if not evidence.is_absolute():
        evidence = ROOT / evidence
    # Capture source state before generated evidence changes the working tree.
    revision_code, revision = run(["git", "rev-parse", "HEAD"])
    status_code, status = run(["git", "status", "--porcelain", "--untracked-files=all"])
    evidence.mkdir(parents=True, exist_ok=True)
    # Never reuse stale coverage from an earlier successful test execution.
    (ROOT / "coverage.json").unlink(missing_ok=True)
    # Explicit files extend default discovery; they must never replace the suite.
    test_code, test_output = run(pytest_command(integrations))
    (evidence / "pytest.txt").write_text(test_output, encoding="utf-8")
    print(test_output, end="")
    gate_code, gate_output = run([sys.executable, "scripts/coverage_summary.py"])
    (evidence / "coverage-summary.txt").write_text(gate_output, encoding="utf-8")
    print(gate_output, end="")
    metadata = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_revision": revision.strip() if revision_code == 0 else "unavailable",
        "working_tree_dirty": bool(status.strip()) if status_code == 0 else None,
        "working_tree_status": status.splitlines() if status_code == 0 else None,
        "source_note": "source_revision identifies HEAD before the run; working_tree_status lists additional local changes tested. Coverage is not feature acceptance.",
        "pytest_exit_code": test_code,
        "coverage_gate_exit_code": gate_code,
        "explicit_integrations": integrations,
        "f4_dependency_gate": f4_state,
    }
    (evidence / "run.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    # Test failures and gate failures stay failures; recording evidence never hides them.
    return test_code if test_code else gate_code


if __name__ == "__main__":
    raise SystemExit(main())
