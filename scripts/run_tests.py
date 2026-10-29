"""Run tests and the coverage gate; write sanitized evidence to build/evidence.

Use --evidence-dir explicitly to refresh a committed evidence directory.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = Path("build/evidence")


def sanitize(text):
    paths = {
        str(ROOT): "<repo>",
        str(Path(sys.prefix).resolve()): "<venv>",
        str(Path.home()): "<home>",
    }
    for path, replacement in sorted(paths.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(path, replacement)
    return text


def run(command):
    result = subprocess.run(
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
    evidence = args.evidence_dir
    if not evidence.is_absolute():
        evidence = ROOT / evidence
    # Capture source state before generated evidence changes the working tree.
    revision_code, revision = run(["git", "rev-parse", "HEAD"])
    status_code, status = run(["git", "status", "--porcelain", "--untracked-files=all"])
    evidence.mkdir(parents=True, exist_ok=True)
    # Never reuse stale coverage from an earlier successful test execution.
    (ROOT / "coverage.json").unlink(missing_ok=True)
    test_code, test_output = run([sys.executable, "-m", "pytest"])
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
    }
    (evidence / "run.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    # Test failures and gate failures stay failures; recording evidence never hides them.
    return test_code if test_code else gate_code


if __name__ == "__main__":
    raise SystemExit(main())
