#!/usr/bin/env python3
"""Turn findings/endpoints.jsonl into ready-to-fire raw HTTP requests.

The output is intentionally placeholder-authenticated: paste it into Caido
Replay or Burp Repeater, replace <SESSION>/<TOKEN> with your own, and send.

Usage:
  make_requests.py --root <run-root> [--base-host example.com] [--scheme https]

Writes:
  findings/requests/<NNNN>_<METHOD>_<slug>.req
  findings/requests/collection.http
  findings/requests/index.md
  findings/requests/manifest.json
  logs/requests.log
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

UA = "Mozilla/5.0 (X11; Linux x86_64) recon-skill"


def log(root: Path, message: str) -> None:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with (logs / "requests.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {message}\n")


def slugify(value: str) -> str:
    value = value.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return (value or "root")[:70]


def normalize(entry: dict, base_host: str, scheme: str) -> dict | None:
    method = str(entry.get("method") or entry.get("verb") or "GET").upper()
    raw_url = entry.get("url") or entry.get("path") or ""
    if not raw_url:
        return None

    host = str(entry.get("host") or "").strip()
    path = raw_url
    if raw_url.startswith(("http://", "https://")):
        parsed = urlparse(raw_url)
        host = parsed.netloc or host
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
    elif raw_url.startswith("//"):
        parsed = urlparse("https:" + raw_url)
        host = parsed.netloc or host
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

    if not host:
        host = base_host
    if not host:
        return None
    if not path.startswith("/"):
        path = "/" + path

    headers = entry.get("headers") or {}
    if isinstance(headers, list):
        parsed_headers = {}
        for item in headers:
            if isinstance(item, str) and ":" in item:
                k, v = item.split(":", 1)
                parsed_headers[k.strip()] = v.strip()
        headers = parsed_headers
    if not isinstance(headers, dict):
        headers = {}

    body = entry.get("body") or entry.get("data") or ""
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    body = str(body)

    return {
        "method": method,
        "host": host,
        "path": path,
        "scheme": scheme,
        "headers": headers,
        "body": body,
        "evidence": entry.get("evidence") or entry.get("source") or entry.get("file") or "",
        "auth": entry.get("auth") or "",
    }


def render(req: dict, seq: int) -> str:
    lines = [f"{req['method']} {req['path']} HTTP/1.1", f"Host: {req['host']}", f"User-Agent: {UA}", "Accept: */*"]

    skip = {"host", "content-length", "user-agent", "accept", "cookie", "authorization", "content-type"}
    content_type = ""
    for key, value in req["headers"].items():
        lk = key.lower()
        if lk == "content-type":
            content_type = str(value)
            continue
        if lk in skip:
            if lk == "cookie":
                lines.append("Cookie: <SESSION>")
            elif lk == "authorization":
                lines.append("Authorization: <TOKEN>")
            continue
        lines.append(f"{key}: {value}")

    if req["body"]:
        if not content_type:
            content_type = "application/json" if req["body"].lstrip().startswith(("{", "[")) else "application/x-www-form-urlencoded"
        lines.append(f"Content-Type: {content_type}")
        lines.append(f"Content-Length: {len(req['body'].encode('utf-8'))}")
    elif content_type:
        lines.append(f"Content-Type: {content_type}")

    if "cookie" not in {k.lower() for k in req["headers"]}:
        lines.append("Cookie: <SESSION>")

    lines.append("Connection: close")
    head = "\r\n".join(lines)
    return head + "\r\n\r\n" + (req["body"] if req["body"] else "") + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--base-host", default="")
    ap.add_argument("--scheme", default="https")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    endpoints = root / "findings" / "endpoints.jsonl"
    if not endpoints.exists():
        print(f"no endpoints file: {endpoints}")
        return 1

    outdir = root / "findings" / "requests"
    outdir.mkdir(parents=True, exist_ok=True)

    seen: set[tuple[str, str, str]] = set()
    rows: list[dict] = []
    skipped = 0

    for line in endpoints.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(entry, dict):
            skipped += 1
            continue
        req = normalize(entry, args.base_host, args.scheme)
        if req is None:
            skipped += 1
            continue
        key = (req["method"], req["host"], req["path"])
        if key in seen:
            continue
        seen.add(key)
        req["seq"] = len(rows) + 1
        rows.append(req)

    collection = []
    index_lines = ["# Ready-to-fire requests", ""]
    for req in rows:
        name = f"{req['seq']:04d}_{req['method']}_{slugify(req['path'])}"
        raw = render(req, req["seq"])
        (outdir / f"{name}.req").write_bytes(raw.encode("utf-8"))
        collection.append(f"### {req['seq']:04d} {req['method']} {req['path']}\n{raw}")
        index_lines.append(f"- `{req['method']} {req['scheme']}://{req['host']}{req['path']}` — `{name}.req`")
        if req["evidence"]:
            index_lines.append(f"  - evidence: {req['evidence']}")

    (outdir / "collection.http").write_text("\n".join(collection), encoding="utf-8")
    (outdir / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    (outdir / "manifest.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    log(root, f"make_requests: {len(rows)} request(s), {skipped} skipped — {outdir}")
    print(json.dumps({"requests": len(rows), "skipped": skipped, "dir": str(outdir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
