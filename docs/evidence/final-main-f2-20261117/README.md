# F2 verification on integrated Main

Verified source: `a479551c61beb2e2f6e04b93b167084bb7397dcc`, the PR98 merge
containing the reviewed F2/F3/F4 integration. This is fresh Main evidence, separate
from the earlier PR100 branch experiment. No Main merge was performed by this work.

## Actual results

| Check | Source/environment | Actual outcome |
| --- | --- | --- |
| Full canonical SQLite | Main push CI, Python 3.14 | 2,001 passed; 96.88% overall coverage; all module gates PASS |
| Full canonical PostgreSQL | Same Main SHA, PostgreSQL 17.6 | 2,001 passed; 96.89% overall coverage; all module gates PASS |
| Real Redis/nginx/TLS | Same Main push | 2,001 regression cases plus 9 real integration cases passed |
| Fresh focused F2/F3/F4 | Main checkout, disposable PostgreSQL 17.6, Python 3.13/Django 6.1.2 | 621 passed, zero failures/errors/skips |
| Real Chromium | Main checkout, synthetic loopback TLS | 14 passed, zero failures/errors/skips; desktop and 320px checks |
| Process/SMTP/scheduler/auto-close recovery | Main checkout, separate disposable PostgreSQL database | 28 passed, zero failures/errors/skips; archived harness with documented portable refusal fixture |
| Built final-image smoke | Healthy loopback Docker image from Main | 9 read-only checks passed: authorization, owner isolation, queue pagination and closed release gates |

Counts overlap and must not be summed. Hosted canonical suites explicitly included
the anonymous escalation/recovery and F3/F4 lifecycle, resolution, handoff and
retired-route checks. `main-case-index.json` retains the 2,001 collected Main node
IDs; hosted logs retain their complete executed outcome. Fresh focused JUnit and
screenshots are retained here. No functional integration failure was found in
these final Main checks.

Actual hosted runs:
- https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/44017903692
- https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/44017903628

## Built image and release limits

The separate project `q04ed58fc793084` serves http://127.0.0.1:55057 and does not
replace the older preview. Image digest:
`sha256:d1aab0f1abab4bd151e4a79832a0c5541fdbe097dad7251a6f9403da8936663d`.
Twelve runtime source hashes were compared with Main and match. The image is
healthy, has 650 synthetic complaints and 550 unused assignment targets. Private
actors/passwords remain outside Git and are not part of this evidence.

All existing intake, anonymous tracking/feedback, privacy and transport release
gates remain disabled. The image smoke verifies expected gated 503s, Head queue
200s with 25 rows on each of the first two pages, Complainant queue refusal, owner
detail access and another owner's 404. It does not claim enabled deployed anonymous
flow acceptance, accepted browser upload or production privacy/TLS attestation.
Successful upload/rollback/download and anonymous flows are covered by the real
Main application tests under isolated test-only configuration. D01/D02 and deployed
privacy acceptance remain separate.

Docker reported 16 CPUs and 8,320,901,120 bytes available memory. The test app has
no per-container CPU/memory limit. These are environment facts, not accepted Q04
benchmark conditions. No 50-user load, report timing, shaped upload or official
performance PASS was executed or inferred from smoke checks.

## Q04 diagnostic correction

The old helper misreported closed tracking as `FAILED (HTTP 503)` and omitted the
feedback route. Reproduction: create the isolated Main environment with default
closed gates and run `python scripts/q04_env.py check --environment NAME`.

The proposed host-side correction reads the application's configured tracking and
feedback guards without contacting Redis or changing settings. Only a known False
guard labels a 503 RELEASE_GATED. True/unknown readiness still labels a 503 FAILED;
a 404 remains unavailable. Feedback is now inventoried. Four of six new regression
cases failed before the correction; all 36 environment-helper cases then passed
on clean correction commit `25eae4ce3c1628807227b7bf2b23fc519e749655`. The actual
corrected read-only image check is retained. The image/application stays at Main
`a479551`; the diagnostic correction is a separate review proposal.

## Reproduction and remaining acceptance

`reproduce.py` and `prepare_q05.py` preserve the prior executable recipe. Use a new
isolated checkout/output directory and an activated virtualenv, install both
requirements plus Playwright 1.58.0/Chromium, and run sequentially or use separate
checkouts for concurrent SQLite/browser suites. Set SCMS_VERIFY_ROOT and the
optional PG/browser/Q05 root overrides, SCMS_VERIFY_OUTPUT and matching disposable
PostgreSQL port. `command.json` files retain actual argv/environment overrides.

Run the canonical wrapper with SCMS_CI_DATABASE_ISOLATED=1 and SCMS_CI_REQUIRE_F4=1.
The fresh local commands selected `focused-pg`, `browser` and `q05-portable-pg`.
The helper correction command is `python -m pytest test_q04_environment.py --no-cov -q`.
The final image used `scripts/q04_env.py up --environment final-main-a479551 --port
55057 --random-seed 171005 --complaints 650`; the follow-up used `check` only.
No benchmark target/reservation was consumed. Never publish the private settings
or actor JSON files. The complete recipe and fixture adaptation are also linked in
the historical PR100 evidence; this folder records the new Main executions.

`requirements.md` maps F2 implementation/tests to this source. `q04-protocol.md`
defines remaining measurements, and `q06-observation.json` is intentionally empty.
The official Q04 window, approved target/resources, source buckets, D02/shaping
conditions and actual 12-month report remain pending owner confirmation/readiness.
The current dashboard explicitly supplies snapshots rather than D03/B30 period
calculations. Q06 requires a genuine first-time participant and an authorized
session; the historical assisted six-screen observation is not an unaided pass.
The presentation and `demo-script.md` remain review drafts until these real results
and the final recording exist. No final all-requirements acceptance is claimed.
