---
name: bug-bounty-investigate
description: Investigate a concrete bug bounty hypothesis using controlled tests, observations, and revisions. Prioritize Medium+ outcomes and Low primitives only as concrete exploit-chain gadgets.
---

# Hypothesis-driven investigation

Prioritize plausible Medium+ consequences. A Low mechanism is useful only as an
evidenced gadget for a specific exploit-chain hypothesis. Record its chain role
and missing next step, rather than opening standalone report/verification work.
Drop informational and isolated Low leads from active pursuit. Do not equate
policy ineligibility with technical refutation or inflate a gadget's severity.

Read `bug-bounty` context and the selected hypothesis. Load only the relevant tool
or technique references; document their paths/versions in the procedure. Claim
the hypothesis and any account/browser resources before testing. Check the
program constraints, current identity, budget, and baseline session health.

State the attacker capability, affected object, expected boundary, and the one
change that tests it. Obtain an unchanged baseline and a contrasting control.
Prefer researcher-owned fixtures; minimize changes and preserve restoration data
in sensitive storage when it contains private values. No bulk collection is
needed to establish a boundary failure. Stop on disruption, unexpected account
effects, scope ambiguity, or the engagement's stated stop conditions.

Observe status, content/semantic effect, identity and ownership, redirects,
caching, asynchronous behavior, and state restoration as applicable. A different
status/length/timing is a lead, not automatically a demonstrated consequence.
On tool failure, distinguish an unavailable environment from a failed hypothesis.
Change the next action based on observations rather than repeating payloads.

Record each meaningful attempt with exact redacted procedure, identity, result,
control, and evidence. `supported` means the proposed consequence has evidence;
`refuted` requires an identified control or a concrete contradiction;
`inconclusive` preserves uncertainty; `blocked` names a missing prerequisite
and recovery step. A blocked test is never evidence of safety.

Before claiming a finding, load `bug-bounty-counterevidence`. For a supported
mechanism, use `bug-bounty-prerequisites` to resolve the actual attacker path before
presenting its conditional impact as proven. Missing access is blocked, while a
demonstrated unreachable acquisition path limits the claim without erasing the
mechanism evidence. Request independent reproduction through `bug-bounty-verify`. Preserve
spin-off ideas as separate hypotheses; pursue only within the original scope
and budget. Restore changes, verify cleanup, and release claims before handoff.
