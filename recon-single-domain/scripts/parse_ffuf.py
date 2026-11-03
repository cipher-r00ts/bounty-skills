#!/usr/bin/env python3
"""Normalize ffuf JSON output into the shared endpoints list.

Usage:
  parse_ffuf.py --json fuzz.json --mode auth --source dirs \
                --out <run>/domain/fuzz/endpoints.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--mode", default="unauth")
    ap.add_argument("--source", default="ffuf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-input", action="store_true")
    args = ap.parse_args()

    src = Path(args.json)
    if not src.exists():
        return 0
    try:
        data = json.loads(src.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return 0

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    known: set[tuple[str, int]] = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                known.add((row.get("url", ""), int(row.get("status", 0))))
            except Exception:  # noqa: BLE001
                continue

    added = 0
    with out.open("a", encoding="utf-8") as fh:
        for item in results:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or ""
            status = int(item.get("status") or 0)
            if not url or (url, status) in known:
                continue
            known.add((url, status))
            parsed = urlparse(url)
            row = {
                "url": url,
                "path": parsed.path or "/",
                "host": parsed.netloc,
                "status": status,
                "length": item.get("length"),
                "words": item.get("words"),
                "lines": item.get("lines"),
                "content_type": item.get("content-type") or item.get("content_type") or "",
                "mode": args.mode,
                "source": args.source,
                "found_at": datetime.now(timezone.utc).isoformat(),
            }
            if args.with_input:
                row["input"] = item.get("input")
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            added += 1

    print(json.dumps({"source": args.source, "mode": args.mode, "added": added, "total": len(known)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
