"""Reference-authorized, read-only projection; never full complaint access."""

import hashlib

from django.core.paginator import Paginator
from django.views.decorators.debug import sensitive_variables

from workflow.history_service import get_complaint_history
from workflow.models import ComplaintHistory

from .models import Complaint
from .references import hash_reference


@sensitive_variables()
def restricted_tracking(reference, page=1):
    """Return only REQ-ANON-03 fields/history, or the same None for any no-match.

    This function has no source/account parameter and records no lookup event.
    HTTP callers must consume a source allowance BEFORE calling it.
    """
    try:
        digest = hash_reference(reference)
        valid = True
    except ValueError:
        # Still perform one indexed query, as for an unknown well-formed value.
        digest, valid = hashlib.sha256(b"invalid-reference").hexdigest(), False
    record = Complaint.objects.filter(
        submitted_by__isnull=True, reference_digest=digest,
    ).values("complaint_id", "category", "location_code", "status", "is_escalated").first()
    if not valid or record is None:
        return None
    states = dict(Complaint.Status.choices)
    events = dict(ComplaintHistory.EventType.choices)
    # A free-text state/remark could contain identifying data. Filter unknown
    # values and project only enum labels/time, never actor/assignee/remarks.
    history = get_complaint_history(record["complaint_id"]).filter(
        event_type__in=events, previous_state__in=["", *states], new_state__in=["", *states],
    ).order_by("-occurred_at", "-pk").values(
        "event_type", "previous_state", "new_state", "occurred_at",
    )
    # Newest page first, chronological within each page; no more than 25 rows.
    current = Paginator(history, 25).get_page(page)
    entries = [
        {"event": events[row["event_type"]], "previous_state": states.get(row["previous_state"], ""),
         "new_state": states.get(row["new_state"], ""), "occurred_at": row["occurred_at"]}
        for row in reversed(list(current.object_list))
    ]
    return {
        "complaint": {"complaint_id": record["complaint_id"], "category": record["category"],
                      "location": record["location_code"], "status": states.get(record["status"], "Unknown"),
                      "is_escalated": record["is_escalated"]},
        "history": entries, "page": current.number, "pages": current.paginator.num_pages,
    }
