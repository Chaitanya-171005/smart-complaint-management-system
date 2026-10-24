"""B04: current-role and object permission checks (TC-02, TC-13, REQ-ACC-01, BR-01)."""

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.test import Client, RequestFactory

from . import permissions as perm
from .models import Department, SecurityEvent

User = get_user_model()
PASSWORD = "Campus123"


@pytest.fixture(autouse=True)
def fast_hasher(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def depts(db):
    return Department.objects.create(name="Hostel"), Department.objects.create(name="IT")


def make(email, role, dept=None):
    return User.objects.create_user(
        email=email, password=PASSWORD, full_name=email, role=role, department=dept
    )


@pytest.fixture
def world(depts):
    hostel, it = depts
    w = SimpleNamespace(
        hostel=hostel,
        it=it,
        owner=make("owner@pes.edu", "COMPLAINANT"),
        other=make("other@pes.edu", "COMPLAINANT"),
        staff=make("staff@pes.edu", "STAFF", hostel),
        staff2=make("staff2@pes.edu", "STAFF", hostel),
        it_staff=make("itstaff@pes.edu", "STAFF", it),
        head=make("head@pes.edu", "HEAD", hostel),
        it_head=make("ithead@pes.edu", "HEAD", it),
        admin=make("admin@pes.edu", "ADMIN"),
    )
    w.c = SimpleNamespace(
        pk=1, submitted_by=w.owner, department=hostel, assignee=w.staff
    )
    w.unassigned = SimpleNamespace(pk=2, submitted_by=w.owner, department=hostel, assignee=None)
    w.anon = SimpleNamespace(pk=3, submitted_by=None, department=hostel, assignee=w.staff)
    return w


# --- viewing -----------------------------------------------------------------------


def test_owner_sees_own_complaint_only(world):
    assert perm.can_view_complaint(world.owner, world.c)
    assert not perm.can_view_complaint(world.other, world.c)


def test_staff_and_head_scoped_to_own_department(world):
    assert perm.can_view_complaint(world.staff, world.c)
    assert perm.can_view_complaint(world.head, world.c)
    assert not perm.can_view_complaint(world.it_staff, world.c)
    assert not perm.can_view_complaint(world.it_head, world.c)


def test_unassigned_staff_in_same_department_can_view_queue_item(world):
    assert perm.can_view_complaint(world.staff2, world.c)


def test_anonymous_complaint_has_no_owner_access(world):
    assert not perm.can_view_complaint(world.owner, world.anon)
    assert not perm.can_view_complaint(world.other, world.anon)


@pytest.mark.parametrize("who", ["admin"])
def test_admin_cannot_read_complaint_details_evidence_or_queue(world, who):
    # SRS 2.2 / REQ-ACC-01: Administrator reads campus reports, not individual complaints.
    admin = getattr(world, who)
    for c in (world.c, world.unassigned, world.anon):
        assert not perm.can_view_complaint(admin, c)
        assert not perm.can_view_evidence(admin, c)
    assert not perm.can_view_department_queue(admin, world.hostel)
    assert not perm.can_view_department_queue(admin, world.it)


def test_unauthenticated_and_inactive_are_refused(world):
    from django.contrib.auth.models import AnonymousUser

    assert not perm.can_view_complaint(AnonymousUser(), world.c)
    assert not perm.can_view_complaint(None, world.c)
    world.owner.is_active = False
    assert not perm.can_view_complaint(world.owner, world.c)


def test_evidence_follows_complaint(world):
    assert perm.can_view_evidence(world.owner, world.c)
    assert not perm.can_view_evidence(world.other, world.c)
    assert not perm.can_view_evidence(world.it_staff, world.c)


# --- acting ------------------------------------------------------------------------


def test_only_assigned_staff_can_resolve(world):
    assert perm.can_resolve_complaint(world.staff, world.c)
    assert not perm.can_resolve_complaint(world.staff2, world.c)
    assert not perm.can_resolve_complaint(world.it_staff, world.c)
    assert not perm.can_resolve_complaint(world.staff, world.unassigned)
    for u in (world.owner, world.head, world.admin):
        assert not perm.can_resolve_complaint(u, world.c)


def test_progress_assigned_staff_or_department_head(world):
    assert perm.can_progress_complaint(world.staff, world.c)
    assert perm.can_progress_complaint(world.head, world.c)
    assert not perm.can_progress_complaint(world.staff2, world.c)
    assert not perm.can_progress_complaint(world.it_head, world.c)
    assert not perm.can_progress_complaint(world.owner, world.c)


def test_reject_roles(world):
    assert perm.can_reject_complaint(world.admin, world.c)
    assert perm.can_reject_complaint(world.head, world.c)
    assert perm.can_reject_complaint(world.staff, world.c)
    assert not perm.can_reject_complaint(world.staff2, world.c)
    assert not perm.can_reject_complaint(world.it_head, world.c)
    assert not perm.can_reject_complaint(world.owner, world.c)


def test_allocation_only_by_own_department_head(world):
    assert perm.can_allocate_complaint(world.head, world.c)
    assert not perm.can_allocate_complaint(world.it_head, world.c)
    for u in (world.staff, world.owner, world.admin):
        assert not perm.can_allocate_complaint(u, world.c)


def test_allocation_target_must_be_active_staff_of_same_department(world):
    assert perm.can_allocate_complaint(world.head, world.c, world.staff2)
    assert not perm.can_allocate_complaint(world.head, world.c, world.it_staff)
    assert not perm.can_allocate_complaint(world.head, world.c, world.owner)
    world.staff2.is_active = False
    assert not perm.can_allocate_complaint(world.head, world.c, world.staff2)


def test_only_originating_complainant_confirms_resolution(world):
    assert perm.can_confirm_resolution(world.owner, world.c)
    assert not perm.can_confirm_resolution(world.other, world.c)
    assert not perm.can_confirm_resolution(world.staff, world.c)
    assert not perm.can_confirm_resolution(world.owner, world.anon)


# --- departments, reports, admin ---------------------------------------------------


def test_department_queue_access(world):
    assert perm.can_view_department_queue(world.staff, world.hostel)
    assert perm.can_view_department_queue(world.head, world.hostel.pk)
    assert not perm.can_view_department_queue(world.staff, world.it)
    assert not perm.can_view_department_queue(world.admin, world.it)
    assert not perm.can_view_department_queue(world.owner, world.hostel)


def test_reports_and_admin_functions(world):
    assert perm.can_view_report(world.admin)
    assert not perm.can_view_report(world.head)  # campus-wide is Admin only
    assert perm.can_view_report(world.head, world.hostel)
    assert not perm.can_view_report(world.head, world.it)
    assert not perm.can_view_report(world.staff, world.hostel)
    assert not perm.can_view_report(world.owner)
    for check in (perm.can_manage_configuration, perm.can_manage_users):
        assert check(world.admin)
        for u in (world.head, world.staff, world.owner):
            assert not check(u)


# --- list scoping ------------------------------------------------------------------


def test_scope_queryset_by_role(world):
    # User rows stand in for complaints: "pk" plays owner, "department" is the same.
    qs = User.objects.all()
    kw = {"owner_field": "pk", "department_field": "department"}
    assert not perm.scope_complaints(world.admin, qs, **kw).exists()
    assert list(perm.scope_complaints(world.owner, qs, **kw)) == [world.owner]
    staff_rows = set(perm.scope_complaints(world.staff, qs, **kw))
    assert staff_rows == {world.staff, world.staff2, world.head}
    assert not perm.scope_complaints(world.it_staff, qs, **kw).filter(pk=world.staff.pk).exists()


def test_scope_is_empty_for_anonymous_and_departmentless_staff(world, db):
    from django.contrib.auth.models import AnonymousUser

    qs = User.objects.all()
    assert not perm.scope_complaints(AnonymousUser(), qs).exists()
    orphan = make("orphan@pes.edu", "STAFF", None)
    assert not perm.scope_complaints(orphan, qs, department_field="department").exists()


# --- current role, not login-time role ---------------------------------------------


def test_role_change_applies_on_next_request(world):
    @perm.role_required("HEAD")
    def view(request):
        return HttpResponse("ok")

    c = Client()
    c.post("/accounts/login/", {"email": "head@pes.edu", "password": PASSWORD})
    rf = RequestFactory()

    def hit():
        req = rf.get("/x/")
        # Load the user fresh, as the auth middleware does on every request.
        req.user = User.objects.get(pk=world.head.pk)
        return view(req)

    assert hit().status_code == 200
    User.objects.filter(pk=world.head.pk).update(role="COMPLAINANT")
    with pytest.raises(PermissionDenied):
        hit()


def test_department_change_applies_immediately(world):
    assert perm.can_view_complaint(world.staff, world.c)
    User.objects.filter(pk=world.staff.pk).update(department=world.it)
    fresh = User.objects.get(pk=world.staff.pk)
    assert not perm.can_view_complaint(fresh, world.c)


def test_deactivated_user_loses_access_at_once(world):
    User.objects.filter(pk=world.staff.pk).update(is_active=False)
    fresh = User.objects.get(pk=world.staff.pk)
    assert not perm.can_resolve_complaint(fresh, world.c)


# --- decorator / mixin / enforcement ----------------------------------------------


def _request(user=None):
    req = RequestFactory().get("/protected/?a=1")
    from django.contrib.auth.models import AnonymousUser

    req.user = user or AnonymousUser()
    return req


def test_role_required_redirects_anonymous_to_login(db):
    @perm.role_required("ADMIN")
    def view(request):
        return HttpResponse("ok")

    resp = view(_request())
    assert resp.status_code == 302
    assert resp["Location"].startswith("/accounts/login/")


def test_role_required_forbids_wrong_role_and_logs(world):
    @perm.role_required("ADMIN")
    def view(request):
        return HttpResponse("ok")

    with pytest.raises(PermissionDenied):
        view(_request(world.head))
    ev = SecurityEvent.objects.get(event_type=SecurityEvent.EventType.AUTHORIZATION_REFUSED)
    assert ev.user == world.head
    assert "role_required" in ev.detail


def test_role_required_allows_listed_roles(world):
    @perm.role_required("ADMIN", "HEAD")
    def view(request):
        return HttpResponse("ok")

    assert view(_request(world.head)).status_code == 200
    assert view(_request(world.admin)).status_code == 200


def test_mixin_matches_decorator(world):
    class Base:
        def dispatch(self, request, *a, **k):
            return HttpResponse("ok")

    class View(perm.RoleRequiredMixin, Base):
        allowed_roles = ("HEAD",)

    assert View().dispatch(_request(world.head)).status_code == 200
    assert View().dispatch(_request()).status_code == 302
    with pytest.raises(PermissionDenied):
        View().dispatch(_request(world.staff))


def test_authorize_or_404_hides_existence(world):
    assert perm.authorize_or_404(perm.can_view_complaint, world.owner, world.c) is world.c
    with pytest.raises(Http404):
        perm.authorize_or_404(perm.can_view_complaint, world.other, world.c)
    with pytest.raises(Http404):
        perm.authorize_or_404(perm.can_view_complaint, world.owner, None)
    assert SecurityEvent.objects.filter(
        event_type=SecurityEvent.EventType.AUTHORIZATION_REFUSED, user=world.other
    ).exists()


def test_require_permission_raises_403_and_logs(world):
    perm.require_permission(perm.can_resolve_complaint, world.staff, world.c)
    with pytest.raises(PermissionDenied):
        perm.require_permission(perm.can_resolve_complaint, world.staff2, world.c)
    assert SecurityEvent.objects.filter(
        event_type=SecurityEvent.EventType.AUTHORIZATION_REFUSED, user=world.staff2
    ).exists()


def test_refusal_log_has_no_request_data(world):
    with pytest.raises(PermissionDenied):
        perm.require_permission(perm.can_resolve_complaint, world.staff2, world.c)
    ev = SecurityEvent.objects.get()
    assert PASSWORD not in ev.detail and "a=1" not in ev.detail


def test_refusal_does_not_change_data(world):
    before = list(User.objects.order_by("pk").values_list("pk", "role", "department_id"))
    with pytest.raises(PermissionDenied):
        perm.require_permission(perm.can_allocate_complaint, world.staff, world.c)
    after = list(User.objects.order_by("pk").values_list("pk", "role", "department_id"))
    assert before == after


# --- landing pages (TC-02) ---------------------------------------------------------


@pytest.mark.parametrize(
    "email,own,other",
    [
        ("owner@pes.edu", "complainant", "admin"),
        ("staff@pes.edu", "staff", "head"),
        ("head@pes.edu", "head", "admin"),
        ("admin@pes.edu", "admin", "staff"),
    ],
)
def test_landing_pages_by_role(world, email, own, other):
    c = Client()
    c.post("/accounts/login/", {"email": email, "password": PASSWORD})
    assert c.get(f"/accounts/landing/{own}/").status_code == 200
    r = c.get(f"/accounts/landing/{other}/")
    assert r.status_code == 302
    assert r["Location"].endswith(f"/accounts/landing/{own}/")


def test_landing_follows_role_change_on_next_request(world):
    c = Client()
    c.post("/accounts/login/", {"email": "staff@pes.edu", "password": PASSWORD})
    assert c.get("/accounts/landing/staff/").status_code == 200
    User.objects.filter(pk=world.staff.pk).update(role="HEAD")
    assert c.get("/accounts/landing/staff/").status_code == 302
    assert c.get("/accounts/landing/head/").status_code == 200
