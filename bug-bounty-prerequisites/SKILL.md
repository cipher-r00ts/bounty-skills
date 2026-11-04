---
name: bug-bounty-prerequisites
description: Resolve the attacker prerequisites separating a demonstrated bug bounty mechanism from a usable exploit chain. Use for missing identifiers, roles, delivery paths, victim actions, or state.
---

# Prove the missing rung

Read the selected hypothesis, existing attempts, and concrete attacker starting
capability. Identify each value, role, action, consumer, or state the claimed
attack requires. Separate what the researcher knows from what the attacker can
obtain through the permitted target surface.

Owning accounts A and B can establish that A reaches B's object given its
identifier. It does not establish that an attacker controlling only A can obtain
that identifier. Conversely, an exposed identifier alone does not demonstrate a
broken authorization boundary. Keep these propositions and their evidence distinct.

Choose a specific unresolved prerequisite and the smallest permitted test that
can settle it. State the acquisition/delivery path, expected evidence, controls,
and what would refute the path. Inspect previous attempts to avoid repeating an
exhausted search. Do not pursue generalized escalation or polish a report while
its own essential attacker path remains unsupported.

Claim the hypothesis, then record each prerequisite observation:

```bash
bug-bounty --run RUN prerequisite --id H-ID --name 'Specific prerequisite' \
  --state reachable --attacker-path 'Acquisition or delivery from stated attacker capability' \
  --note 'Observed result, bounds, and control' --owner WORKER \
  --evidence redacted-prerequisite-check.txt
```

Use `reachable` only with demonstrated evidence. Use `unreachable` for the named
path when a meaningful test supports that conclusion; do not claim universal
impossibility from one failed route. Use `blocked` for unavailable access,
environment, or testing permission, and `untested` for a concrete remaining
question. Preserve a recovery step or next discriminating test in the note.

A proven mechanism with an unresolved prerequisite remains a candidate, not a
submission-ready impact claim. A blocked check is not a refutation. Keep honest
current impact distinct from conditional stronger impact. Do not use found
credentials or test other people's resources merely because they might resolve
a prerequisite; the engagement's authorization still controls execution.

Prerequisite records change the hypothesis revision. Once requirements are
resolved, obtain a current reproduction packet through `bug-bounty-verify`; earlier
verification cannot establish the newly completed attacker path. Handoff the
remaining proof gap or the exact supported path and evidence.

Adapted in original wording from the candidate/prerequisite mechanics in
[bbp Phase 06](https://github.com/mdpsec/bug-bounty-hunting-prompts/blob/main/phases/phase-06-triage.md).
