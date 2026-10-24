"""B04 integration tests: the permission helpers against real database rows.

``complaints.Complaint`` does not exist yet (F2, Atul). Until it is merged these tests use
a test-only ``StandInComplaint`` model (see the ``complaint_model`` fixture) with the agreed field contract (docs/AUTHORIZATION.md):
``submitted_by`` (User or null for anonymous), ``department`` and ``assignee`` (User or null).
When the real model lands, ``test_real_complaint_model_follows_contract`` starts running
instead of skipping; then point ``complaint_model`` below at the real model and adapt
``new_complaint`` to its required fields.
"""

import itertools

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, models

from . import permissions as perm
from .models import Department

User = get_user_model()


@pytest.fixture(autouse=True)
def fast_hasher(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def complaint_model(transactional_db):
    """Test-only stand-in for complaints.Complaint (field names are the contract).

    Defined and registered only for the duration of one test, so no other test (for
    example a transactional one that flushes every registered table) ever sees it.
    """

    class StandInComplaint(models.Model):
        submitted_by = models.ForeignKey(
            settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="+"
        )
        department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="+")
        assignee = models.ForeignKey(
            settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="+"
        )

        class Meta:
            app_label = "accounts"

    with connection.schema_editor() as editor:
        editor.create_model(StandInComplaint)
    try:
        yield StandInComplaint
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(StandInComplaint)
        apps.all_models["accounts"].pop("standincomplaint", None)
        apps.clear_cache()


def person(email, role, dept=None):
    return User.objects.create_user(
        email=email, password="Campus123", full_name=email, role=role, department=dept
    )


def new_complaint(model, *, submitted_by, department, assignee=None):
    return model.objects.create(
        submitted_by=submitted_by, department=department, assignee=assignee
    )


@pytest.fixture
def campus(complaint_model):
    hostel = Department.objects.create(name="Hostel")
    it = Department.objects.create(name="IT")
    p = type("P", (), {})()
    p.hostel, p.it = hostel, it
    p.alice = person("alice@pes.edu", "COMPLAINANT")
    p.bob = person("bob@pes.edu", "COMPLAINANT")
    p.h_staff1 = person("hs1@pes.edu", "STAFF", hostel)
    p.h_staff2 = person("hs2@pes.edu", "STAFF", hostel)
    p.it_staff = person("its@pes.edu", "STAFF", it)
    p.h_head = person("hh@pes.edu", "HEAD", hostel)
    p.it_head = person("ith@pes.edu", "HEAD", it)
    p.admin = person("admin@pes.edu", "ADMIN")
    m = complaint_model
    p.c_alice_hostel = new_complaint(m, submitted_by=p.alice, department=hostel, assignee=p.h_staff1)
    p.c_bob_hostel = new_complaint(m, submitted_by=p.bob, department=hostel)  # unassigned
    p.c_alice_it = new_complaint(m, submitted_by=p.alice, department=it, assignee=p.it_staff)
    p.c_anon_hostel = new_complaint(m, submitted_by=None, department=hostel, assignee=p.h_staff2)
    p.all = [p.c_alice_hostel, p.c_bob_hostel, p.c_alice_it, p.c_anon_hostel]
    p.users = [
        p.alice, p.bob, p.h_staff1, p.h_staff2, p.it_staff, p.h_head, p.it_head, p.admin,
    ]
    return p


def visible(user, model):
    return set(perm.scope_complaints(user, model.objects.all()).values_list("pk", flat=True))


def pks(*complaints):
    return {c.pk for c in complaints}


# --- ownership ---------------------------------------------------------------------


def test_complainant_sees_only_own_complaints(campus, complaint_model):
    assert visible(campus.alice, complaint_model) == pks(campus.c_alice_hostel, campus.c_alice_it)
    assert visible(campus.bob, complaint_model) == pks(campus.c_bob_hostel)


def test_anonymous_complaints_belong_to_no_account(campus, complaint_model):
    for who in (campus.alice, campus.bob):
        assert campus.c_anon_hostel.pk not in visible(who, complaint_model)
        assert not perm.can_view_complaint(who, campus.c_anon_hostel)
        assert not perm.can_confirm_resolution(who, campus.c_anon_hostel)


def test_only_originating_complainant_can_confirm(campus):
    assert perm.can_confirm_resolution(campus.alice, campus.c_alice_hostel)
    assert not perm.can_confirm_resolution(campus.bob, campus.c_alice_hostel)
    assert not perm.can_confirm_resolution(campus.h_staff1, campus.c_alice_hostel)


# --- department boundaries ---------------------------------------------------------


def test_staff_and_head_see_only_their_department(campus, complaint_model):
    hostel = pks(campus.c_alice_hostel, campus.c_bob_hostel, campus.c_anon_hostel)
    assert visible(campus.h_staff1, complaint_model) == hostel
    assert visible(campus.h_staff2, complaint_model) == hostel
    assert visible(campus.h_head, complaint_model) == hostel
    assert visible(campus.it_staff, complaint_model) == pks(campus.c_alice_it)
    assert visible(campus.it_head, complaint_model) == pks(campus.c_alice_it)


def test_other_department_access_is_refused_for_every_action(campus):
    c = campus.c_alice_it
    for u in (campus.h_staff1, campus.h_head):
        assert not perm.can_view_complaint(u, c)
        assert not perm.can_progress_complaint(u, c)
        assert not perm.can_resolve_complaint(u, c)
        assert not perm.can_reject_complaint(u, c)
        assert not perm.can_allocate_complaint(u, c)


def test_queue_visibility_does_not_authorize_unassigned_staff_to_resolve(campus):
    c = campus.c_alice_hostel  # assigned to h_staff1
    assert perm.can_view_complaint(campus.h_staff2, c)
    assert not perm.can_progress_complaint(campus.h_staff2, c)
    assert not perm.can_resolve_complaint(campus.h_staff2, c)
    assert perm.can_resolve_complaint(campus.h_staff1, c)
    assert not perm.can_resolve_complaint(campus.h_staff1, campus.c_bob_hostel)  # unassigned


def test_allocation_only_by_own_department_head_to_own_staff(campus):
    c = campus.c_bob_hostel
    assert perm.can_allocate_complaint(campus.h_head, c, campus.h_staff1)
    assert not perm.can_allocate_complaint(campus.h_head, c, campus.it_staff)
    assert not perm.can_allocate_complaint(campus.it_head, c, campus.h_staff1)
    assert not perm.can_allocate_complaint(campus.h_staff1, c, campus.h_staff2)


# --- confirmed Administrator permissions (SRS 2.2, REQ-ACC-01) ----------------------


def test_admin_has_no_access_to_complaint_content(campus, complaint_model):
    assert visible(campus.admin, complaint_model) == set()
    for c in campus.all:
        assert not perm.can_view_complaint(campus.admin, c)
        assert not perm.can_view_evidence(campus.admin, c)
        assert not perm.can_progress_complaint(campus.admin, c)
        assert not perm.can_resolve_complaint(campus.admin, c)
        assert not perm.can_allocate_complaint(campus.admin, c)
        assert not perm.can_confirm_resolution(campus.admin, c)
    assert not perm.can_view_department_queue(campus.admin, campus.hostel)


def test_admin_keeps_its_listed_powers(campus):
    c = campus.c_bob_hostel
    assert perm.can_reject_complaint(campus.admin, c)  # state model: from SUBMITTED, F4 checks state
    assert perm.can_view_report(campus.admin)
    assert perm.can_manage_configuration(campus.admin)
    assert perm.can_manage_users(campus.admin)
    for u in (campus.h_head, campus.h_staff1, campus.alice):
        assert not perm.can_manage_users(u)
        assert not perm.can_manage_configuration(u)
        assert not perm.can_view_report(u)  # campus-wide


# --- list scoping and object checks must agree --------------------------------------


def test_list_scope_and_object_check_agree_for_every_user_and_complaint(campus, complaint_model):
    for user, complaint in itertools.product(campus.users, campus.all):
        in_list = complaint.pk in visible(user, complaint_model)
        assert in_list == perm.can_view_complaint(user, complaint), (user.email, complaint.pk)


def test_changes_apply_on_the_next_query(campus, complaint_model):
    assert campus.c_alice_hostel.pk in visible(campus.h_staff1, complaint_model)
    User.objects.filter(pk=campus.h_staff1.pk).update(department=campus.it)
    moved = User.objects.get(pk=campus.h_staff1.pk)
    assert campus.c_alice_hostel.pk not in visible(moved, complaint_model)
    assert campus.c_alice_it.pk in visible(moved, complaint_model)
    User.objects.filter(pk=campus.h_staff1.pk).update(role="COMPLAINANT", department=None)
    demoted = User.objects.get(pk=campus.h_staff1.pk)
    assert visible(demoted, complaint_model) == set()


def test_fresh_rows_from_the_database_work_without_loading_related_objects(campus, complaint_model):
    fresh = complaint_model.objects.get(pk=campus.c_alice_hostel.pk)  # only *_id values loaded
    assert perm.can_view_complaint(campus.alice, fresh)
    assert perm.can_resolve_complaint(campus.h_staff1, fresh)
    assert not perm.can_resolve_complaint(campus.h_staff2, fresh)


# --- contract with the real model (F2) ----------------------------------------------


def test_real_complaint_model_follows_contract():
    try:
        real = apps.get_model("complaints", "Complaint")
    except LookupError:
        pytest.skip("complaints.Complaint is not merged yet; contract: docs/AUTHORIZATION.md")
    fields = {f.name: f for f in real._meta.get_fields()}
    for name in (perm.OWNER_FIELD, perm.DEPARTMENT_FIELD, perm.ASSIGNEE_FIELD):
        assert name in fields, f"Complaint must have a '{name}' field (docs/AUTHORIZATION.md)"
    assert fields[perm.OWNER_FIELD].null, "anonymous complaints have no submitter"
    assert fields[perm.OWNER_FIELD].related_model is User
    assert fields[perm.DEPARTMENT_FIELD].related_model is Department
    assert fields[perm.ASSIGNEE_FIELD].related_model is User
