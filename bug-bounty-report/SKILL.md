---
name: bug-bounty-report
description: Package demonstrated Medium+ bug bounty findings with reproducible evidence, honest limitations, and independent verification. Low primitives belong only in concrete chain-gadget notes or a proven stronger chain.
---

# Report what was demonstrated

Only prepare standalone finding packages for demonstrated Medium, High, or
Critical impact. Do not package Informational or Low issues. Low behavior belongs
only in private chain-gadget notes or as a proven component of a stronger report;
never describe a hypothetical chain as demonstrated impact. See the shared
[severity policy](../bug-bounty/references/severity-policy.md).

Read the supported claim, relevant attempts, verification result, and engagement
requirements. Preserve original attribution and evidence references. Reconcile
contradictory observations before summarizing; do not average verdicts or hide
unresolved disagreement.

Write the concrete attacker starting capability, prerequisites, shortest working
reproduction, expected versus observed behavior, demonstrated consequence,
counterevidence/limits, independent verification status, and restoration steps.
Use exact redacted request references or runnable commands with credentials
resolved privately at execution time. Do not embed live credentials in commands,
reports, logs, or screenshots.

Keep raw captures and failed test history in private evidence; link a small
representative proof. Verify attachment existence and hashes before handoff.
Manually review images and secret-bearing formats the text helper cannot scan.
Do not equate response anomalies, exposed syntax, or a scanner label with impact.
Use program-specific reporting/severity policy only when it actually applies.

Run `bug-bounty check`. If unresolved hypotheses remain, report partial coverage
with blockers and next actions. Do not claim a completed engagement or independent
reproduction when the checker or actual evidence disagrees. Changes to the
technical claim after verification require a new reproduction packet.

For a report intended for user submission, load `bug-bounty-triage` and then
`bug-bounty-dedupe`. Obtain a passing decision for the exact draft bytes and a
complete comparison of the supplied same-target candidate manifest. Run
`bug-bounty --run RUN ready --id H-ID --report FILE`. Record the comparison search's
limits; no supplied candidates does not establish global uniqueness. Report-byte
edits require renewed triage/duplicate review; changes to the actual technical
claim or attacker prerequisites also require fresh reproduction.

Write any intended commit-ready report outside the ignored run directory, review
it for sensitive material, and hand it to the user. This skill does not submit,
publish, email, or create platform findings automatically.
