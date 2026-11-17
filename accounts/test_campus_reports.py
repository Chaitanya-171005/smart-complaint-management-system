"""B30 / REQ-RPT-01 / TC-14: campus report figures, date boundaries, CSV equality, privacy, access.

Fixed datasets, so every expected number is written out by hand rather than recomputed.
"""

import csv
import io
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.test import Client

from accounts import campus_reports as reports
from complaints.models import Complaint

pytestmark = pytest.mark.django_db

URL = "/accounts/admin-config/reports/"
UTC = dt_timezone.utc
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def at(day, hour=9, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def login(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def make(complaint_factory, category_factory, location_factory):
    """Create a complaint with plain keyword values; resolved_after_hours sets resolved_at."""
    wiring, library = category_factory(name="B30 Wiring"), category_factory(name="B30 Plumbing")
    hall, lab = location_factory(code="B30-HALL"), location_factory(code="B30-LAB")
    refs = {"wiring": wiring, "plumbing": library, "hall": hall, "lab": lab}

    def create(day, *, category="wiring", location="hall", resolved_after_hours=None, hour=9, **overrides):
        submitted = at(day, hour)
        if resolved_after_hours is not None:
            overrides["resolved_at"] = submitted + timedelta(hours=resolved_after_hours)
        return complaint_factory(
            category_record=refs[category], location_record=refs[location], submitted_at=submitted,
            due_at=overrides.pop("due_at", submitted + timedelta(hours=24)), **overrides,
        )

    return create


S = Complaint.Status


@pytest.fixture
def dataset(make, department_factory):
    """Nine complaints in 10-12 Nov plus two outside the range."""
    other = department_factory()
    make(10, status=S.CLOSED, resolved_after_hours=2, closed_at=at(11))
    make(10, category="plumbing", location="lab", status=S.RESOLVED, resolved_after_hours=4)
    make(11, status=S.IN_PROGRESS, is_escalated=True, escalation_level=1)  # open and overdue (due 12 Nov 09:00)
    make(11, status=S.REOPENED, reopen_count=2, resolved_after_hours=6)  # open, overdue, reopened twice
    make(12, status=S.ASSIGNED, due_at=at(30))  # open, not overdue
    make(12, status=S.REJECTED)
    make(12, status=S.SUBMITTED, department=other, category="plumbing", location="lab", due_at=at(30))
    make(12, hour=23, status=S.CLOSED, resolved_after_hours=8, reopen_count=1, department=other)
    make(12, status=S.ASSIGNED, anonymous=True, due_at=at(30))
    make(9, status=S.ASSIGNED)   # before the range
    make(13, status=S.ASSIGNED)  # after the range
    return other


# --- figures ----------------------------------------------------------------------------------


def test_counts_groups_and_open_metrics_on_a_fixed_dataset(dataset):
    report = reports.build_report(date(2026, 11, 10), date(2026, 11, 12), now=NOW)

    assert report.total == 9
    assert dict(report.by_category) == {"B30 Wiring": 7, "B30 Plumbing": 2}
    assert dict(report.by_location) == {"B30-HALL": 7, "B30-LAB": 2}
    assert sorted(count for _, count in report.by_department) == [2, 7]
    # open: IN_PROGRESS, REOPENED, ASSIGNED, SUBMITTED, ASSIGNED(anonymous) = 5
    assert report.open_count == 5
    # overdue = open and due before NOW: the 11 Nov IN_PROGRESS and REOPENED complaints (due 12 Nov)
    assert report.overdue_count == 2
    assert report.escalated_count == 1
    assert report.reopened_count == 2
    assert report.reopen_total == 3


def test_groups_are_ordered_by_volume_then_label(dataset):
    report = reports.build_report(date(2026, 11, 10), date(2026, 11, 12), now=NOW)
    assert report.by_category == [("B30 Wiring", 7), ("B30 Plumbing", 2)]


def test_mean_and_median_resolution_time(dataset):
    report = reports.build_report(date(2026, 11, 10), date(2026, 11, 12), now=NOW)
    # Resolved or Closed now: 2, 4 and 8 hours. The REOPENED complaint (6 hours, stale resolved_at) is not measured.
    assert report.resolved_measured == 3
    assert report.mean_hours == Decimal("4.67")
    assert report.median_hours == Decimal("4.00")


def test_median_differs_from_mean_with_an_odd_set(make):
    for hours in (1, 2, 12):
        make(10, status=S.CLOSED, resolved_after_hours=hours)
    report = reports.build_report(date(2026, 11, 10), date(2026, 11, 10), now=NOW)
    assert report.mean_hours == Decimal("5.00")
    assert report.median_hours == Decimal("2.00")


@pytest.mark.parametrize("status", [S.REOPENED, S.IN_PROGRESS, S.ASSIGNED])
def test_a_complaint_worked_again_after_resolution_is_not_measured(make, status):
    """F4 keeps resolved_at when a resolution is rejected; that old time must not count."""
    make(10, status=S.CLOSED, resolved_after_hours=2)
    make(10, status=status, resolved_after_hours=50, reopen_count=1)
    report = reports.build_report(date(2026, 11, 10), date(2026, 11, 10), now=NOW)
    assert report.resolved_measured == 1
    assert report.mean_hours == Decimal("2.00")


def test_non_positive_durations_are_excluded_and_counted(make):
    make(10, status=S.CLOSED, resolved_after_hours=3)
    make(10, status=S.CLOSED, resolved_after_hours=0)
    make(10, status=S.CLOSED, resolved_after_hours=-1)
    report = reports.build_report(date(2026, 11, 10), date(2026, 11, 10), now=NOW)
    assert (report.resolved_measured, report.resolved_excluded) == (1, 2)
    assert report.mean_hours == Decimal("3.00")


def test_empty_range_gives_zeros_and_no_averages(make):
    make(10)
    report = reports.build_report(date(2026, 11, 1), date(2026, 11, 2), now=NOW)
    assert report.total == 0
    assert (report.open_count, report.overdue_count, report.escalated_count) == (0, 0, 0)
    assert (report.reopened_count, report.reopen_total) == (0, 0)
    assert report.by_category == report.by_location == report.by_department == []
    assert report.mean_hours is None and report.median_hours is None


# --- date boundaries ----------------------------------------------------------------------------


def test_both_selected_days_are_whole_days_and_included(make):
    make(10, hour=0)    # first instant of the start day: in
    make(10, hour=23)   # still the start day: in
    make(11, hour=23)   # last day, late: in
    make(12, hour=0)    # first instant of the next day: out
    report = reports.build_report(date(2026, 11, 10), date(2026, 11, 11), now=NOW)
    assert report.total == 3


def test_single_day_range_is_valid(make):
    make(10)
    assert reports.build_report(date(2026, 11, 10), date(2026, 11, 10), now=NOW).total == 1


def test_inverted_and_overlong_ranges_are_refused():
    with pytest.raises(ValueError):
        reports.build_report(date(2026, 11, 12), date(2026, 11, 10))
    with pytest.raises(ValueError):
        reports.build_report(date(2025, 1, 1), date(2026, 11, 10))


@pytest.mark.parametrize("date_from, date_to", [
    (date(9999, 12, 30), date(9999, 12, 31)),   # the reviewed OverflowError case
    (date(9999, 12, 31), date(9999, 12, 31)),
    (date(1, 1, 1), date(1, 1, 2)),
    (date(1999, 12, 31), date(2000, 1, 1)),
    (date(2100, 12, 31), date(2101, 1, 1)),
])
def test_dates_outside_the_supported_window_are_refused_not_crashed(date_from, date_to):
    with pytest.raises(ValueError):
        reports.date_window(date_from, date_to)


def test_the_supported_window_edges_are_allowed():
    reports.date_window(date(2000, 1, 1), date(2000, 1, 1))
    reports.date_window(date(2100, 12, 31), date(2100, 12, 31))


def test_a_twelve_month_range_is_allowed():
    reports.date_window(date(2025, 11, 17), date(2026, 11, 16))


def test_overdue_is_judged_at_the_report_moment(make):
    make(10, status=S.ASSIGNED, due_at=at(15))
    before = reports.build_report(date(2026, 11, 10), date(2026, 11, 10), now=at(14))
    after = reports.build_report(date(2026, 11, 10), date(2026, 11, 10), now=at(16))
    assert (before.overdue_count, after.overdue_count) == (0, 1)


# --- department scope (the contract B31 reuses) ------------------------------------------------


def test_department_scope_counts_only_that_department(dataset, department):
    report = reports.build_report(date(2026, 11, 10), date(2026, 11, 12), department=dataset, now=NOW)
    assert report.total == 2
    assert report.scope_label == f"Department: {dataset.name}"
    assert report.reopen_total == 1


# --- CSV equals the displayed report -----------------------------------------------------------


def parse(content):
    return list(csv.reader(io.StringIO(content)))


def test_csv_rows_carry_exactly_the_report_figures(dataset):
    report = reports.build_report(date(2026, 11, 10), date(2026, 11, 12), now=NOW)
    rows = {(section, label): value for section, label, value in parse(reports.report_to_csv(report))[1:]}

    assert rows[("summary", "Total complaints")] == str(report.total) == "9"
    assert rows[("summary", "Open")] == "5"
    assert rows[("summary", "Overdue")] == "2"
    assert rows[("summary", "Escalated")] == "1"
    assert rows[("summary", "Reopened (complaints)")] == "2"
    assert rows[("summary", "Reopens (total count)")] == "3"
    assert rows[("resolution", "Mean hours")] == "4.67"
    assert rows[("resolution", "Median hours")] == "4.00"
    assert rows[("report", "Scope")] == "Campus-wide"
    assert rows[("report", "Date from")] == "2026-11-10"
    assert rows[("report", "Date to (included)")] == "2026-11-12"
    for section, pairs in (("by_category", report.by_category), ("by_location", report.by_location),
                           ("by_department", report.by_department)):
        assert [(label, int(value)) for (s, label), value in rows.items() if s == section] == sorted(
            pairs, key=lambda pair: pairs.index(pair)
        )


def test_csv_group_totals_equal_the_total(dataset):
    rows = parse(reports.report_to_csv(reports.build_report(date(2026, 11, 10), date(2026, 11, 12), now=NOW)))
    for section in ("by_category", "by_location", "by_department"):
        assert sum(int(value) for s, _, value in rows[1:] if s == section) == 9


FORMULA_CASES = [
    "=SUM(A1)", "+cmd", "-1+1", "@user",
    " =1+1", "   +cmd", "\t=1+1", "\n=1+1", "\r\n@x", " \t -2+3",     # leading whitespace and controls
    "\u00a0=1+1", "\u2003=1+1", "\u200b=1+1", "\ufeff=1+1", "\u2028=1+1",  # no-break, em, zero-width, BOM, line separator
    "\uff1d1+1", "\uff0b1", "\uff0d1", "\uff20x",                       # full-width = + - @
    "\x00=1+1",
]
SAFE_CASES = ["Wiring", "A - B", "x=1", "5th floor", "Block A", "e-mail", "", "Room =1", "100%"]


def _csv_labels(labels):
    report = reports.CampusReport(
        date_from=date(2026, 11, 10), date_to=date(2026, 11, 10), scope_label="Campus-wide", generated_at=NOW,
        total=1, by_category=[(label, 1) for label in labels], by_location=[], by_department=[],
        open_count=0, overdue_count=0, escalated_count=0, reopened_count=0,
        reopen_total=0, resolved_measured=0, resolved_excluded=0,
    )
    return [row[1] for row in parse(reports.report_to_csv(report)) if row[0] == "by_category"]


@pytest.mark.parametrize("label", FORMULA_CASES, ids=[repr(c) for c in FORMULA_CASES])
def test_csv_neutralises_formulas_even_after_leading_whitespace_or_invisible_characters(label):
    (cell,) = _csv_labels([label])
    assert cell == "'" + label


@pytest.mark.parametrize("label", SAFE_CASES, ids=[repr(c) for c in SAFE_CASES])
def test_csv_leaves_ordinary_text_alone(label):
    assert _csv_labels([label]) == [label]


def test_csv_leaves_numbers_alone():
    assert reports._safe_cell(7) == "7" and reports._safe_cell(Decimal("4.50")) == "4.50"
    assert reports._safe_cell(None) == ""


# --- privacy -------------------------------------------------------------------------------------


def test_anonymous_complaints_are_counted_but_nothing_identifies_them(make, user_factory):
    named = user_factory(full_name="Visible Complainant Person", email="visible.person@example.test")
    make(10, submitted_by=named)
    anonymous = make(10, anonymous=True, title="Private title text", description="Private anonymous description text.")
    report = reports.build_report(date(2026, 11, 10), date(2026, 11, 10), now=NOW)
    exported = reports.report_to_csv(report)

    assert report.total == 2
    for secret in (anonymous.reference_digest, anonymous.complaint_id, "Private title text",
                   "Private anonymous description", named.email, "Visible Complainant Person"):
        assert secret not in exported
        assert secret not in repr(report)


def test_report_screen_and_csv_never_show_references_or_people(dataset, scms_admin_user, user_factory):
    digests = list(Complaint.objects.exclude(reference_digest=None).values_list("reference_digest", flat=True))
    people = [u.email for u in Complaint.submitted_by.field.related_model.objects.exclude(pk=scms_admin_user.pk)]
    client = login(scms_admin_user)
    params = {"date_from": "2026-11-10", "date_to": "2026-11-12"}
    page = client.get(URL, params).content.decode()
    export = client.get(URL, {**params, "export": "csv"}).content.decode()
    assert digests
    for text in (page, export):
        assert not any(digest in text for digest in digests)
        assert not any(email in text for email in people)
        assert "SCMS-" not in text


# --- access --------------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["staff_user", "head_user", "complainant_user"])
def test_only_the_administrator_may_request_campus_reports(request, fixture, dataset):
    client = login(request.getfixturevalue(fixture))
    params = {"date_from": "2026-11-10", "date_to": "2026-11-12"}
    assert client.get(URL, params).status_code == 403
    assert client.get(URL, {**params, "export": "csv"}).status_code == 403


def test_signed_out_requests_go_to_login(dataset):
    response = Client().get(URL, {"date_from": "2026-11-10", "date_to": "2026-11-12", "export": "csv"})
    assert response.status_code == 302 and "login" in response["Location"]


def test_report_is_read_only(scms_admin_user):
    client = login(scms_admin_user)
    for method in (client.post, client.put, client.delete, client.patch):
        assert method(URL).status_code == 405


# --- the screen and download ---------------------------------------------------------------------


def test_screen_shows_the_figures_and_the_download_matches(dataset, scms_admin_user):
    client = login(scms_admin_user)
    params = {"date_from": "2026-11-10", "date_to": "2026-11-12"}
    page = client.get(URL, params).content.decode()
    assert "<td>Total complaints</td><td>9</td>" in page
    assert "<td>Reopens (total count)</td><td>3</td>" in page
    assert "B30 Wiring" in page and "B30-HALL" in page
    assert "export=csv" in page

    response = client.get(URL, {**params, "export": "csv"})
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    assert response["Cache-Control"] == "no-store"
    rows = {(s, label): value for s, label, value in parse(response.content.decode())[1:]}
    assert rows[("summary", "Total complaints")] == "9"


def test_empty_range_screen_says_so(scms_admin_user):
    page = login(scms_admin_user).get(URL, {"date_from": "2026-01-01", "date_to": "2026-01-02"}).content.decode()
    assert "No complaints in this range." in page
    assert "<td>Total complaints</td><td>0</td>" in page


@pytest.mark.parametrize("params", [
    {"date_from": "2026-11-12", "date_to": "2026-11-10"},
    {"date_from": "not-a-date", "date_to": "2026-11-10"},
    {"date_from": "2026-11-10"},
    {"date_from": "2024-01-01", "date_to": "2026-11-10"},
    {"date_from": "9999-12-30", "date_to": "9999-12-31"},
    {"date_from": "9999-12-31", "date_to": "9999-12-31"},
    {"date_from": "0001-01-01", "date_to": "0001-01-02"},
])
def test_bad_ranges_get_an_error_not_a_report(scms_admin_user, params):
    response = login(scms_admin_user).get(URL, params)
    assert response.status_code == 400
    assert b"Total complaints" not in response.content


def test_first_visit_shows_only_the_form(scms_admin_user):
    response = login(scms_admin_user).get(URL)
    assert response.status_code == 200
    assert b"Show report" in response.content and b"Total complaints" not in response.content
