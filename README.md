# Bug bounty skills for OpenCode

A set of OpenCode skills for web application and bug bounty recon: subdomain
enumeration, HTTP triage, host and domain recon, portal testing, JavaScript
acquisition and analysis, historical JS diffing, account registration, Caido
workflows, and completion discipline.

Extracted from a private hunting setup so other hunters can use the same
pipeline. Each skill is a directory with a `SKILL.md` frontmatter file plus its
`scripts/`, `references/`, or `templates/` folders.

## Install

OpenCode loads skills from `.opencode/skills/` in a project and from
`~/.config/opencode/skills/` globally.

Project-local install (recommended — the command examples inside each skill use
these paths):

```bash
git clone <this-repo> your-project/.opencode/skills
```

Global install:

```bash
git clone <this-repo> ~/.config/opencode/skills
```

When installed globally, the `.opencode/skills/<name>/...` paths in the skill
docs do not exist in the current project. Substitute
`~/.config/opencode/skills/<name>/...` for them.

Restart OpenCode after installing so it rescans skill directories.

## Skills

| Skill | Purpose |
|---|---|
| `recon` | Dispatcher: runs recon for a hackbot target from recorded scope, writes reports |
| `recon-wildcard` | Subdomain enumeration for wildcard/apex scope, per-source diffs, httpx |
| `recon-single-host` | Host-level recon for one exact host: DNS, TLS, headers, well-known, JS |
| `recon-single-domain` | Full post-triage workflow for one domain, composes the other skills |
| `httpx-triage` | Prioritize httpx output, registration-open and portal queues |
| `recon-portal` | Bounded, non-destructive testing of admin/portal panels |
| `registration` | Register and verify a test account via Gmail alias and OTP |
| `js-acquire` | Collect JS: browser, inline, lazy bundles, sourcemaps, Wayback URLs |
| `js-security-analysis` | Analyze a JS corpus: gadgets, routes, APIs, secrets, hosts |
| `js-wayback-diff` | Historical JS timeline and diffs against current bundles |
| `caido-mode` | Caido SDK CLI: HTTPQL history search, proxied curl, replay, collections |
| `unlazy` | Completion discipline: acceptance gates, Depth Tree, evidence checks |

## Requirements

The recon pipeline expects these on `PATH`:

- `bash`, `curl`, `jq`, `python3`
- `subfinder`, `httpx`, `ffuf`, `katana`, `nuclei`, `dnsx`, `tlsx`
- optional: `assetfinder`, `gau`, `waybackurls`, `arjun`
- the private `hackbot` CLI used to store targets and scope (the `recon`
  scripts call `hackbot target show`; replace with your own target store if you
  do not have it)

Skill-specific dependencies:

- `caido-mode`: Node.js with `npm`, a running Caido instance, and a Caido
  Personal Access Token. Run `npm install` in `caido-mode/` after cloning.
- `registration`: a Gmail account with an app password or OAuth setup, plus
  Composio for the mailbox helper.

## Target-specific examples

Script headers and docs use real hosts from a previous engagement
(`three.com.hk`, `simworld.net`) as examples. They are illustrative only — no
credentials, tokens, or harvested data are included. Replace them with your own
in-scope hosts.

## Layout and sync

This repo is also used as a standalone working copy. To refresh it from the
original project:

```bash
rsync -a --delete --exclude '.DS_Store' ~/BugBounty/.opencode/skills/ ~/skills/
```

That command is intentionally one-way. Review the diff before committing.

`caido-mode/node_modules/` is ignored by git; reinstall with `npm install` in
that folder.

## Credits and license

- `unlazy` is MIT licensed, copyright (c) 2026 Leonxlnx, upstream:
  https://github.com/Leonxlnx/unlazy. Its upstream CI workflow was removed from
  this copy so this repo's Actions stay quiet; restore it from upstream if you
  want the test matrix.
- `caido-mode` is built on the official `@caido/sdk-client`.
- The remaining skills were written for this pipeline. Add a root `LICENSE`
  before distributing publicly if you want to grant explicit reuse terms.
