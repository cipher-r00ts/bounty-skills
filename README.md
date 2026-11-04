# Bug bounty skills for OpenCode

A set of OpenCode skills for web application and bug bounty recon: subdomain
enumeration, HTTP triage, host and domain recon, portal testing, JavaScript
acquisition and analysis, historical JS diffing, account registration, Caido
workflows, hypothesis-driven hunting with evidence and verification, and
completion discipline.

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
| `bug-bounty` | Coordinator: hypothesis memory, evidence, resume packets, independent reproduction |
| `bug-bounty-map` | Map actors, workflows, trust boundaries, and observed behavior into hypotheses |
| `bug-bounty-walk` | Discover hypotheses through real browser workflows and captured traffic |
| `bug-bounty-investigate` | Controlled tests for one concrete hypothesis; Medium+ focus |
| `bug-bounty-access` | Establish researcher-owned accounts, roles, sessions, and objects |
| `bug-bounty-prerequisites` | Resolve the attacker prerequisites separating a mechanism from a usable chain |
| `bug-bounty-counterevidence` | Challenge a candidate and justify technical closure or preserve the gap |
| `bug-bounty-triage` | Assess demonstrated Medium+ impact, prerequisites, and report readiness |
| `bug-bounty-dedupe` | Compare with same-target reports for shared root cause and new evidence |
| `bug-bounty-report` | Package demonstrated findings with reproducible evidence and limitations |
| `bug-bounty-verify` | Independently reproduce a frozen packet with fresh evidence and controls |
| `recon` | Dispatcher: runs recon for a hackbot target from recorded scope, writes reports |
| `recon-wildcard` | Subdomain enumeration for wildcard/apex scope, per-source diffs, httpx |
| `recon-single-host` | Host-level recon for one exact host: DNS, TLS, headers, well-known, JS |
| `recon-single-domain` | Full post-triage workflow for one domain, composes the other skills |
| `httpx-triage` | Prioritize httpx output, registration-open and portal queues |
| `recon-portal` | Bounded, non-destructive testing of admin/portal panels |
| `registration` | Register and verify multiple test accounts, roles, and peers via Gmail alias and OTP |
| `js-acquire` | Collect JS: browser, inline, lazy bundles, sourcemaps, Wayback URLs |
| `js-security-analysis` | Analyze a JS corpus: gadgets, routes, APIs, secrets, hosts |
| `js-wayback-diff` | Historical JS timeline and diffs against current bundles |
| `caido-mode` | Caido SDK CLI: HTTPQL history search, proxied curl, replay, collections |
| `unlazy` | Completion discipline: acceptance gates, Depth Tree, evidence checks |

## Using the bug-bounty group

The `bug-bounty*` skills are a coordinated set, not independent prompts.
`bug-bounty` is the entry point and routes work to the focused skills, which in
turn call the recon, JavaScript, Caido, and registration skills for execution.
Install the whole repo rather than a single `bug-bounty` folder, and keep the
group together when copying it into another project.

`bug-bounty/scripts/install.py` can symlink the group into OpenCode, Codex, and
`~/.local/bin`:

```bash
python3 bug-bounty/scripts/install.py
```

`registration` deliberately creates multiple accounts, roles, and same-type
peers per target. Cross-user and role-based authorization tests need distinct
identities, so this is expected behavior rather than account farming. The
prohibition on creating accounts to evade rate limits still applies, and any
program-specific signup restrictions still take precedence.

## Notes on this copy

This repo is maintained separately from the private hunting project it was
extracted from, so a few files intentionally differ from that working copy.
Users and agents installing these skills should know:

- The `registration` skill supports multiple accounts and roles per target for
  authorization testing; older copies limited this to one account per domain.
- `caido-mode` is written for a generic install. Point `CAIDO_URL` at your
  instance and run `bin/caido setup` with your own PAT; the documented
  `127.0.0.1:8081` default is just the author's local setup.
- `unlazy`'s upstream CI workflow is omitted so this repo's Actions stay quiet.
- `bug-bounty*` adapt mdpsec's Bug Bounty Hunting Prompts (MIT); provenance and
  license text are in `bug-bounty/references/upstream.md`.
- Examples and script headers use hosts from past engagements (see
  [Target-specific examples](#target-specific-examples) below); replace them
  with your own in-scope targets.

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
rsync -a --delete \
  --exclude '.DS_Store' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'README.md' --exclude '.gitignore' \
  ~/BugBounty/.opencode/skills/ ~/skills/
```

That command is intentionally one-way. Review the diff before committing. The
`README.md` and `.gitignore` excludes keep this repo's own files from being
deleted, and bytecode is never copied.

`caido-mode/node_modules/` is ignored by git; reinstall with `npm install` in
that folder.

## Credits and license

- `unlazy` is MIT licensed, copyright (c) 2026 Leonxlnx, upstream:
  https://github.com/Leonxlnx/unlazy. Its upstream CI workflow was removed from
  this copy so this repo's Actions stay quiet; restore it from upstream if you
  want the test matrix.
- The `bug-bounty*` skills adapt mdpsec's Bug Bounty Hunting Prompts (MIT),
  reviewed at commit `5ed4158`. Full provenance and license notice are in
  `bug-bounty/references/upstream.md`.
- `caido-mode` is built on the official `@caido/sdk-client`.
- The remaining skills were written for this pipeline. Add a root `LICENSE`
  before distributing publicly if you want to grant explicit reuse terms.
