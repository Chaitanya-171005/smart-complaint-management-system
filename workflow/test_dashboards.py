"""B31 scoped current-record snapshots; D03/B30 calculations remain gated."""
import csv
from io import StringIO

import pytest
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import reverse

from workflow.dashboards import current_snapshot, snapshot_csv

pytestmark = pytest.mark.django_db


@pytest.fixture
def dataset(user_factory, department_factory, complaint_factory, category_factory):
    department = department_factory()
    other = department_factory()
    owner = user_factory()
    stranger = user_factory()
    head = user_factory(role='HEAD',department=department)
    first = category_factory(name='Synthetic lights')
    second = category_factory(name='Synthetic water')
    complaint_factory(submitted_by=owner,department=department,category_record=first,status='ASSIGNED')
    complaint_factory(submitted_by=owner,department=department,category_record=first,status='RESOLVED')
    complaint_factory(submitted_by=stranger,department=department,category_record=second,status='REOPENED')
    complaint_factory(anonymous=True,department=department,category_record=second,status='CLOSED',
                      description='PRIVATE BODY WITH SUFFICIENT LENGTH', resolution_remarks='PRIVATE RESOLUTION')
    complaint_factory(submitted_by=stranger,department=other,category_record=first,status='ASSIGNED')
    return owner,head,stranger,department,other


def total(snapshot):
    return snapshot['rows'][0][2]


def test_fixed_dataset_owner_and_department_figures(dataset):
    owner,head,stranger,department,other = dataset
    assert total(current_snapshot(actor=owner)) == 2
    assert total(current_snapshot(actor=stranger)) == 2
    report = current_snapshot(actor=head,department_id=department.pk)
    assert total(report) == 4
    statuses = {label:count for group,label,count in report['rows'] if group=='status'}
    assert statuses['Assigned'] == statuses['Resolved'] == statuses['Reopened'] == statuses['Closed'] == 1
    assert sum(count for group,_,count in report['rows'] if group=='category') == 4
    assert len([row for row in report['rows'] if row[0]=='department']) == 1
    with pytest.raises(Http404):
        current_snapshot(actor=head,department_id=other.pk)


def test_filters_are_scoped_and_csv_matches_display(dataset, client):
    owner,head,_,department,_ = dataset
    client.force_login(head)
    url = reverse('workflow:department_report',args=[department.pk])
    filters={'status':'RESOLVED','category':'Synthetic lights'}
    screen = client.get(url,filters)
    assert screen.status_code == 200 and total(screen.context) == 1
    export = client.get(url,{**filters,'format':'csv'})
    assert export.status_code == 200
    rows=list(csv.reader(StringIO(export.content.decode())))
    assert rows[0] == ['section','label','count']
    assert rows[1:] == [[str(cell) for cell in row] for row in screen.context['rows']]
    assert 'attachment;' in export.headers['Content-Disposition']
    assert 'no-store' in export.headers['Cache-Control']
    assert export.headers['X-Content-Type-Options']=='nosniff'
    assert total(current_snapshot(actor=owner,category='not-permitted-category')) == 0


@pytest.mark.parametrize('role',['STAFF','ADMIN'])
def test_unauthorized_roles_do_not_receive_dashboards(dataset,client,user_factory,role):
    _,_,_,department,_=dataset
    actor=user_factory(role=role,department=department if role=='STAFF' else None)
    client.force_login(actor)
    assert client.get(reverse('workflow:dashboard')).status_code == 403
    assert client.get(reverse('workflow:department_report',args=[department.pk]), {'format':'csv'}).status_code==403


def test_owner_cannot_request_department_report_and_head_cannot_change_scope(dataset,client):
    owner,head,_,department,other=dataset
    url=reverse('workflow:department_report',args=[department.pk])
    client.force_login(owner)
    assert client.get(url).status_code == 404
    client.force_login(head)
    for output in ('html','csv'):
        assert client.get(reverse('workflow:department_report',args=[other.pk]),{'format':output}).status_code==404
    assert total(client.get(reverse('workflow:dashboard')).context)==4
    assert client.get(reverse('workflow:dashboard'),{'department':other.pk}).status_code==400


@pytest.mark.parametrize('filter_value',[{'start':'2026-01-01'}, {'end':'2026-12-31'},
                                         {'status':'INVALID'}, {'format':'json'}, {'owner':'1'}])
def test_unagreed_date_and_unrecognized_filters_are_refused(dataset,client,filter_value):
    client.force_login(dataset[1])
    assert client.get(reverse('workflow:department_report',args=[dataset[3].pk]),filter_value).status_code==400


def test_fresh_roles_and_department_membership_apply_on_next_request(dataset,client):
    _,head,_,department,other=dataset
    client.force_login(head)
    url=reverse('workflow:department_report',args=[department.pk])
    type(head).objects.filter(pk=head.pk).update(department=other)
    assert client.get(url).status_code==404
    assert total(current_snapshot(actor=head))==1
    type(head).objects.filter(pk=head.pk).update(role='STAFF')
    with pytest.raises(PermissionDenied):
        current_snapshot(actor=head)
    type(head).objects.filter(pk=head.pk).update(is_active=False)
    with pytest.raises(PermissionDenied):
        current_snapshot(actor=head)


def test_anonymous_identity_and_source_fields_never_appear(dataset,client):
    _,head,_,department,_=dataset
    from complaints.models import Complaint
    anonymous=Complaint.objects.get(submitted_by=None)
    client.force_login(head)
    url=reverse('workflow:department_report',args=[department.pk])
    for output in ('html','csv'):
        response=client.get(url,{'format':output})
        assert response.status_code==200
        for secret in ('PRIVATE BODY','PRIVATE RESOLUTION',anonymous.reference_digest,
                       anonymous.complaint_id,head.email,'submitted_by','reference_digest','uploaded_by'):
            assert secret.encode() not in response.content


def test_csv_formula_neutralization_and_html_escape(dataset,client):
    from complaints.models import Complaint
    owner,head,_,department,_=dataset
    Complaint.objects.filter(submitted_by=owner).update(category='=SYNTHETIC("<script>")')
    snapshot=current_snapshot(actor=head)
    assert "'=SYNTHETIC" in snapshot_csv(snapshot)
    client.force_login(head)
    response=client.get(reverse('workflow:department_report',args=[department.pk]))
    assert b'<script>' not in response.content and b'&lt;script&gt;' in response.content


def test_empty_snapshot_and_anonymous_access(client,user_factory):
    owner=user_factory()
    assert total(current_snapshot(actor=owner))==0
    assert client.get(reverse('workflow:dashboard')).status_code==302
    client.force_login(owner)
    response=client.get(reverse('workflow:dashboard'))
    assert response.status_code==200 and total(response.context)==0
    assert client.post(reverse('workflow:dashboard')).status_code==405
    assert client.get(reverse('workflow:dashboard'),{'format':'csv'}).status_code==400
