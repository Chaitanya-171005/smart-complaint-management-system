"""Administrator screens for departments and locations (B05). Logic lives in reference_services."""

from django import forms
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from . import reference_services as svc
from .models import Department, Location, User
from .permissions import role_required

admin_only = role_required(User.Role.ADMIN)


class DepartmentForm(forms.Form):
    name = forms.CharField(max_length=50, strip=True)


class LocationForm(forms.Form):
    code = forms.CharField(max_length=100, help_text="Stable code other modules use; cannot be changed later.")
    block = forms.CharField(max_length=20)
    floor = forms.CharField(max_length=10, required=False)
    room_area = forms.CharField(max_length=30, label="Room / area")


class LocationEditForm(forms.Form):
    block = forms.CharField(max_length=20)
    floor = forms.CharField(max_length=10, required=False)
    room_area = forms.CharField(max_length=30, label="Room / area")


def _apply(form, action):
    """Run a service call; show its validation messages on the form. True on success."""
    try:
        action(form.cleaned_data)
    except ValidationError as exc:
        for field, messages in getattr(exc, "message_dict", {"__all__": exc.messages}).items():
            for message in messages:
                form.add_error(field if field in form.fields else None, message)
        return False
    return True


def _active_flag(request):
    value = request.POST.get("active")
    if value not in {"true", "false"}:
        raise Http404
    return value == "true"


# --- departments -----------------------------------------------------------------------


@admin_only
@require_http_methods(["GET", "POST"])
def departments(request):
    form = DepartmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if _apply(form, lambda d: svc.create_department(request.user, d["name"])):
            return redirect("accounts:admin_departments")
    return render(request, "accounts/admin_departments.html",
                  {"form": form, "departments": Department.objects.all()}, status=400 if form.errors else 200)


@admin_only
@require_http_methods(["GET", "POST"])
def department_edit(request, pk):
    department = get_object_or_404(Department, pk=pk)
    form = DepartmentForm(request.POST or None, initial={"name": department.name})
    if request.method == "POST" and form.is_valid():
        if _apply(form, lambda d: svc.rename_department(request.user, department, d["name"])):
            return redirect("accounts:admin_departments")
    return render(request, "accounts/admin_edit.html",
                  {"form": form, "title": f"Edit department: {department.name}",
                   "back": "accounts:admin_departments"}, status=400 if form.errors else 200)


@admin_only
@require_POST
def department_active(request, pk):
    department = get_object_or_404(Department, pk=pk)
    svc.set_department_active(request.user, department, _active_flag(request))
    return redirect("accounts:admin_departments")


# --- locations -------------------------------------------------------------------------


@admin_only
@require_http_methods(["GET", "POST"])
def locations(request):
    form = LocationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if _apply(form, lambda d: svc.create_location(request.user, **d)):
            return redirect("accounts:admin_locations")
    return render(request, "accounts/admin_locations.html",
                  {"form": form, "locations": Location.objects.all()}, status=400 if form.errors else 200)


@admin_only
@require_http_methods(["GET", "POST"])
def location_edit(request, pk):
    location = get_object_or_404(Location, pk=pk)
    form = LocationEditForm(
        request.POST or None,
        initial={"block": location.block, "floor": location.floor, "room_area": location.room_area},
    )
    if request.method == "POST" and form.is_valid():
        if _apply(form, lambda d: svc.update_location(request.user, location, **d)):
            return redirect("accounts:admin_locations")
    return render(request, "accounts/admin_edit.html",
                  {"form": form, "title": f"Edit location: {location.code}",
                   "back": "accounts:admin_locations"}, status=400 if form.errors else 200)


@admin_only
@require_POST
def location_active(request, pk):
    location = get_object_or_404(Location, pk=pk)
    svc.set_location_active(request.user, location, _active_flag(request))
    return redirect("accounts:admin_locations")
