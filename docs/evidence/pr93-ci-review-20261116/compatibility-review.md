# Scoped F2 review of PR92 and CI corrections for PR93

Review heads: PR92 43ff72a80eabcd79091e3c7e0f06107c004fb189; PR93 fc8f41a9a3e34b2fdd0d58739d75eca6f6fc05c3.

## Confirmed PR93 findings
- The intake-browser pytest/tee pipeline did not explicitly enable pipefail. It now runs under explicit bash and set -euo pipefail.
- The B13 Redis workflow did not prepare the disposable database required by PR92's newer shared CI checks. It now selects scms.settings/SQLite, creates a fresh directory under RUNNER_TEMP, and exports the new DB/evidence paths plus SCMS_CI_DATABASE_ISOLATED=1 before invoking CI.
- The real-Redis pipeline also explicitly enables pipefail.
- Five executable shell-control regression tests cover exit 0/7 propagation in both pipelines, retained logs, fresh unique DB/evidence paths and preservation of an unrelated existing DB. These are shell-control tests, not real browser/Redis acceptance.

## Scoped PR92 privacy/routing review
- Reviewed anonymous_summary, department queue rendering/authorization, assignment, escalation and the F3/F4 durable notification handoff.
- Reviewed canonical private-reference paths, CSRF/isolation/rate limiting, feedback projections and current department authorization in the combined candidate.
- 211 focused SQLite cases passed on PR92 itself. 285 PostgreSQL cases passed on the local combined candidate, including anonymous privacy/tracking, assignment/escalation handoff and reference feedback. Suites overlap.
- No confirmed blocking F2/F3 privacy/routing defect was found within that reviewed scope. This is not a full independent SMTP/deployment/F4 approval.
- The published PR93 review names the two CI issues. The chat mentions a privacy issue without an exact route, reproduction or requested change. That separate claim remains unverified; request the precise finding from Chaitanya and do not mark it resolved based on green CI.

## Integration
The local combined candidate is a compatibility experiment, not a public merge. The only content conflict was .env.docker.example. Both F2 feedback/reopen defaults and F3 SMTP settings were retained; all release gates remain disabled. Chaitanya's chosen merge order and final Main verification are still required.

## Remaining acceptance
The official Q04 queue/assignment benchmark awaits a newly confirmed window on atul-review. Other Q04 measurements need their endpoints/dataset/policies. Deployed privacy/SMTP, genuine unaided Q06 and final integrated acceptance are pending. No benchmark, production activation, Main merge or policy approval was performed in this review.

## Completed local combined regression
- 1,977 passed in 939.90 seconds; 96.85% overall coverage and all four module gates passed.
- Clean committed local source: 4c4d830c470d38c0c11197dae35955c9631eaa9d; tree b42c351c0630a8f642cf83aaa2372dc4453545a0.
- The canonical runner explicitly included anonymous escalation/recovery, F3/F4 lifecycle/resolution/handoff and retired-route checks; the F4 dependency gate was required.
- These local combined results are not hosted CI results for the public PR93 head. Docker Compose preflight and real Redis/nginx/TLS/browser execution were not rerun on this combined candidate here; the Docker CLI is unavailable and browser execution was blocked earlier. The existing Mac/hosted 14-case evidence belongs to the previous source.
- No Main/PR92 merge was pushed. After the chosen merge order, run the full shared CI entry point and browser/integration jobs on the final source.

## Suggested scoped review text for PR92
Reviewed the anonymous privacy/routing overlap at 43ff72a80eabcd79091e3c7e0f06107c004fb189. The scoped SQLite review passed 211 cases; local PR92+PR93 PostgreSQL integration passed 285 cases; the clean combined regression passed 1,977 with 96.85% coverage and all module gates. No confirmed blocking finding in the reviewed F2/F3 privacy/routing scope. This does not establish production SMTP/privacy or full F4 acceptance. The local combination needed one .env.docker.example conflict resolution preserving both sets of defaults. Please provide the exact privacy reproduction/line mentioned for PR93; the posted PR93 review currently specifies the two CI issues, which have been corrected in the prepared update.
