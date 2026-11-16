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
- Correction: the original scoped review missed the case-variant rejection-reason bypass. Chaitanya independently confirmed that uppercase/mixed-case private references and digests could be persisted and displayed to assigned staff. This is a confirmed P1 privacy vulnerability, not an unverified claim.
- The earlier scoped checks and passing CI did not establish absence of this vulnerability. This note does not approve production SMTP/deployment/F4 or final privacy acceptance.

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

## Correction and verification of confirmed P1 disclosure

The confirmed vulnerability was present in PR93 commit `20fd191e4f94a09c1067397557b3410af4387d94` and in the earlier local combined candidate. A rejection reason containing a case variant of the private reference or its SHA-256 digest bypassed the case-sensitive check and could reach protected feedback records and staff HTML. See [the independent finding](https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/93#issuecomment-6920768676). The original scoped review missed this case; its prior “unverified” characterization is withdrawn.

The runtime correction is published in commit `ff26d5416e14be6353fa4dbb87458a5d49af279a`, with evidence in `855d18699f6c10b6856042ac38c662123bcd37fd`. It case-folds the disclosure comparison for rejection text, the private reference and its digest before any complaint/history/feedback/notification changes. Reference authentication remains canonical and case-sensitive.

Twenty-four committed regression cases cover lowercase, uppercase and mixed-case references/digests, both reopening and maximum-reopen Head review, service rejection, CSRF-protected HTTP responses, unchanged database snapshots, and both authorized Staff/Head outputs. Earlier positive-feedback, authorization, rate-limit, CSRF and rollback checks remain covered.

Actual verification of the corrected source (tree `7963144cd5f95eac29aa3d1438485acfab40a354`):
- Linux: 1,908 full regression tests passed, 96.80% overall coverage, all module coverage gates passed.
- Linux: 192 focused SQLite checks and the same 192 checks on disposable PostgreSQL 17.6 passed.
- Mac: 192 focused checks passed, with zero failures, errors or skips.
- The five hosted CI checks on evidence commit `855d18699f6c10b6856042ac38c662123bcd37fd` passed.
- Suites overlap; these counts must not be added as unique tests. Evidence is committed under `docs/evidence/pr93-reference-privacy-20261116/`.

The 1,977-test combined run above predates this security correction and is retained only as historical compatibility evidence. It does not prove the P1 fix or final PR92/Main integration acceptance. Final security re-review, the chosen merge order and full verification of the final combined Main source remain required. No Main merge, release activation, official Q04 benchmark or production SMTP/deployment acceptance is claimed by this documentation correction.

