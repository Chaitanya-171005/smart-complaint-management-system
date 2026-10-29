# Authorization (B04)

All access rules live in `accounts/permissions.py`. Views and services of F2 to F4 call
these helpers; they do not re-implement role checks and never rely on hidden UI.
The role and department are read from the database on every request, so a change applies
on the next request.

## Shared Complaint contract (F1, F2, F4)
The checks read three fields of a complaint. Their names are set once, in
`accounts/permissions.py` (`OWNER_FIELD`, `DEPARTMENT_FIELD`, `ASSIGNEE_FIELD`):

| Field | Type | Meaning |
|---|---|---|
| `submitted_by` | FK to `accounts.User`, null | The signed-in submitter. Null for an anonymous complaint (no account owns it). |
| `department` | FK to `accounts.Department` | Department the complaint was routed to. |
| `assignee` | FK to `accounts.User`, null | Staff member the work is assigned to. |

`submitted_by` is the proposed name, because Tanmay's tracking service and tests already use
it and SRS B-2 calls the field "submitter". The first version of these helpers said `owner`.
**Status: proposed, to be confirmed by Atul (owns the `Complaint` model) and Tanmay.** If the
team picks another name, change the three constants and the tests follow. Either the related
object or the `<name>_id` value works. `test_real_complaint_model_follows_contract` skips
until `complaints.Complaint` exists, then checks the model against this table.

## Administrator and complaint content (decision against the SRS)
The SRS gives the Administrator users/roles/membership, master data, routing/SLA, campus
reports and state-model rejection (2.2). REQ-ACC-01 names who reads complaints: the owner,
department Staff and Head ("other-department access is refused"), and section 4.3 says no
additional permissions are implied. So **the Administrator may not read complaint details,
history, evidence or department queues**; campus numbers come from report aggregates (B30).
Admin can still reject (the state model lists Administrator rejection from SUBMITTED) and use
all Admin-only functions. One point still for the team to confirm with the supervisor: if an
Administrator must see a complaint in order to reject it, that needs an explicit, narrow rule
(for example, only while it is SUBMITTED). It is not assumed here.

## Rules
| Check | Allowed |
|---|---|
| `can_submit_complaint` | active authenticated Complainant; checked before constructing B07 intake options |
| `can_view_complaint` / `can_view_evidence` | submitter; Staff and Head of the complaint's department. Not Admin. |
| `can_progress_complaint` | assigned Staff of that department; Head of that department |
| `can_resolve_complaint` | assigned Staff only (BR-01) |
| `can_reject_complaint` | Admin; Head of that department; assigned Staff |
| `can_allocate_complaint(user, c, assignee)` | Head of that department; target must be active Staff of the same department |
| `can_confirm_resolution` | the originating Complainant only |
| `can_view_department_queue` | Staff/Head of that department. Not Admin. |
| `can_view_report(user, dept=None)` | Admin (campus-wide); Head (own department) |
| `can_manage_configuration`, `can_manage_users` | Admin |

## Using them
- `@role_required("ADMIN")` or `RoleRequiredMixin`: anonymous goes to login, wrong role gets 403.
- `authorize_or_404(check, user, obj)`: for reading one record; refused looks the same as missing.
- `require_permission(check, user, obj)`: 403 for actions; call before changing any data.
- `scope_complaints(user, queryset)`: use for every list, queue and filter. It agrees with `can_view_complaint` row by row (tested); Admin gets an empty list.
- Refusals are written to `SecurityEvent` (`AUTHORIZATION_REFUSED`) with no request data.

Permission says who may act. Whether the state transition is valid is F4's lifecycle check; call both.
