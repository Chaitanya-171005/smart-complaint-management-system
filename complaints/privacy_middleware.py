"""Isolate the anonymous route before session/authentication middleware runs."""

from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import HttpResponse, QueryDict
from django.utils.cache import patch_cache_control
from django.utils.deprecation import MiddlewareMixin
from django.views.debug import ExceptionReporter, SafeExceptionReporterFilter

from .checks import tracking_release_ready
from .tracking_limits import TrackingUnavailable, consume_attempt


class AnonymousReporterFilter(SafeExceptionReporterFilter):
    def is_active(self, request):
        return True

    def get_safe_request_meta(self, request):
        return {"REQUEST_METHOD": request.method, "PATH_INFO": request.path_info}

    def get_safe_cookies(self, request):
        return {}

    def get_safe_settings(self):
        return {}

    def get_post_parameters(self, request):
        return QueryDict()

    def get_traceback_frame_variables(self, request, tb_frame):
        return [(name, self.cleansed_substitute) for name in tb_frame.f_locals]


class AnonymousExceptionReporter(ExceptionReporter):
    def get_traceback_data(self):
        data = super().get_traceback_data()
        data.update({
            "user_str": "Anonymous", "exception_value": "Anonymous request failed.",
            "unicode_hint": "", "exception_notes": "", "template_info": None,
            "template_does_not_exist": False, "postmortem": None,
            "request_GET_items": [], "request_FILES_items": [],
        })
        return data


class AnonymousPrivacyMiddleware(MiddlewareMixin):
    """Strip automatic identity on this route only; keep CSRF enforcement.

    This does not modify the browser's existing login cookie or log it out. No
    request headers, source keys or session values are copied into intake data.
    Reverse-proxy/APM/network logs must be separately disabled/redacted at deploy.
    """

    def process_request(self, request):
        path = request.path_info.rstrip("/")
        if path not in {"/complaints/anonymous", "/complaints/track"}:
            return
        request.anonymous_intake = True
        request.anonymous_tracking = path == "/complaints/track"
        request.anonymous_privacy_isolated = not hasattr(request, "session")
        request.exception_reporter_filter = AnonymousReporterFilter()
        request.exception_reporter_class = AnonymousExceptionReporter
        request.sensitive_post_parameters = "__ALL__"
        refusal = None
        if (request.anonymous_tracking and request.method == "POST"
                and request.anonymous_privacy_isolated and request.is_secure()
                and tracking_release_ready()):
            # Consume before reading credentials/body or doing a complaint query.
            # Only REMOTE_ADDR is trusted; forwarding headers are never accepted
            # from arbitrary clients. The ingress must set the actual peer.
            try:
                allowed, retry = consume_attempt(request.META.get("REMOTE_ADDR", ""))
                request.tracking_allowed = allowed
                if not allowed:
                    refusal = HttpResponse("Too many tracking attempts. Please try again later.", status=429)
                    refusal["Retry-After"] = str(retry)
            except TrackingUnavailable:
                refusal = HttpResponse("Reference tracking is temporarily unavailable. Please try again later.", status=503)
            if refusal is None:
                try:
                    length = int(request.META.get("CONTENT_LENGTH", "0") or "0")
                except ValueError:
                    length = -1
                if (not 0 <= length <= 1024
                        or (length > 0 and request.content_type != "application/x-www-form-urlencoded")):
                    refusal = HttpResponse("No matching complaint was found.", status=400)
        # Keep only the anti-CSRF cookie. In particular, auth middleware cannot
        # load an existing account/session and SessionMiddleware cannot refresh it.
        csrf_cookie = request.COOKIES.get(settings.CSRF_COOKIE_NAME)
        request.COOKIES = ({settings.CSRF_COOKIE_NAME: csrf_cookie} if csrf_cookie else {})
        for name in list(request.META):
            if (name.startswith("HTTP_") and name not in {
                "HTTP_HOST", "HTTP_ORIGIN", "HTTP_REFERER", "HTTP_X_CSRFTOKEN",
                "HTTP_X_FORWARDED_PROTO",
            }) or name.startswith("REMOTE_"):
                request.META.pop(name, None)
        if csrf_cookie:
            request.META["HTTP_COOKIE"] = f"{settings.CSRF_COOKIE_NAME}={csrf_cookie}"
        try:
            origin = f"{request.scheme}://{request.get_host()}"
        except DisallowedHost:
            # Do not let Django's security logger print an attacker-supplied
            # Host containing a reference or identifying value on this route.
            refusal = HttpResponse("Invalid anonymous request.", status=400)
            origin = ""
        if "HTTP_ORIGIN" in request.META and request.META["HTTP_ORIGIN"] != origin:
            # Preserve cross-origin refusal without feeding raw header values
            # into django.security.csrf's reason log. Anonymous forms are self-only.
            request.META["HTTP_ORIGIN"] = "https://invalid-origin.invalid"
        if "HTTP_REFERER" in request.META:
            try:
                referer = urlsplit(request.META["HTTP_REFERER"])
                base = f"{referer.scheme}://{referer.netloc}"
                request.META["HTTP_REFERER"] = (
                    base + "/" if base == origin else "https://invalid-origin.invalid/"
                )
            except ValueError:
                request.META.pop("HTTP_REFERER", None)
        request.META["QUERY_STRING"] = ""
        request.GET = QueryDict()
        return refusal

    def process_exception(self, request, exception):
        if getattr(request, "anonymous_intake", False):
            # Do not log exception values or feed them into an APM/error email.
            return HttpResponse("Anonymous request could not be completed. Please try again.", status=500)

    def process_response(self, request, response):
        if getattr(request, "anonymous_intake", False):
            patch_cache_control(response, private=True, no_store=True, no_cache=True, max_age=0)
            response["Referrer-Policy"] = "no-referrer"
            response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            response["Content-Security-Policy"] = "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response
