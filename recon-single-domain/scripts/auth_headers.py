#!/usr/bin/env python3
"""Convert a Caido `export-curl --config` file into headers for ffuf/curl.

The config contains `header = "Name: Value"` and `proxy = "..."` lines. Values
are secrets: write the output to a 0600 file and never print them.

Usage:
  auth_headers.py --config /tmp/caido/host/auth.cfg --out /tmp/recon-auth/host/headers.txt
  auth_headers.py --config ... --format json
  auth_headers.py --config ... --names        # safe: header names only
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

HEADER_RE = re.compile(r'^\s*header\s*=\s*"?(?P<value>.+?)"?\s*$')
PROXY_RE = re.compile(r'^\s*proxy\s*=\s*"?(?P<value>.+?)"?\s*$')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--format", choices=["ffuf", "json"], default="ffuf")
    ap.add_argument("--names", action="store_true")
    args = ap.parse_args()

    path = Path(args.config).expanduser()
    if not path.exists():
        print(f"auth config not found: {path}")
        return 1

    headers: list[str] = []
    proxy = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = HEADER_RE.match(line)
        if m:
            value = m.group("value").strip().strip('"')
            if value:
                headers.append(value)
            continue
        m = PROXY_RE.match(line)
        if m:
            proxy = m.group("value").strip().strip('"')

    if args.names:
        print(json.dumps({
            "headers": [h.split(":", 1)[0].strip() for h in headers],
            "proxy": proxy,
        }))
        return 0

    payload = json.dumps(headers, indent=2) if args.format == "json" else "\n".join(headers) + ("\n" if headers else "")
    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        os.chmod(out, 0o600)
        print(json.dumps({"out": str(out), "headers": len(headers), "proxy": bool(proxy)}))
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
