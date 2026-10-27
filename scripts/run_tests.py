"""Run tests, enforce module coverage, and record sanitized E02 evidence."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "e02"


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


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    # Never reuse stale coverage from an earlier successful test execution.
    (ROOT / "coverage.json").unlink(missing_ok=True)
    test_code, test_output = run([sys.executable, "-m", "pytest"])
    (EVIDENCE / "pytest.txt").write_text(test_output, encoding="utf-8")
    print(test_output, end="")
    gate_code, gate_output = run([sys.executable, "scripts/coverage_summary.py"])
    (EVIDENCE / "coverage-summary.txt").write_text(gate_output, encoding="utf-8")
    print(gate_output, end="")
    revision_code, revision = run(["git", "rev-parse", "HEAD"])
    metadata = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_revision": revision.strip() if revision_code == 0 else "unavailable",
        "source_note": "Includes the working-tree corrections committed with this evidence.",
        "pytest_exit_code": test_code,
        "coverage_gate_exit_code": gate_code,
    }
    (EVIDENCE / "run.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    # Test failures and gate failures stay failures; recording evidence never hides them.
    return test_code if test_code else gate_code


if __name__ == "__main__":
    raise SystemExit(main())
