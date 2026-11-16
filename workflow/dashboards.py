"""B31 current-record snapshots; D03/B30 period calculations are not supplied."""
import csv
from collections import Counter
from io import StringIO

from django.core.exceptions import ValidationError
from django.http import Http404

from accounts.models import User
from accounts.permissions import can_view_report, has_role, require_permission, scope_complaints
from complaints.models import Complaint
from workflow.services import filter_complaints


def _dashboard_role(user):
    return has_role(user, User.Role.COMPLAINANT, User.Role.HEAD)


def current_snapshot(*, actor, department_id=None, status='', category=''):
    current = (User.objects.filter(pk=actor.pk).first()
               if actor is not None and actor.is_authenticated else None)
    require_permission(_dashboard_role, current)
    if department_id is not None:
        if not has_role(current, User.Role.HEAD) or not can_view_report(current, department_id):
            raise Http404
    elif has_role(current, User.Role.HEAD) and current.department_id is None:
        raise Http404
    if status and status not in Complaint.Status.values:
        raise ValidationError('Choose a valid status.')
    scoped = scope_complaints(current, Complaint.objects.all())
    filtered = filter_complaints(scoped, status=status, category=category)
    # One query supplies every figure: export and screen share the same rows.
    # Never select reporter identity, reference, history, proof or free text.
    records = list(filtered.values('status','category','location_code','department__name'))
    statuses = Counter(row['status'] for row in records)
    rows = [('summary','Total',len(records))]
    rows += [('status',label,statuses[value]) for value,label in Complaint.Status.choices]
    for section, field in [('category','category'),('location','location_code'),
                           ('department','department__name')]:
        counts = Counter(row[field] for row in records)
        rows += [(section,label,count) for label,count in sorted(counts.items())]
    return {'rows':rows, 'statuses':Complaint.Status.choices,
            'selected_status':status,'selected_category':category,
            'department_id':current.department_id if current.role == User.Role.HEAD else None,
            'is_head':current.role == User.Role.HEAD}


def _csv_cell(value):
    value = str(value)
    # Master-data labels are untrusted spreadsheet input too.
    if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t','\r','\n')):
        return "'" + value
    return value


def snapshot_csv(snapshot):
    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['section','label','count'])
    writer.writerows([_csv_cell(cell) for cell in row] for row in snapshot['rows'])
    return output.getvalue()
