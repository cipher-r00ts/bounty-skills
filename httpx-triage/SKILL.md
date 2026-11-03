---
name: HTTPX Subdomain Triage
description: >
  Turn httpx output into a prioritized, table-free recon report. Use when httpx results exist or the user
  asks "which subdomains should I test", "prioritize these hosts", "triage the recon output", "what is
  juicy", or wants the registration-open and portal lists. Adds interactivity (can I create an account?)
  ahead of every other signal, then splits hosts into manual-hunting and agent-recon queues.
---

# HTTPX subdomain triage

Input is the merged `live/httpx.jsonl` (preferred) or an hx-style
`live/httpx.txt`. Output is a set of markdown reports and two action lists.

Priority order, highest first:

1. Can a stranger create an account? → manual hunting, tier 0.
2. Is it a management/analytics/support portal? → agent recon, tier 1.
3. Is it an auth or API surface? → tier 2.
4. Normal application → tier 3.
5. Static, edge, dead → tier 4.

An admin panel nobody can log into is worth less than a plain app that will
give you a session. That is why interactivity now outranks the admin keyword.

## Pipeline

```bash
# score once so the browser pass knows what is worth visiting
.opencode/skills/httpx-triage/scripts/triage.sh --target <target>

# open the real apps in a browser (through Caido by default)
.opencode/skills/recon-wildcard/scripts/browser-probe.sh --target <target>

# check account creation paths on the top hosts
.opencode/skills/httpx-triage/scripts/regprobe.sh --target <target> --limit 100

# register on tier 0 hosts with the registration skill
# (mailbox.py alias -> otp/link, see .opencode/skills/registration/SKILL.md)

# merge everything and write the priority report
.opencode/skills/httpx-triage/scripts/triage.sh  --target <target>
.opencode/skills/httpx-triage/scripts/report.sh  --target <target>
```

`browser-probe.sh` is the part that separates a real app from an httpx line:
it renders each candidate, records the final URL after redirects, the rendered
title, form and password counts, the SPA framework and a text snippet. Those
facts are merged into the score and shown in the report as browser evidence.
`regprobe.sh` checks account paths and classifies a host as `registration`,
`login` or nothing. `report.sh` writes the single target-level report.

Run the whole chain once per target. Do not run `report.sh` per root: the
priority report is target-wide, and a per-root run would overwrite it with a
subset.

## Step 1 — parse

For every JSON line keep: host, URL, status, content length, word count, title,
webserver, CDN name, tech list, final URL. Deduplicate per host, preferring a
non-404 observation, then 200, then https. Ignore `failed: true` lines but
count them in the data-quality note.

If the input is the txt view, parse the bracketed fields positionally, take the
final status when redirects are chained, and strip userinfo before deciding the
host. A missing CDN field means "not detected", not "no WAF".

Then merge `triage/browser.tsv` on host: the rendered title wins over the
pre-JS title, a password field implies a login surface even when the probe
found nothing, an SPA framework is evidence of interactivity, and a final URL
on another host is an off-scope redirect (do not test the destination).

## Step 2 — score

Points are internal. Do not print raw scores as a table; the report shows the
score next to each host as a bullet.

### Interactivity (decisive)

- registration reachable: +50 and tier 0 regardless of other signals
- login form with password field, no registration: +20 (browser-observed
  password fields count even when the static HTML has none)
- client-side app shell that calls an API (SPA markers, `__NEXT_DATA__`,
  `ng-version`, heavy JS): +10 (a browser-detected React/angular/Vue/Next app
  counts)
- off-scope SSO login redirect (e.g. Entra ID): +15 and a tier-2 floor
- page is a static marketing page: no bonus

### Subdomain label keywords

- `admin`, `administrator`, `adm`: +30
- `api`, `apis`: +25
- `staging`, `stage`, `stg`: +25
- `dev`, `develop`, `developer`: +25
- `test`, `testing`, `qa`, `uat`: +20
- `internal`, `intranet`, `corp`: +25
- `vpn`, `remote`, `citrix`: +20
- `login`, `auth`, `sso`, `oauth`: +25
- `portal`, `dashboard`, `panel`, `analytics`, `console`, `ops`, `bi`, `manage`: +20
- `jenkins`, `jira`, `confluence`, `gitlab`, `github`, `bitbucket`: +30
- `grafana`, `kibana`, `elastic`, `splunk`, `datadog`: +28
- `sonarqube`, `nexus`, `artifactory`: +28
- `mail`, `smtp`, `webmail`, `exchange`: +15
- `ftp`, `sftp`, `upload`: +20
- `backup`, `bak`, `old`, `legacy`: +22
- `beta`, `preview`, `demo`, `sandbox`: +18
- `payment`, `payments`, `pay`, `checkout`, `billing`: +25
- `cdn`, `assets`, `static`, `media`, `files`: +5
- `docs`, `documentation`, `wiki`: +8
- `help`, `support`, `status`: +5

Match on labels, not substrings inside unrelated words. `capital.example.com`
is not an API.

### Status

- 200: +10
- 301 or 302: +5
- 401: +20
- 403: +18
- 404: −5
- 500: +15
- 503: +5

### Edge

- no CDN detected: +15
- CDN or WAF detected: −5

### Server and tech

- version string in the server header: +10
- `IIS`: +8
- `Apache`: +5
- `express` or `node`: +8
- no server header: +5
- `Werkzeug`: +12 (dev server in production)
- `Jetty` or `Tomcat`: +10

Take the strongest applicable server signal, not the sum.

### Title

- `index of`, `directory listing`: +35
- `swagger`, `openapi`, `redoc`, `api docs`: +25
- `jenkins`, `gitlab`, `grafana`, `kibana`, `jira`: +30
- `dashboard`, `admin`, `panel`, `console`: +20
- `login`, `sign in`: +15
- `error`, `exception`, `debug`, `stack trace`: +20
- empty or `403 forbidden`: +5

### Size

- zero words: −5
- 1–20 words: +5 (sparse page, often a bare API or an error)
- more than 500 words: +8

Clamp the final score at zero.

## Step 3 — assign tiers

- Tier 0 — registration reachable. Manual hunting.
- Tier 1 — portal class (admin, analytics, console, dashboard, support, corp,
  internal, panel, ops, BI, manage) or score ≥ 70. Agent recon.
- Tier 2 — auth or API surface (401, 403, login/auth/api labels, a detected
  login page) or score ≥ 45.
- Tier 3 — everything at score ≥ 20.
- Tier 4 — the rest.

## Step 4 — the two queues

The priority report keeps the queues separate, table-free:

- **Tier 0 — registration open.** Register with the `registration` skill
  (per-target Gmail alias, OTP and confirmation-link pickup), then map the
  authenticated surface, test BOLA/IDOR with your own objects, mass assignment
  on signup, stored XSS in profile fields, uploads.
- **Tier 1 — portals.** The agent queue: default credentials (one attempt per
  pair), client-side auth checks, 403 bypass, content discovery. That workflow
  lives in `recon-portal`.

Do not mix "I can log in" hosts with "I cannot get in" hosts; the testing
strategy is different.

## Step 5 — reports

The priority report lives at the target root, not inside the artifact tree:

- `targets/<target>/PRIORITY.md` — the report to read first.
- With `total hosts ≤ --split-threshold` (default 250): that single file holds
  every tier, every host exactly once.
- Above the threshold: `PRIORITY.md` becomes an index and each tier gets its
  own file under `targets/<target>/priority/`: `tier0.md`, `tier1.md`, … and
  `tier1_001.md`, `tier1_002.md` when a tier exceeds 250 hosts.
- Force either layout with `--single` or `--split`; tune the cut with
  `--split-threshold N`.

Never compress the host list into a table to save space; split the file
instead and link the parts. `report-lint.sh` checks both trees.

Always include in the index:

- counts per tier and per status
- how many hosts sit behind a CDN
- how many expose registration
- the most common tech
- a line stating that tiers are priority, not confirmed vulnerabilities

## Edge cases

- All hosts behind one CDN: say so; prioritise by interactivity and titles
  anyway, and note that WAF behaviour may flatten status differences.
- Uniform 403 across every registration path: record `unknown`, not "no
  registration". WAF bot management causes this.
- Soft 404 apps: trust the keyword evidence over the status code; `regprobe.sh`
  compares against a baseline 404 path for this reason.
- Duplicate hosts across ports: one row per host, keep the most informative
  observation.
- IP-literal results: keep them, flag them as direct-origin candidates.
- Malformed lines: skip and report the count in the data-quality note.

## Framing for the report

Suggested checks should stay within OWASP-style, in-scope testing:

- broken access control: IDOR/BOLA with two accounts you own
- authentication flaws: reset tokens, OAuth `redirect_uri`, session flags
- injection: reflected/stored XSS, SQLi in parameters that reach a query
- SSRF on URL-taking features (webhooks, imports, previews)
- misconfiguration: debug pages, directory listing, exposed API docs
- default credentials on portals, tested once per pair with logging
- subdomain takeover only when the DNS record and the provider error actually
  match; a 404 on a hostname is not takeover evidence
