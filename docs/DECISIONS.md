# Open decisions and recorded decisions

## D01 - Initial routing, SLA and escalation configuration (REQ-ADM-03)

**Status: initial implementation configuration.** Categories and base SLAs seed with B17;
departments, initial routes and the default-department escalation policy are configured only
after F1 supplies its Department master data. All values remain Administrator-editable and are
stored as configuration, not hard-coded into routing, due-date or escalation logic.

| Configuration | Initial value |
| --- | --- |
| Categories | Electrical, Plumbing, Wi-Fi/Network, Cleanliness, Security, Other |
| Departments | F1-owned master data: Maintenance, IT Support, Housekeeping, Security, Administration |
| Default department | Administration, configured after F1's data is present |
| Category minimum priority | Electrical: Medium; Security: High; all other categories: Low |
| SLA duration | Low: 7 days; Medium: 3 days; High: 1 day; Critical: 4 hours |
| Initial category routes | Configure after F1 data: Electrical/Plumbing -> Maintenance; Wi-Fi/Network -> IT Support; Cleanliness -> Housekeeping; Security -> Security |
| Escalation | Every 24 hours after due time; maximum level 3 |

Location-specific routes are intentionally not seeded because the team has not agreed
campus location codes. They can be added by an Administrator once F1's canonical location
reference data is available.

**Department deactivation integration contract (F1).** A Department cannot be deactivated
while it is referenced by an active routing rule or as the default department of an
escalation policy. F1's Department-deactivation service must enforce this guard (or require
an Administrator to first replace/deactivate those B17 configurations); B17 does not own
Department lifecycle operations.

## D06 - Password-reset assistance (REQ-AUTH-01, SRS section 7)

**Source.** REQ-AUTH-01: a duplicate email creates no account and gets the same generic
acknowledgement as a successful registration, "directing existing-account users to
password-reset assistance (its flow is unspecified)". SRS section 7 lists password-reset
assistance among the items to confirm before fixed assertions are written.

**Status: INTERIM, needs team confirmation before final acceptance.** The team has not yet
said what the assistance is. Until it does, the code does this and nothing more:

- The acknowledgement page (`register_done.html`) is identical for new and duplicate
  emails and tells existing-account users to sign in or ask for password-reset assistance.
  It does not name a channel, because none has been decided.
- No self-service reset flow is built, no reset email is sent, and no reset token or
  endpoint exists. Adding one silently would go beyond the SRS.
- The assistance wording is one string in one template, so changing it later does not touch
  registration logic or tests of the generic response (the two responses are compared
  byte for byte, so they cannot drift apart).

**Decision needed (owner: team, with Q&A from the supervisor if required).** Pick one:

1. Manual assistance: an Administrator resets the password on request. Needs a named
   contact or channel for the acknowledgement text. No new code except the wording.
2. Self-service reset by email link. Needs a new requirement (token lifetime, rate limit,
   email wording, security events) and a new issue; it changes the duplicate-email response
   timing and wording rules.
3. Assistance outside the system (campus IT desk). Wording only.

**Record the answer here** (date, who decided, option chosen) and then update the wording
and the acceptance test for the acknowledgement page.

| Date | Decided by | Option | Notes |
|---|---|---|---|
| (pending) | | | |
