"""Review-packet metadata/commands are checked as well as runner stdout."""
import json
from pathlib import Path

import pytest

from scripts import check_evidence_redaction as check


@pytest.mark.parametrize("filename,value", [
    ("browser/command.json", "/Users/synthetic/project/manage.py"),
    ("browser/result.json", "/home/synthetic/venv/bin/python"),
    ("REPRODUCE.md", "/Users/synthetic/.private/actors.json"),
    ("browser/command.json", r"C:\Users\synthetic\project\manage.py"),
    ("browser/result.json", "/private/tmp/scms-disposable/source"),
    ("REPRODUCE.md", "/tmp/scms-disposable/source"),
])
def test_metadata_and_reproduction_leaks_are_detected_without_echoing_them(tmp_path, filename, value):
    path = tmp_path / "docs/evidence" / check.PACKETS[0] / filename
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"command": value}) if path.suffix == ".json" else value)
    assert check.violations(tmp_path) == [(path.relative_to(tmp_path).as_posix(), 1)]
    assert value not in repr(check.violations(tmp_path))


def test_redacted_metadata_and_portable_reproduction_are_allowed(tmp_path):
    folder = tmp_path / "docs/evidence" / check.PACKETS[0]
    folder.mkdir(parents=True)
    (folder / "command.json").write_text(json.dumps({"cwd": "<repo>", "python": "<venv>/bin/python"}))
    (folder / "REPRODUCE.md").write_text('Set Q04_PRIVATE_STATE=/absolute/private/state; use "$Q04_PRIVATE_STATE".')
    assert check.violations(tmp_path) == []


def test_committed_review_packets_have_no_unredacted_local_paths():
    assert check.violations() == []


def test_review_packet_metadata_still_parses_as_json():
    for packet in check.PACKETS:
        for path in (check.ROOT / "docs/evidence" / packet).rglob("*.json"):
            json.loads(path.read_text())
