#!/usr/bin/env python3
"""Extract hosts (subdomains) from an acquired JavaScript corpus.

Usage:
  extract_hosts.py --root <run-root> --domain example.com [--include-third-party]

Writes:
  findings/hosts.jsonl
  findings/subdomains.txt            every unique host
  findings/subdomains-scope.txt      hosts at or below --domain
  findings/subdomains-thirdparty.txt the rest
  logs/hosts.log
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://([A-Za-z0-9._-]+)", re.I)
PROTO_REL_RE = re.compile(r"[\"'(]//([A-Za-z0-9._-]+\.[A-Za-z]{2,})")
HOST_FIELD_RE = re.compile(r"[\"']?(?:host|hostname|domain)[\"']?\s*[:=]\s*[\"']([A-Za-z0-9._-]+\.[A-Za-z]{2,})", re.I)
BARE_RE = re.compile(r"\b((?:[A-Za-z0-9-]+\.)+(?:com|net|org|io|hk|cn|co|ai|dev|app|cloud|vip|me|info|biz|tv|xyz|site|online|shop|tech|sg|jp|uk|au))\b", re.I)


def log(root: Path, message: str) -> None:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with (logs / "hosts.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {message}\n")


def classify(host: str, domain: str) -> tuple[bool, str]:
    try:
        ipaddress.ip_address(host)
        return False, "ip"
    except ValueError:
        pass
    if not domain:
        return False, "unknown"
    if host == domain or host.endswith("." + domain):
        return True, "in-scope"
    return False, "third-party"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--domain", default="")
    ap.add_argument("--include-third-party", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    domain = args.domain.lower().strip(".") if args.domain else ""

    scan_roots = [root / "raw" / "external", root / "raw" / "inline", root / "raw" / "historical"]
    files: list[Path] = []
    for base in scan_roots:
        if base.is_dir():
            files.extend(p for p in base.rglob("*") if p.is_file())

    hits: dict[str, dict] = defaultdict(lambda: {"sources": [], "count": 0})
    for path in sorted(files):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        found: set[str] = set()
        for rx in (URL_RE, PROTO_REL_RE, HOST_FIELD_RE, BARE_RE):
            for m in rx.finditer(text):
                found.add(m.group(1).lower().rstrip("."))
        for host in found:
            if not host or "." not in host or len(host) > 253:
                continue
            entry = hits[host]
            entry["count"] += 1
            if rel not in entry["sources"]:
                entry["sources"].append(rel)

    findings = root / "findings"
    findings.mkdir(parents=True, exist_ok=True)

    rows = []
    for host, entry in sorted(hits.items()):
        in_scope, kind = classify(host, domain)
        rows.append({
            "host": host,
            "in_scope": in_scope,
            "kind": kind,
            "hits": entry["count"],
            "sources": entry["sources"][:20],
        })

    with (findings / "hosts.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    scope = [r["host"] for r in rows if r["in_scope"]]
    third = [r["host"] for r in rows if not r["in_scope"]]
    (findings / "subdomains.txt").write_text("\n".join(r["host"] for r in rows) + ("\n" if rows else ""), encoding="utf-8")
    (findings / "subdomains-scope.txt").write_text("\n".join(scope) + ("\n" if scope else ""), encoding="utf-8")
    (findings / "subdomains-thirdparty.txt").write_text("\n".join(third) + ("\n" if third else ""), encoding="utf-8")

    log(root, f"extract_hosts: {len(rows)} host(s) from {len(files)} file(s); in-scope={len(scope)} third-party={len(third)} domain={domain or '-'}")
    print(json.dumps({"hosts": len(rows), "in_scope": len(scope), "third_party": len(third)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
