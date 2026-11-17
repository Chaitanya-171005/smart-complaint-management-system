"""Cron deployment and command failure contracts; no Docker or SMTP is started."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.utils import timezone

from routing.escalation import run_escalation
from workflow.models import ComplaintHistory


@pytest.mark.django_db(transaction=True)
def test_two_scheduler_workers_do_not_duplicate_escalation(routing_configuration, complaint_factory):
    now = timezone.now()
    complaint = complaint_factory(anonymous=True, due_at=now)
    barrier = Barrier(2)

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            run = run_escalation(now=now)
            return run.escalated, run.failed
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sum(item[0] for item in results) == 1
    assert sum(item[1] for item in results) == 0
    complaint.refresh_from_db()
    assert complaint.escalation_level == 1
    assert ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id,
                                           event_type="ESCALATED").count() == 1


@pytest.mark.django_db(transaction=True)
def test_command_repeated_tick_is_noop_at_same_policy_interval(routing_configuration, complaint_factory):
    now = timezone.now()
    complaint_factory(anonymous=True, due_at=now - timedelta(seconds=1))
    output = StringIO()
    with patch("django.utils.timezone.now", return_value=now):
        call_command("run_escalation", stdout=output)
        call_command("run_escalation", stdout=output)
    assert "escalated=1" in output.getvalue()
    assert "examined=0 escalated=0" in output.getvalue()


@pytest.mark.parametrize("with_run", [False, True])
def test_scheduler_failure_traceback_suppresses_private_exception(with_run):
    import traceback
    from types import SimpleNamespace

    error = RuntimeError("PRIVATE_REFERENCE_EXCEPTION")
    if with_run:
        error.escalation_run = SimpleNamespace(pk=1, status="FAILED", examined=0,
                                             escalated=0, skipped=0, failed=0)
    with patch("routing.management.commands.run_escalation.run_escalation", side_effect=error):
        with pytest.raises(CommandError) as caught:
            call_command("run_escalation", stdout=StringIO())
    assert "PRIVATE_REFERENCE_EXCEPTION" not in "".join(traceback.format_exception(caught.value))


def test_scheduled_service_and_cron_are_one_shot_and_do_not_enable_f4():
    root = Path(__file__).resolve().parent.parent
    text = (root / "docker-compose.yml").read_text()
    task = text.split("  scheduled-task:", 1)[1].split("\nvolumes:", 1)[0]
    assert 'profiles: [scheduled]' in task
    assert 'entrypoint: ["python", "manage.py"]' in task
    assert 'command: ["run_escalation"]' in task
    assert 'restart: "no"' in task
    assert 'disable: true' in task
    assert "ports:" not in task and "depends_on:" not in task
    assert "environment: *app_environment" in task
    lines = (root / "deploy/escalation.cron.example").read_text().splitlines()
    active = [line for line in lines if line.strip() and not line.startswith("#")]
    assert len(active) == 1
    assert "--rm --no-deps scheduled-task run_escalation" in active[0]
    assert "deliver_notifications" not in active[0] and "auto_close" not in active[0]
