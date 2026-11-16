"""Disposable Q04 escalation measurement; prints results only, sends no mail.

SQLite is diagnostic. PostgreSQL requires Q04_DISPOSABLE_POSTGRES=1 and PGHOST,
PGPORT, PGUSER (PGPASSWORD/PGSSLMODE as needed) for an independently provisioned
disposable cluster. Never supply an application database: this runner creates
and later drops ONLY its own UUID-named database, via the postgres maintenance DB.
Policy values are required inputs, not new campus defaults. Seed defaults to
171005. Preparation/migrations/repeat/interruption checks are outside timing.
"""
import argparse
from contextlib import contextmanager
from datetime import timedelta
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import platform
import random
import secrets
import subprocess  # nosec B404 - fixed repository revision lookup only
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def require(condition):
    if not condition:
        raise RuntimeError("Benchmark correctness check failed.")


@contextmanager
def disposable_database(engine):
    if engine == "sqlite":
        with tempfile.TemporaryDirectory(prefix="scms-q04-escalation-") as directory:
            yield {"DJANGO_DB_ENGINE": "sqlite", "DJANGO_DB_PATH": str(Path(directory) / "bench.sqlite3")}
        return
    if os.environ.get("Q04_DISPOSABLE_POSTGRES") != "1":
        raise ValueError("PostgreSQL requires explicit Q04_DISPOSABLE_POSTGRES=1 ownership acknowledgement.")
    if not all(os.environ.get(key) for key in ("PGHOST", "PGPORT", "PGUSER")):
        raise ValueError("Set PGHOST, PGPORT and PGUSER for the disposable cluster.")
    import psycopg
    from psycopg import sql
    name = "scms_q04_" + uuid4().hex
    # Explicit dbname prevents inherited PGDATABASE from selecting application data.
    admin = psycopg.connect(dbname="postgres", autocommit=True)
    owned = False
    try:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        owned = True
        print("Task-owned PostgreSQL database: " + name, file=sys.stderr)
        yield {"DJANGO_DB_ENGINE": "postgresql", "DJANGO_DB_NAME": name,
               "DJANGO_DB_HOST": os.environ["PGHOST"], "DJANGO_DB_PORT": os.environ["PGPORT"],
               "DJANGO_DB_USER": os.environ["PGUSER"],
               "DJANGO_DB_PASSWORD": os.environ.get("PGPASSWORD", "synthetic-local-trust-only")}
    finally:
        try:
            if owned:
                # No FORCE, session termination, volume deletion or caller-supplied name.
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
                print("Removed task-owned PostgreSQL database: " + name, file=sys.stderr)
        finally:
            admin.close()


def seed_dataset(*, count, seed, sla_minutes, interval_minutes, maximum_level, tag="MAIN", at=None):
    """Validated synthetic records with real ID allocation, routing, SLA and history."""
    from django.db import transaction
    from django.utils import timezone
    from accounts.models import Department, Location, User
    from complaints.identifiers import allocate_complaint_id
    from complaints.models import Complaint
    from routing.intake import route_and_prioritize
    from routing.models import Category, EscalationPolicy, RoutingRule, SLAConfiguration
    from workflow.history_service import record_history

    def save(model):
        model.full_clean()
        model.save()
        return model

    rng = random.Random(seed)  # nosec B311 - deterministic synthetic fixtures, not security tokens
    department = save(Department(name=f"Q04 {tag} department"))
    category = save(Category(name=f"Q04 {tag} category"))
    location = save(Location(code=f"Q04-{tag}", block="Synthetic", floor="1", room_area=tag))
    rule = RoutingRule(category=category, location_code=location.code, department=department, precedence=1)
    rule.full_clean(exclude=["scope_key"]); rule.save()
    sla = SLAConfiguration(category=category, priority="LOW", duration_minutes=sla_minutes)
    sla.full_clean(exclude=["scope_key"]); sla.save()
    policy = EscalationPolicy.objects.filter(key="default").first() or EscalationPolicy(key="default")
    policy.default_department = department
    policy.interval_minutes, policy.maximum_level = interval_minutes, maximum_level
    save(policy)
    users = {}
    for role in ("COMPLAINANT", "STAFF", "HEAD"):
        user = User(email=f"q04-{tag.lower()}-{role.lower()}@example.test",
                    full_name=f"Synthetic {role}", role=role,
                    department=department if role != "COMPLAINANT" else None)
        user.set_unusable_password()
        users[role] = save(user)
    anchor = at or timezone.now()
    eligible, controls = [], []
    # Three terminal states, future-due and maximum-level controls.
    specs = [(rng.choice(["ASSIGNED", "IN_PROGRESS", "REOPENED"]), False, False)
             for _ in range(count)] + [(s, False, False) for s in ("RESOLVED", "CLOSED", "REJECTED")]
    specs += [("ASSIGNED", True, False), ("ASSIGNED", False, True)]
    for index, (status, future, maximum) in enumerate(specs):
        due = anchor + timedelta(days=1) if future else (anchor if index == 0 else anchor - timedelta(minutes=1))
        submitted = due - timedelta(minutes=sla_minutes)
        anonymous = index % 2 == 0
        with transaction.atomic():
            public_id = allocate_complaint_id(submitted_at=submitted)
            outcome = route_and_prioritize(complaint_id=public_id, category=category,
                location_code=location.code, indicated_priority="LOW", submitted_at=submitted)
            complaint = Complaint(complaint_id=public_id, category_key=str(category.pk),
                category=category.name, location_code=location.code, block=location.block,
                floor=location.floor, room_area=location.room_area,
                title="Q04_PRIVATE_TITLE", description="Q04_PRIVATE_DESCRIPTION synthetic complaint details.",
                submitted_by=None if anonymous else users["COMPLAINANT"],
                reference_digest=hashlib.sha256(f"synthetic-only-{seed}-{tag}-{index}".encode()).hexdigest()
                    if anonymous else None,
                assignee=users["STAFF"], submitted_at=submitted, **outcome.as_complaint_fields())
            complaint.status = status
            if maximum:
                complaint.is_escalated, complaint.escalation_level = True, maximum_level
            save(complaint)
            record_history(public_id, "SUBMITTED", "ANONYMOUS" if anonymous else "COMPLAINANT",
                           new_state="SUBMITTED", actor=None if anonymous else users["COMPLAINANT"])
            record_history(public_id, "ALLOCATED", "SYSTEM", "SUBMITTED", "ASSIGNED")
        (eligible if index < count else controls).append(complaint.pk)
    return eligible, controls


def snapshot():
    from complaints.models import Complaint
    # Escalation is permitted to change only its flag/level, not these fields.
    return list(Complaint.objects.order_by("pk").values_list("pk", "department_id", "assignee_id",
        "submitted_by_id", "reference_digest", "priority", "status", "due_at", "routing_rule_key",
        "title", "description", "category_key", "category", "location_code", "block", "floor", "room_area"))


def notification_counts():
    from workflow import models
    if not hasattr(models, "NotificationEvent"):
        return None
    return {name: getattr(models, name).objects.count()
            for name in ("NotificationEvent", "Notification", "EmailDelivery")}


def measure(eligible, controls):
    from django.core.management import call_command
    from django.db import connection
    from django.db.models import Count
    from complaints.models import Complaint
    from routing.models import EscalationRun
    from workflow.models import ComplaintHistory
    from routing.escalation import _eligible
    from routing.models import EscalationPolicy
    from routing.models import RoutingDecision
    from django.utils import timezone

    require(_eligible(timezone.now(), EscalationPolicy.objects.get(key="default")).count() == len(eligible))
    before = snapshot()
    routing_before = list(RoutingDecision.objects.order_by("pk").values())
    controls_before = list(Complaint.objects.filter(pk__in=controls).order_by("pk").values_list("pk", "escalation_level"))
    notices_before = notification_counts()
    history_before = ComplaintHistory.objects.filter(event_type="ESCALATED").count()
    queries = 0
    def count_query(execute, sql, params, many, context):
        nonlocal queries
        queries += 1
        return execute(sql, params, many, context)
    output = StringIO()
    with connection.execute_wrapper(count_query):
        started = time.perf_counter()
        call_command("run_escalation", stdout=output, skip_checks=False)
        elapsed = time.perf_counter() - started
    run = EscalationRun.objects.latest("pk")
    require((run.status, run.escalated, run.failed) == ("COMPLETED", len(eligible), 0))
    require(snapshot() == before)
    require(list(RoutingDecision.objects.order_by("pk").values()) == routing_before)
    require(Complaint.objects.filter(pk__in=eligible, escalation_level=1, is_escalated=True).count() == len(eligible))
    require(list(Complaint.objects.filter(pk__in=controls).order_by("pk").values_list("pk", "escalation_level")) == controls_before)
    added_history = ComplaintHistory.objects.filter(event_type="ESCALATED").count() - history_before
    duplicates = ComplaintHistory.objects.filter(event_type="ESCALATED").values("complaint_ref").annotate(n=Count("pk")).filter(n__gt=1).count()
    require(added_history == len(eligible) and duplicates == 0)
    notices_after = notification_counts()
    notice_delta = None if notices_after is None else {k: notices_after[k]-notices_before[k] for k in notices_after}
    if notice_delta is not None:
        # Anonymous => Head + assignee; authenticated additionally includes owner.
        require(notice_delta == {"NotificationEvent": len(eligible),
            "Notification": 2*len(eligible)+len(eligible)//2,
            "EmailDelivery": 2*len(eligible)+len(eligible)//2})
        from workflow.models import NotificationEvent
        for event in NotificationEvent.objects.filter(kind="ESCALATED").values():
            text = str(event)
            require("Q04_PRIVATE" not in text and "synthetic-only" not in text)
    # Repeat at the same logical instant: a slow batch must not confuse a
    # legitimately elapsed next-level interval with duplicate processing.
    from routing.escalation import run_escalation
    repeated = run_escalation(now=run.started_at)
    require(repeated.escalated == repeated.failed == 0)
    require(ComplaintHistory.objects.filter(event_type="ESCALATED").count() == history_before + added_history)
    require(notification_counts() == notices_after)
    return {"eligible": len(eligible), "controls": len(controls), "elapsed_seconds": elapsed,
        "complaints_per_second": len(eligible)/elapsed, "timed_queries": queries,
        "processed": run.escalated, "errors": run.failed, "new_history": added_history,
        "duplicate_history_groups": duplicates, "notification_delta": notice_delta,
        "notification_dependency": "F4_NOT_INSTALLED" if notice_delta is None else "F4_OUTBOX_VERIFIED",
        "repeat_processed": repeated.escalated,
        "logical_start": run.started_at.isoformat(),
        "threshold_comparison": "MET" if elapsed <= 60 else "EXCEEDED"}


def interruption_check(options, at):
    from routing import escalation
    from complaints.models import Complaint
    from workflow.models import ComplaintHistory
    eligible, _ = seed_dataset(count=8, seed=options.seed, sla_minutes=options.sla_minutes,
        interval_minutes=options.interval_minutes, maximum_level=options.maximum_level, tag="INTERRUPT", at=at)
    original = escalation.record_history
    calls = 0
    def interrupt(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise KeyboardInterrupt("Synthetic interruption before history commit")
        return original(*args, **kwargs)
    try:
        with patch.object(escalation, "record_history", interrupt):
            escalation.run_escalation(now=at)
    except KeyboardInterrupt as error:
        failed = error.escalation_run
    else:
        raise AssertionError("Interruption was not exercised")
    require((failed.escalated, failed.failed, failed.status) == (3, 1, "FAILED"))
    retry = escalation.run_escalation(now=at)
    require(retry.failed == 0 and retry.escalated == 5)
    require(Complaint.objects.filter(pk__in=eligible, escalation_level=1).count() == 8)
    require(ComplaintHistory.objects.filter(complaint_ref__in=Complaint.objects.filter(pk__in=eligible)
        .values_list("complaint_id", flat=True), event_type="ESCALATED").count() == 8)
    return {"committed_before_interrupt": 3, "rolled_back": 1, "retry_processed": 5,
            "final_history": 8, "kind": "simulated KeyboardInterrupt; not process-kill/power-loss"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", choices=["sqlite", "postgresql"], default="sqlite")
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=171005)
    for name in ("sla-minutes", "interval-minutes", "maximum-level"):
        parser.add_argument("--"+name, type=int, required=True)
    options = parser.parse_args(argv)
    if not __debug__:
        parser.error("Do not run correctness verification with Python optimization enabled.")
    if options.count < 1:
        parser.error("count must be positive")
    sys.path.insert(0, str(ROOT))
    try:
        with disposable_database(options.database) as database:
            os.environ.update(database, DJANGO_SETTINGS_MODULE="scms.settings",
                DJANGO_SECRET_KEY=secrets.token_urlsafe(64), DJANGO_DEBUG="False",
                DJANGO_MAIL_BACKEND="console", DJANGO_SMTP_USE_TLS="True", DJANGO_SMTP_USE_SSL="False",
                COMPLAINT_INTAKE_ENABLED="False", ANONYMOUS_INTAKE_ENABLED="False",
                ANONYMOUS_PRIVACY_READY="False", ANONYMOUS_TRANSPORT_VERIFIED="False")
            import django
            django.setup()
            from django.core.management import call_command
            from django.db import connections
            try:
                call_command("migrate", verbosity=0)
                eligible, controls = seed_dataset(count=options.count, seed=options.seed,
                    sla_minutes=options.sla_minutes, interval_minutes=options.interval_minutes,
                    maximum_level=options.maximum_level)
                result = measure(eligible, controls)
                from datetime import datetime
                result["interruption"] = interruption_check(options, datetime.fromisoformat(result["logical_start"]))
                result.update(database=options.database, seed=options.seed, python=platform.python_version(),
                    django=django.get_version(), platform=platform.platform(),
                    cpu_count=os.cpu_count(), policy={"sla_minutes":options.sla_minutes,
                    "interval_minutes":options.interval_minutes,"maximum_level":options.maximum_level},
                    source=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),  # nosec B603,B607 - fixed Git revision lookup via agent PATH
                    benchmark_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    acceptance="UNVERIFIED: SQLite diagnostic" if options.database=="sqlite" else
                        "PostgreSQL component only; confirm representative Q04 deployment/resources and F4 acceptance")
                result["measurement_scope"] = "In-process management command including system checks and query counter; excludes fixture/migration preparation, process startup and SMTP delivery"
                result["database_version"] = connections["default"].pg_version if options.database == "postgresql" else __import__("sqlite3").sqlite_version
                print(json.dumps(result, indent=2))
                if options.database == "postgresql" and options.count == 5000 and result["elapsed_seconds"] > 60:
                    return 1
            finally:
                connections.close_all()
    except Exception:
        # No connection strings, complaint data, references or exception values.
        print("Benchmark failed; no acceptance claimed. Inspect the isolated fixture/tests safely.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
