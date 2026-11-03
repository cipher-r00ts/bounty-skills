#!/usr/bin/env python3
"""composio_setup.py — headless Composio Gmail MCP setup.

Takes a Composio project API key, creates a Gmail-only Tool Router session,
writes its MCP endpoint and headers into the global OpenCode config, and
generates a Gmail Connect Link. No browser callback is needed on this host:
the user opens the Connect Link on any device and approves the mailbox.

API key: https://dashboard.composio.dev > Settings > Project Settings > API Keys

Examples:
  composio_setup.py --api-key ak_...
  COMPOSIO_API_KEY=ak_... composio_setup.py
  composio_setup.py --api-key ak_... --no-link
  composio_setup.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

API_BASE = "https://backend.composio.dev/api/v3.1"
CONFIG_DEFAULT = "~/.config/opencode/opencode.json"
STATE_DEFAULT = "~/.cache/opencode/composio-session.json"
USER_DEFAULT = "bb-registration"
TOOLKIT = "gmail"
MCP_SERVER_NAME = "composio"


class SetupError(RuntimeError):
    pass


def load_json(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.is_file():
        return {}
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"cannot parse {p}: {exc}") from exc
    if not isinstance(value, dict):
        raise SetupError(f"{p} is not a JSON object")
    return value


def atomic_write(path: str, data: dict, mode: int = 0o600) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".composio-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def api_request(
    method: str,
    path: str,
    api_key: str,
    body: dict | None = None,
    *,
    timeout: int = 30,
) -> dict:
    url = API_BASE + path
    payload = None
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
        "User-Agent": "opencode-registration/1.0",
    }
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("message") or parsed.get("error") or detail
        except json.JSONDecodeError:
            pass
        hint = ""
        if exc.code == 401:
            hint = " The project API key is invalid. Copy it from Settings > Project Settings > API Keys."
        elif exc.code == 403:
            hint = " The key lacks session permissions, or the plan does not allow this."
        elif exc.code == 429:
            hint = " Rate limited; retry shortly."
        raise SetupError(f"Composio API {exc.code}: {str(detail)[:400]}{hint}") from exc
    except urllib.error.URLError as exc:
        raise SetupError(f"cannot reach Composio: {exc.reason}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SetupError(f"Composio returned non-JSON: {raw[:200]!r}") from exc
    if not isinstance(value, dict):
        raise SetupError(f"unexpected Composio response: {value!r}")
    return value


def create_session(api_key: str, user_id: str) -> dict:
    variants = [
        {"user_id": user_id, "toolkits": {"enable": [TOOLKIT]}, "mcp": True},
        {"user_id": user_id, "toolkits": {"enable": [TOOLKIT]}},
        {"user_id": user_id, "toolkits": [TOOLKIT], "mcp": True},
        {"user_id": user_id, "toolkits": [TOOLKIT]},
    ]
    last: SetupError | None = None
    for body in variants:
        try:
            return api_request("POST", "/tool_router/session", api_key, body)
        except SetupError as exc:
            last = exc
            text = str(exc)
            if " 400:" in text or " 422:" in text:
                continue
            raise
    raise last or SetupError("session creation failed")


def session_fields(data: dict) -> tuple[str, str, dict]:
    session_id = data.get("session_id") or data.get("id") or data.get("sessionId")
    mcp = data.get("mcp") if isinstance(data.get("mcp"), dict) else {}
    url = mcp.get("url") or mcp.get("mcp_url") or data.get("mcp_url")
    headers = mcp.get("headers") if isinstance(mcp.get("headers"), dict) else {}
    if not session_id:
        raise SetupError(
            "Composio created a session but returned no session id; response keys: "
            + ", ".join(sorted(data))
        )
    if not url:
        raise SetupError(
            "Composio returned no MCP URL; response keys: " + ", ".join(sorted(data))
        )
    return str(session_id), str(url), headers


def connection_link(api_key: str, session_id: str) -> str | None:
    variants = [
        {"toolkit": TOOLKIT},
        {"toolkit_slug": TOOLKIT},
    ]
    for body in variants:
        try:
            data = api_request(
                "POST", f"/tool_router/session/{session_id}/link", api_key, body
            )
            return (
                data.get("redirect_url")
                or data.get("redirectUrl")
                or data.get("url")
                or data.get("link")
            )
        except SetupError as exc:
            if " 400:" in str(exc) or " 422:" in str(exc):
                continue
            raise
    return None


def update_config(path: str, url: str, headers: dict, api_key: str) -> None:
    data = load_json(path)
    mcp = data.get("mcp") if isinstance(data.get("mcp"), dict) else {}
    servers = mcp.get("servers") if isinstance(mcp.get("servers"), dict) else {}
    servers[MCP_SERVER_NAME] = {
        "type": "remote",
        "url": url,
        "oauth": False,
        "headers": headers or {"x-api-key": api_key},
    }
    mcp["servers"] = servers
    data["mcp"] = mcp
    data.setdefault("$schema", "https://opencode.ai/config.json")
    atomic_write(path, data, 0o600)


def save_state(session_id: str, user_id: str, url: str, headers: dict) -> None:
    atomic_write(
        STATE_DEFAULT,
        {
            "session_id": session_id,
            "user_id": user_id,
            "mcp_url": url,
            "mcp_headers": headers,
            "created_at": time.time(),
        },
        0o600,
    )


def resolve_key(args) -> str:
    key = (args.api_key or os.environ.get("COMPOSIO_API_KEY") or "").strip()
    if not key:
        raise SetupError(
            "no Composio project API key. Create a free account at "
            "https://dashboard.composio.dev, copy the key from "
            "Settings > Project Settings > API Keys, and pass --api-key "
            "or set COMPOSIO_API_KEY."
        )
    return key


def selftest() -> int:
    failures: list[str] = []
    payload = {
        "session_id": "ses_test",
        "mcp": {"url": "https://mcp.example/session/1", "headers": {"x-api-key": "k"}},
    }
    sid, url, headers = session_fields(payload)
    if (sid, url, headers) != (
        "ses_test",
        "https://mcp.example/session/1",
        {"x-api-key": "k"},
    ):
        failures.append(f"session_fields: {(sid, url, headers)}")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "opencode.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"mcp": {"servers": {"other": {"type": "remote", "url": "x"}}}}, handle)
        update_config(path, "https://mcp.example/session/1", {"x-api-key": "k"}, "k")
        data = json.load(open(path, encoding="utf-8"))
        server = data["mcp"]["servers"]["composio"]
        if server.get("oauth") is not False:
            failures.append(f"config oauth: {server}")
        if server.get("headers") != {"x-api-key": "k"}:
            failures.append(f"config headers: {server}")
        if data["mcp"]["servers"].get("other") is None:
            failures.append("config did not preserve other servers")
        if oct(os.stat(path).st_mode & 0o777) != "0o600":
            failures.append(f"config mode: {oct(os.stat(path).st_mode & 0o777)}")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print("selftest: ok (session parsing, config merge, mode 0600)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="composio_setup.py",
        description="Create a headless Composio Gmail MCP session and wire it into OpenCode.",
    )
    parser.add_argument("--api-key", help="Composio project API key (ak_...)")
    parser.add_argument("--user-id", default=USER_DEFAULT, help="stable Composio user id")
    parser.add_argument("--config", default=CONFIG_DEFAULT, help="OpenCode config to update")
    parser.add_argument("--no-link", action="store_true", help="do not create a Gmail Connect Link")
    parser.add_argument("--print-only", action="store_true", help="print the session, do not write config")
    parser.add_argument("--selftest", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return selftest()
    try:
        key = resolve_key(args)
        data = create_session(key, args.user_id)
        session_id, url, headers = session_fields(data)
        host = urlparse(url).netloc or "unknown"
        if args.print_only:
            print(json.dumps({"session_id": session_id, "mcp_host": host}, indent=2))
            return 0
        update_config(args.config, url, headers, key)
        save_state(session_id, args.user_id, url, headers)
        print(f"session : {session_id}")
        print(f"mcp     : {host} (endpoint stored in config)")
        print(f"config  : {os.path.expanduser(args.config)} (0600)")
        if not args.no_link:
            link = connection_link(key, session_id)
            if link:
                print()
                print("Approve Gmail on any device:")
                print(link)
            else:
                print()
                print("No Connect Link returned; ask the agent to call COMPOSIO_MANAGE_CONNECTIONS.")
        print()
        print("next: opencode mcp list; then use GMAIL_GET_PROFILE / GMAIL_FETCH_EMAILS")
        return 0
    except SetupError as exc:
        print(f"composio_setup: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
