# Q06 automated follow-up — branch evidence, not final Main acceptance

Runtime source: `2a40cbf34c1caff4242d729e4a0f2609ef5ad557`, based on PR #103
`68cd6fafe59c49b21d99a0b4ec889579883b2b84`. These browser runs happened on that
runtime working tree before its source commit; the later shared-shell test
expectation change did not alter runtime behavior. Clean published-commit CI is
separate evidence. No Main merge, production activation or human observation is
claimed.

## Actual automated browser results

| Source | Passed | Failed | Errors | Skipped | Unique cases |
|---|---:|---:|---:|---:|---:|
| Independent PR #103 review at `68cd6fa` | 57 | 9 | 0 | 0 | 66 |
| Follow-up runtime working tree | 68 | 0 | 0 | 0 | 68 |

The follow-up includes the same 66-case checklist with its actual shorter normal
navigation and two new committed four-page browser cases. Assertions were not
weakened to ignore screen count, overflow, focus or error descriptions. The nine
baseline failures and their reproduction observations remain in `before-pr103`.
Anonymous CSP errors were separately observed in baseline console records even
when a functional case passed; all private surfaces now use inline fixed CSS,
without script or stylesheet requests. No privacy guard is disabled in source.

Environment: Python 3.14, Django 6.1.3, pytest 9.1.1, Playwright 1.58.0, real
Chromium 145.0.7632.6; desktop 1280px and 320px mobile emulation. Fresh SQLite test
database, synthetic records/accounts, loopback TLS and disposable fakeredis
fixtures. Release-gated and enabled-fixture states are separately exercised.
Fixtures enabling test routes do not establish deployed anonymous readiness.

## Required regression and published-commit checks

Local permitted-loopback canonical run: **2,038 passed**, all module coverage gates
pass (96.86% overall). Source metadata records runtime `2a40cbf` plus untracked
evidence documents at run start; runtime code was committed. The earlier restricted
attempt (2,019 pass, 6 fail, 13 errors) could not bind synthetic HTTP/SMTP listeners
and remains recorded as a failed attempt.

Published `6da634c` checks all pass: SQLite **2,038**, PostgreSQL **2,038**, real
Chromium regression **16**, real Redis/TLS **9**; the Redis workflow also repeats
full regression. Suites overlap and their counts are not added. Coverage gates
remain 70% line / 60% branch per module. Actual hosted logs and exact jobs are
retained under `checks/hosted-6da634c`:

- Unified: https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/44364028790
- Browser: https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/44364028756
- Redis/TLS: https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/44364028857

A later evidence-only commit does not turn this into final Main evidence; check
its own published-head CI before integration. Initial source/test correction
attempts are retained, including the old test assumption that every page uses an
external CSS link. Private pages deliberately use inline CSS; the complete full
suite includes that corrected privacy-safe contract.

## SRS acceptance checklist

Sources: Team6_SRS.pdf §3.1 (p4), NFR-QUAL-02 (p13); Team6_STP.pdf VM-03 (p3).

| Criterion | Automated result | Evidence / limitation |
|---|---|---|
| Registration → login → intake → acknowledgement in ≤4 primary screens | PASS, 4 at both widths | 1 registration; 2 generic receipt with blank login; 3 Complainant home with intake; 4 acknowledgement. Every visible full page counted. |
| Desktop and 320px readable layout | PASS in tested Chromium | Long labels, forms, role queues, acknowledgement and refusals; page width checks. Bounded navigation/table scrolling remains intentional. |
| Required/invalid inputs, correction, resubmission | PASS | Registration, login and intake; saved appropriate non-secret input. Password/file re-entry remains intentional browser/security behavior. |
| Error labels, announcements and corrective focus | PASS DOM/keyboard checks | Valid error-description IDs, alert summary, first invalid field focus; no live screen-reader or cognitive assessment. |
| Visible acknowledgement / copyable complaint ID | PASS | Native clipboard, rejected/unavailable API fallbacks and keyboard/manual copying. |
| Anonymous submission/reference tracking | PASS when synthetic test prerequisites enabled | Styled private pages, masked references, successful tracking/manual copy; deployed privacy/transport readiness remains unaccepted. |
| Role navigation and permission refusal | PASS | Four roles, queue links and safe 403 home guidance; status remains 403. |
| Keyboard, labels, focus, status text | PASS for exercised paths | Real keyboard-only intake and DOM/style checks; not a complete WCAG certification. |
| Broken links, overflow, JS exceptions | PASS for exercised paths | Zero uncaught JavaScript exceptions in recorded observations. Expected HTTP 403/503 console responses remain distinct. |
| Genuine first-time unaided user | PENDING / unavailable | No human tester, assistance count or usability feedback is fabricated. |
| Final integrated Main / deployment | PENDING | Parent and follow-up require independent review and authorized integration, then final-SHA verification. |

Automated branch verdict: **DEMO READY WITH LIMITATIONS**, conditional on green
published-commit checks and reviewed integration. This is not a release verdict
for current Main. There are no remaining failures in this automated browser
checklist; human acceptance, physical devices, other browser engines, live
screen-reader use and final delivery-build acceptance remain outside it.

## Corrected defects and retained safeguards

- Generic registration receipt now offers blank CSRF-protected login. Registration
  still does not authenticate or reveal whether an address already exists.
- Complainant home offers the existing intake service only when its current gate
  and nonempty notice permit it. Login redirects, role checks, token binding,
  intake validation, transaction/retry behavior and all release defaults remain.
- Anonymous pages inline only the reviewed fixed repository stylesheet; CSP still
  denies scripts and subresources. No ambient identity cookie-bearing asset
  requests are introduced. Shared anonymous middleware isolation stays intact.
- Registration errors have real description targets. Intake errors announce a
  correction prompt; authenticated pages focus the first invalid field. Private
  pages remain script-free with server-rendered messages.
- Safe 403 guidance offers a home link without exposing objects or exception text.

Selected actual screenshots and all per-case JSON observations are retained.
Reference secrets are masked; keys, cookies and databases are excluded. Textual
local paths are redacted without changing numerical outcomes or image pixels.
`results.json` and JUnit are authoritative counts; `sha256.json` hashes this packet.
See REPRODUCE.md and DEMO.md. Historical failed test attempts are retained locally;
no failed run is relabelled as a pass.

## Actual Gunicorn static-delivery follow-up

The combined preview `44a12d0` exposed a built-instance defect missed by the
test server: /accounts/login/ returned 200, but /static/ui/scms.css and
/static/ui/forms.js returned 404 with DEBUG=False. This was observed directly
on the isolated real Docker/Gunicorn build, separately from the 68 browser cases.
The new static regression failed 5 cases before correction (3 passed).

The correction pins WhiteNoise 6.12.0 and places its public-only wrapper after
SecurityMiddleware, while AnonymousPrivacyMiddleware remains first. It serves
collected STATIC_ROOT only, with finders/autorefresh disabled. Startup refuses
public/private evidence root equality or nesting in either direction. No private
evidence URL alias, anonymous asset request, script permission, HTTP intake gate
or production secret is introduced. Focused static/role/privacy checks: **253
passed**, with expected warnings for the uncollected test-only static directory.
Actual rebuilt-container and published-commit checks must accompany this change;
earlier browser/full CI results above retain their original source provenance.

Configuration reference: https://whitenoise.readthedocs.io/en/stable/django.html
Pinned release: https://pypi.org/project/whitenoise/6.12.0/

Published static-fix source `fcf053ccb7730e028461e7a1dec38fc0efaa9afc` now has
**2,046 SQLite and 2,046 PostgreSQL passes**, 16 browser passes and 9 real
Redis/TLS passes, with all module gates unchanged. Actual logs are in
checks/hosted-fcf053c. The combined runtime `81eae6675b75c242cf8dfd0a3691778c9a64fb81`
passed 2,065 tests on each database, 68 Q06 browser cases and 28 process/SMTP/
scheduler recovery cases. Its real Docker/Gunicorn browser checks pass14/14
at both widths, also after replacement; public CSS/JS return200. The actual
persistence probe retains the same complaint/file/hash/history/outbox graph.
These remain combined **branch** results, not final Main or human acceptance.
Local scratch-directory spellings in negative-control logs are output-redacted.
