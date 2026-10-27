"""Report line and branch coverage separately for each SCMS module."""

import json
from pathlib import Path

report = json.loads(Path("coverage.json").read_text())

print(f'{"Module":<14} {"Line coverage":>16} {"Branch coverage":>18}')

for module in ("accounts", "complaints", "routing", "workflow"):
    summaries = [
        entry["summary"]
        for name, entry in report["files"].items()
        if name.replace("\\", "/").startswith(module + "/")
    ]

    if not summaries:
        print(f"{module:<14} {'NO DATA':>16} {'NO DATA':>18}")
        continue

    statements = sum(s["num_statements"] for s in summaries)
    covered_lines = sum(s["covered_lines"] for s in summaries)
    branches = sum(s.get("num_branches", 0) for s in summaries)
    covered_branches = sum(s.get("covered_branches", 0) for s in summaries)

    line_result = (
        f"{100 * covered_lines / statements:.2f}%"
        if statements else "N/A"
    )
    branch_result = (
        f"{100 * covered_branches / branches:.2f}%"
        if branches else "N/A (no branches)"
    )

    print(f"{module:<14} {line_result:>16} {branch_result:>18}")

print("\nTargets per implemented module: line >= 70%; branch >= 60%.")
print("Placeholder code and absent branches do not establish feature completion.")
