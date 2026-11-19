# Q06 genuine first-time usability session — blank record

Source: [Q06 issue #41](https://github.com/Chaitanya-171005/smart-complaint-management-system/issues/41) and its 18 November coordination comment. This is a preparation template, not a completed test.

## Arrange before the session

- [ ] Confirm an agreed final delivery build and authorized test configuration with the F1/F2 owners. Record source commit, image/build ID, URL, browser, viewport/device, and test data below.
- [ ] Recruit a person who has never used or rehearsed SCMS. Record how first-time status was confirmed. Do not substitute a teammate's assisted retest or browser automation.
- [ ] Agree how a **primary screen** is counted before observing. Record the actual sequence and revisits; the unaided registration and submission limit is **at most four primary screens**.
- [ ] Confirm current emergency information with its owner (D01) before evaluating the notice. Use synthetic data and an authorized environment.
- [ ] Prepare desktop and **320-pixel-wide** viewport capture. Avoid recording passwords, private references, complaint text, or personal information in shared evidence.
- [ ] Give the participant the goal only: register, sign in if needed, and submit a complaint. Do not give route hints or a rehearsal.

## Session record — fill only from observation

Date/time and observer: ______

Participant code and first-time confirmation method: ______

Build commit / image / configuration / URL / browser: ______

Desktop viewport: ______ × ______; 320px viewport: **320 × ______**

Agreed primary-screen counting rule: ______

| Step | Screen and viewport | Start/end time | Action, error, or revisit | Help requested or offered (exactly what and when) | Evidence reference |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| Additional steps | | | | | |

Actual primary-screen count and sequence: ______

Completed or abandoned; observed outcome: ______

Unaided completion? ______ (Any helped continuation remains assisted.)

## Observe on desktop and at 320px

- [ ] Registration and submission steps; screen count and elapsed time.
- [ ] Required field validation appears beside the affected field, preserves safe input, and allows correction and resubmission.
- [ ] Status is conveyed by text, not colour alone.
- [ ] Complaint identifier is clear and easy to copy; test copy success and clipboard failure fallback.
- [ ] Submission confirmation and owner-confirmed emergency information are clear.
- [ ] At 320px, no clipped controls, hidden error text, horizontal overflow, or unusable copy action.

Desktop evidence IDs: ______

320px evidence IDs: ______

Observed issues, owner, fix reference, and actual retest result: ______

Reviewer/date and acceptance decision: ______

Existing assisted evidence in #41 visited six primary screens and left first-time unaided and four-screen acceptance pending. Record this new session independently; do not transfer those observations into the blank fields above.

## Draft coordination note for issue #41 — not posted

Please identify available genuine first-time SCMS participants for an unaided registration and complaint-submission session on the agreed final delivery build. F1/F2 owners: please confirm the authorized test URL/configuration and the D01 emergency wording. Before the session, agree the primary-screen counting rule and prepare desktop and 320px capture. The observer will record each actual screen and revisit, timing, assistance, errors, completion, clipboard success/failure, validation and correction, and sanitized evidence using this blank form. Assisted continuation will be reported as assisted; no result will be claimed before observation.
