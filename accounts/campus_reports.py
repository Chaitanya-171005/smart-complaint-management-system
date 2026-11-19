"""Campus report and matching CSV (B30, REQ-RPT-01).

One calculation, two renderings: ``build_report`` computes every figure once, and both the
screen and ``report_to_csv`` read that same ``CampusReport``, so the export cannot drift from
what is displayed. ``department`` is part of the contract so B31's department report can call
the same function with a Head's own department.

The report holds aggregates only. It never reads or returns a submitter, an account relation, a
reference digest, free text or evidence, so an anonymous complaint is counted but cannot be
attributed through the report or the CSV (REQ-ANON-02).

Rules still waiting for the D03 decision are PROVISIONAL and gathered in one place below so the
decision changes a constant, not the logic. They are printed on the screen and in the CSV.
"""

import csv
import io
import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from complaints.models import Complaint

# --- D03 provisional rules -------------------------------------------------------------------
# Dataset: complaints whose submission time falls in the selected dates.
# Dates: both selected days are included, whole days in the campus time zone (settings.TIME_ZONE),
#        i.e. submitted_at >= start 00:00 and < the day after the end date, 00:00.
# Open: still being handled, so not RESOLVED (awaiting the Complainant), CLOSED or REJECTED.
# Overdue: open and past its due time at the moment the report is generated.
# Resolution time: resolved_at - submitted_at, only for complaints that are RESOLVED or CLOSED now
#        and whose resolved_at is later than submitted_at (a missing or non-positive duration is
#        excluded and counted separately). F4 keeps the old resolved_at when a resolution is
#        rejected, so a complaint that is REOPENED or being worked again is NOT measured until it is
#        resolved again; a re-resolved complaint is measured to its latest resolved_at.
RULES_VERSION = "provisional-D03-v2"
RESOLVED_STATUSES = (Complaint.Status.RESOLVED, Complaint.Status.CLOSED)
OPEN_STATUSES = (
    Complaint.Status.SUBMITTED,
    Complaint.Status.ASSIGNED,
    Complaint.Status.IN_PROGRESS,
    Complaint.Status.REOPENED,
)
RULES_TEXT = (
    "Complaints are included by submission date; both selected days are included (whole days, campus "
    "time zone). Open = Submitted, Assigned, In progress or Reopened. Overdue = open and past due when the "
    "report was generated. Resolution time = resolved time minus submitted time, for complaints that are "
    "Resolved or Closed now and have a later resolved time. Rules marked provisional until decision D03 is confirmed."
)
MAX_RANGE_DAYS = 366
# Dates outside this window are refused with a message. Without it, a date such as 9999-12-31 raises
# OverflowError when the day after the range end is computed (an HTTP 500 instead of a validation error).
MIN_REPORT_DATE = date(2000, 1, 1)
MAX_REPORT_DATE = date(2100, 12, 31)


def _hours(seconds):
    return (Decimal(str(seconds)) / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CampusReport:
    date_from: object
    date_to: object
    scope_label: str
    generated_at: datetime
    total: int
    by_category: list
    by_location: list
    by_department: list
    open_count: int
    overdue_count: int
    escalated_count: int
    reopened_count: int
    reopen_total: int
    resolved_measured: int
    resolved_excluded: int
    mean_hours: Decimal = None
    median_hours: Decimal = None
    rules_version: str = RULES_VERSION
    rules_text: str = field(default=RULES_TEXT)


def date_window(date_from, date_to):
    """Return the half-open [start, end) datetimes for two inclusive dates."""
    for value in (date_from, date_to):
        if not MIN_REPORT_DATE <= value <= MAX_REPORT_DATE:
            raise ValueError(f"Dates must be between {MIN_REPORT_DATE} and {MAX_REPORT_DATE}.")
    if date_to < date_from:
        raise ValueError("The end date cannot be before the start date.")
    if (date_to - date_from).days >= MAX_RANGE_DAYS:
        raise ValueError(f"The date range cannot be longer than {MAX_RANGE_DAYS} days.")
    zone = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(date_from, time.min), zone)
    end = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min), zone)
    return start, end


def _grouped(queryset, field_name):
    rows = queryset.values(field_name).annotate(count=Count("pk")).order_by("-count", field_name)
    return [(row[field_name], row["count"]) for row in rows]


def build_report(date_from, date_to, *, department=None, now=None):
    """Compute the report. ``department`` None is campus-wide (Administrator only; the caller
    must have authorized it with ``can_view_report``). Pass ``now`` to fix the overdue moment."""
    start, end = date_window(date_from, date_to)
    now = now or timezone.now()
    complaints = Complaint.objects.filter(submitted_at__gte=start, submitted_at__lt=end)
    if department is not None:
        complaints = complaints.filter(department=department)

    counts = complaints.aggregate(
        total=Count("pk"),
        open_count=Count("pk", filter=Q(status__in=OPEN_STATUSES)),
        overdue_count=Count("pk", filter=Q(status__in=OPEN_STATUSES, due_at__lt=now)),
        escalated_count=Count("pk", filter=Q(is_escalated=True)),
        reopened_count=Count("pk", filter=Q(reopen_count__gt=0)),
        reopen_total=Sum("reopen_count"),
    )
    by_department = [
        (row["department__name"], row["count"])
        for row in complaints.values("department__name").annotate(count=Count("pk")).order_by(
            "-count", "department__name"
        )
    ]

    durations = []
    excluded = 0
    for submitted_at, resolved_at in complaints.filter(resolved_at__isnull=False, status__in=RESOLVED_STATUSES).values_list(
        "submitted_at", "resolved_at"
    ):
        seconds = (resolved_at - submitted_at).total_seconds()
        if seconds > 0:
            durations.append(seconds)
        else:
            excluded += 1

    return CampusReport(
        date_from=date_from,
        date_to=date_to,
        scope_label="Campus-wide" if department is None else f"Department: {department.name}",
        generated_at=now,
        total=counts["total"],
        by_category=_grouped(complaints, "category"),
        by_location=_grouped(complaints, "location_code"),
        by_department=by_department,
        open_count=counts["open_count"],
        overdue_count=counts["overdue_count"],
        escalated_count=counts["escalated_count"],
        reopened_count=counts["reopened_count"],
        reopen_total=counts["reopen_total"] or 0,
        resolved_measured=len(durations),
        resolved_excluded=excluded,
        mean_hours=_hours(statistics.fmean(durations)) if durations else None,
        median_hours=_hours(statistics.median(durations)) if durations else None,
    )


FORMULA_STARTS = frozenset("=+-@\uff1d\uff0b\uff0d\uff20")  # ASCII and full-width forms
_IGNORED_CATEGORIES = frozenset({"Cc", "Cf", "Zs", "Zl", "Zp"})


def _safe_cell(value):
    """Stop spreadsheet formula injection in text cells.

    A cell is prefixed with an apostrophe (read as text) when its first meaningful character starts
    a formula. Leading whitespace, control characters and invisible format characters (a space, tab,
    newline, no-break space, zero-width space, byte-order mark) are skipped first, because some
    spreadsheet programs trim them before reading the cell, so " =1+1" must be treated like "=1+1".
    Numbers are written as they are.
    """
    if value is None:
        return ""
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    meaningful = next(
        (ch for ch in text if not (ch.isspace() or unicodedata.category(ch) in _IGNORED_CATEGORIES)), ""
    )
    leading = text[:1]
    if meaningful in FORMULA_STARTS or leading in ("\t", "\r", "\n"):
        return "'" + text
    return text


def report_rows(report):
    """The CSV as rows: the same figures, in the same order, as the screen shows."""
    rows = [
        ["section", "label", "value"],
        ["report", "Scope", report.scope_label],
        ["report", "Date from", report.date_from.isoformat()],
        ["report", "Date to (included)", report.date_to.isoformat()],
        ["report", "Generated at (UTC)", report.generated_at.astimezone(timezone.UTC).strftime("%Y-%m-%d %H:%M:%S")],
        ["report", "Rules version", report.rules_version],
        ["summary", "Total complaints", report.total],
        ["summary", "Open", report.open_count],
        ["summary", "Overdue", report.overdue_count],
        ["summary", "Escalated", report.escalated_count],
        ["summary", "Reopened (complaints)", report.reopened_count],
        ["summary", "Reopens (total count)", report.reopen_total],
        ["resolution", "Complaints measured", report.resolved_measured],
        ["resolution", "Excluded (non-positive duration)", report.resolved_excluded],
        ["resolution", "Mean hours", "" if report.mean_hours is None else report.mean_hours],
        ["resolution", "Median hours", "" if report.median_hours is None else report.median_hours],
    ]
    for section, pairs in (
        ("by_category", report.by_category),
        ("by_location", report.by_location),
        ("by_department", report.by_department),
    ):
        rows.extend([section, label, count] for label, count in pairs)
    return rows


def report_to_csv(report):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    for row in report_rows(report):
        writer.writerow([_safe_cell(cell) for cell in row])
    return buffer.getvalue()
