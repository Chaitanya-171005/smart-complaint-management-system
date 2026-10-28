"""B07 / TC-03: validation boundaries, active references and safe bound values."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from accounts.models import User
from complaints.forms import ComplaintForm
from complaints.reference_data import CategoryOption, LocationOption
from complaints.services import build_complaint_form


@pytest.fixture
def options():
    # Synthetic test options only; not confirmed campus categories or locations.
    return {
        "categories": (
            CategoryOption("synthetic-active", "Synthetic active category"),
            CategoryOption("synthetic-inactive", "Synthetic inactive category", active=False),
        ),
        "locations": (
            LocationOption("synthetic-room", "Synthetic Block", "Synthetic Room", "1"),
            LocationOption("synthetic-closed", "Synthetic Block", "Closed Room", active=False),
        ),
    }


@pytest.fixture
def payload():
    return {
        "category": "synthetic-active",
        "sub_category": "",
        "location": "synthetic-room",
        "title": "Synthetic maintenance request",
        "description": "This is a synthetic description for form validation.",
        "priority": ComplaintForm.Priority.MEDIUM,
    }


def bind(options, payload):
    return ComplaintForm(payload, **options)


def test_valid_input_returns_canonical_reference_options(options, payload):
    form = bind(options, payload)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["category"] is options["categories"][0]
    assert form.cleaned_data["location"] is options["locations"][0]
    assert form.cleaned_data["priority"] == ComplaintForm.Priority.MEDIUM
    assert form.cleaned_data["sub_category"] == ""
    assert not hasattr(form, "save")


@pytest.mark.parametrize("field", ["category", "location", "title", "description", "priority"])
def test_required_fields(options, payload, field):
    payload.pop(field)
    form = bind(options, payload)
    assert not form.is_valid()
    assert form.has_error(field, "required")


@pytest.mark.parametrize(
    "field,length,valid",
    [
        ("title", 120, True), ("title", 121, False),
        ("description", 19, False), ("description", 20, True),
        ("description", 2000, True), ("description", 2001, False),
        ("sub_category", 50, True), ("sub_category", 51, False),
    ],
)
def test_field_length_boundaries(options, payload, field, length, valid):
    payload[field] = "x" * length
    form = bind(options, payload)
    assert form.is_valid() is valid
    if not valid:
        assert field in form.errors


def test_whitespace_is_trimmed_before_description_minimum(options, payload):
    payload["description"] = "  " + "x" * 19 + "  "
    form = bind(options, payload)
    assert not form.is_valid()
    assert form.has_error("description", "min_length")


@pytest.mark.parametrize("field", ["title", "description"])
def test_whitespace_only_required_text_is_rejected(options, payload, field):
    payload[field] = "   "
    form = bind(options, payload)
    assert not form.is_valid()
    assert form.has_error(field, "required")


@pytest.mark.parametrize(
    "field,value",
    [
        ("category", "synthetic-inactive"), ("category", "unknown"),
        ("location", "synthetic-closed"), ("location", "unknown"),
        ("priority", "ADMIN"), ("priority", "medium"),
    ],
)
def test_inactive_unknown_or_invalid_choices_are_refused(options, payload, field, value):
    payload[field] = value
    form = bind(options, payload)
    assert not form.is_valid()
    assert form.has_error(field, "invalid_choice")


@pytest.mark.parametrize("priority", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
def test_supported_indicated_priorities(options, payload, priority):
    payload["priority"] = priority
    assert bind(options, payload).is_valid()


def test_missing_reference_configuration_cannot_validate(payload):
    form = ComplaintForm(payload, categories=(), locations=())
    assert not form.is_valid()
    assert "category" in form.errors and "location" in form.errors


def test_safe_values_survive_errors_and_html_is_escaped(options, payload):
    payload["title"] = "<script>alert(1)</script>"
    payload["location"] = "unknown"
    form = bind(options, payload)
    assert not form.is_valid()
    assert form["description"].value() == payload["description"]
    assert form["category"].value() == payload["category"]
    assert form["title"].value() == payload["title"]
    rendered = form.as_p()
    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "Select a valid choice" in rendered


def test_client_cannot_supply_role_owner_state_or_department(options, payload):
    payload.update(role="ADMIN", submitted_by="123", department="456", status="CLOSED")
    form = bind(options, payload)
    assert form.is_valid()
    assert {"role", "submitted_by", "department", "status"}.isdisjoint(form.cleaned_data)


@pytest.mark.parametrize("name", ["", "x" * 51, "   ", " " * 50 + "x"])
def test_bad_category_configuration_is_refused(options, payload, name):
    options["categories"] = (CategoryOption("synthetic-active", name),)
    form = bind(options, payload)
    assert not form.is_valid()
    assert "category" in form.errors


@pytest.mark.parametrize(
    "block,floor,room",
    [
        ("", "1", "Room"), ("x" * 21, "1", "Room"),
        ("Block", "x" * 11, "Room"), ("Block", "1", ""),
        ("Block", "1", "x" * 31),
        ("   ", "1", "Room"), ("Block", "1", "   "),
        (" " * 20 + "x", "1", "Room"),
    ],
)
def test_bad_location_configuration_is_refused(options, payload, block, floor, room):
    options["locations"] = (LocationOption("synthetic-room", block, room, floor),)
    form = bind(options, payload)
    assert not form.is_valid()
    assert "location" in form.errors


def test_exact_reference_field_limits(options, payload):
    options["categories"] = (CategoryOption("synthetic-active", "x" * 50),)
    options["locations"] = (LocationOption("synthetic-room", "x" * 20, "x" * 30, "x" * 10),)
    assert bind(options, payload).is_valid()


def test_optional_floor_can_be_empty(options, payload):
    options["locations"] = (LocationOption("synthetic-room", "Block", "Room"),)
    assert bind(options, payload).is_valid()


def test_location_label_uses_block_floor_and_room(options):
    assert options["locations"][0].label == "Synthetic Block / 1 / Synthetic Room"


def test_reference_deactivation_is_rechecked_for_new_bound_form(options, payload):
    assert bind(options, payload).is_valid()
    options["categories"] = (CategoryOption("synthetic-active", "Synthetic category", active=False),)
    assert not bind(options, payload).is_valid()


@pytest.mark.parametrize(
    "records,error",
    [
        ((object(),), TypeError),
        ((CategoryOption("", "Synthetic"),), ValueError),
        ((CategoryOption(" ", "Synthetic"),), ValueError),
        ((CategoryOption("same", "One"), CategoryOption("same", "Two")), ValueError),
    ],
)
def test_reference_contract_rejects_ambiguous_configuration(options, records, error):
    options["categories"] = records
    with pytest.raises(error):
        ComplaintForm(**options)


def test_authorized_form_construction(complainant_user, options, payload):
    form = build_complaint_form(complainant_user, payload, **options)
    assert form.is_valid()


@pytest.mark.parametrize("role", [User.Role.STAFF, User.Role.HEAD, User.Role.ADMIN])
def test_other_roles_are_refused(user_factory, options, payload, role):
    user = user_factory(role=role)
    with pytest.raises(PermissionDenied):
        build_complaint_form(user, payload, **options)


def test_inactive_complainant_is_refused(user_factory, options, payload):
    user = user_factory(is_active=False)
    with pytest.raises(PermissionDenied):
        build_complaint_form(user, payload, **options)


@pytest.mark.django_db
def test_anonymous_user_is_refused(options, payload):
    with pytest.raises(PermissionDenied):
        build_complaint_form(AnonymousUser(), payload, **options)


def test_refreshed_user_role_change_is_respected(complainant_user, options, payload):
    User.objects.filter(pk=complainant_user.pk).update(role=User.Role.ADMIN)
    complainant_user.refresh_from_db()
    with pytest.raises(PermissionDenied):
        build_complaint_form(complainant_user, payload, **options)
