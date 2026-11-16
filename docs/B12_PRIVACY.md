# B12 anonymous privacy boundary and release checks

Owner: Atul (F2); affected integrations require F1/F3/F4/Q03 review. Related to
#17, REQ-ANON-02, REQ-SEC-06/08 and BR-03. This file distinguishes tested application
controls from deployment and future-module checks; it is not a blanket anonymity
certification for unimplemented reports, notifications or tracking.

## Implemented and tested controls

| Surface | Enforced boundary |
| --- | --- |
| Anonymous HTTP request | Middleware runs before session/auth, removes session/auth/identity headers, source IP and GET parameters; only the CSRF cookie is retained for validation, and its response lifetime is restricted to the browser session. No account lookup is used by intake. |
| Signed-in visitor | Existing browser login is neither attached to the complaint nor refreshed/changed by the anonymous route. It remains usable on other routes. |
| Complaint and routing | Submitter is NULL; no name/email/IP column is added. Current category/location/routing/SLA validation still applies. |
| Operation receipt | Random operation-key hash and normalized payload hash only; no user, session, source or IP field. This key is not a tracking reference or source-throttling key. |
| Reference | High-entropy digest only at rest; raw value is omitted from result repr and issued once after commit, with no recovery route. |
| Intake evidence | No uploader account; generic evidence filenames replace original names. JPEG/PNG are rebuilt from oriented pixels without EXIF/text/ICC metadata. PDF document/page metadata, annotations and embedded attachments are omitted; unreachable copied objects are removed before writing. Sanitized bytes are revalidated. |
| History | Initial submitter actor is ANONYMOUS with empty remarks; automatic routing is SYSTEM with no submitter account. Existing anonymous-history guards discard identifying remarks. |
| Unauthorized reads | An account does not become owner merely by using the anonymous page. Anonymous callers/reference/ID holders cannot use authenticated acknowledgements or evidence downloads. Department permissions still govern staff access. |
| Security refusals | An account's authorization refusal is retained, but the anonymous complaint target is generic, without its PK/ID, preventing an account-to-anonymous-complaint join in SecurityEvent. |
| Error responses/reports | Generic errors, sensitive POST/local variables, no account/session/cookie/query/file values in anonymous Django exception reports; raw exception values are not emitted by view/cleanup handlers. |
| Browser response | HTTPS required; no-store/private/no-cache, no-referrer, noindex/noarchive, no external resources/scripts and restrictive CSP on the anonymous route. |

`complaints.privacy.complainant_label()` returns exactly `Anonymous` for an
anonymous record, without guessing identity from assignees/uploaders/sessions.
`anonymous_summary()` is an explicit allowlist for authorized display/export/
report/staff-notification integrations: ID, the Anonymous label, category,
location, status, priority and escalation. It excludes submitter, reference
digest, free text, evidence names/bytes and all account relations. It is not an
access check and must never be used to grant public full-record access.

### F3 consumers (B14/B15/B16/B17/B18)

The B12/F3 integration for Issue #74 uses the projection in the authorized B15
department queue. Anonymous rows show the label `Anonymous`, the generic title
`Anonymous complaint`, and only allowlisted category/location/status/priority/
escalation data. The queue does not render anonymous title or description,
submitter/account relations, or the private reference digest. Authenticated queue
rows retain their complaint title and use the existing authenticated complainant
label. Department authorization and filtering are unchanged. Head allocation and
reassignment continue to use the complaint ID and normal B15 service; the
anonymous record needs no submitter account. Routing and SLA remain the normal
intake path, and B18 escalation eligibility/history/run outcome do not depend on
`submitted_by`. B18 run errors and command output contain generic outcomes and
aggregate counters, not complaint fields or exception values.

F3 does not implement F4 delivery. B18's existing notification hook remains a
no-op until F4 supplies the notification service; F4 must call the authorized
privacy projection and must not send reporter email or a private reference.
F4 still needs its own review for staff/history/report/export output. B13 will
need its own restricted history projection and transient tracking throttle.

This contribution is stacked on the fetched
`origin/feature/B11-B12-anonymous-flow` head `9bc57ad` (PR #71), not directly on
Main. A Git merge-tree check against fetched `origin/Main` `5c375e7` reports the
existing content conflict in `complaints/evidence.py`: B11's anonymous-safe
cleanup logging overlaps Main's Q05 evidence-recovery lease/durability changes.
That upstream conflict is intentionally left for PR #71; the B12 queue changes
do not modify evidence storage or recovery.

Verification on 2026-11-11 used uncommitted B12 changes on top of base
`9bc57ad`: 241 focused F3/B12 tests passed, the explicit anonymous-escalation
integration check passed, and the full suite passed 1,131 tests with the
coverage gate. Overall line/branch coverage was 96.04%; module coverage was
accounts 98.42%/96.63%, complaints 98.38%/96.33%, routing 93.77%/85.15%, and
workflow 92.73%/95.00%. Django system checks passed and
`makemigrations --check --dry-run` reported no changes. No schema changes were
made. These are local working-tree results, not clean-source evidence.

The upstream-preloaded-identity check is separate from middleware ordering: it
rejects a request that already has session/user/cached-user state, including
when an outer WSGI/custom request wrapper populated it before the configured
first middleware. Regressions cover those preloaded objects and bad ordering.
Neither check removes the deployment checklist below.

## What metadata removal cannot guarantee

Names/email/phone numbers can be deliberately written into the complaint,
visible PDF text or image pixels. No software can infer every person's identity
from arbitrary user-authored content. The form warns users not to include these
details. It also states that PDF annotations are removed. Image re-encoding may
change encoded bytes; the anonymous retry fingerprint uses the sanitized bytes.
JPEG re-encoding uses quality 95 without chroma subsampling to reduce additional
loss, but it is still lossy and can produce a larger file than the upload.
Near-limit regressions use deterministic noisy JPEGs just below both candidate
5 MB conventions (5,000,000 and 5,242,880 bytes): when the sanitized image exceeds
the configured bound, the entire submission is rejected before staging or database
writes. A near-limit JPEG whose sanitized output fits is accepted without retaining
original metadata. Users may need to resize or select another image; the application
does not silently lower quality, preserve private originals or bypass the B09 limit.
These two test bounds do not resolve D02; the team must confirm its byte convention.
Only the sanitized bytes' SHA-256 is retained: the original can contain private
metadata and is deliberately not preserved or fingerprinted as a second artifact.
PDF parsing stays strict; malformed/scanner-specific PDFs that require repair
can be refused with the generic select-another-file error. Real campus scanner
compatibility remains part of B09/D02 acceptance; this is not a universal-PDF claim.

This application does not promise network-level anonymity, hide physical browser
history/screenshots, recover a lost tracking reference, or remove identity from
arbitrary handwritten/visible evidence. Do not claim those guarantees in a demo.

## Required verification before enabling release

Both new settings default to False. They accept only exact case-sensitive True:

```text
ANONYMOUS_INTAKE_ENABLED=False
ANONYMOUS_PRIVACY_READY=False
```

Keep them False until the responsible owners record the following checks:

- F1/F3/team confirm D01 campus references/emergency instructions and D02 byte
  convention. Supply the actual notice and shared intake flag; use no invented
  campus numbers or unlabelled synthetic policy.
- E03/Q02 verify TLS and HSTS at ingress, correctly overwritten proxy headers and
  blocked direct backend access. Forward/test the HTTPS mode, redirect, secure
  cookie, HSTS and attestation env values in the actual Docker environment.
  `ANONYMOUS_TRANSPORT_VERIFIED` stays False until those deployment checks pass;
  `anonymous_transport_ready()` also requires positive HSTS. Configure/test the
  total upload body limit before Django.
- E03/Q03 disable or redact anonymous-route access logs, request/response body
  capture, cookies, query strings, source IP/user-agent/forwarded headers and APM
  traces at reverse proxies, web servers, error collectors and analytics. This
  must happen outside Django too; middleware cannot erase upstream logs.
- Explicitly redact Cookie/Set-Cookie, CSRF-cookie values, X-CSRFToken and posted
  csrfmiddlewaretoken on BOTH signed-in and anonymous routes. The CSRF cookie
  is stable browser metadata; keeping it for CSRF does not make upstream logs
  unlinkable. Anonymous response cookies have no Max-Age or Expires, including
  after acceptance and validation failure; this replaces a previously persistent
  CSRF cookie with a session-lifetime one without modifying login cookies. It does
  not prevent within-session correlation. No proxy/APM/analytics collector may use
  CSRF values to correlate identity.
- Configure the explicit direct/proxy HTTPS mode, secure session/CSRF cookies
  and SSL redirection described in B11_ANONYMOUS.md. Verify trusted proxy header
  replacement and denied direct backend access under #27/#28.
- **Release blocker: review and complete the remaining F4 consumers.** The F3
  queue/allocation/escalation integration is implemented on the Issue #74 branch
  and must be merged and owner-reviewed. Complete #75 (F4 notices, reports and
  CSV), including any real staff notification without reporter email or reference
  disclosure.
  Keep release disabled while F4 integration or any deployment checklist item is
  pending.
- F4/report/notification owners use the Anonymous label and explicit safe
  projection, omit raw references and submitter linkage, and test real exports,
  messages and staff screens as those surfaces become available. Anonymous intake
  sends no submitter email and creates no notification account linkage itself.
- B13 keeps throttle source metadata transient and unlinked; it must never reuse
  the persisted anonymous operation receipt as a source/identity key.
- Record the configured revision, sanitized results and owner reviews. Preserve
  the existing F3/F4 event-contract and durable staging/outbox/restart follow-ups.

Only then may the deployment owner set both flags to True, keep DEBUG=False and
cookie-based CSRF, run `manage.py check --deploy`, restart/redeploy and verify the
actual anonymous flow. The privacy-ready flag records an operator attestation;
it cannot prove that external logging/integrations were checked. Missing or
misordered privacy middleware, insecure HTTP, debug mode, session-based CSRF or
missing release values fail closed rather than accepting a complaint.

## B10 recovery integration

Anonymous evidence staging uses the merged B10 shared writer lease and synced
file writes through the outer database commit. Cleanup consults primary accepted
Attachment metadata, preserves committed files after callback failure, and logs
fixed messages without private parser/storage exceptions. Recovery requires the
exclusive lease and retains integrity checks and reversible quarantine behavior.

`integration_checks/anonymous_recovery.py` explicitly exercises anonymous process
death before/during/after commit, same-key retry without recovering a previously
returned reference, and an anonymous writer blocking concurrent recovery. Run it
explicitly; its filename does not alter default pytest collection. The dedicated
PostgreSQL runner requires 34 cases: 30 existing recovery cases and these four
anonymous cases, with no skips or failures. GitHub Actions retains the actual
backend/source metadata in `b11-recovery-postgresql-evidence`.

These checks cover evidence recovery integration; they do not establish all
anonymous PostgreSQL/privacy acceptance, real F4 delivery, F3/F4 output privacy,
D01/D02 policy or deployed TLS/log-redaction acceptance. Anonymous intake remains
disabled pending those prerequisites; PR73 remains a separate draft dependency.
