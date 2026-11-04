---
name: bug-bounty-counterevidence
description: Challenge a bug bounty candidate, test alternative explanations, and justify technical closure or preserve a proof gap. Keep below-floor policy rejection separate from technical refutation.
---

# Try to refute the claim

Start with the exact claim, attacker starting state, and observed evidence.
Construct a plausible alternative explanation: authorized ownership, intended
public data, stale sessions, proxy/cache artifacts, environment restrictions,
client-side-only changes, or a prerequisite the attacker cannot obtain.

Test the explanation with the smallest relevant control. Verify the control is
on this actual path, runs before the sensitive effect, and covers the identity
and method used. A safe sibling route, familiar library name, WAF page, 403,
missing credentials, or setup failure alone does not establish safety.

For a refutation, name the control or contradictory observation, where it was
seen, and how the baseline establishes the test was meaningful. For a supported
claim, preserve meaningful limiting facts and say why they do not neutralize
the demonstrated effect. Keep impact distinct from submission-policy eligibility.
Under our severity policy, a technically valid standalone Low/Informational issue
is below focus, not refuted. Keep a Low primitive only for a concrete chain role;
do not force a negative technical verdict or an inflated severity.

Record new observations as attempts under an owned claim. If this is independent
review, use a verification packet and separate review output instead of editing
the investigator's history. Do not overwrite origin attribution or silently
discard an unresolved candidate.

Handoff: exact claim evaluated, strongest alternative explanation, controls
performed, evidence, remaining proof gaps, and the observation that would change
the conclusion. Confidence follows the proof, not the desired severity.
