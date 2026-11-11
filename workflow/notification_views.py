"""B28 minimal notice projection; no history text, reporter or evidence payload."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe
from django.views.decorators.vary import vary_on_cookie

from workflow.notifications import mark_notification_read, notifications_for


@never_cache
@vary_on_cookie
@login_required
@require_safe
def notification_list(request):
    notices = notifications_for(request.user).order_by("-created_at", "-pk")
    return render(request, "workflow/notifications.html", {
        "page": Paginator(notices, 25).get_page(request.GET.get("page", 1)),
    })


@never_cache
@vary_on_cookie
@login_required
@require_POST
def notification_read(request, notice_id):
    mark_notification_read(request.user, notice_id)
    return redirect("workflow:notifications")
