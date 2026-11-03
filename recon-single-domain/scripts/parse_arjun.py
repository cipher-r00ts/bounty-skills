#!/usr/bin/env python3
"""Normalize arjun JSON output into params.jsonl (tolerant of shapes).

Usage:
  parse_arjun.py --json out.json --path /api/x --out <run>/domain/params/params.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "JSON"}


def collect(obj, method: str | None, found: list[tuple[str, str]]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.upper() in METHODS:
                collect(value, key.upper(), found)
            elif isinstance(value, (dict, list)):
                collect(value, method, found)
            elif isinstance(key, str):
                found.append((method or "GET", key))
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, str):
                found.append((method or "GET", item))
            else:
                collect(item, method, found)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--path", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = Path(args.json)
    try:
        data = json.loads(src.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return 0

    found: list[tuple[str, str]] = []
    # arjun 2.x: {url: {"headers": {...}, "method": "GET", "params": [...]}}
    structured = False
    if isinstance(data, dict):
        for _url, info in data.items():
            if isinstance(info, dict) and isinstance(info.get("params"), list):
                structured = True
                method = str(info.get("method") or "GET").upper()
                for param in info["params"]:
                    if isinstance(param, str):
                        found.append((method, param))
    if not structured:
        collect(data, None, found)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                seen.add((row.get("path"), row.get("method"), row.get("param")))
            except Exception:  # noqa: BLE001
                continue

    added = 0
    with out.open("a", encoding="utf-8") as fh:
        for method, param in found:
            key = (args.path, method, param)
            if key in seen:
                continue
            seen.add(key)
            fh.write(json.dumps({
                "path": args.path,
                "method": method,
                "param": param,
                "source": "arjun",
                "found_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False) + "\n")
            added += 1

    print(json.dumps({"path": args.path, "added": added}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
