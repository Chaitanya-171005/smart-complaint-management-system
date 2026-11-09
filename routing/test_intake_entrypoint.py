from datetime import timedelta

import pytest
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from complaints.intake import execute_intake, new_intake_key, submission_digest
from complaints.models import Complaint, ComplaintIdSequence, IntakeReceipt
from routing.intake import route_and_prioritize
from routing.models import Priority, RoutingDecision, SLAConfiguration
from routing.resolver import RoutingConfigurationError
from routing.services import set_sla_configuration, update_routing_rule
from routing.sla import SLAConfigurationError

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def intake(routing_configuration, user_factory):
    config = routing_configuration
    category, location = config["category"], config["location"]
    outcomes = []

    def operation(ctx):
        outcome = route_and_prioritize(
            complaint_id=ctx.complaint_id, category=category, location_code=location.code,
            indicated_priority=Priority.LOW, submitted_at=ctx.submitted_at,
        )
        outcomes.append(outcome)
        complaint = Complaint(
            complaint_id=ctx.complaint_id, submitted_at=ctx.submitted_at,
            submitted_by=ctx.user, category_key=str(category.pk), category=category.name,
            location_code=location.code, block=location.block, floor=location.floor,
            room_area=location.room_area, title="Synthetic faulty light",
            description="The light in this synthetic test room does not turn on.",
            **outcome.as_complaint_fields(),
        )
        complaint.full_clean()
        complaint.save()

    args = dict(user=user_factory(), key=new_intake_key(),
                payload_digest=submission_digest(fields={"category": str(category.pk),
                                                          "location": location.code,
                                                          "priority": "LOW"}),
                operation=operation)
    return config, args, outcomes


def test_rule_match_and_complaint_fields(intake):
    config, args, outcomes = intake
    result = execute_intake(**args)
    complaint = Complaint.objects.get(complaint_id=result.complaint_id)
    outcome = outcomes[0]
    decision = RoutingDecision.objects.get(complaint_id=result.complaint_id)
    assert complaint.department == decision.department == config["rule"].department
    assert not complaint.unrouted and not decision.unrouted
    assert complaint.routing_rule_key == str(config["rule"].pk)
    assert complaint.status == Complaint.Status.ASSIGNED
    assert decision.decided_at == complaint.submitted_at
    assert outcome.decision == decision and outcome.sla_source == "CATEGORY"
    assert outcome.as_complaint_fields() == {
        "department": complaint.department, "unrouted": False,
        "routing_rule_key": str(config["rule"].pk), "priority": complaint.priority,
        "due_at": complaint.due_at, "status": Complaint.Status.ASSIGNED,
    }


def test_fallback(intake):
    config, args, outcomes = intake
    config["rule"].delete()
    result = execute_intake(**args)
    complaint = Complaint.objects.get(complaint_id=result.complaint_id)
    assert complaint.department == config["policy"].default_department
    assert complaint.unrouted and complaint.routing_rule_key == ""
    assert outcomes[0].decision.rule is None
    complaint.full_clean()


def test_minimum_priority_and_due(intake, sla_factory):
    config, args, outcomes = intake
    category = config["category"]
    category.minimum_priority = Priority.HIGH
    category.save(update_fields=["minimum_priority"])
    sla_factory(category=category, priority=Priority.HIGH, duration_minutes=42)
    result = execute_intake(**args)
    complaint = Complaint.objects.get(complaint_id=result.complaint_id)
    assert complaint.priority == Priority.HIGH
    assert complaint.due_at == complaint.submitted_at + timedelta(minutes=42)
    assert outcomes[0].sla_source == "CATEGORY"


def test_replay_creates_no_duplicates(intake):
    _, args, outcomes = intake
    first = execute_intake(**args)
    second = execute_intake(**args)
    assert not first.replayed and second.replayed
    assert second.complaint_id == first.complaint_id
    assert Complaint.objects.count() == RoutingDecision.objects.count() == IntakeReceipt.objects.count() == 1
    assert len(outcomes) == 1


def assert_rollback(args, error):
    before = list(ComplaintIdSequence.objects.values_list("year", "last_value"))
    with pytest.raises(error):
        execute_intake(**args)
    assert not Complaint.objects.exists()
    assert not RoutingDecision.objects.exists()
    assert not IntakeReceipt.objects.exists()
    assert list(ComplaintIdSequence.objects.values_list("year", "last_value")) == before


def test_routing_failure_rolls_back(intake):
    config, args, _ = intake
    config["rule"].delete()
    config["policy"].delete()
    assert_rollback(args, RoutingConfigurationError)


def test_sla_failure_rolls_back(intake):
    config, args, _ = intake
    config["sla"].delete()
    SLAConfiguration.objects.filter(category=None, priority=Priority.LOW).update(active=False)
    assert_rollback(args, SLAConfigurationError)


def test_configuration_changes_do_not_rewrite_records(intake, user_factory, department_factory):
    config, args, _ = intake
    result = execute_intake(**args)
    complaint = Complaint.objects.filter(complaint_id=result.complaint_id)
    decision = RoutingDecision.objects.filter(complaint_id=result.complaint_id)
    original_complaint, original_decision = complaint.values().get(), decision.values().get()
    from accounts.models import User
    admin = user_factory(role=User.Role.ADMIN)
    update_routing_rule(admin, config["rule"], department=department_factory())
    set_sla_configuration(admin, category=config["category"], priority=Priority.LOW,
                          duration_minutes=333)
    assert complaint.values().get() == original_complaint
    assert decision.values().get() == original_decision


def test_transaction_and_value_errors_propagate(intake):
    config, _, _ = intake
    args = dict(complaint_id="SCMS-2026-000001", category=config["category"],
                location_code=config["location"].code, indicated_priority=Priority.LOW,
                submitted_at=timezone.now())
    with pytest.raises(TransactionManagementError):
        route_and_prioritize(**args)
    with pytest.raises(ValueError):
        route_and_prioritize(**{**args, "indicated_priority": "invalid"})
    assert not RoutingDecision.objects.exists()
