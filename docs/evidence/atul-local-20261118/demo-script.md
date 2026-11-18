# Atul evidence demonstration — review draft

Use the identified branch/image and this packet. It is not a final release
presentation or a substitute for actual performance/human acceptance.

1. Identify Main `a479551`, tested helper branch `7d12ea4`, PR #101 and the exact
   image digest. Explain that Main was not merged by this work and peer review
   remains pending. Link the submitted #92 approval and its reviewed SHA.
2. Show the sanitizer's two failing-before cases, configured/resolved path fix,
   99 focused passes, 2,009 SQLite and 2,009 PostgreSQL passes, and per-module
   line/branch coverage. Keep the original sandbox failure visible.
3. Show the genuine F2/F3/F4 case evidence: validation, anonymous privacy,
   tracking/feedback, routing, department authorization, queues, assignment,
   evidence authorization and recovery. Distinguish test-only enablement from
   the deployed HTTP routes, whose gates remain disabled.
4. Show the stopped expired-session warmup, followed by the separate fresh
   retest's database warmup gate and all 1,100 raw samples. Present measured
   queue p95 2.896 s and assignment p95 7.148 s against 1.5 s: both FAIL.
   Show zero request errors and all 550 correct assignment/history/event graphs.
5. Show actual restart/replacement evidence: one accepted complaint, one file,
   one receipt/routing decision, two history/events and 52 notices/outbox rows.
   Compare identical graph/file hashes and replay after both operations.
6. State the remaining decisions and owners: D02 local proposal is not team
   approval; performance remediation/retest, other Q04 scenarios, final Main
   recovery/deployment sign-off and genuine first-time Q06 remain pending.
   Never call assisted six-screen evidence a four-screen unaided pass.

Update this draft after the agreed delivery build and real outstanding results
exist. No sprint video, human observation or final freeze is fabricated here.
