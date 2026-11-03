#!/usr/bin/env python3
"""oauth_setup.py — one-time Gmail API authorization (read-only).

Creates a local loopback OAuth flow with PKCE, exchanges the code for a refresh
token, verifies the mailbox with a profile call, and stores the result outside
the repository:

  {"gmail": {"address": ..., "oauth": {"client_id": ..., "client_secret": ...,
             "refresh_token": ..., "scope": "https://www.googleapis.com/auth/gmail.readonly"}}}

The refresh token is never printed. Nothing is sent and only gmail.readonly is
requested.

Google Cloud, one time:
  1. create a project and enable the Gmail API
  2. OAuth consent screen: External + Testing, add the burner as a test user,
     add scope https://www.googleapis.com/auth/gmail.readonly
  3. Credentials > Create credentials > OAuth client ID > Desktop app
  4. download the JSON and pass it with --client-secrets

Examples:
  oauth_setup.py --client-secrets ~/Downloads/client_secret_xxx.json
  oauth_setup.py --client-id '...apps.googleusercontent.com' --client-secret '...'
  oauth_setup.py --client-secrets ... --print-url

Headless host (no browser):
  oauth_setup.py --client-secrets ... --start
  # open the printed URL on any device, approve, copy the failed redirect URL
  oauth_setup.py --finish 'http://127.0.0.1:8765/?code=...&state=...'
  oauth_setup.py --help
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mailbox import (  # noqa: E402
    DEFAULT_CONFIGS,
    GMAIL_READONLY_SCOPE,
    GMAIL_TOKEN_URL,
    MailboxError,
    _load_json,
)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
DEFAULT_CONFIG = DEFAULT_CONFIGS[0]
STATE_BYTES = 24


class SetupError(RuntimeError):
    pass


class CallbackHandler(BaseHTTPRequestHandler):
    server_version = "mailbox-oauth/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = {
            key: values[0]
            for key, values in urllib.parse.parse_qs(parsed.query).items()
            if values
        }
        self.server.oauth_result = params  # type: ignore[attr-defined]
        error = params.get("error")
        if error:
            title = "Authorization denied"
            body = f"Google returned: {error}. You can close this tab."
        else:
            title = "Mailbox authorized"
            body = "You can close this tab and return to the terminal."
        page = (
            "<!doctype html><meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<body style='font-family:system-ui;max-width:38rem;margin:4rem auto'>"
            f"<h1>{title}</h1><p>{body}</p></body>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *_args) -> None:
        pass


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def pkce_pair() -> tuple[str, str]:
    verifier = b64url(os.urandom(64))
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def load_client(
    client_secrets: str | None,
    client_id: str | None,
    client_secret: str | None,
    config_path: str,
) -> tuple[str, str]:
    existing = _load_json(config_path).get("gmail", {})
    if isinstance(existing, dict):
        oauth = existing.get("oauth", {})
        if isinstance(oauth, dict):
            client_id = client_id or oauth.get("client_id")
            client_secret = client_secret or oauth.get("client_secret")

    if client_secrets:
        path = Path(client_secrets).expanduser()
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SetupError(f"client secret JSON not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise SetupError(f"client secret JSON is not valid JSON: {path}: {exc}") from exc
        section = document.get("installed") or document.get("web") or document
        if not isinstance(section, dict):
            raise SetupError("unexpected client secret JSON shape")
        client_id = client_id or section.get("client_id")
        client_secret = client_secret or section.get("client_secret")
        if "web" in document and "installed" not in document:
            print(
                "warning: this is a Web application client. Use a Desktop app "
                "client, or add http://127.0.0.1:<port>/ as an authorized redirect URI.",
                file=sys.stderr,
            )

    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        raise SetupError(
            "missing OAuth client. Create a Desktop-app OAuth client in Google "
            "Cloud, download the JSON, and pass --client-secrets PATH."
        )
    return client_id, client_secret


def auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_READONLY_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "include_granted_scopes": "true",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(
    code: str,
    verifier: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
) -> dict:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    data = urllib.parse.urlencode(payload).encode()
    request = urllib.request.Request(
        GMAIL_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            token = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        hint = ""
        if "redirect_uri_mismatch" in detail:
            hint = " Use a Desktop-app OAuth client, not a Web application client."
        raise SetupError(f"token exchange failed ({exc.code}): {detail[:400]}{hint}") from exc
    except urllib.error.URLError as exc:
        raise SetupError(f"cannot reach Google OAuth: {exc.reason}") from exc
    if "error" in token:
        raise SetupError(
            f"token exchange failed: {token.get('error')}: {token.get('error_description', '')}"
        )
    return token


def fetch_profile(access_token: str) -> dict:
    request = urllib.request.Request(
        PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SetupError(f"profile call failed ({exc.code}): {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise SetupError(f"cannot reach Gmail API: {exc.reason}") from exc


def write_config(path: str, address: str, client_id: str, client_secret: str, token: dict) -> None:
    target = os.path.expanduser(path)
    data = _load_json(target)
    gmail = data.get("gmail")
    if not isinstance(gmail, dict):
        gmail = {}
    gmail["address"] = address
    gmail["backend"] = "gmail-api"
    gmail["oauth"] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": token["refresh_token"],
        "scope": token.get("scope", GMAIL_READONLY_SCOPE),
        "obtained_at": datetime.now(timezone.utc).isoformat(),
    }
    data["gmail"] = gmail

    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".secrets-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)


def state_file() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "opencode"
    return base / "gmail-oauth-state.json"


def write_private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".oauth-state-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def parse_redirect(value: str) -> tuple[str, str, str]:
    text = value.strip().strip("<>\"'").replace("&amp;", "&")
    if text.startswith("?") or text.startswith("code="):
        text = "http://127.0.0.1/?" + text.lstrip("?")
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urllib.parse.urlparse(text)
        params = urllib.parse.parse_qs(parsed.query)
        return (
            params.get("code", [""])[0],
            params.get("state", [""])[0],
            params.get("error", [""])[0],
        )
    return text, "", ""


def cmd_start(args, client_id: str, client_secret: str) -> int:
    verifier, challenge = pkce_pair()
    state = b64url(secrets.token_bytes(STATE_BYTES))
    port = args.port or 8765
    redirect_uri = f"http://127.0.0.1:{port}/"
    url = auth_url(client_id, redirect_uri, state, challenge)
    write_private_json(
        state_file(),
        {
            "state": state,
            "verifier": verifier,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "created_at": time.time(),
            "config": args.config,
        },
    )
    print("1. Open this URL on any device and sign in with the dedicated account:")
    print()
    print(url)
    print()
    print("2. Approve access. The browser will fail to load")
    print(f"   {redirect_uri}?code=...  — that is expected.")
    print("3. Copy the full address bar and finish the exchange:")
    print()
    print(f"   {sys.argv[0]} --finish 'http://127.0.0.1:{port}/?code=...&state=...'")
    return 0


def cmd_finish(args) -> int:
    path = state_file()
    if not path.is_file():
        raise SetupError("no pending OAuth state; run --start first")
    try:
        pending = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SetupError(f"pending OAuth state is corrupt: {path}") from exc
    if time.time() - float(pending.get("created_at", 0)) > 900:
        raise SetupError("pending OAuth state is older than 15 minutes; run --start again")

    code, returned_state, error = parse_redirect(args.finish)
    if error:
        raise SetupError(f"authorization failed: {error}")
    if not code:
        raise SetupError("no authorization code in --finish value")
    if returned_state and returned_state != pending["state"]:
        raise SetupError("OAuth state mismatch; run --start again")
    if not returned_state:
        print("warning: no state in the pasted URL; relying on PKCE binding", file=sys.stderr)

    token = exchange_code(
        code,
        pending["verifier"],
        pending["redirect_uri"],
        pending["client_id"],
        pending["client_secret"],
    )
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise SetupError(
            "Google returned no refresh_token. Remove the app's prior grant at "
            "https://myaccount.google.com/permissions and re-run --start."
        )
    profile = fetch_profile(token["access_token"])
    address = profile.get("emailAddress", "")
    if not address:
        raise SetupError("Gmail profile did not return an email address")
    scopes = token.get("scope", "")
    if GMAIL_READONLY_SCOPE not in scopes:
        raise SetupError(f"gmail.readonly was not granted; scopes: {scopes}")

    write_config(
        pending.get("config") or args.config,
        address,
        pending["client_id"],
        pending["client_secret"],
        token,
    )
    path.unlink(missing_ok=True)
    print(f"authorized {address} with {GMAIL_READONLY_SCOPE}")
    print(f"stored refresh token in {os.path.expanduser(pending.get('config') or args.config)} (mode 0600)")
    print("verify with: mailbox.py check")
    return 0


def run_flow(args, client_id: str, client_secret: str) -> int:
    verifier, challenge = pkce_pair()
    state = b64url(secrets.token_bytes(STATE_BYTES))

    server = HTTPServer(("127.0.0.1", args.port), CallbackHandler)
    server.timeout = 1
    server.oauth_result = {}  # type: ignore[attr-defined]
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/"
    url = auth_url(client_id, redirect_uri, state, challenge)

    print("Open this URL in the browser and sign in with the dedicated Gmail account:")
    print()
    print(url)
    print()
    print("Waiting for the local callback on 127.0.0.1:%d (timeout %ds)..." % (port, args.timeout))
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    deadline = time.monotonic() + max(30, args.timeout)
    result: dict = {}
    try:
        while time.monotonic() < deadline:
            server.handle_request()
            result = getattr(server, "oauth_result", {}) or {}
            if result:
                break
    finally:
        server.server_close()

    if not result:
        raise SetupError("timed out waiting for the OAuth callback")
    if result.get("error"):
        raise SetupError(
            f"authorization failed: {result['error']}: {result.get('error_description', '')}"
        )
    if result.get("state") != state:
        raise SetupError("OAuth state mismatch; aborting")
    code = result.get("code")
    if not code:
        raise SetupError("OAuth callback had no authorization code")

    token = exchange_code(code, verifier, redirect_uri, client_id, client_secret)
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise SetupError(
            "Google returned no refresh_token. Remove the app's prior grant at "
            "https://myaccount.google.com/permissions and re-run with prompt=consent."
        )

    profile = fetch_profile(token["access_token"])
    address = profile.get("emailAddress", "")
    if not address:
        raise SetupError("Gmail profile did not return an email address")

    scopes = token.get("scope", "")
    if GMAIL_READONLY_SCOPE not in scopes:
        raise SetupError(f"gmail.readonly was not granted; scopes: {scopes}")

    write_config(args.config, address, client_id, client_secret, token)
    print()
    print(f"authorized {address} with {GMAIL_READONLY_SCOPE}")
    print(f"stored refresh token in {os.path.expanduser(args.config)} (mode 0600)")
    print("verify with: mailbox.py check")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oauth_setup.py",
        description="One-time read-only Gmail API authorization.",
    )
    parser.add_argument("--client-secrets", help="downloaded OAuth client JSON")
    parser.add_argument("--client-id", help="OAuth client ID")
    parser.add_argument("--client-secret", help="OAuth client secret")
    parser.add_argument("--config", default=os.environ.get("GMAIL_CONFIG", DEFAULT_CONFIG),
                        help="secrets JSON to update")
    parser.add_argument("--port", type=int, default=0,
                        help="loopback port (default: random for local flow, 8765 for --start)")
    parser.add_argument("--timeout", type=int, default=300, help="seconds to wait for consent")
    parser.add_argument("--no-browser", action="store_true", help="print the URL, do not open it")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--print-url", action="store_true", help="print the URL and exit (dry run)")
    mode.add_argument("--start", action="store_true",
                      help="headless step 1: print URL, save PKCE state")
    mode.add_argument("--finish", metavar="REDIRECT_URL",
                      help="headless step 2: exchange the pasted redirect URL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.finish:
            return cmd_finish(args)
        client_id, client_secret = load_client(
            args.client_secrets, args.client_id, args.client_secret, args.config
        )
        if args.start:
            return cmd_start(args, client_id, client_secret)
        if args.print_url:
            verifier, challenge = pkce_pair()
            print(auth_url(client_id, "http://127.0.0.1:8080/", b64url(os.urandom(24)), challenge))
            return 0
        return run_flow(args, client_id, client_secret)
    except SetupError as exc:
        print(f"oauth_setup: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
