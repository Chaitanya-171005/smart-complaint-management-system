# PR93 P1 anonymous-reference disclosure correction

Reviewer report: https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/93#issuecomment-6920768676

Base PR93 revision: `20fd191e4f94a09c1067397557b3410af4387d94`.
Tested Linux source: `391d5d6e0ff4cbede443dde31a5e98023176ee80`; tree `7963144cd5f95eac29aa3d1438485acfab40a354`.

The old service accepted an uppercase private reference in a rejection reason.
The two service negative controls failed as expected (both reopen and Head-review paths);
a CSRF-protected HTTP negative control also failed, returning 200 instead of the required 400.
Those before-fix logs are retained separately and are not passing results.

The runtime correction case-folds only the free-text disclosure comparison for the
current private reference and its digest. Lookup authentication remains canonical
and case-sensitive. Invalid reasons are refused before any complaint, feedback,
history, notification event, notification or email-delivery mutation.

Twenty-four new regression cases exercise lowercase/uppercase/mixed-case reference
and digest text in both reopen and maximum-reopen Head-review paths through the
service and CSRF-protected HTTP endpoint. Snapshot assertions protect the entire
state/history/notification graph; HTTP tests additionally inspect the anonymous
response and both authorized Staff/Head readers for credential disclosure.
Existing positive-feedback, authorization, CSRF, rate-limit, stale-revision,
transaction rollback and valid-reason cases remain in the focused suite.

Actual Linux verification on this PR93 source:
- 192 focused SQLite checks passed, with actual JUnit included.
- The same 192 checks passed on disposable PostgreSQL 17.6.
- 1908 full regression checks passed; 96.80% overall coverage; all module gates passed.
- Django system and migration-drift checks passed on PostgreSQL.

The publisher separately runs the 192 focused cases on the user's Mac and refuses
to push if any fail, error or skip. Its Mac evidence is separate from these Linux
results. The two previously published CI corrections remain included in the base.

These results do not establish final PR92+PR93 integration acceptance. They do not
execute a real-browser test, production SMTP/deployment verification, official Q04
benchmark or unaided Q06 test. No Main merge or release-gate change is included.
