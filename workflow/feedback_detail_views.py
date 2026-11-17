from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.views.decorators.vary import vary_on_cookie

from workflow.reference_feedback import authorized_feedback_history
from workflow.services import paginate_complaints


@never_cache
@vary_on_cookie
@login_required
@require_safe
def feedback_detail(request, complaint_id):
    complaint, feedback = authorized_feedback_history(actor=request.user, complaint_id=complaint_id)
    return render(request, "workflow/feedback_detail.html", {
        "complaint": complaint,
        "feedback_page": paginate_complaints(feedback, request.GET.get("page", 1)),
    })
