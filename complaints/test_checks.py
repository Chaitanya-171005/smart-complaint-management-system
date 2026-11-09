"""Check registration, invalid configuration and real management-command exits."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings as django_settings
from django.core.checks import Tags, run_checks

from complaints.checks import valid_evidence_byte_limit


@pytest.mark.parametrize("value", [5_000_000, 5 * 1024 * 1024])
def test_supported_limits_pass_registered_system_check(settings, value):
    settings.EVIDENCE_MAX_BYTES = value
    assert valid_evidence_byte_limit(value)
    assert not [error for error in run_checks(tags=[Tags.files]) if error.id == "complaints.E001"]


@pytest.mark.parametrize("value", [0, -1, 1, 5_000_001, None, True, False, 5_000_000.0,
                                  "5000000", "invalid", ""])
def test_invalid_limits_fail_registered_system_check(settings, value):
    settings.EVIDENCE_MAX_BYTES = value
    errors = [error for error in run_checks(tags=[Tags.files]) if error.id == "complaints.E001"]
    assert len(errors) == 1
    assert errors[0].is_serious()
    assert errors[0].obj == "EVIDENCE_MAX_BYTES"
    assert "5000000" in errors[0].msg and "5242880" in errors[0].msg


@pytest.mark.parametrize("value,success", [("5000000", True), ("5242880", True),
                                          ("1", False), ("invalid", False), ("", False)])
def test_manage_check_reads_environment_and_exits_before_serving(value, success):
    env = {**os.environ, "EVIDENCE_MAX_BYTES": value,
           "DJANGO_SECRET_KEY": django_settings.SECRET_KEY}
    result = subprocess.run(
        [sys.executable, "manage.py", "check", "--tag", "files"],
        cwd=Path(__file__).resolve().parents[1], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20,
    )
    assert (result.returncode == 0) is success, result.stdout
    if not success:
        assert "complaints.E001" in result.stdout
        assert "ValueError" not in result.stdout


@pytest.mark.parametrize("value", ["1", "invalid"])
def test_runserver_aborts_on_invalid_limit_before_serving(value):
    env = {**os.environ, "EVIDENCE_MAX_BYTES": value,
           "DJANGO_SECRET_KEY": django_settings.SECRET_KEY}
    result = subprocess.run(
        [sys.executable, "manage.py", "runserver", "127.0.0.1:0", "--noreload"],
        cwd=Path(__file__).resolve().parents[1], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert "complaints.E001" in result.stdout
    assert "Starting development server" not in result.stdout
