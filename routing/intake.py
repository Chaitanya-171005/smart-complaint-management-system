"""The single F3 call for trusted intake; creates no Complaint, receipt, history or notification."""

from dataclasses import dataclass
from datetime import datetime

from accounts.models import Department
from complaints.models import Complaint
from routing.models import RoutingDecision
from routing.resolver import route_and_record
from routing.sla import derive_priority_and_due


@dataclass(frozen=True)
class RoutingOutcome:
    department: Department
    unrouted: bool
    routing_rule_key: str
    priority: str
    due_at: datetime
    sla_source: str
    decision: RoutingDecision

    def as_complaint_fields(self) -> dict:
        return {
            "department": self.department,
            "unrouted": self.unrouted,
            "routing_rule_key": self.routing_rule_key,
            "priority": self.priority,
            "due_at": self.due_at,
            "status": Complaint.Status.ASSIGNED,
        }


def route_and_prioritize(*, complaint_id, category, location_code, indicated_priority,
                         submitted_at) -> RoutingOutcome:
    """Derive the SLA and record routing in the caller's intake transaction."""
    sla = derive_priority_and_due(category, indicated_priority, submitted_at)
    decision = route_and_record(complaint_id, category, location_code, now=submitted_at)
    return RoutingOutcome(
        department=decision.department,
        unrouted=decision.unrouted,
        routing_rule_key=str(decision.rule_id) if decision.rule_id else "",
        priority=sla.priority,
        due_at=sla.due_at,
        sla_source=sla.source,
        decision=decision,
    )
