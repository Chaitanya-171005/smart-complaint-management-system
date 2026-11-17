from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.views.decorators.vary import vary_on_cookie

from workflow.dashboards import current_snapshot, snapshot_csv


@never_cache
@vary_on_cookie
@login_required
@require_safe
def dashboard(request, department_id=None):
    try:
        # Authorize scope before reporting filter errors or exporting any figures.
        snapshot = current_snapshot(actor=request.user, department_id=department_id,
                                    status=request.GET.get('status',''),
                                    category=request.GET.get('category',''))
        if set(request.GET) - {'status','category','format'}:
            raise ValidationError('Date-range reporting is pending D03/B30; only status/category filters are supported.')
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
        return HttpResponse('Unsupported report filters. Date-range and calculated reports await D03/B30.', status=400)
    snapshot['export_query'] = urlencode({'status':snapshot['selected_status'],
                                         'category':snapshot['selected_category'],'format':'csv'})
    snapshot['department_report'] = department_id is not None
    return render(request, 'workflow/dashboard.html', snapshot)
