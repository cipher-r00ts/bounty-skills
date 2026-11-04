---
name: bug-bounty-verify
description: Independently reproduce a bug bounty claim or meaningful exploit chain from a frozen packet with fresh evidence and controls. Use after discovery in a separate agent or fresh session.
---

# Independent reproduction

Spend reproduction effort on plausible Medium+ findings or meaningful chain
proof. Do not independently polish or certify an isolated Low/Informational issue;
a Low gadget is relevant only as part of a concrete chain investigation.

Start from a `bug-bounty packet` file supplied by the coordinator, current program
constraints, and necessary safe fixtures/account labels. Do not read discovery
transcripts, run.json, or sibling reviewers' conclusions to form your result.
The helper itself reads state to check ownership and revisions; this does not
mean the reviewing model needs the discovery history in its context.

Confirm the claim's stated attacker capability and prerequisites. Independently
derive and execute a minimal permitted reproduction with a baseline and negative
control. Check the actual consequence, not only the investigator's response
pattern. Use fresh owned objects when possible. Coordinate resource claims with
the controller before account mutations or shared browser work.

Keep the input package unchanged. Save your evidence separately and use a
different attributable owner label. Register and clean temporary resources;
restore changed state. Do not copy the old capture and call it a reproduction.

Record `verify --packet V-ID` with verdict `reproduced`, `refuted`, or `blocked`,
your actual procedure, control, limitations, and fresh evidence. A stale packet
requires a new packet from the coordinator. Missing access yields blocked,
not refuted. A different owner label alone cannot certify independence.

If the host cannot provide a separate context, explicitly report that limitation
and leave independent reproduction pending; do not impersonate a second worker.
Return the packet ID, evidence references, observed effect, counterevidence,
prerequisite gaps, and cleanup status. The coordinator owns final report edits.
