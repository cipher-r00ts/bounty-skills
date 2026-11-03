# Recon workflow reference

## Toolchain

The scripts put these directories on `PATH` themselves:

```bash
$HOME/go/bin
$HOME/.pdtm/go/bin
$HOME/.local/bin
```

Tools used, in pipeline order:

- `subfaster` — fast passive source sweep (first source, so httpx starts early)
- `subfinder` — broader passive sweep, catches what subfaster misses
- `assetfinder` — cheap extra pass, mostly duplicates
- `github-subdomains` — GitHub code search; needs `GITHUB_TOKEN` in the
  environment (never passed on the command line, never logged)
- `crt.sh` — optional extra source, `--with-crtsh`
- `httpx` — the HTTP stage, same profile as the user's `hx` wrapper
- `dnsx`, `tlsx`, `katana`, `nuclei` — single-host stage, optional
- `anew`, `jq`, `curl` — plumbing

Install gaps with `pdtm` or `go install`; re-check with:

```bash
. .opencode/skills/recon/scripts/lib.sh && recon_tool_versions
```

`github-subdomains` needs `export GITHUB_TOKEN=...`. Without it the source is
skipped with a warning and the rest of the pipeline still runs.

## Why the pipeline is incremental

The old flow ran every passive source, merged, then called httpx once. That
wastes the fastest source's lead time. Here each source is diffed against
everything already seen and only the new hosts are pushed into httpx:

```text
subfaster  -> raw -> normalize -> diff(seen) -> httpx batch 1
subfinder  -> raw -> normalize -> diff(seen) -> httpx batch 2
assetfinder-> raw -> normalize -> diff(seen) -> httpx batch 3
github     -> raw -> normalize -> diff(seen) -> httpx batch 4
```

`state/<domain>/seen.txt` is the running union; `state/<domain>/batches/` keeps
each diff so a run can be audited or replayed. `state/<domain>/summary.tsv`
records raw and new counts per source.

## Idempotency

Re-running `enum.sh` is safe:

- `seen.txt` is never truncated, so already-probed hosts are not re-sent
- `live/jsonl/*.jsonl` keeps one file per batch, and the merged views are
  rebuilt with per-URL deduplication (last observation wins)
- `summary.tsv` appends, so you can see what each run added

To force a full re-scan of one source, delete its `passive/<domain>/<tool>.txt`
and its `state/<domain>/batches/*-<tool>.new.txt`, then re-run. Do not delete
`seen.txt` unless you intend to re-probe everything.

## Artifact map

```text
artifacts/recon/
├── scope/scope.txt              frozen scope for the run
├── state/
│   ├── plan.json                classified scope
│   ├── plan.md                  plan with exact commands
│   ├── scope.md                 scope snapshot rendered
│   ├── <domain>/seen.txt        unique in-scope hosts, all sources
│   ├── <domain>/batches/        per-source diffs pushed to httpx
│   ├── <domain>/summary.tsv     per-source counts
│   ├── regprobe/paths.txt       registration paths probed
│   └── handoff/hosts.txt        tier 0-2 hosts for the host skill
├── passive/<domain>/            raw tool output, one file per source
├── passive/<domain>.txt         merged unique host list
├── live/jsonl/<stamp>-<tag>.jsonl   httpx JSON per batch
├── live/httpx.jsonl             merged, deduped by URL
├── live/httpx.txt               hx-style one-liner view
├── live/httpx_simple.txt        URLs only
├── hosts/<host>/                per-host artifacts
├── triage/candidates.tsv        score, tier, evidence
├── triage/browser.tsv           what the browser actually saw
├── triage/regprobe.tsv          registration/login findings
└── reports/                     detailed reports (hosts, portal checks)
```

## Priority report

`report.sh` writes the human-facing report to `targets/<target>/PRIORITY.md`,
not into `artifacts/`. A small scope stays in one file; above
`--split-threshold` (default 250) the file becomes an index and each tier gets
`targets/<target>/priority/tier<N>.md` (chunked further when a tier is huge).

The browser stage (`browser-probe.sh`) renders each candidate through
`agent-browser`, so the report can distinguish a real login portal from a
marketing shell that httpx saw as an empty 200. Its traffic goes through Caido
when the proxy is reachable, which also keeps the HTTP history complete.

## httpx profile

`hx-append.sh` mirrors the user's `hx` flags:

```bash
httpx -silent -json -follow-redirects -sc -cl -wc -title -server \
  -tech-detect -ip -cname -cdn -threads 100 -rate-limit 200 \
  -timeout 10 -retries 2 -p 80,443,8080,8000,8443,9443
```

JSON is the source of truth; `httpx.txt` is regenerated from it so both views
exist without scanning twice. If the user changes the `hx` profile, change it in
`hx-append.sh` only.

## Failure handling

- A source that fails keeps its partial raw output; the run continues.
- An empty source contributes nothing and is recorded with zero counts.
- If every source is missing, `enum.sh` exits with a warning after writing an
  empty merged list — report that instead of inventing hosts.
- CDN/WAF blocks show up as uniform 403s across the registration probe. That is
  `unknown` interactivity, not "no registration".
- If httpx returns nothing for a source diff, re-run that batch with
  `--no-merge` to keep the output separate, then inspect it by hand.

## Scope discipline

`enum.sh` normalizes every host and keeps only names ending in the scope root.
Wildcards that resolve outside the root (shared hosting, `*.cdn-provider.net`)
are dropped by design. If a scope entry is an exact host, use the host skill;
enumerating its subdomains would be out of scope.
