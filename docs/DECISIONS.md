# Open decisions and recorded decisions

## D02 - Exact evidence byte limit

**Status: pending team confirmation.** REQ-CMP-03 says at most 5 MB; SRS section 7
explicitly leaves the byte convention open. Issue #14 requires this decision
before final exact-limit acceptance. The B09 foundation uses a provisional
conservative 5,000,000-byte default and supports 5,242,880 by configuration.
Tests cover both candidates without claiming either is agreed. F2/F4 must
record the decision here before closing #14; see B09.md.

## D01 - Campus configuration and emergency channels

**Status: provisional, pending campus confirmation.** B17's initial routing/SLA
configuration is an implementation baseline, not confirmed campus policy.
F1/F3 must confirm categories, canonical location codes and emergency channels
before final intake acceptance. B07 tests use synthetic data and do not invent
campus emergency numbers. B07's adapter contract and the category-name limit
discrepancy with B17 are documented in B07.md for owner confirmation.

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
