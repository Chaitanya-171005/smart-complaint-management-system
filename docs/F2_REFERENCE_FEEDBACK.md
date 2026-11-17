# F2/F4 anonymous-reference feedback integration

This contribution is built on the private combined candidate, including current
PRs #73/#82/#83/#89 and the F4 #77/#78/#84/#91 chain. It does not approve those
branches or enable a deployed release. Apply its migration after the reviewed
F4 merge migration `0006_merge_b15_f4_b28`.

## Boundary and behaviour

- `/anonymous/feedback/` is a no-login GET/POST flow. The first POST checks the
  private reference; a second POST re-enters that reference with an opaque state
  revision and explicit confirm/reject action. A public ID or an account does
  not grant this authority. No temporary credential, reference, account, address
  or network source is stored in sessions or returned in bound inputs/URLs.
- Only a matching anonymous RESOLVED complaint can change. Confirmation closes
  it and accepts an optional integer rating 1–5. Rejection validates a stripped
  20–2000-character reason using the conservative Unicode description minimum.
  The current raw reference/digest cannot be placed in that persisted reason.
- A row lock and opaque revision serialize feedback, competing feedback and
  the existing auto-close service. Stale/replayed actions produce a modified
  record refusal. History, notices, email jobs, feedback and state commit or
  roll back together. SMTP is never called inside the action.
- Anonymous history keeps no actor/assignee account or free-text remarks.
  `AnonymousResolutionFeedback` retains the required rejection reason/rating in
  a separate append-only protected model, linked to its anonymous action event.
  It contains no reporter account, raw reference, source or IP columns.
- `authorized_feedback_history` and the paginated account-only
  `/complaints/<id>/resolution-feedback/` page expose these reasons only to
  current authorized department readers. The existing parent permission is
  rechecked. Anonymous reference lookup cannot read this page or its reasons.
  The department queue links to it for anonymous complaints. F1/F4 date-range
  reports can reuse the checked reader; period reporting remains separate work.

## Shared policy and privacy

`COMPLAINT_MAX_REOPENS` defaults to 2 and is shared by account and reference
rejection. Integers 0–32767 are supported; zero sends every rejection for Head
review. Invalid configuration fails system check `workflow.E001` and refuses
rejection without mutation. At the maximum, the complaint stays RESOLVED, the
count does not increase, an ANONYMOUS ESCALATED feedback event notifies the Head,
and the UI explains that reopening was refused. Existing auto-close checks hold
this current-resolution Head review. Due time, department, assignee and overdue
escalation flags are preserved; no D04 policy is invented.

`ANONYMOUS_FEEDBACK_ENABLED` is False by default and independently gated. It also
requires B13 tracking readiness: first-position privacy isolation, verified HTTPS,
cookie-based CSRF, privacy readiness, trusted source handling and configured
shared memory-only Redis. `complaints.E004` refuses an enabled incomplete setup.
Tracking and feedback consume the SAME 10-attempt/10-minute source allowance
before parsing the reference. Feedback accepts only bounded URL-encoded forms
(32768 bytes, allowing a 2000-character Unicode reason); tracking keeps 1024.
Duplicate/extra fields, file uploads, invalid actions and client-supplied actor,
complaint ID or state do not grant authority.

Form responses use same-origin referrers to avoid Chromium's Origin:null POST
behaviour under no-referrer, while retaining strict same-origin CSRF checks.
Tracking forms now use the same form policy. Successful feedback and other
non-form responses retain no-referrer; all anonymous responses remain no-store,
noindex and under the restrictive self-only form CSP. Invalid/missing CSRF or
hostile Origin still refuses the action. No release gate is enabled here.

## Verification

Use a disposable database and test-only secret. Run the focused service/HTTP
tests, then the normal clean-source CI wrapper. Repeat the selected integration
suite on actual PostgreSQL; SQLite alone does not establish its row-lock rules.

```sh
python -m pytest workflow/test_reference_feedback.py workflow/test_reopening.py \
  complaints/test_tracking.py workflow/test_autoclose.py --no-cov -q
sh scripts/ci_checks.sh build/evidence/new-feedback-run
```

`integration_checks/reference_feedback_browser.py` covers real normal browser
submissions for confirmation, reopening and maximum review at 320/1280px, then
tracking the result. The browser fixture uses synthetic TLS and executes Lua
against fakeredis; it is not deployed Redis acceptance. Run it together with
`integration_checks/intake_browser.py` on a supported Chromium environment.
This workspace's first attempt could not launch Chromium because an OS socket
was denied. No browser success is claimed for that attempt; retain its log and
run the committed workflow on the published candidate or a capable Mac.

Remaining acceptance: module-owner review and shared integration, real browser
execution, final Q02 ingress/Redis/logging/SMTP deployment checks, D01/D02/D04/D05
decisions, Q04 authorized target-environment measurements and human unaided Q06.
