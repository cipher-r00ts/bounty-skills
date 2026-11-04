---
name: Account Registration
description: >
  Register and verify test accounts on an in-scope target without a human:
  generate a per-account Gmail alias, wait for the verification email, pull the
  OTP or confirmation link, and record the account. Use when triage marks a host
  tier 0, or the user says "register an account", "sign up and verify", "read
  the verification email", "get the OTP", or "use gmail for signup".
---

# Account registration

Tier 0 hosts are the ones where a stranger can create an account. That is the
cheapest way to get a session and test the authenticated surface. This skill
closes the only step that used to need a human: the verification email.

The mailbox is read-only. Nothing is sent, nothing is marked read, and the
password never appears in output.

## Rules — read before the first form

1. **Scope.** The host must be in `targets/<target>/PRIORITY.md` or
   `state/handoff/hosts.txt`. Do not register on a host that is only linked
   from an in-scope page.
2. **Opt-in.** Some programs forbid account creation or automated signup. If the
   program notes do not allow it, stop and ask. Never mass-create accounts.
3. **Accounts for authorization testing.** There is no one-account-per-target
   or one-account-per-type cap. Create accounts as needed across the account
   types and roles supported by the target, including multiple accounts of
   the same type for cross-user authorization tests. Base the number on the
   planned tests and program constraints; reuse suitable existing accounts.
   Do not create accounts to dodge rate limits.
4. **No bypass.** A CAPTCHA, phone/SMS check, invite code, or manual approval is
   a stop sign. Hand it to the human; do not solve, rent, or bypass it.
5. **Fictional identity.** Use a consistent test persona, never a real person's
   name, address, or phone number. Do not put the client's or your own identity
   in the form.
6. **Secrets stay local.** Accounts are written under
   `targets/<target>/state/registration/`, which is gitignored. Never paste a
   password or OAuth credential into a report, commit, or chat.

## One-time setup — direct Gmail API

The API path requests exactly one scope, `gmail.readonly`. The tool cannot
send, delete, or modify mail. The refresh token is stored outside the repo with
mode `0600`.

In the [Google Cloud console](https://console.cloud.google.com/):

1. Create a project (for example `bb-registration`) and select it.
2. **APIs & Services > Library > Gmail API > Enable**.
3. **OAuth consent screen**: user type **External**, publishing status
   **Testing**. Add the burner Gmail address under **Test users**. Add the scope
   `https://www.googleapis.com/auth/gmail.readonly`.
4. **Credentials > Create credentials > OAuth client ID > Desktop app**. Create
   it and download the JSON.
5. Authorize:

```bash
# machine with a browser
.opencode/skills/registration/scripts/oauth_setup.py \
  --client-secrets ~/Downloads/client_secret_XXXX.json

# headless host (no GUI): start, approve elsewhere, finish
.opencode/skills/registration/scripts/oauth_setup.py \
  --client-secrets ~/Downloads/client_secret_XXXX.json --start
# open the printed URL on any device, approve, copy the failed
# http://127.0.0.1:8765/?code=... address bar
.opencode/skills/registration/scripts/oauth_setup.py \
  --finish 'http://127.0.0.1:8765/?code=...&state=...'
```

The browser flow opens the consent screen and captures the loopback callback.
The headless flow writes the PKCE verifier and state to
`~/.cache/opencode/gmail-oauth-state.json` (mode `0600`, 15-minute lifetime),
then exchanges the pasted redirect. The authorization code is single-use and
useless without the local verifier.

Sign in with the burner. Google shows "Google hasn't verified this app" because
the app is in Testing — **Advanced > Go to (unsafe)** is expected for a personal
read-only client. On success the script verifies the mailbox with a profile call
and writes:

```json
{"gmail": {"address": "...", "oauth": {"client_id": "...",
  "client_secret": "...", "refresh_token": "...", "scope": "..."}}}
```

`--no-browser` prints the loopback URL without opening it (pair it with an SSH
tunnel); `--print-url` is a dry run.

Verify at any time:

```bash
.opencode/skills/registration/scripts/mailbox.py check
```

`check` reports `backend: gmail-api`, the granted scope, the message count, and
the inbox unseen count. It reads no message content.

**Seven-day caveat.** An External app left in Testing gets refresh tokens that
expire after 7 days. When `check` says `invalid_grant`, re-run `oauth_setup.py`.

### Keeping the token alive

The 7-day limit applies only while the consent screen is in **Testing**. Google's
[personal-use exception](https://support.google.com/cloud/answer/13464323)
allows an unverified app with fewer than 100 users, so:

1. **Google Auth Platform > Audience > Publishing status > Publish app**. This
   moves the project to **In production**. Do not submit for verification;
   personal use is exempt, and the unverified warning plus 100-user cap are
   acceptable for one mailbox.
2. Re-run `oauth_setup.py` once. The new refresh token is issued under
   production status and is no longer subject to the 7-day rule.
3. Keep the client secret private: the app is now in production, even if
   unverified.

If the console insists on verification for `gmail.readonly`, the alternatives
are a Workspace **Internal** app (no expiry, no warning, needs a Workspace
organization) or the IMAP App Password backend below (no expiry, but a
full-mailbox IMAP credential). `setup.sh` writes `backend: imap` and
`oauth_setup.py` writes `backend: gmail-api`, so switching is explicit and does
not require deleting the other credential.

### Fallback — IMAP App Password

If a Google Cloud project is not an option, the IMAP backend still works. It
needs **2-Step Verification**, an **App Password**, and IMAP enabled:

```bash
.opencode/skills/registration/scripts/setup.sh \
  --address 'recon.example@gmail.com'
```

That writes `app_password` instead of `oauth`; `mailbox.py` picks the backend
from the config. The App Password grants full mailbox IMAP access at the
protocol level even though this tool only reads, so use a dedicated burner.

All three backends accept `--config` or `$GMAIL_CONFIG`; Composio is configured
through the OpenCode MCP entry instead. Use a dedicated account; do not hand
this repository your personal mailbox.

## Backend selection

Three ways to read the verification mail, in order of preference:

1. **Composio Gmail MCP** — managed OAuth, no 7-day Testing token, read-only
   workflow. Use it when the `composio` MCP tools are available.
2. **Direct Gmail API** (`mailbox.py`) — our OAuth client. Works today; the
   refresh token is subject to the Testing-mode caveat above.
3. **IMAP App Password** (`mailbox.py`) — no expiry, broader credential.

If the `composio` MCP is connected, prefer the Composio read tools for Gmail.
Keep `mailbox.py` for alias generation, parsing, and as the fallback.

## Composio Gmail MCP

The server is configured in `~/.config/opencode/opencode.json`. This host uses
the consumer-key header path, so there is no OAuth callback:

```json
{
  "mcp": {
    "servers": {
      "composio": {
        "type": "remote",
        "url": "https://connect.composio.dev/mcp",
        "oauth": false,
        "headers": {"x-consumer-api-key": "<consumer key>"}
      }
    }
  }
}
```

The config is mode `0600`. **On this host `opencode mcp list` already shows
`✓ composio connected`; skip the sign-in below and start with
`GMAIL_GET_PROFILE`.** The consumer key is a broad Composio credential: keep it
in the 0600 config, never in the repo, and revoke it in the Composio dashboard
when the engagement ends.

For a fresh host, run `/mcps` in the OpenCode UI, select **composio**, and sign
in with a Composio account (free Hobby plan, no credit card). Do not run
`opencode mcp auth` through a shell; the authorization link can be lost in
background output. The server status must change from `needs authentication`
to connected before the tools appear.

On a headless host, skip `/mcps` and use a Composio project key:

1. Create a free Composio account at <https://dashboard.composio.dev>.
2. **Settings → Project Settings → API Keys** → copy the project key (`ak_...`).
3. Create a Gmail-only session MCP and write it into the OpenCode config:

```bash
.../composio_setup.py --api-key 'ak_...'
# or: COMPOSIO_API_KEY=ak_... .../composio_setup.py
```

The script creates a Gmail-only Tool Router session, writes the endpoint and
header into `~/.config/opencode/opencode.json` (mode `0600`), and prints a
**Connect Link**. Open that link on any device and approve the burner. The
session MCP URL and headers are secrets; the script only prints the hostname.

When a Gmail action first runs, Composio returns a **Connect Link**. Open it,
approve Gmail for the burner account, then wait for the connection:

- `COMPOSIO_SEARCH_TOOLS` — find Gmail tools and get a suggested plan.
- `COMPOSIO_GET_TOOL_SCHEMAS` — fetch the exact arguments for a tool slug.
- `COMPOSIO_MANAGE_CONNECTIONS` — list or create the Gmail connection.
- `COMPOSIO_WAIT_FOR_CONNECTIONS` — wait for the user to finish the Connect Link.
- `COMPOSIO_MULTI_EXECUTE_TOOL` — execute the chosen Gmail tool.

Gmail tools used by this skill:

- `GMAIL_GET_PROFILE` — confirm which mailbox is connected.
- `GMAIL_FETCH_EMAILS` — search with Gmail syntax and return message metadata.
- `GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID` — full body for one message.
- `GMAIL_GET_THREAD` / `GMAIL_LIST_THREADS` — only when threading matters.

**Read-only discipline.** Never call Composio's Gmail send, delete, trash,
modify-label, draft-send, filter, or settings tools. The connection has broad
scopes; the skill's behaviour is what keeps it read-only. Do not paste message
bodies into `COMPOSIO_REMOTE_BASH_TOOL` or `COMPOSIO_REMOTE_WORKBENCH`; keep
OTPs local.

### Fetch and parse a verification mail

1. Generate the alias with `mailbox.py alias` (below).
2. Register in the browser.
3. Search Composio:

```text
COMPOSIO_SEARCH_TOOLS  query: "gmail search messages fetch email body"
COMPOSIO_GET_TOOL_SCHEMAS  tool_slug: "GMAIL_FETCH_EMAILS"
COMPOSIO_MULTI_EXECUTE_TOOL
  tool_slug: "GMAIL_FETCH_EMAILS"
  arguments: {"query": "to:<alias> newer_than:1d", "max_results": 5}
```

4. If the body is not in the response, call
   `GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID` with the message id.
5. Save the body to a temp file and run the tested extractor:

```bash
.../mailbox.py parse --file /tmp/opencode/msg.txt \
  --subject 'Verification code' --domain three.com.hk --json
```

`parse` returns ranked `codes` and `links`; use the first entry, or pick from the
alternatives when the site sends more than one. It accepts plain text or HTML
from stdin as well as `--file`.

6. Complete the flow in the same browser tab that registered.

If the Connect Link expires, retry the Gmail call; Composio generates a fresh
link. If the tools do not appear, check `/mcps` and the Composio connection
status before falling back to `mailbox.py`.

## Per-target flow

### 1. Confirm the target and make an alias

Identify the supported account types, roles, and tenants needed for the planned
checks. Inspect existing account records, then repeat this flow for each
additional account needed, including same-type peers. Assign each account a
unique, filesystem-safe account ID and generate a fresh alias/password.

```bash
.opencode/skills/registration/scripts/mailbox.py alias --tag 3hk --json
```

```json
{
  "alias": "recon.example+3hk-a1b2c3@gmail.com",
  "password": "…20 chars…"
}
```

Gmail delivers `+alias` mail to the base inbox. The alias keeps each account's
verification mail separable and makes the account obvious in the target's
records. Use the generated password; do not invent a weak one.

Some validators reject `+` in the local part. If the form refuses the alias,
fall back to the base address, note it in the account record, and rely on
`--subject-re` plus `--since` to pick the right mail. If the base address is
already used, use another available researcher-controlled address accepted by
the target. If none is available, record the missing prerequisite; an existing
login does not count as a distinct account.

### 2. Register in the browser

Open the registration page in the normal test browser (through Caido when the
target workflow uses it) and keep that tab: some links are bound to the cookie
set during signup. Isolate each account's cookies and storage in separate
browser profiles/contexts, or explicitly switch sessions and verify the active
identity before testing. Label saved sessions by account ID.

Fill only what the form requires. Use the generated alias and password and the
target's test persona. Stop at CAPTCHA, SMS, or payment.

### 3. Pull the verification material

Use the **Composio flow above** when the `composio` MCP is connected. The
commands below are the direct Gmail API/IMAP fallback and work without
Composio.

```bash
# numeric or alphanumeric OTP
.../mailbox.py otp  --to 'recon.example+3hk-a1b2c3@gmail.com' \
  --wait 120 --subject-re 'verif|confirm|code|otp' --json

# confirmation link
.../mailbox.py link --to 'recon.example+3hk-a1b2c3@gmail.com' \
  --wait 120 --domain three.com.hk --json
```

Both return the newest matching message. `codes` and `links` are ranked; the
first entry is the pick, the rest are there when the site sends more than one.
`--domain` boosts links on the target's registrable domain so a tracking or
unsubscribe URL cannot win.

If the mail may already have arrived, drop `--wait`. To inspect without
extracting:

```bash
.../mailbox.py list --to '<alias>' --since 1h --json
.../mailbox.py read --uid <uid> --box '[Gmail]/All Mail'
```

### 4. Complete verification

- **Code:** type it into the open tab.
- **Link:** open it in the same browser profile. Before following, check the
  final host is in scope. A link that lands on an unrelated domain is a finding
  to record, not a link to open.
- Re-run `otp`/`link` with a larger `--wait` if the first mail was a welcome
  message without a code.

### 5. Record the account

Write one record per account at
`targets/<target>/state/registration/<host>/<account-id>.json`; never overwrite
another account's record. Check legacy `<host>.json` records for reusable
accounts too:

```json
{
  "account_id": "member-a",
  "account_type": "member",
  "role": "member",
  "tenant_id": "researcher-tenant-a",
  "purpose": "cross-user authorization checks with member-b",
  "host": "app.example.com",
  "url": "https://app.example.com/register",
  "alias": "recon.example+3hk-a1b2c3@gmail.com",
  "password": "…",
  "persona": {"name": "…", "note": "synthetic test identity"},
  "created_at": "2026-11-01T14:00:00Z",
  "status": "verified",
  "notes": "email verification, no phone check"
}
```

Record observed account type, role, and tenant; use `null` when unknown or
not applicable. Set `status` to `pending`, `verified`, `blocked`, or `abandoned`. On `blocked`,
record what stopped it (CAPTCHA, SMS, invite) so the next run does not retry
blindly.

### 6. Continue testing

Use the session for the tier 0 checks: map the authenticated surface, test
BOLA/IDOR with objects you own, mass assignment on signup, stored XSS in
profile fields, upload handling. Keep the account alive for the duration of the
test and log out when done.

## Command reference

- `check` — backend, granted scope, mailbox reachability, unseen count.
- `alias --tag <t> [--json]` — alias plus generated password.
- `list --to <alias> [--since 15m] [--json]` — recent matching messages.
- `wait --to <alias> --timeout 120 [--subject-re RE] [--json]` — block until one
  arrives.
- `otp --to <alias> [--wait 120] [--subject-re RE] [--json]` — best code.
- `link --to <alias> [--wait 120] [--domain example.com] [--json]` — best link.
- `read --uid <uid> --box '<mailbox>' [--json]` — full message. On the Gmail API
  backend the UID is the Gmail message id and `--box` is ignored.
- `parse --subject '<subject>' [--domain example.com] [--file PATH] [--json]` —
  extract ranked codes and links from a message body on stdin or in a file.
- `selftest` — offline parser checks; run after editing the script.

Exit codes: `0` found, `3` timeout or nothing extracted, `2` configuration or
authentication error.

`--no-spam` exists for speed; leave spam in the search during verification,
because transactional mail lands there more often than people expect.

## Troubleshooting

- **`composio` MCP says `needs authentication`** — run `/mcps` in the OpenCode UI,
  select **composio**, and sign in. Do not run `opencode mcp auth` through a
  shell; the link can be lost in background output.
- **`/mcps` is unavailable in this client** — create a free Composio account,
  copy the consumer API key from **AI Clients** in the dashboard, and add it to
  the MCP entry as `"oauth": false` with
  `"headers": {"x-consumer-api-key": "..."}`. Keep the config file mode `0600`.
  This avoids the browser callback on a headless host.
- **Composio returned a Connect Link** — open it, approve Gmail for the burner,
  then call `COMPOSIO_WAIT_FOR_CONNECTIONS`; links expire, so retry the action
  if needed.
- **`GMAIL_FETCH_EMAILS` finds nothing** — use `in:anywhere`, widen
  `newer_than:1d`, quote the alias, and confirm the connected account with
  `GMAIL_GET_PROFILE`. A form that strips `+tag` needs the base address.
- **Composio Gmail tools absent** — call `COMPOSIO_SEARCH_TOOLS` with "gmail",
  check `/mcps`, and reconnect if the connection is unhealthy. Fall back to
  `mailbox.py` while it is unavailable.
- **`invalid_grant`** — the refresh token expired (Testing-mode apps: 7 days) or
  the grant was revoked. Re-run `oauth_setup.py`.
- **`redirect_uri_mismatch`** — the OAuth client was created as a Web
  application. Create a **Desktop app** client and use its JSON.
- **`access_denied`** — the signed-in address is not in the consent screen's
  test users, or the scope was unchecked. Add the burner under Test users.
- **`accessNotConfigured` / 403** — the Gmail API is not enabled on the project.
- **`Google hasn't verified this app`** — expected in Testing. Advanced > Go to
  the app. Only do this for the client you created.
- **No refresh token returned** — revoke the app's access at
  `myaccount.google.com/permissions`, then re-run; the flow requests
  `prompt=consent`.
- **`Application-specific password required`** — IMAP fallback only: 2-Step
  Verification is off, or a normal password was stored. Create an App Password
  and re-run `setup.sh`.
- **Timeout but the account was created** — widen `--since` to `1h`, confirm the
  alias character-for-character, and search spam. Some forms silently strip the
  `+tag`, so also try `--to` with the base address.
- **Code extracted is wrong** — read the message and pick from `codes[]`
  manually; the top entry is a heuristic, not a guarantee.
- **Link redirects to login** — it is probably cookie-bound. Open it in the same
  tab/profile that registered, not a fresh session.
- **Link host is off-scope** — do not follow. Record the redirect as a finding
  candidate and verify the account state directly on the target instead.
