"""Deterministic CI failure and dependency-gate contracts."""
from types import SimpleNamespace
import subprocess
from pathlib import Path

import pytest

from scripts import ci_environment, run_tests


def test_current_checks_are_explicit_and_f4_is_reported_blocked(tmp_path):
    paths, state = run_tests.integration_selection(tmp_path)
    assert paths == list(run_tests.CURRENT_INTEGRATIONS)
    assert "BLOCKED" in state
    assert "not F4 acceptance" in state


@pytest.mark.parametrize("installed,required", [(True, False), (False, True), (True, True)])
def test_f4_gate_never_filters_missing_test_files(tmp_path, installed, required):
    if installed:
        (tmp_path / "workflow").mkdir()
        (tmp_path / "workflow/notifications.py").touch()
    paths, state = run_tests.integration_selection(tmp_path, required)
    assert paths == [*run_tests.CURRENT_INTEGRATIONS, *run_tests.F4_INTEGRATIONS]
    assert state == "required"
    # They are deliberately absent: pytest must fail, not silently remove them.
    assert not (tmp_path / paths[-1]).exists()


def test_synthetic_deployment_replaces_secrets_and_transport_config():
    env = ci_environment.synthetic_environment({"DJANGO_SECRET_KEY": "PRIVATE",
        "DJANGO_SMTP_PASSWORD": "PRIVATE", "DJANGO_DB_ENGINE": "postgresql",
        "DJANGO_SETTINGS_MODULE": "private.settings", "DJANGO_DEBUG": "True"})
    assert "PRIVATE" not in env.values()
    assert env["DJANGO_MAIL_BACKEND"] == "smtp"
    assert env["DJANGO_DEBUG"] == "False"
    assert env["DJANGO_DB_ENGINE"] == "sqlite"
    assert env["DJANGO_SECURE_SSL_REDIRECT"] == "True"
    assert env["DJANGO_SESSION_COOKIE_SECURE"] == env["DJANGO_CSRF_COOKIE_SECURE"] == "True"
    assert env["DJANGO_SMTP_USE_TLS"] == "True"
    assert len(env["DJANGO_SECRET_KEY"]) >= 50


@pytest.mark.parametrize("failure,expected_calls", [(0, 2), (7, 1)])
def test_preflight_propagates_command_failure(tmp_path, monkeypatch, failure, expected_calls):
    monkeypatch.setattr(ci_environment, "ROOT", tmp_path)
    monkeypatch.setattr(ci_environment.compileall, "compile_dir", lambda *a, **k: True)
    monkeypatch.setattr(ci_environment.compileall, "compile_file", lambda *a, **k: True)
    calls = []
    def execute(command, **kwargs):
        calls.append(command)
        assert kwargs["check"] is False
        return SimpleNamespace(returncode=failure)
    monkeypatch.setattr(ci_environment.subprocess, "run", execute)
    assert ci_environment.main() == failure
    assert len(calls) == expected_calls


def test_real_pytest_collects_default_and_explicit_checks_exactly_once(tmp_path):
    (tmp_path / "test_default.py").write_text("def test_default(): pass\n")
    folder = tmp_path / "integration_checks"
    folder.mkdir()
    (folder / "anonymous_escalation.py").write_text("def test_explicit(): pass\n")
    command = run_tests.pytest_command(["integration_checks/anonymous_escalation.py"])
    # This temporary two-file fixture is not a Django project.
    result = subprocess.run(command + ["--collect-only", "--no-cov", "-p", "no:django", "-q"],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 tests collected" in result.stdout
    assert result.stdout.count("::test_default") == 1
    assert result.stdout.count("::test_explicit") == 1


def test_automation_uses_canonical_gates_without_failure_suppression():
    root = Path(__file__).resolve().parent
    workflow = (root / ".github/workflows/evidence-recovery.yml").read_text()
    assert "branches: [Main, 'integration/**', 'feature/**', 'fix/**']" in workflow
    assert "branches: [Main]" in workflow
    assert "paths:" not in workflow
    assert workflow.count("sh scripts/ci_checks.sh") == 2
    assert "postgres:17.6" in workflow
    assert "SCMS_CI_REQUIRE_F4:" in workflow
    assert "continue-on-error" not in workflow
    for name in ("anonymous-recovery.yml", "q04-harness.yml"):
        specialized = (root / ".github/workflows" / name).read_text()
        assert "workflow_dispatch:" in specialized
        assert "pull_request:" not in specialized and "push:" not in specialized
    jenkins = (root / "Jenkinsfile").read_text()
    assert "sh scripts/ci_checks.sh" in jenkins
    assert "SCMS_CI_DATABASE_ISOLATED = '1'" in jenkins
    assert "${BUILD_NUMBER}.sqlite3" in jenkins
