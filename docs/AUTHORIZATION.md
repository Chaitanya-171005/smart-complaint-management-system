# Authorization (B04)

All access rules live in `accounts/permissions.py`. Views and services of F2 to F4 call
these helpers; they do not re-implement role checks and never rely on hidden UI.
The role and department are read from the database on every request, so a change applies
on the next request.

## Complaint-like objects
The checks read `owner` (User, or None for anonymous complaints), `department` and
`assignee` (User or None). Either the object or the `<name>_id` value works.

## Rules
| Check | Allowed |
|---|---|
| `can_view_complaint` / `can_view_evidence` | owner; Staff and Head of the complaint's department; Admin (read-only, open decision) |
| `can_progress_complaint` | assigned Staff of that department; Head of that department |
| `can_resolve_complaint` | assigned Staff only (BR-01) |
| `can_reject_complaint` | Admin; Head of that department; assigned Staff |
| `can_allocate_complaint(user, c, assignee)` | Head of that department; target must be active Staff of the same department |
| `can_confirm_resolution` | the originating Complainant only |
| `can_view_department_queue` | Staff/Head of that department; Admin |
| `can_view_report(user, dept=None)` | Admin (campus-wide); Head (own department) |
| `can_manage_configuration`, `can_manage_users` | Admin |

## Using them
- `@role_required("ADMIN")` or `RoleRequiredMixin`: anonymous goes to login, wrong role gets 403.
- `authorize_or_404(check, user, obj)`: for reading one record; refused looks the same as missing.
- `require_permission(check, user, obj)`: 403 for actions; call before changing any data.
- `scope_complaints(user, queryset)`: use for every list, queue and filter.
- Refusals are written to `SecurityEvent` (`AUTHORIZATION_REFUSED`) with no request data.

Permission says who may act. Whether the state transition is valid is F4's lifecycle check; call both.
