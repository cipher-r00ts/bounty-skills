---
name: Recon
description: >
  Run bug bounty recon on a hackbot target from its recorded scope. Use this skill whenever the user says
  "run recon on <target>", "recon this scope", "start recon", "enumerate this target", "do wildcard recon",
  or gives a target name plus a scope list of domains, URLs and wildcards. Dispatches to the wildcard,
  single-host, triage and portal skills, keeps every artifact under the target directory, and produces
  table-free markdown reports.
---

# Recon (dispatcher)

Entry point for recon on one hackbot target. You classify the scope, run the
right sub-skill per scope entry, and keep the report index honest.

Everything this skill writes stays inside the target tree:

```text
targets/<target>/
├── PRIORITY.md                  the report to read first
├── priority/tier<N>.md          tier files, only when the scope is large
└── artifacts/recon/
    ├── scope/scope.txt          scope snapshot used for this run
    ├── state/plan.json          classified scope items
    ├── state/plan.md            human-readable plan
    ├── passive/<domain>/        raw per-tool subdomain output
    ├── live/                    httpx jsonl + txt views
    ├── hosts/<host>/            per-host artifacts
    ├── triage/                  scores, browser observations, reg probes
    └── reports/                 detailed reports (per host, portal checks)
```

## Before you start

1. Resolve the target: `hackbot target show <target> --json`. If it does not
   exist, stop and ask the user to create it; do not invent scope.
2. Confirm scope out loud in the plan: every item you will touch must appear in
   the recorded scope. Never scan a host that is not in it.
3. Check the toolchain:

```bash
. .opencode/skills/recon/scripts/lib.sh
recon_tool_versions
```

Missing tools are skipped by the scripts, not fatal. Say which ones were
missing in the final summary.

## Step 1 — classify and plan

```bash
.opencode/skills/recon/scripts/recon.sh init --target <target>
```

This creates the layout, snapshots the scope, and prints the plan. Read it:
wildcard entries go to `recon-wildcard`, bare apex domains also go to
`recon-wildcard`, exact hosts go to `recon-single-host`, IPs are recorded but
not automated.

If the user supplied a scope override for this run, pass it explicitly:

```bash
.opencode/skills/recon/scripts/recon.sh init --target <target> --scope-file scope.txt
```

The snapshot becomes the source of truth for the run, so re-running `init`
without `--scope*` reuses it instead of re-reading the database.

## Step 2 — run the pipeline

Wildcard or apex domain:

```bash
.opencode/skills/recon-wildcard/scripts/enum.sh --target <target> --domain <domain>
```

This streams each source through httpx as soon as its diff lands. It is
resumable: `state/<domain>/seen.txt` prevents duplicate work.

Single host, full workflow (map, JS, ffuf, params, tech checks, report):

```bash
.opencode/skills/recon-single-domain/scripts/run.sh --target <target> --host <host>
```

Authenticated variant:

```bash
.opencode/skills/recon-single-domain/scripts/run.sh --target <target> --host <host> \
  --auth-config /tmp/caido/<host>/auth.cfg --mode auth
```

Passive map only:

```bash
.opencode/skills/recon-single-host/scripts/host-recon.sh --target <target> --host <host>
```

## Step 3 — triage, browse, report

```bash
# rank once
.opencode/skills/httpx-triage/scripts/triage.sh --target <target>

# open the real apps in a browser (through Caido), capture login forms / SPAs
.opencode/skills/recon-wildcard/scripts/browser-probe.sh --target <target>

# account-creation probe on the top hosts
.opencode/skills/httpx-triage/scripts/regprobe.sh --target <target> --limit 100

# merge and write the target-root priority report
.opencode/skills/httpx-triage/scripts/triage.sh  --target <target>
.opencode/skills/httpx-triage/scripts/report.sh  --target <target>
```

Load the `httpx-triage` skill before interpreting the output. Tier 0 is the
manual queue (registration works); tier 1 is the agent queue (portals).

The report is always `targets/<target>/PRIORITY.md` — one file for a small
scope, or an index plus `targets/<target>/priority/tier<N>.md` above the split
threshold (default 250 hosts).

## Step 4 — hand off

`report.sh` writes `state/handoff/hosts.txt` (tier 0–2). Feed it to the host
skill in batches, or to `recon-portal` when the host is a portal:

```bash
while read -r h; do
  .opencode/skills/recon-single-host/scripts/host-recon.sh --target <target> --host "$h"
done < targets/<target>/artifacts/recon/state/handoff/hosts.txt
```

## Step 5 — close the loop

```bash
.opencode/skills/recon/scripts/recon.sh index --target <target>
.opencode/skills/recon/scripts/report-lint.sh --target <target>
```

`report-lint.sh` fails on markdown tables, broken links, unlinked reports and
oversized parts. Fix failures before you call the run finished.

Finally summarise for the user, without tables:

- scope items processed and hosts discovered
- tier counts and the registration-open hosts (manual queue)
- portal hosts handed to agent recon
- what the browser pass changed versus the httpx-only ranking
- missing tools or sources that failed
- a link to `targets/<target>/PRIORITY.md` (and `priority/` when split)

## Guardrails

- Scope only. A host that does not match the snapshot is out of scope; ask.
- Respect the rate limits in the scripts (`--rate`); do not raise them to
  finish faster.
- No destructive testing, no brute force, no credential attempts through this
  skill. Credential work lives in `recon-portal` and needs explicit approval.
- Never write a finding from recon alone. Findings need a reproduced impact.
- Reports are table-free. If content grows, split into parts and link them; do
  not compress it into a table.
