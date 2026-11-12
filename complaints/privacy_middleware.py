"""Isolate the anonymous route before session/authentication middleware runs."""

from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse, QueryDict
from django.utils.cache import patch_cache_control
from django.utils.deprecation import MiddlewareMixin
from django.views.debug import ExceptionReporter, SafeExceptionReporterFilter


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
        if request.path_info.rstrip("/") != "/anonymous/new":
            return
        request.anonymous_intake = True
        # Defense against an upstream request wrapper preloading identity. The
        # first-in-MIDDLEWARE release check is still mandatory independently.
        request.anonymous_privacy_isolated = not any(
            hasattr(request, name) for name in ("session", "user", "_cached_user")
        )
        request.exception_reporter_filter = AnonymousReporterFilter()
        request.exception_reporter_class = AnonymousExceptionReporter
        request.sensitive_post_parameters = "__ALL__"
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
        if "HTTP_REFERER" in request.META:
            try:
                referer = urlsplit(request.META["HTTP_REFERER"])
                request.META["HTTP_REFERER"] = f"{referer.scheme}://{referer.netloc}/"
            except ValueError:
                request.META.pop("HTTP_REFERER", None)
        request.META["QUERY_STRING"] = ""
        request.GET = QueryDict()

    def process_exception(self, request, exception):
        if getattr(request, "anonymous_intake", False):
            # Do not log exception values or feed them into an APM/error email.
            return HttpResponse("Anonymous submission could not be completed. Please try again.", status=500)

    def process_response(self, request, response):
        if getattr(request, "anonymous_intake", False):
            # CsrfViewMiddleware has already set its cookie on the response.
            # Keep validation intact but replace any persistent CSRF cookie with
            # a browser-session cookie on anonymous responses only. Auth/session
            # cookie settings and the existing signed-in session are unchanged.
            cookie = response.cookies.get(settings.CSRF_COOKIE_NAME)
            if cookie is None and request.META.get("CSRF_COOKIE"):
                # Successful POSTs need not render a new csrf_token, so Django
                # may omit Set-Cookie. Replace an incoming persistent cookie too.
                response.set_cookie(
                    settings.CSRF_COOKIE_NAME, request.META["CSRF_COOKIE"],
                    path=settings.CSRF_COOKIE_PATH, domain=settings.CSRF_COOKIE_DOMAIN,
                    secure=settings.CSRF_COOKIE_SECURE, httponly=settings.CSRF_COOKIE_HTTPONLY,
                    samesite=settings.CSRF_COOKIE_SAMESITE,
                )
                cookie = response.cookies[settings.CSRF_COOKIE_NAME]
            if cookie is not None:
                cookie["max-age"] = ""
                cookie["expires"] = ""
            patch_cache_control(response, private=True, no_store=True, no_cache=True, max_age=0)
            response["Referrer-Policy"] = "no-referrer"
            response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            response["Content-Security-Policy"] = "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response
