---
name: bug-bounty-access
description: Establish usable researcher-owned accounts, roles, sessions, and objects for a bug bounty hunt. Use when access is unverified, incomplete, stale, or needed for a planned hypothesis.
---

# Prepare usable access

Read the `bug-bounty` run context and current scope/program constraints. Use existing
registration, browser, and Caido workflows for their actual commands. Inspect
existing account labels and sessions before provisioning anything. This skill
does not authorize signup, paid actions, bypasses, or work outside recorded scope.

Establish what each available identity can actually do: authenticate, reach the
application, exercise the relevant role, create an owned test object, and recover
or refresh the session where needed. Distinguish registration success from
usable product access. A pending invitation, empty tenant, provisioning wall,
expired session, or inaccessible required role is a specific limitation.

Use stable account labels in run metadata; keep credentials, factors, session
files, and private object values in existing sensitive storage. Record only
redacted evidence. Assign exact account/profile ownership before shared mutation,
and preserve original state plus restoration requirements.

Record each meaningful observation with:

```bash
bug-bounty --run RUN access --account ACCOUNT_LABEL --role ROLE --state usable \
  --capability 'Observed actions available and relevant object ownership' \
  --owner WORKER --evidence redacted-access-check.txt
```

Use `partial` when some useful access exists but a relevant capability is missing,
and `unavailable` when this identity cannot currently be used. Name the exact
failure and useful next step in `--capability`. A recorded usable state is an
observation, not a guarantee that the session remains live; recheck it before a
test that depends on it.

Continue useful public or single-account investigation when the available access
supports it. Do not invent a second identity or stall all work behind an
unavailable role. Request user intervention only for a concrete missing resource
whose resolution matters to the assignment; otherwise preserve the blocker.

Handoff account labels, observed roles/capabilities, usable owned-object types,
evidence, session limitations, ownership, and restoration work. Do not mark a
cross-account prerequisite reachable merely because both test accounts exist.

Adapted in original wording from the access-preparation mechanics in
[bbp Phase 01](https://github.com/mdpsec/bug-bounty-hunting-prompts/blob/main/phases/phase-01-access.md).
