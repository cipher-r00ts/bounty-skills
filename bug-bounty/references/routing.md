# Skill selection and architecture

The host model chooses the next action. Skills provide methods; the `bug-bounty`
helper stores observations and checks invariants. It neither calls a model nor
sends requests. Shell/browser/proxy tools remain owned by the host.

Use the smallest relevant bundle:

- Unknown surface: `bug-bounty-map` plus existing `recon` or `recon-single-domain`.
  Inspect their options before running broad stages; their defaults do not
  supersede the engagement's rates or authorization.
- Client behavior or API clues: `js-acquire` then `js-security-analysis`.
  Static clues become hypotheses, not findings. Source locations are valuable
  evidence; live reproduction requires its own authorization and observations.
- Captured application traffic: `caido-mode` for exact local command syntax,
  authentication file handling, proxy history, and Replay handoffs. Keep auth
  material out of new run metadata and public commands.
- A plausible boundary failure: `bug-bounty-investigate`, then the specific local
  technique reference justified by the mechanism. There is no required taxonomy.
- Candidate closure: `bug-bounty-counterevidence`; name the actual control or keep
  the proof gap open. A blocked environment is not a negative test.
- Supported claim: `bug-bounty-verify` in a fresh context, then `bug-bounty-report`.
- Missing usable product access: `bug-bounty-access`; signup alone is insufficient.
- Interactive product exploration: `bug-bounty-walk`; one controller owns the session.
- Proven mechanism with a missing attacker-delivery rung: `bug-bounty-prerequisites`.
- Draft after current reproduction: `bug-bounty-triage` for intended behavior,
  actual impact, constraints, and focused accuracy checks.
- Triaged report: `bug-bounty-dedupe` for offline comparison of root causes and
  remediation, then `ready` against the exact report file. See [workflow commands](workflow.md).

Do not load every skill at startup. Pass a compact shared contract to workers,
not unrelated transcripts. Keep facts, inference, and unresolved questions
separate. Tool failures are observations that can change the plan; do not hide
them or repeatedly retry an unchanged failing setup.

What is implemented: file-backed runs, append-only attempt/event behavior,
atomic locked updates, task/resource claims, budget visibility, evidence copies
and hashes, separate verification packets, revision-bound review records,
bounded output, and completion checks.

What remains a host/procedure responsibility: actual skill selection, delegation,
fresh reviewer sessions, request scope/rate enforcement, browser isolation,
process termination, and judging technical evidence. Prompt guidance cannot
constrain an unrestricted shell. Review labels cannot authenticate an identity.

These are original workflow instructions inspired by locally reviewed Strix
prompt composition/counterevidence/lifecycle patterns and the bbp pack's phased
handoffs/independent reproduction. No upstream runtime, payload library, or
private helper is bundled. Relevant local sources: `/tmp/opencode/strix` and
`/tmp/opencode/bbp`; those checkouts are not runtime dependencies.
The [upstream record](upstream.md) pins the bbp source and preserves its license.
