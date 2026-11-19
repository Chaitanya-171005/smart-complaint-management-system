# SCMS Phase 1 frontend implementation

## Branch and provenance

- Worktree: `/tmp/scms-ui-phase1` (macOS resolves this to `/private/tmp/scms-ui-phase1`).
- Branch: `feature/scms-ui-phase1`.
- Verified base: PR #99, `c78a532df219e139bfd7847c0d69ba3e0753a04b`.
- PR source branch reported by GitHub: `integration/final-f2-f3-f4-tanmay-20261117`.
- The user fetched GitHub's PR ref directly and created this isolated worktree. The local HEAD matched the supplied live PR metadata before implementation.
- Original contributor commits are ancestors; no history was rewritten. No push, PR creation or merge was performed.

## Implementation and screens

The shared Django base and role-aware navigation use local static CSS and system fonts. The light university dashboard theme provides navy/blue accents, cards, tables, form controls, alerts, lifecycle badges, focus indicators, a skip link and responsive breakpoints at 950px and 680px. Mobile navigation scrolls horizontally. Tables scroll within their container. Minimal local JavaScript announces POST submission progress without disabling controls or altering submitted fields; the server still owns validation and retry behavior.

| Area | Screens and behavior |
| --- | --- |
| Authentication | Login, registration, registration completion; existing generic errors and validation retained |
| Complainant | Useful landing cards, complaint submission, personal list, current snapshot dashboard, notifications |
| Staff | Queue navigation; work-status links offered only for the current assignee; existing work-status page supplies authorized progress and resolution actions |
| Head | Department queue and assignment, work status, department snapshot and CSV export, notifications |
| Administrator | Users/roles, departments, locations, routing/SLA/escalation configuration, configuration audit; no invented reporting endpoint |
| Complaint intake | Authenticated and anonymous submission, acknowledgements, emergency notices, evidence fields and download links |
| Complaint workflow | List/detail, history, progress, resolution, confirmation, reopening, feedback template shell and notifications |
| Anonymous | Intake, tracking, accepted/reference screen, feedback shell and unavailable states; existing deployment gates retained |

All 28 standalone page templates now inherit the shared shell. The existing notification fragment is reused for signed-in pages. Existing empty states and validation output remain. Backend models, migrations, lifecycle services, URLs, authorization, privacy gates, email/Redis and deployment configuration were not modified. The separately assigned feedback HTTP 500 defect was not addressed; feedback templates only inherit the presentation shell.

## Verification

- Runtime: Python 3.14.6, Django 6.1.3, existing `/tmp/scms-b13-review-venv` environment.
- Disposable database configuration: `DJANGO_DB_PATH=/tmp/scms-ui-phase1-verification.sqlite3`; pytest creates its isolated test database in this new worktree. Existing application databases were not used.
- `manage.py check`: no issues.
- Template compilation: every existing application HTML template compiles.
- Role rendering/navigation tests check all four roles, URL resolution, permitted landing links, disallowed administrative access, public screens, CSRF rejection and assignee-only work links.
- Local asset tests exercise Django static serving in-process. `findstatic` locates the stylesheet; `collectstatic` copied 132 files to a separate temporary destination.
- `node --check accounts/static/ui/forms.js`: passed.
- `git diff --check`: passed.
- Initial new UI run: 14 passed; three additional assignee and asset cases were added afterward; all 17 UI cases are included in the passing final run.
- Focused authentication/intake/routing/workflow suite: 1,791 passed, 2 subtests passed.
- Initial unrestricted full suite: 1,979 passed, 7 failed, 13 errors, 2 subtests passed. One failure was an outdated no-forms assertion in the staff queue: the new shell adds logout. That assertion now specifically checks that assignment controls remain absent. The other 19 cases failed because this environment refuses local socket binding (13 HTTP load fixture cases, 2 image health HTTP cases, 4 SMTP cases).
- Final full regression with only those 19 socket cases deselected: 1,983 passed, 19 deselected, 2 subtests passed in 68.58 seconds.

No browser was launched. Node Playwright is unavailable and a direct localhost bind probe raised `PermissionError: [Errno 1] Operation not permitted`. Desktop, tablet and mobile visual appearance, browser JavaScript behavior and screenshots remain unverified. No browser verification is claimed. The initial socket failures remain environmental limitations; no production code or existing socket tests were changed to bypass them.

## Reproduce

From this worktree with installed project development dependencies:

```bash
export DJANGO_SECRET_KEY='local-verification-key-only'
export DJANGO_DB_PATH=/tmp/scms-ui-phase1-verification.sqlite3
python manage.py check
python -m pytest accounts/test_ui_phase1.py --no-cov -q
python -m pytest accounts complaints routing workflow --no-cov -q
python -m pytest --no-cov -q
```

The unrestricted command also runs the localhost HTTP/SMTP tests, which require a host that permits socket binding. To visually review on such a host, use a separate development database/configuration, preserve anonymous gates, and launch the isolated worktree on an unused port. Do not point it at an existing application database.

## New files

- `accounts/static/ui/forms.js`
- `accounts/static/ui/scms.css`
- `accounts/templates/ui/base.html`
- `accounts/templates/ui/navigation.html`
- `accounts/test_ui_phase1.py`
- `docs/UI_PHASE1.md` (this report)

## Modified files

- `accounts/templates/accounts/admin_audit.html`
- `accounts/templates/accounts/admin_departments.html`
- `accounts/templates/accounts/admin_edit.html`
- `accounts/templates/accounts/admin_locations.html`
- `accounts/templates/accounts/admin_users.html`
- `accounts/templates/accounts/landing.html`
- `accounts/templates/accounts/login.html`
- `accounts/templates/accounts/register.html`
- `accounts/templates/accounts/register_done.html`
- `complaints/templates/complaints/acknowledgement.html`
- `complaints/templates/complaints/anonymous_accepted.html`
- `complaints/templates/complaints/anonymous_submit.html`
- `complaints/templates/complaints/reference_feedback.html`
- `complaints/templates/complaints/submit.html`
- `complaints/templates/complaints/tracking.html`
- `complaints/templates/complaints/unavailable.html`
- `routing/templates/routing/configuration.html`
- `routing/templates/routing/queue.html`
- `routing/test_b15_http.py`
- `workflow/templates/workflow/action.html`
- `workflow/templates/workflow/complaint_detail.html`
- `workflow/templates/workflow/complaint_list.html`
- `workflow/templates/workflow/confirm.html`
- `workflow/templates/workflow/dashboard.html`
- `workflow/templates/workflow/feedback_detail.html`
- `workflow/templates/workflow/notifications.html`
- `workflow/templates/workflow/reject.html`
- `workflow/templates/workflow/unavailable.html`
- `workflow/templates/workflow/work_status.html`
