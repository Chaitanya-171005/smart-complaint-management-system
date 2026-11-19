"""Check current review packets for unredacted local path spellings.

This is output-redaction hygiene, not filesystem path containment. The check
does not confer permission to access files or change runtime release settings.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PACKETS = ("final-main-f2-20261117", "atul-local-20261118")
LOCAL_PATH = re.compile(
    r"/(?:Users|home)/[^/\s\"'<>]+(?:/[^\s\"'<>]*)?"
    r"|[A-Za-z]:[\\/]+Users[\\/]+[^\s\"'<>]+"
    r"|/(?:private/)?tmp/scms-[^\s\"'<>]+"
)


def violations(root=ROOT):
    """Return filenames/line numbers only; never echo the private path itself."""
    found = []
    for packet in PACKETS:
        folder = root / "docs/evidence" / packet
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix in {".json", ".md", ".txt"}:
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if LOCAL_PATH.search(line):
                        found.append((path.relative_to(root).as_posix(), number))
    return found


def main():
    found = violations()
    for path, number in found:
        print(f"Unredacted local path: {path}:{number}")
    print(f"Review evidence output-redaction check: {'FAIL' if found else 'PASS'}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
