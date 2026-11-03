---
name: Single Host Recon
description: >
  Host-level recon for one exact host in scope: DNS, TLS, HTTP metadata, security headers, well-known files,
  JS bundle and endpoint extraction, optional crawl and safe nuclei templates. Use when the scope lists an
  exact URL or hostname, or when triage hands over a specific subdomain. Writes artifacts per host and a
  table-free report.
---

# Single host recon

For scope entries that are exact hosts, and for the winners handed over by
triage (`state/handoff/hosts.txt`).

## Run

```bash
.opencode/skills/recon-single-host/scripts/host-recon.sh --target <target> --host <host>
```

Options:

- `--url https://host/` — start from a specific URL instead of the https root
- `--crawl` — shallow katana crawl (depth 2, rate 30 by default)
- `--nuclei` — low-rate `exposure,misconfig,tech,headers` templates only
- `--depth`, `--rate`, `--timeout` — keep them conservative
- `--force` — only when you have confirmed the host is in scope by hand

The script refuses a host that does not match `state/plan.json`, so a typo does
not turn into out-of-scope traffic.

## What it collects

- DNS A and CNAME records (`dnsx`, falling back to `getent`)
- certificate SANs, CN and subject org (`tlsx`)
- status, title, server, tech, CDN, IP (`httpx`)
- response headers and the landing page
- `robots.txt`, `sitemap.xml`, `.well-known/security.txt`, `humans.txt`,
  `security.txt`, each with its status code
- script and link references, then up to 25 JS bundles fetched and mined for
  URLs and path-like strings
- optional crawl and nuclei output

Everything lands in `artifacts/recon/hosts/<host>/` and the draft report in
`reports/hosts/<host>.md`.

## How to read it

Start with the draft, then add the interpretation the script cannot do:

- `sitemap.xml` returning 200 usually maps the app better than any wordlist.
- `security.txt` gives you the program's contact and sometimes policy hints.
- Compare `robots.txt` disallow entries against what actually loads; hidden
  admin paths are often listed there.
- In the JS bundles, prioritise absolute hosts (internal APIs, staging
  backends) and paths containing `admin`, `internal`, `v2`, `graphql`.
- Missing security headers are hardening gaps. Only report them when the
  program's policy accepts them, and never as a standalone critical finding.
- A 403 on the root but 200 on `/login` means the app is alive; test the login
  flow rather than hammering the root.

## After the report

If the host has a login or registration page, it belongs in the manual queue:
create an account, then test with two accounts you own. If it is a portal with
no registration, move to `recon-portal`.

## Guardrails

- Passive by default. `--nuclei` is opt-in and limited to safe tags; do not
  enable intrusive template sets on a production host you do not own.
- No credential attempts here.
- One host per run; do not point the script at a wildcard.
- Findings need reproduction. The draft report records observations only.
