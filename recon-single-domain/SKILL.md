---
name: Single Domain Recon
description: >
  Full recon for one domain or host: authenticated or unauthenticated mapping, JS acquisition and analysis,
  wordlist-driven ffuf discovery, parameter discovery, and technology-specific checks, ending in a
  table-free per-host report. Use for an exact host in scope, or after wildcard triage hands over a target.
---

# Single domain recon

Runs the complete post-triage workflow for one host. It composes the other
skills instead of duplicating them:

- `recon-single-host` — passive map (DNS, TLS, headers, well-known, JS refs)
- `js-acquire` — browser capture of first-party JS and inline blocks
- `js-security-analysis` — hosts/subdomains and ready-to-fire requests
- `js-wayback-diff` — historical-only API paths
- this skill — wordlists, ffuf, parameters, tech checks, report

## Modes

- **Unauthenticated** — default when invoked from a wildcard handoff or when no
  session is supplied.
- **Authenticated** — pass a Caido `export-curl --config` snapshot. The session
  is validated before anything runs; headers are copied to
  `/tmp/recon-auth/<host>/headers.txt` with mode 600 and never enter the repo.
- **auto** — use the session if it validates, otherwise fall back to
  unauthenticated with a warning.

```bash
# unauth
.opencode/skills/recon-single-domain/scripts/run.sh --target 3hk --host mlp.three.com.hk

# auth (after the caido-mode skill exported a config)
.opencode/skills/recon-single-domain/scripts/run.sh \
  --target 3hk --host corp.portal.three.com.hk \
  --auth-config /tmp/caido/corp.portal.three.com.hk/auth.cfg --mode auth
```

If auth is supplied but the session is dead, `--mode auth` stops instead of
silently testing anonymously; `auto` downgrades and says so.

## Pipeline

```text
map -> JS -> wordlists -> fuzz (unauth, then auth) -> params -> tech -> report
```

Each stage can be skipped (`--skip-map`, `--no-js`, `--skip-fuzz`,
`--skip-params`, `--skip-tech`) and every command is printed with `--dry-run`.

### 1. Map

Runs `host-recon.sh` when the host has no `httpx.jsonl` yet. This supplies the
tech stack for the technology checks and the sitemap/robots/JS refs used to
build custom wordlists.

### 2. JavaScript

Browser capture via `agent-browser` through Caido, first-party only
(`--same-site-only`), capped with `--js-max` (default 80). Then
`extract_hosts.py` writes in-scope and third-party hosts. `--wayback` adds the
timeline and historical diff.

### 3. Wordlists

Profiles over the installed roots (`SECLISTS_ROOT`, `API_ROOT`):

- `light` — SecLists common + API endpoints
- `standard` — raft-medium-directories + API endpoints (default)
- `deep` — raft-small-words + raft-medium-files + API endpoints

Plus custom paths from sitemap, robots, the host map, JS endpoints, and an
optional katana crawl (`--crawl`). Onelistforall/assetnote are used
automatically when their roots exist; otherwise the build logs them as missing.

Per-host output: `domain/wordlists/dirs.txt`, `params.txt`, `manifest.json`.

### 4. Fuzzing

`ffuf` with bounded defaults: rate 40, 20 threads, status filter
`200,204,301,302,307,401,403,405`, 404 filtered, extensions
`php,asp,aspx,jsp,json,js,txt,bak,old,zip`. Requests go direct: do not push a
wordlist run through Caido, it floods history. In auth mode the same lists run
again with the session, and `domain/fuzz/auth-only.txt` records endpoints that
only respond when logged in — often the highest-value result.

### 5. Parameters

`arjun` (installed in the repo `.venv`) when available, otherwise an ffuf
parameter sweep with `burp-parameter-names.txt` (5000 names) against up to 10
discovered paths. Results land in `domain/params/params.jsonl`. Arjun is the
default engine; `--tool ffuf` forces the fallback.

### 6. Technology checks

Fingerprint-driven, read-only GETs:

- Spring: `/actuator`, `/actuator/health`, `/actuator/env`, `/actuator/mappings`
- Grafana: `/api/health`, `/public/build/manifest.json`, `/api/dashboards/home`
- Jenkins: `/api/json`, `/manage`
- Tomcat: `/manager/html`, `/host-manager/html`
- Always: Swagger/OpenAPI paths, `/.git/HEAD`, `/.env`, `/server-status`,
  `/phpinfo.php`

Hits require a matching response body, not just a 200. Add stack-specific
cheatsheets under `references/tech/` as they are provided; the script's check
table is the place to wire new paths.

## Output

```text
targets/<target>/artifacts/recon/hosts/<host>/
├── httpx.jsonl, headers.txt, sitemap.xml ...   from the map
├── js/                                         js-acquire run root
└── domain/
    ├── mode.json
    ├── wordlists/{dirs,params}.txt
    ├── fuzz/{endpoints.jsonl,ffuf_*.json,auth-only.txt}
    ├── params/params.jsonl
    └── checks/tech.jsonl

targets/<target>/artifacts/recon/reports/hosts/<host>-domain.md
```

The report is table-free and links back to JS findings. `report-lint.sh` runs at
the end; fix failures rather than ignoring them.

## Guardrails

- Scope check against `state/plan.json` before any request.
- Never commit auth headers; they live under `/tmp/recon-auth/`.
- Fuzzing is rate-limited and direct; do not raise the rate to finish faster.
- Technology checks are GET-only and read a bounded body. No exploitation.
- Historical and JS-discovered hosts are leads; do not test outside recorded
  scope.
- If the program forbids automated scanning, run the map and JS stages only.
