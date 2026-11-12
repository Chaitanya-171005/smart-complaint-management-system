"""The authenticated intake and department allocation flows share one complaint."""
import pytest
from django.urls import reverse

from accounts.models import User
from complaints.models import Complaint, IntakeReceipt
from routing.models import RoutingDecision
from workflow.models import ComplaintHistory


@pytest.mark.django_db(transaction=True)
def test_submission_routing_queue_allocation_and_history(
    client, settings, tmp_path, complainant_user, routing_configuration,
    head_user, staff_user, user_factory,
):
    settings.COMPLAINT_INTAKE_ENABLED = True
    settings.COMPLAINT_EMERGENCY_NOTICE = 'Synthetic test notice'
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / 'evidence'
    config = routing_configuration
    client.force_login(complainant_user)
    url = reverse('complaints:submit')
    form = client.get(url)
    assert form.status_code == 200
    response = client.post(url, {
        'request_token': form.context['request_token'],
        'category': str(config['category'].pk), 'location': config['location'].code,
        'title': 'Synthetic broken light',
        'description': 'The light in this synthetic room does not turn on.',
        'sub_category': '', 'priority': 'LOW',
    })
    assert response.status_code == 303
    complaint = Complaint.objects.get()
    assert IntakeReceipt.objects.get().accepted_complaint == complaint
    assert complaint.department == config['department']
    assert complaint.status == Complaint.Status.ASSIGNED and complaint.assignee is None
    assert RoutingDecision.objects.filter(complaint_id=complaint.complaint_id).count() == 1
    assert client.get(response.url).status_code == 200

    client.force_login(head_user)
    queue = client.get(reverse('routing:queue'))
    assert queue.status_code == 200
    assert complaint.complaint_id in queue.content.decode()
    other = user_factory(role=User.Role.STAFF, department=config['department'])
    assign_url = reverse('assign_complaint', args=[complaint.complaint_id])
    assert client.post(assign_url, {'assignee': staff_user.pk}).status_code == 302
    assert client.post(assign_url, {'assignee': other.pk, 'expected_assignee': staff_user.pk,
                                    'reason': 'Shift coverage'}).status_code == 302
    complaint.refresh_from_db()
    assert complaint.assignee == other
    events = list(ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).order_by('pk'))
    assert [(event.event_type, event.actor_kind, event.actor_id, event.assignee_id, event.remarks)
            for event in events] == [
        ('SUBMITTED', 'COMPLAINANT', None, None, ''),
        ('ALLOCATED', 'SYSTEM', None, None, ''),
        ('ALLOCATED', 'HEAD', head_user.pk, staff_user.pk, ''),
        ('REASSIGNED', 'HEAD', head_user.pk, other.pk, 'Shift coverage'),
    ]
