---
name: js-security-analysis
description: >
  Analyze an acquired JavaScript corpus for security-relevant behaviour: DOM gadgets, routes, API calls,
  secrets, libraries, subdomains, and ready-to-fire HTTP requests. Use when a JS file, URL, inline script,
  or js-acquire run root is provided and the user asks to analyze, review, audit, deobfuscate, or mine it.
---

# JavaScript security analysis

Second half of the pipeline: `js-acquire` collects bytes and provenance, this
skill explains what they contain and produces leads for authorized validation.
Never probe endpoints, use credentials, or submit payloads because code reveals
them. Generate requests as artifacts; executing them is a separate decision.

Historical versions are handled by `js-wayback-diff`; consume its output here
rather than re-fetching the archive.

## Inputs and output root

Prefer a `js-acquire` run root, e.g.
`targets/<target>/artifacts/recon/js/`. `raw/` is immutable input. A single file
or directory can also be analyzed; create a run root and record provenance in
`analysis/site-summary.md`.

```text
<run-root>/
├── raw/                        immutable acquisition input
├── beautified/{inline,external}
├── ast/{inline,external}/, ast/symbols.json
├── analysis/
│   ├── inline/, external/      one note per input
│   ├── site-summary.md
│   └── checklist.md
├── findings/
│   ├── api/<Functionality>/<version>/
│   ├── gadgets.md
│   ├── endpoints.jsonl
│   ├── hosts.jsonl
│   ├── subdomains.txt
│   ├── subdomains-scope.txt
│   ├── subdomains-thirdparty.txt
│   ├── requests/               ready-to-fire raw HTTP + collection.http
│   ├── historical.jsonl        from js-wayback-diff
│   ├── secrets.jsonl
│   ├── comments.jsonl
│   ├── libraries.md
│   ├── framework-techstack.md
│   └── feature-map.md
├── logs/
└── verification_report.md
```

## Step 1 — checklist before analysis

Create `analysis/checklist.md` before deobfuscating or scanning. One row per
input per lens, plus cross-file rows. For long corpora load the `unlazy` skill
and write `GATES.md` first so the run cannot be reported done at 30%.

```markdown
- [ ] <file> - beautify/deobfuscate | artifact: beautified/external/<file> | log: logs/deobfuscate.log
- [ ] <file> - AST and symbols | artifact: ast/external/<file>.ast.json | log: logs/ast.log
- [ ] <file> - gadgets | artifact: findings/gadgets.md | log: logs/gadgets.log
- [ ] <file> - routes, flags, comments | artifact: analysis/external/<file>.md | log: logs/routes.log
- [ ] <file> - API calls | artifact: findings/endpoints.jsonl | log: logs/api.log
- [ ] <file> - libraries and framework | artifact: findings/libraries.md | log: logs/library.log
- [ ] <file> - secrets | artifact: findings/secrets.jsonl | log: logs/secrets.log
- [ ] cross-file hosts and subdomains | artifact: findings/hosts.jsonl | log: logs/hosts.log
- [ ] cross-file ready-to-fire requests | artifact: findings/requests/ | log: logs/requests.log
- [ ] cross-file feature map | artifact: findings/feature-map.md | log: logs/feature-map.log
- [ ] cross-file site summary | artifact: analysis/site-summary.md | log: logs/site-summary.log
```

For a lens with no result, create a non-empty artifact or log containing
`None found` and explain coverage. Check a row only when its artifact and
timestamped log both exist. Redact cookies, tokens and full secret values from
all artifacts.

## Step 2 — inventory and triage

Inventory every file in `raw/manifest.json`; if absent, hash the inputs and note
the limitation. Classify each file: bundled/minified (webpack/rollup/vite,
module arrays, `__webpack_require__`), hand-obfuscated (string-array decoders,
dispatchers), source-mapped, or application vs vendor. Record classification
and hash per file.

## Step 3 — beautify, deobfuscate, AST

Write behavior-preserving readable copies to `beautified/`. Do not “fix” code.
Generate AST JSON when a parser is available and merge globals/exports into
`ast/symbols.json`. On parser failure, write a non-empty failure note and
continue with lexical analysis.

## Step 4 — security gadgets

Inspect DOM sources/sinks, `postMessage` origin checks, prototype pollution,
client-side auth gates, dynamic imports, navigation/redirect construction,
WebSocket/GraphQL boundaries, and sensitive storage. Write one consolidated
`findings/gadgets.md`, one numbered section per primitive with file, location,
source → sink path, sanitization, confidence, and suggested authorized
validation. A sink is not proof of exploitability; mark unresolved sources.

## Step 5 — routes, parameters, flags, APIs

Extract admin/privileged routes, role checks, feature flags, TODO/FIXME
comments, environment names and interesting parameters into the per-file note
and `findings/comments.jsonl`.

For every fetch/XHR/Axios/GraphQL/WebSocket/Beacon/form/SDK call append one
object to `findings/endpoints.jsonl`, and a readable note under
`findings/api/<Functionality>/<version>/`. Record:

- method, path/template, host, source file and location, request/response shape
- auth material observed (dynamic cookie, storage, header, static value, none)
- ID-shaped path/query/body fields as IDOR candidates, not claims
- privilege signals, flags, redirects, error handling

Example:

```json
{"method":"GET","path":"/api/orders/{orderId}","host":"app.example.com","evidence":"external/app.js:1234","auth":"session cookie","body":""}
```

## Step 6 — hosts and subdomains from JS

This is the check the original analysis skill was missing. Run:

```bash
python3 .opencode/skills/js-security-analysis/scripts/extract_hosts.py \
  --root targets/<target>/artifacts/recon/js --domain example.com
```

It scans `raw/external`, `raw/inline` and `raw/historical`, extracts hosts from
URLs, protocol-relative URLs, `host:`/`hostname:` fields and bare domain
literals, then writes:

- `findings/hosts.jsonl` — host, in-scope flag, hit count, source files
- `findings/subdomains.txt` — every unique host
- `findings/subdomains-scope.txt` — hosts at or below the target domain
- `findings/subdomains-thirdparty.txt` — everything else, for takeover and
  dependency review

Feed new in-scope names back into `recon-wildcard` / `recon-single-host`. Mark
subdomain-takeover candidates only when a CNAME or provider error actually
matches; a hostname in a JS file is a lead, not a finding.

## Step 7 — ready-to-fire HTTP requests

Generate raw requests that can be pasted into Caido Replay or Burp Repeater:

```bash
python3 .opencode/skills/js-security-analysis/scripts/make_requests.py \
  --root targets/<target>/artifacts/recon/js --base-host app.example.com
```

Output:

- `findings/requests/<NNNN>_<METHOD>_<slug>.req` — raw HTTP/1.1 requests with
  `Cookie: <SESSION>` / `Authorization: <TOKEN>` placeholders
- `findings/requests/collection.http` — one file for bulk import
- `findings/requests/index.md` — human-readable index with evidence
- `findings/requests/manifest.json` — normalized endpoint metadata

Placeholders are deliberate: never bake a live session into an artifact that
gets committed. Replace them at send time, and only for hosts in scope.

## Step 8 — libraries, framework, tech stack

`findings/libraries.md`: every third-party library, detected version, evidence,
confidence, and whether it appears outdated. Verify CVEs against advisories; do
not infer a version from code shape. `findings/framework-techstack.md`:
framework, router, build tool, GraphQL/REST/WebSocket signals, analytics,
server-side clues. Separate facts from inference.

This feeds `recon-single-domain`'s technology-specific checks (Spring actuator,
Grafana endpoints, Jenkins exposure, Swagger/OpenAPI, GraphQL, …).

## Step 9 — secrets and high-entropy strings

`findings/secrets.jsonl`, one object per candidate, separated into known
patterns (AWS, Google, Stripe, Slack, JWT, private keys, bearer, database) and
high-entropy strings. Mask values to a safe prefix/suffix; never write a full
secret into artifacts or chat. Sentry DSNs, public client IDs, UUIDs, hashes and
feature flags are informational unless code evidence shows sensitive access.

## Step 10 — historical versions

Run `js-wayback-diff` against the corpus, then consume:

- `findings/historical.jsonl` — per URL/version pair, paths and hosts present
  in the archive but absent from the current bundle
- `diffs/<slug>.diff` — bounded textual diffs
- `findings/historical-summary.md` — ranked old-only endpoints

Treat old-only paths as leads: they may be removed from the UI but still routed
server-side. Add them to the feature map and, when authorized, to the request
collection with placeholders.

## Step 11 — cross-file summary and feature map

`analysis/site-summary.md`: auth/session flow, privileged routes, API surface,
hosts, framework/build stack, shared utilities, sourcemap coverage, limitations.
`findings/feature-map.md`: prioritized handoff.

Use P1 only for a clear, low-effort path to meaningful impact; P2 for credible
leads needing runtime confirmation; P3 for informational or low-confidence
observations. Static candidates are not vulnerability claims.

## Step 12 — verify and hand off

```bash
python3 .opencode/skills/js-security-analysis/scripts/verify_checklist.py \
  targets/<target>/artifacts/recon/js --checklist targets/<target>/artifacts/recon/js/analysis/checklist.md
```

The verifier checks every row, artifact size, and timestamped log, then writes
`verification_report.md`. Do not call the run complete while it exits non-zero.

Handoff: run root, verification report, feature map, site summary, host lists,
request collection, and counts (files, gadgets, endpoints, hosts, secrets,
historical-only paths). State coverage and limitations explicitly.
