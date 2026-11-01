"""Report F1-F4 coverage and fail closed when the quality gate is unmet."""

import argparse
import json
import sys
from pathlib import Path

MODULES = ("accounts", "complaints", "routing", "workflow")
MIN_STATEMENTS = 10
LINE_TARGET = 70
BRANCH_TARGET = 60


def summarize(report):
    if report.get("meta", {}).get("branch_coverage") is not True:
        raise ValueError("report has no branch coverage; rerun the documented test command")
    files = report["files"]
    if not isinstance(files, dict):
        raise ValueError("files must be an object")
    rows = []
    for module in MODULES:
        summaries = [
            entry["summary"]
            for name, entry in files.items()
            if name.replace("\\", "/").startswith(module + "/")
        ]
        totals = {key: 0 for key in (
            "num_statements", "covered_lines", "num_branches", "covered_branches"
        )}
        for summary in summaries:
            for key in totals:
                value = summary[key]
                if type(value) is not int or value < 0:
                    raise ValueError(f"{module}: {key} must be a nonnegative integer")
                totals[key] += value
            if (summary["covered_lines"] > summary["num_statements"]
                    or summary["covered_branches"] > summary["num_branches"]):
                raise ValueError(f"{module}: covered counts exceed total counts")
        statements = totals["num_statements"]
        branches = totals["num_branches"]
        line = 100 * totals["covered_lines"] / statements if statements else None
        branch = 100 * totals["covered_branches"] / branches if branches else None
        if not summaries:
            status = "NO DATA"
        elif statements < MIN_STATEMENTS:
            status = "PLACEHOLDER"
        elif branch is None:
            status = "NO BRANCH DATA"
        elif line < LINE_TARGET or branch < BRANCH_TARGET:
            status = "FAIL"
        else:
            status = "PASS"
        rows.append((module, statements, line, branch, status))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="?", default="coverage.json", type=Path)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        rows = summarize(report)
    except FileNotFoundError:
        print(f"ERROR: {args.report} is missing. Run python scripts/run_tests.py.", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"ERROR: invalid coverage report: {error}", file=sys.stderr)
        return 2
    print(f'{"Module":<14} {"Statements":>10} {"Line":>10} {"Branch":>10}  Status')
    for module, statements, line, branch, status in rows:
        line_text = f"{line:.2f}%" if line is not None else "N/A"
        branch_text = f"{branch:.2f}%" if branch is not None else "N/A"
        print(f"{module:<14} {statements:>10} {line_text:>10} {branch_text:>10}  {status}")
    passed = all(row[-1] == "PASS" for row in rows)
    print(f"\nTargets: line >= {LINE_TARGET}%; branch >= {BRANCH_TARGET}% per module.")
    print(f"Fewer than {MIN_STATEMENTS} statements: PLACEHOLDER (heuristic, not feature acceptance).")
    print("Coverage gate: " + ("PASS" if passed else "FAIL; incomplete/under-target modules remain."))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
