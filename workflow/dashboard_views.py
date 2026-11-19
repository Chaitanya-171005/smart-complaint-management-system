from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.views.decorators.vary import vary_on_cookie

from accounts.admin_views import ReportRangeForm
from accounts.campus_reports import build_report, report_rows, report_to_csv
from workflow.dashboards import authorized_report_department, current_snapshot, snapshot_csv


def _period_report(request, department_id):
    department = authorized_report_department(actor=request.user, department_id=department_id)
    if set(request.GET) - {'date_from', 'date_to', 'export'}:
        return HttpResponse('Unsupported report filters.', status=400)
    if request.GET.get('export', '') not in ('', 'csv'):
        return HttpResponse('Choose HTML or CSV.', status=400)
    form = ReportRangeForm(request.GET)
    report = None
    rows = []
    if form.is_valid():
        report = build_report(form.cleaned_data['date_from'], form.cleaned_data['date_to'],
                              department=department)
        if request.GET.get('export') == 'csv':
            response = HttpResponse(report_to_csv(report), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="department-period-report.csv"'
            response['X-Content-Type-Options'] = 'nosniff'
            return response
        rows = report_rows(report)[1:]
    keep = request.GET.copy()
    keep.pop('export', None)
    return render(request, 'workflow/department_period_report.html',
                  {'form': form, 'report': report, 'rows': rows,
                   'department_id': department_id, 'report_query': keep.urlencode()},
                  status=200 if report else 400)


@never_cache
@vary_on_cookie
@login_required
@require_safe
def dashboard(request, department_id=None):
    if department_id is not None and set(request.GET) & {'date_from', 'date_to', 'export'}:
        return _period_report(request, department_id)
    try:
        # Authorize scope before reporting filter errors or exporting any figures.
        snapshot = current_snapshot(actor=request.user, department_id=department_id,
                                    status=request.GET.get('status',''),
                                    category=request.GET.get('category',''))
        if set(request.GET) - {'status','category','format'}:
            raise ValidationError('Only status/category snapshot filters are supported here.')
        output = request.GET.get('format','html')
        if output not in ('html','csv'):
            raise ValidationError('Choose HTML or CSV.')
        if output == 'csv':
            if department_id is None or not snapshot['is_head']:
                raise ValidationError('Department CSV requires the authorized department report route.')
            response = HttpResponse(snapshot_csv(snapshot), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="department-current-snapshot.csv"'
            response['X-Content-Type-Options'] = 'nosniff'
            return response
    except ValidationError:
        return HttpResponse('Unsupported report filters.', status=400)
    snapshot['export_query'] = urlencode({'status':snapshot['selected_status'],
                                         'category':snapshot['selected_category'],'format':'csv'})
    snapshot['department_report'] = department_id is not None
    return render(request, 'workflow/dashboard.html', snapshot)
