---
name: Portal Recon
description: >
  Agent-assisted testing of portal-class hosts that do not offer registration: admin, analytics, support,
  dashboard, corp and internal panels. Use after triage hands over a tier 1 portal, or when the user says
  "check this admin panel", "try default creds", "bypass the 403", "see if the login is client-side only",
  or "fuzz this portal". Runs bounded, non-destructive checks and records every attempt.
---

# Portal recon

Tier 1 hosts from triage. These are the panels a normal user cannot register
for, so the interesting questions are different from a consumer app:

- does the front end trust a client-side flag the server should be enforcing?
- is the 403 only on the route, not on the API behind it?
- are the docs or the API spec exposed?
- is a default credential still valid?
- is there an older path the new gate forgot?

## Step 0 — read before touching

- Confirm the host is tier 1 in `targets/<target>/PRIORITY.md` (or
  `triage/candidates.tsv`) and appears in `state/handoff/hosts.txt`.
- Run the single-host skill first if you have not; its JS and endpoint
  artifacts are the best input here.
- Open `reports/hosts/<host>-portal.md` after each probe run and append what
  you learn; do not start a second report file.

## Step 1 — bounded probes

```bash
.opencode/skills/recon-portal/scripts/checks.sh --target <target> \
  --url https://portal.example.com --all
```

What it does, all unauthenticated and single-shot:

- compares the baseline response against a fixed set of header bypasses
  (`X-Forwarded-For`, `X-Original-URL`, `X-Rewrite-URL`, `X-Custom-IP-Authorization`, …)
- compares path normalization variants (`//`, `/./`, `/%2e/`, `/..;/`, `;`,
  `.json`, whitespace encodings)
- reads the CORS response for a reflected evil origin, including credentials
- greps the landing page and first ten scripts for client-side auth flags
  (`isAdmin`, `isLoggedIn`, role checks, localStorage/sessionStorage use)

Flag every difference, not every request. A redirect to `/login` when the
baseline was 403 is worth a look; a 404 with a different body length is not.

## Step 2 — manual credential check (requires explicit approval)

Never run this unless the user has approved credential testing for this program.

Rules:

1. One attempt per credential pair per form. Stop the host at the first 423,
   repeated 429, or lockout banner.
2. Keep the set tiny: `admin:admin`, `admin:password`, `admin:admin123`,
   `test:test`. Nothing else.
3. Log every attempt to `state/portal-attempts.log` before sending it.
4. Try HTTP Basic and the visible form separately; a 200 on Basic auth with a
   dashboard body is the success signal, not a 200 on the login page.
5. If the login is a SPA calling a JSON API, replay the API call directly and
   inspect the response body, not just the status.

## Step 3 — client-side authorization

Look for the pattern where the UI hides a route but the server serves it:

- a role or plan flag in localStorage, sessionStorage or a cookie that the app
  reads to decide what to render
- a JWT whose payload contains `role` and is accepted without signature
  verification (`alg: none`, weak secret) — test only with your own token
- a redirect after login that can be skipped by requesting the target URL
  directly with the pre-login cookie
- API responses that include fields the UI hides (another tenant's data,
  internal flags) — that is a lead for BOLA, not a bug yet

Confirm by replaying with two accounts you own, never by guessing other users'
identifiers.

## Step 4 — discovery

If the host exposes a docs endpoint, pull it before fuzzing:

- `/swagger`, `/swagger-ui`, `/openapi.json`, `/api-docs`, `/redoc`, `/graphql`
- `/actuator`, `/debug`, `/console`, `/server-status`, `/.well-known/`
- `robots.txt` disallow entries

Then run a small, rate-limited wordlist against the interesting base paths.
Do not run a 100k word list against a production portal; start with the
program's own JS and docs, then a short list.

## Step 5 — record

Append to `reports/hosts/<host>-portal.md`:

- what you sent (header, path, body shape) and what came back
- why it matters, in one sentence
- whether it is a lead, a confirmed issue, or a dead end

Only when you can reproduce an impact with your own account, write a finding:

```bash
hackbot finding add --help
```

Recon observations stay in the report. Findings are for reproduced issues.

## Guardrails

- Scope only, one host at a time.
- No password spraying, no credential stuffing, no user enumeration at scale.
- No destructive actions: no delete, no settings changes, no data exports
  beyond what a normal account can do.
- Respect rate limits; if the host starts returning 429 or 503, stop.
- If the program forbids automated scanning, use the browser and do it by hand.
