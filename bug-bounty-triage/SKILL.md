---
name: bug-bounty-triage
description: Assess a reproduced bug bounty report for demonstrated Medium+ impact, attacker prerequisites, intended behavior, and readiness. Use after investigation rather than for new hunting.
---

# Final substantive triage

Apply our [severity policy](../bug-bounty/references/severity-policy.md): standalone
Informational/Low reports do not pass our submission focus. A Low primitive may
be retained privately as a gadget for a specific chain, but the complete chain
must demonstrate Medium+ impact before a passing standalone report decision.
Record below-floor rejection as researcher policy, not technical disproval.

Read one current report, its supported claim, prerequisite records, independent
reproduction, and relevant program constraints. Do not accept the investigator's
severity or a prior model's verdict as proof. A different owner label alone does
not establish independent review.

Ask what the attacker demonstrably gains starting from the capability stated in
the report. Trace each prerequisite and victim action. Check that the reproduced
path matches the report, actual limits are disclosed, and controls rule out
plausible alternative explanations. Investigate whether behavior is intended
using relevant documented behavior or observed product expectations; do not infer
a security boundary solely from a suggestive interface label.

Keep this review focused on the report's existing claim. Perform only authorized
bounded checks needed to resolve its prerequisites, reproducibility, or accuracy.
Record new unrelated ideas for a later investigation rather than turning triage
into another hunt. Use current evidence to assess impact; submission floors and
format requirements apply only when the actual program specifies them.

Have the report owner reconcile corrections before recording the final gate:

```bash
bug-bounty --run RUN triage --id H-ID --owner TRIAGER --report report.md \
  --verdict pass --impact 'Demonstrated attacker consequence' \
  --attacker-path 'Starting capability and supported prerequisite chain' \
  --business-intent 'Evidence-based intended-behavior assessment' \
  --limits 'Actual constraints and unresolved nonessential questions' \
  --note 'Why the report is accurate and reproducible' --evidence redacted-triage.txt
```

Use `needs-evidence` for missing or contradictory proof and name the exact next
check. Use `rejected` when evidence supports rejection, explaining whether this
is a technical refutation, intended behavior, or program-policy ineligibility.
Do not conflate those outcomes or erase original evidence.

`pass` records a substantive review of the exact report bytes and current claim;
it requires current independent reproduction and reachable explicit prerequisites.
It does not certify every attachment or make publication automatic. Changes to
the claim/report require the affected review gates again. Handoff the frozen
report for `bug-bounty-dedupe`, then run `ready --id H-ID --report report.md`.

Adapted in original wording from the focused final-review mechanics in
[bbp Phase 09](https://github.com/mdpsec/bug-bounty-hunting-prompts/blob/main/phases/phase-09-triage-gate.md).
