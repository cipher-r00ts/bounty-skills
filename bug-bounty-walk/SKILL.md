---
name: bug-bounty-walk
description: Discover bug bounty hypotheses through real browser workflows and captured traffic while preserving session ownership. Use for an authorized interactive hunt rather than a generic scanner sweep.
---

# Let application behavior guide discovery

Look for plausible Medium+ outcomes. Keep Low behavior only when it provides a
specific evidenced gadget for an exploit-chain hypothesis; skip standalone
Informational/Low vulnerability queues and report work.

Read `bug-bounty` context, the target map, existing flow evidence, and usable access
observations. Select a valuable product flow based on actual application behavior
and the assignment. Use the host's browser and existing Caido/JS skills for exact
tool syntax; the `bug-bounty` helper only records observations.

Keep one controller for a shared browser session. Follow the flow through its
relevant transitions, observing identities, owned objects, request/response
semantics, origins, redirects, asynchronous work, and persistence as applicable.
Separate a visible UI change from a server-side consequence. Record actual
evidence and distinguish inferred behavior from observed behavior.

Before a concrete security test, create or select a durable hypothesis and claim
it plus shared mutation resources. A browser walk does not itself authorize
state-changing tests. Use owned fixtures and the engagement's permitted bounds;
register temporary resources and restore reversible changes.

Checkpoint each useful flow observation:

```bash
bug-bounty --run RUN walk --flow 'Product action and identity context' \
  --status observed --observation 'Observed behavior, boundaries, and limitations' \
  --hypothesis H-ID --owner CONTROLLER --evidence redacted-flow.txt
```

Omit `--hypothesis` when the observation yields no concrete test question. Use
`--status blocked` and describe the exact access/tool/environment gap when the
flow cannot be exercised. An unvisited or blocked flow is not clean coverage.

When delegation is authorized, hand independent work a bounded question,
selected references, safe evidence, exact artifact ownership, and stop conditions.
Stateless server-side investigation may proceed separately while the controller
continues browsing. Workers must not navigate the controller's profile or mutate
the same account concurrently. Keep session-dependent work with its owner.

Use `bug-bounty-investigate` for promising hypotheses and diversify the next question
when workers converge on the same mechanism. Stop according to the engagement
budget or concrete exhaustion of useful permitted questions, not a finding quota.
Handoff observed flows, linked hypotheses, unresolved routes, and cleanup state.

Adapted in original wording from the browser-led discovery mechanics in
[bbp Phase 04b](https://github.com/mdpsec/bug-bounty-hunting-prompts/blob/main/phases/phase-04b-browser-walk.md)
and [Phase 05b](https://github.com/mdpsec/bug-bounty-hunting-prompts/blob/main/phases/phase-05b-critical.md).
