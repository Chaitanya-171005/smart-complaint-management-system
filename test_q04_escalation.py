"""Benchmark correctness and isolation, without a live PostgreSQL service."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from scripts import q04_escalation as benchmark


def test_sqlite_database_is_new_and_removed_on_failure():
    with pytest.raises(RuntimeError):
        with benchmark.disposable_database("sqlite") as env:
            path = Path(env["DJANGO_DB_PATH"])
            assert not path.exists()
            path.write_text("task-owned")
            raise RuntimeError("Synthetic failure")
    assert not path.exists() and not path.parent.exists()


def test_postgres_refused_without_disposable_cluster_acknowledgement(monkeypatch):
    monkeypatch.delenv("Q04_DISPOSABLE_POSTGRES", raising=False)
    with pytest.raises(ValueError, match="ownership"):
        with benchmark.disposable_database("postgresql"):
            pytest.fail("Must not connect")


def test_postgres_requires_explicit_endpoint(monkeypatch):
    monkeypatch.setenv("Q04_DISPOSABLE_POSTGRES", "1")
    monkeypatch.delenv("PGHOST", raising=False)
    with pytest.raises(ValueError, match="PGHOST"):
        with benchmark.disposable_database("postgresql"):
            pytest.fail("Must not connect")


@pytest.mark.parametrize("creation_fails", [False, True])
def test_postgres_cleanup_only_drops_a_database_created_by_this_call(monkeypatch, creation_fails):
    import psycopg
    monkeypatch.setenv("Q04_DISPOSABLE_POSTGRES", "1")
    monkeypatch.setenv("PGHOST", "/synthetic-private-socket")
    monkeypatch.setenv("PGPORT", "5432")
    monkeypatch.setenv("PGUSER", "synthetic")
    admin = Mock()
    if creation_fails:
        admin.execute.side_effect = RuntimeError("Synthetic CREATE failure")
    connect = Mock(return_value=admin)
    monkeypatch.setattr(psycopg, "connect", connect)
    try:
        with benchmark.disposable_database("postgresql") as env:
            assert env["DJANGO_DB_NAME"].startswith("scms_q04_")
            raise ValueError("Synthetic body failure")
    except (ValueError, RuntimeError):
        pass
    connect.assert_called_once_with(dbname="postgres", autocommit=True)
    queries = [str(call.args[0]) for call in admin.execute.call_args_list]
    assert "CREATE DATABASE" in queries[0]
    assert len(queries) == (1 if creation_fails else 2)
    if not creation_fails:
        assert "DROP DATABASE" in queries[1] and "FORCE" not in queries[1]
    admin.close.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_small_benchmark_checks_history_controls_repeat_and_interruption():
    from complaints.models import Complaint
    from routing.models import RoutingDecision
    options = dict(count=6, seed=171005, sla_minutes=120, interval_minutes=60, maximum_level=2)
    eligible, controls = benchmark.seed_dataset(**options)
    assert len(eligible) == 6 and len(controls) == 5
    assert RoutingDecision.objects.count() == Complaint.objects.count() == 11
    result = benchmark.measure(eligible, controls)
    assert result["processed"] == result["new_history"] == 6
    assert result["repeat_processed"] == result["duplicate_history_groups"] == 0
    assert result["notification_dependency"] == "F4_NOT_INSTALLED"
    assert result["timed_queries"] > 0 and result["elapsed_seconds"] > 0
    result = benchmark.interruption_check(SimpleNamespace(**options), timezone.now())
    assert result["committed_before_interrupt"] == 3
    assert result["retry_processed"] == 5
    assert result["final_history"] == 8
