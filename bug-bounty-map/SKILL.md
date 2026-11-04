---
name: bug-bounty-map
description: Map a bug bounty target’s actors, workflows, trust boundaries, and observed behavior into focused hypotheses. Use before investigating an unfamiliar in-scope surface or missing access context.
---

# Map behavior before choosing tests

Read the `bug-bounty` run context and engagement scope. Reuse existing recon, browser,
proxy, and JS artifacts before acquiring more. Tool-specific execution belongs
to the matching existing skill; avoid rerunning a broad pipeline for one question.

Identify the application's important user actions, actor/role distinctions,
owned resources, state transitions, and server/client trust boundaries. Separate
observed facts with evidence references from assumptions needing validation.
An API name in JS is a clue; a browser request establishes an exercised route.
Use `bug-bounty-access` for usable account/role/object observations and `bug-bounty-walk`
when real workflow transitions can expose questions static recon cannot answer.

Prioritize questions where a concrete attacker capability could violate an
important boundary. For each useful question, record a hypothesis with `add`:
observed basis, attacker capability/prerequisites, smallest discriminating test,
supporting/refuting outcomes, and priority. Do not generate a vulnerability-class
checklist or assert that unvisited surfaces are safe.
Select plausible Medium+ consequences. Low primitives enter the worklist only
for a concrete exploit-chain role; routine informational facts stay in the map.

Keep a short target map in run-local notes: actors/access available, key flows,
resource ownership, evidence, inferred boundaries, and unresolved questions.
Update it when tests contradict an assumption; retain why it changed.

Handoff the map path, hypothesis IDs, available account labels, source references,
and access blockers. Finish mapping when there is enough context for valuable
bounded tests, not when every URL has been enumerated. Missing credentials
should lead to useful unauthenticated work or a named blocker.
