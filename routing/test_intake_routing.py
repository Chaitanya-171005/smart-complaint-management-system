import pytest

from accounts.models import Department, Location
from complaints.intake import execute_intake, new_intake_key, submission_digest
from complaints.models import ComplaintIdSequence, IntakeReceipt
from routing.models import Category, EscalationPolicy, RoutingDecision, RoutingRule
from routing.resolver import RoutingConfigurationError, route_and_record, route_complaint

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def setup_routing(complainant_user):
    category, _ = Category.objects.get_or_create(name="Electrical", defaults={"minimum_priority": "MEDIUM"})
    department = Department.objects.create(name="Maintenance")
    default = Department.objects.create(name="Administration")
    Location.objects.create(code="HOSTEL-A", block="Hostel", room_area="A")
    policy = EscalationPolicy.objects.create(default_department=default, interval_minutes=60, maximum_level=3)
    rule = RoutingRule.objects.create(category=category, location_code="HOSTEL-A", department=department)
    args = dict(user=complainant_user, key=new_intake_key(),
                payload_digest=submission_digest(fields={"category": "Electrical", "location": "HOSTEL-A"}))
    def operation(ctx):
        route_and_record(ctx.complaint_id, category, "HOSTEL-A", now=ctx.submitted_at)
    return category, department, default, policy, rule, args, operation


def test_success_and_replay(setup_routing):
    category, department, _, _, rule, args, operation = setup_routing
    expected = route_complaint(category, "HOSTEL-A")
    result = execute_intake(**args, operation=operation)
    decision = RoutingDecision.objects.get(complaint_id=result.complaint_id)
    assert (decision.department, decision.rule, decision.basis) == (department, rule, expected.basis)
    assert decision.decided_at == result.submitted_at
    assert not result.replayed
    replay = execute_intake(**args, operation=operation)
    assert replay.replayed and replay.complaint_id == result.complaint_id
    assert RoutingDecision.objects.filter(complaint_id=result.complaint_id).count() == 1


def test_failure_rolls_back_sequence_and_receipt(setup_routing):
    _, _, _, policy, rule, args, operation = setup_routing
    rule.active = False
    rule.save()
    policy.delete()
    before = list(ComplaintIdSequence.objects.values_list("year", "last_value"))
    with pytest.raises(RoutingConfigurationError):
        execute_intake(**args, operation=operation)
    assert not RoutingDecision.objects.exists()
    assert not IntakeReceipt.objects.exists()
    assert list(ComplaintIdSequence.objects.values_list("year", "last_value")) == before


def test_configuration_changes_are_prospective(setup_routing):
    _, department, default, _, rule, args, operation = setup_routing
    first = execute_intake(**args, operation=operation)
    original = RoutingDecision.objects.filter(complaint_id=first.complaint_id).values().get()
    rule.precedence = 1
    rule.active = False
    rule.save()
    department.active = False
    department.save()
    assert RoutingDecision.objects.filter(complaint_id=first.complaint_id).values().get() == original
    second = execute_intake(**{**args, "key": new_intake_key()}, operation=operation)
    new = RoutingDecision.objects.get(complaint_id=second.complaint_id)
    assert new.department == default and new.rule is None and new.unrouted and new.basis == "DEFAULT"
