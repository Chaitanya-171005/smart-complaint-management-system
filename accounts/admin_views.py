"""Administrator screens for departments and locations (B05). Logic lives in reference_services."""

from django import forms
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from . import reference_services as svc
from . import user_admin_services as user_svc
from .config_audit import ENTITY_TYPES
from .models import ConfigAuditEvent, Department, Location, User
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


# --- users, roles and membership (B06) -------------------------------------------------------


class UserRoleForm(forms.Form):
    role = forms.ChoiceField(choices=User.Role.choices)
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(), required=False, empty_label="No department"
    )

    def __init__(self, *args, target, **kwargs):
        super().__init__(*args, **kwargs)
        current = Department.objects.filter(pk=target.department_id)
        # Active departments for new assignments, plus the user's current one so it is kept.
        self.fields["department"].queryset = svc.active_departments() | current


@admin_only
def users(request):
    listing = User.objects.select_related("department").order_by("email")
    return render(request, "accounts/admin_users.html", {"people": listing})


@admin_only
@require_http_methods(["GET", "POST"])
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = UserRoleForm(
        request.POST or None, target=target,
        initial={"role": target.role, "department": target.department_id},
    )
    if request.method == "POST" and form.is_valid():
        if _apply(form, lambda d: user_svc.set_role_and_membership(
            request.user, target, role=d["role"], department=d["department"]
        )):
            return redirect("accounts:admin_users")
    return render(request, "accounts/admin_edit.html",
                  {"form": form, "title": f"Role and department: {target.email}",
                   "back": "accounts:admin_users"}, status=400 if form.errors else 200)


# --- configuration audit (B29, REQ-ADM-04): read-only ----------------------------------------


class AuditFilterForm(forms.Form):
    entity_type = forms.ChoiceField(required=False)
    action = forms.ChoiceField(required=False)
    actor = forms.CharField(required=False, max_length=254)
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["entity_type"].choices = [("", "All entities"), *ENTITY_TYPES.items()]
        self.fields["action"].choices = [("", "All actions"), *ConfigAuditEvent.Action.choices]


@admin_only
@require_http_methods(["GET"])
def audit_log(request):
    """Who changed which configuration, from what to what, and when. Never editable."""
    form = AuditFilterForm(request.GET or None)
    events = ConfigAuditEvent.objects.all()
    if form.is_valid():
        data = form.cleaned_data
        if data["entity_type"]:
            # Older databases may hold lowercase entity names from before the class-name
            # convention; the table is append-only, so match case-insensitively.
            events = events.filter(entity_type__iexact=data["entity_type"])
        if data["action"]:
            events = events.filter(action=data["action"])
        if data["actor"]:
            events = events.filter(actor_identifier__icontains=data["actor"].strip())
        if data["date_from"]:
            events = events.filter(created_at__date__gte=data["date_from"])
        if data["date_to"]:
            events = events.filter(created_at__date__lte=data["date_to"])
    page = Paginator(events, 50).get_page(request.GET.get("page"))
    keep = request.GET.copy()
    keep.pop("page", None)
    return render(
        request,
        "accounts/admin_audit.html",
        {"form": form, "page": page, "filter_query": keep.urlencode()},
        status=400 if form.is_bound and not form.is_valid() else 200,
    )
