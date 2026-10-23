from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import RegistrationForm
from .services import register_complainant


@require_http_methods(["GET", "POST"])
def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            # Same response whether or not the email already exists.
            register_complainant(
                full_name=data["full_name"],
                email=data["email"],
                password=data["password"],
                user_type=data["user_type"],
                hostel_block=data["hostel_block"],
                hostel_room=data["hostel_room"],
            )
            return redirect("accounts:register_done")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


def register_done(request):
    return render(request, "accounts/register_done.html")
