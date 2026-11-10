"""POST-only credential lookup; references never appear in response URLs/forms."""

from django.db import transaction
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from .checks import tracking_release_ready
from .tracking import restricted_tracking


@transaction.non_atomic_requests
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def track_reference(request):
    if (not getattr(request, "anonymous_tracking", False)
            or not getattr(request, "anonymous_privacy_isolated", False)
            or not request.is_secure() or not tracking_release_ready()):
        return render(request, "complaints/tracking.html", {"unavailable": True}, status=503)
    result, searched = None, request.method == "POST"
    if searched:
        if not getattr(request, "tracking_allowed", False):
            return render(request, "complaints/tracking.html", {"unavailable": True}, status=503)
        values = request.POST.getlist("reference")
        reference = values[0] if len(values) == 1 else None
        # Return no bound form or raw user input in any response, even errors.
        page = request.POST.get("page", "1")
        page = int(page) if page.isascii() and page.isdecimal() and len(page) <= 9 else 1
        result = restricted_tracking(reference, page)
    return render(request, "complaints/tracking.html", {"result": result, "searched": searched})
