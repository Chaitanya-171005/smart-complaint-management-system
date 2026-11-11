import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError

from workflow.history_service import record_history
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db


def test_history_stores_accounts_and_old_call_style(head_user, staff_user):
    event = record_history("one", "ALLOCATED", "HEAD", actor=head_user, assignee=staff_user)
    assert event.actor == head_user and event.assignee == staff_user
    old = record_history("two", "SUBMITTED", "SYSTEM", "", "SUBMITTED", "old style")
    assert old.actor is None and old.assignee is None and old.remarks == "old style"
    with pytest.raises(ProtectedError):
        head_user.delete()
    with pytest.raises(ProtectedError):
        staff_user.delete()


def test_anonymous_clears_accounts_and_database_enforces_constraint(head_user, staff_user):
    event = record_history("one", "SUBMITTED", "ANONYMOUS", actor=head_user, assignee=staff_user)
    assert event.actor is None and event.assignee is None
    direct = ComplaintHistory(complaint_ref="two", event_type="SUBMITTED", actor_kind="ANONYMOUS",
                              actor=head_user, assignee=staff_user)
    direct.save()
    assert direct.actor is None and direct.assignee is None
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE workflow_complainthistory SET actor_id = %s WHERE id = %s", [head_user.pk, event.pk])
