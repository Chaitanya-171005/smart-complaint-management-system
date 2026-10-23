from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import RegistrationForm
from .services import RegistrationError, register_complainant


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
