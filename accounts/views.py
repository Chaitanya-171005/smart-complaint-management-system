from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import LoginForm, RegistrationForm
from .models import User
from .services import RegistrationError, attempt_login, landing_url_name, register_complainant

GENERIC_LOGIN_ERROR = "Invalid email or password."
LOCKED_LOGIN_ERROR = "Too many failed sign-in attempts. Please try again later."


@require_http_methods(["GET", "POST"])
def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                # Same response whether or not the email already exists.
                register_complainant(
                    full_name=data["full_name"],
                    email=data["email"],
                    password=data["password"],
                    user_type=data["user_type"],
                    hostel_block=data["hostel_block"],
                    hostel_room=data["hostel_room"],
                )
            except RegistrationError:
                # Unexpected fault (already logged): generic message, no details.
                form.add_error(
                    None, "We could not complete your registration. Please try again later."
                )
                return render(request, "accounts/register.html", {"form": form}, status=500)
            return redirect("accounts:register_done")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


def register_done(request):
    return render(request, "accounts/register_done.html")


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(landing_url_name(request.user.role))

    error = None
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            result = attempt_login(
                request, form.cleaned_data["email"], form.cleaned_data["password"]
            )
            if result.status == "ok":
                # Always the landing page for the user's current role; a "next"
                # parameter is ignored on purpose (no open redirect).
                return redirect(landing_url_name(result.user.role))
            error = LOCKED_LOGIN_ERROR if result.status == "locked" else GENERIC_LOGIN_ERROR
        else:
            error = GENERIC_LOGIN_ERROR
    else:
        form = LoginForm()
    # The password field is never re-rendered with a value (PasswordInput).
    return render(request, "accounts/login.html", {"form": form, "error": error})


@login_required
def landing(request):
    """/accounts/home/ sends the user to the landing page for their role."""
    return redirect(landing_url_name(request.user.role))


def _role_landing(role):
    # B04 replaces this simple check with the shared permission helpers.
    @login_required
    def view(request):
        if request.user.role != role:
            return redirect(landing_url_name(request.user.role))
        return render(
            request,
            "accounts/landing.html",
            {"role_label": User.Role(role).label},
        )

    return view


landing_complainant = _role_landing(User.Role.COMPLAINANT)
landing_staff = _role_landing(User.Role.STAFF)
landing_head = _role_landing(User.Role.HEAD)
landing_admin = _role_landing(User.Role.ADMIN)
