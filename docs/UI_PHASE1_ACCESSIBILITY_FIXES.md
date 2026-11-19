# Phase 1 accessibility fixes — 17 November 2026

## Scope and provenance

- Branch/worktree: `feature/scms-ui-phase1`, `/private/tmp/scms-ui-phase1`.
- Parent implementation: `c5e61fe6c83d27c7b0993157ee2f299dfe0ba04a`.
- Only shared CSS, static regression tests and this verification evidence changed.
- No models, migrations, templates, routes, lifecycle, authorization or deployment settings changed.
- No existing database, account, Docker container or running server was modified by audit tooling. In particular `/tmp/scms-ui-preview/ui.sqlite3` was not opened or overwritten. No pushes, merges or PRs were performed.

## P1: sidebar contrast

The dark `.sidebar` background uses `--navy: #142d50`. A later duplicate `.sidebar a` declaration previously changed its light text to the same navy. A later `.nav-label` declaration similarly replaced the light label color. The duplicate color overrides were removed while retaining spacing/layout declarations.

Normal links retain `#f4f8ff` on navy. Hover, active, `[aria-current="page"]` and `:focus-visible` use the same light text on `#29496f`. Keyboard focus keeps the existing three-pixel outline, using `#ffcb66` against the dark navigation. The original label color `#c1d4ee` is retained. No new navigation actions or current-page attributes were added.

## P2: form boundaries

Shared text inputs, selects and textareas now use `#64748b` instead of `#91a2b8`. The existing focus outline is preserved. Explicit disabled styles retain the strong border on `#e2e8f0`; `aria-invalid="true"` uses a red `#a32028` boundary. Native checkbox/radio styling, labels, validation behavior and submitted fields were not changed.

## Calculated contrast

These are source-color calculations using sRGB relative luminance, **not newly measured browser computed styles**.

| State | Text/border/outline | Background | Ratio |
| --- | --- | --- | --- |
| Sidebar normal link | `#f4f8ff` | `#142d50` | 12.96:1 |
| Sidebar hover/active/current/keyboard-focus link | `#f4f8ff` | `#29496f` | 8.66:1 |
| Sidebar label | `#c1d4ee` | `#142d50` | 9.15:1 |
| Sidebar focus outline | `#ffcb66` | `#142d50` / `#29496f` | 9.20:1 / 6.14:1 |
| Normal/focused control boundary | `#64748b` | white | 4.76:1 |
| Disabled control boundary | `#64748b` | `#e2e8f0` | 3.86:1 |
| Control boundary against page | `#64748b` | `#f3f6fa` | 4.39:1 |
| Invalid control boundary | `#a32028` | white / disabled background | 7.51:1 / 6.10:1 |

## Regression verification

- Python 3.14.6, Django 6.1.3, existing `/tmp/scms-b13-review-venv` runtime.
- Disposable test configuration: `DJANGO_DB_PATH=/tmp/scms-ui-accessibility-verification.sqlite3`; pytest creates its separate test database in the isolated UI checkout.
- Django system checks: passed, no issues.
- Existing Phase 1 UI tests plus six new contrast tests: **23 passed**.
- New static tests examine every matching color declaration, including later duplicate rules, against the backgrounds used by the component states. They require sidebar text contrast of at least 4.5:1 and control boundary/focus-indicator contrast of at least 3:1. Mutation cases prove that navy-on-navy overrides, low-contrast label overrides and the original input-border color are rejected.
- These conservative CSS color contracts are not a general CSS cascade engine or a replacement for real-browser rendering.
- Full regression result: **1,989 passed, 19 deselected, 2 subtests passed in 69.96 seconds**.
- `git diff --check`: passed.

The same 19 localhost HTTP/SMTP socket-dependent cases from the previous run were deselected explicitly. Their names are preserved in the evidence directory. They were not changed or represented as passing.

## Real-browser reverification: blocked

The connected browser inventory was reachable, but opening the preview in the in-app browser returned: `No ChatGPT browser route is available for browser session …`. The native Brave fallback returned a Computer Use permission denial. No new application page could be opened through either browser path in this turn.

Starting a separate instance was also blocked: a direct localhost bind probe failed with `PermissionError: [Errno 1] Operation not permitted`. Consequently no separate browser server, test accounts or workflow data were created. The existing preview database and accounts were not repurposed.

| Requested browser check | Result in this turn |
| --- | --- |
| Desktop 1440 × 900 | Not verified |
| Laptop 1280 × 800 | Not verified |
| Tablet 768 × 1024 | Not verified |
| Mobile 390 × 844 | Not verified |
| Updated sidebar computed colors and interactive states | Source/static verified only |
| Updated normal/focus/disabled/error control states | Source/static verified only |
| Navigation, overflow, keyboard focus and labels | Existing backend UI tests passed; no new browser result |
| Browser console/network errors | Not inspected in this turn |
| New screenshots | None; earlier audit images predate these fixes and are not evidence of them |
| Complainant dashboard/intake/evidence/confirmation/rejection | Not browser verified |
| Staff dashboard/queue/progress/resolution/notifications | Not browser verified |
| Head dashboard/assignment/reporting/CSV | Not browser verified |
| Administrator dashboard/users/departments/locations/routing/audit | Not browser verified |
| Anonymous unavailable states | Not browser reverified; gates unchanged |

The separate CLOSED-complaint feedback HTTP 500 issue was not changed. Its current browser reproducibility remains unverified; no claim is made that it is fixed or absent.

## Verdict

The two reported color defects are corrected in the CSS and protected by passing static regression checks. **Browser sign-off remains pending**, including authenticated role workflows and all four requested viewport checks. No new screenshots or full authenticated browser approval can be supplied from this blocked session.
