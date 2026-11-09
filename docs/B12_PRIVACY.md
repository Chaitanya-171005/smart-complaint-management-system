# B12 anonymous privacy boundary and release checks

Owner: Atul (F2); affected integrations require F1/F3/F4/Q03 review. Related to
#17, REQ-ANON-02, REQ-SEC-06/08 and BR-03. This file distinguishes tested application
controls from deployment and future-module checks; it is not a blanket anonymity
certification for unimplemented reports, notifications or tracking.

## Implemented and tested controls

| Surface | Enforced boundary |
| --- | --- |
| Anonymous HTTP request | Middleware runs before session/auth, removes session/auth/identity headers, source IP and GET parameters; only the CSRF cookie is retained for validation. No account lookup is used by intake. |
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
location, status and escalation. It excludes submitter, reference digest,
free text, evidence names/bytes and all account relations. It is not an access
check and must never be used to grant public full-record access. F4 should use
these boundaries as its staff/history/report screens are implemented. B13 will
need its own restricted history projection and transient tracking throttle.

## What metadata removal cannot guarantee

Names/email/phone numbers can be deliberately written into the complaint,
visible PDF text or image pixels. No software can infer every person's identity
from arbitrary user-authored content. The form warns users not to include these
details. It also states that PDF annotations are removed. Image re-encoding may
change encoded bytes; the anonymous retry fingerprint uses the sanitized bytes.
Oversized sanitized files are rejected rather than bypassing the B09 limit.

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
- E03/Q02 verify TLS at ingress, correctly trusted/stripped proxy headers and no
  direct backend bypass. Configure/test the total upload body limit before Django.
- E03/Q03 disable or redact anonymous-route access logs, request/response body
  capture, cookies, query strings, source IP/user-agent/forwarded headers and APM
  traces at reverse proxies, web servers, error collectors and analytics. This
  must happen outside Django too; middleware cannot erase upstream logs.
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
