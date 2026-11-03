---
name: Wildcard Subdomain Recon
description: >
  Enumerate subdomains for a wildcard or apex scope entry and stream each source's new hosts into httpx
  immediately. Use when the scope contains *.example.com, a bare apex domain, or when the user asks to
  "enumerate subdomains", "run the subdomain pipeline", "find all subdomains", or "recon the wildcard".
  Produces per-source diffs, live HTTP metadata, a real browser pass over the apps, and the target-root
  priority report.
---

# Wildcard subdomain recon

Runs the passive sources in order and treats every source as its own batch:
the diff is pushed to httpx the moment it exists, instead of waiting for the
slowest source.

## Run

```bash
.opencode/skills/recon-wildcard/scripts/enum.sh --target <target> --domain <root>
```

Options that matter:

- `--include-apex` — also probe the root itself (use for bare apex scope entries)
- `--with-crtsh` — add the certificate-transparency source
- `--tools subfaster,subfinder,assetfinder,github` — reorder or narrow sources
- `--no-http` — collect names only, no httpx
- `--rate 200 --threads 100 --timeout 10` — keep these conservative
- `--source-timeout 900` — hard cap per source; a hung source is killed and its
  partial output is kept. Lower it when you want a fast pass with only the
  quick sources.
- `--triage` — after enumeration, run the full priority pipeline: triage, a
  browser pass over the top candidates, the registration probe, re-triage, and
  the target-root report. Needs `agent-browser`.
- `--browse-limit 60` / `--regprobe-limit 100` — cap the two active stages in
  `--triage`; they are the only part of this skill that sends real traffic.

The source order is not arbitrary. `subfaster` is the fastest and gets httpx
started earliest; `subfinder` widens coverage; `assetfinder` is a cheap
third opinion; `github-subdomains` is noisy (expect duplicates) but regularly
finds names the passive DNS sources never see.

## What happens to each source

1. Raw output is written to `passive/<root>/<tool>.raw.txt`.
2. It is normalized: lowercase, scheme/path/port stripped, wildcards removed,
   and anything outside `<root>` dropped.
3. The normalized set is diffed against `state/<root>/seen.txt`; the diff goes
   to `state/<root>/batches/<n>-<tool>.new.txt`.
4. Only that diff is sent to `hx-append.sh`, tagged with the source name.
5. `seen.txt` and `summary.tsv` are updated before the next source starts.

If a source is missing, not configured, fails or times out, log it and continue.
Never abort the run because one source is unavailable. `subfinder -all` against
a program with many configured providers can be slow; it runs after subfaster
precisely because the fast source has already fed httpx by then.

## Reading the result

- `passive/<root>.txt` — every unique in-scope host across all sources
- `live/httpx.jsonl` — merged HTTP observations (source of truth)
- `live/httpx.txt` — hx-style one-liners for a quick eyeball
- `state/<root>/summary.tsv` — per-source raw and new counts
- `triage/browser.tsv` — what the browser saw, once the browser pass has run

Report the yield per source in the chat summary: it tells the user which
source is actually earning its runtime for this program.

## After enumeration

The useful output is a priority report, and it is built from what the apps
actually do, not only from httpx headers:

```bash
# 1. initial ranking (no traffic)
.opencode/skills/httpx-triage/scripts/triage.sh --target <target>

# 2. browse the real apps, through Caido by default
.opencode/skills/recon-wildcard/scripts/browser-probe.sh --target <target>

# 3. registration probe on the top hosts
.opencode/skills/httpx-triage/scripts/regprobe.sh --target <target> --limit 100

# 4. merge browser + registration evidence and write the report
.opencode/skills/httpx-triage/scripts/triage.sh  --target <target>
.opencode/skills/httpx-triage/scripts/report.sh  --target <target>
```

`browser-probe.sh` opens each candidate with `agent-browser`, records the
rendered title, final URL, form/password counts, SPA framework and a text
snippet, and keeps the traffic in Caido's history. That is what catches a
React portal with an empty httpx title, or a login form that only exists after
JavaScript runs.

Or run all of it in one command:

```bash
.opencode/skills/recon-wildcard/scripts/enum.sh --target <target> --domain <root> --triage
```

The result is `targets/<target>/PRIORITY.md`: one report when the scope is
small, or an index plus `priority/tier<N>.md` files when the target has too
many hosts for one file. For each tier 0-2 host, continue with
`recon-single-domain`; `state/handoff/hosts.txt` is still the queue.

Browser prerequisites: `npm install -g agent-browser && agent-browser install`.
On this box Chrome also needs the local lib wrapper, which `browser-probe.sh`
detects automatically.

## Notes and limits

- The scripts never brute-force names; they are passive only.
- A wildcard root that returns the same IP for every name (wildcard DNS) will
  show up as many live hosts with identical metadata. Flag it in the report
  instead of treating every name as a separate target.
- GitHub results need `GITHUB_TOKEN`; without it that source is skipped and
  recorded as such.
- Re-running is safe. To re-probe everything for one source, remove its raw and
  batch files, not `seen.txt`.
