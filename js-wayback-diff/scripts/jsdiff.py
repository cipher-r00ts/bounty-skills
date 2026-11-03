#!/usr/bin/env python3
"""Diff Wayback JS snapshots against the current bundle and surface
historical-only API paths, hosts and parameters.

Usage:
  jsdiff.py --root targets/3hk/artifacts/recon/js --domain three.com.hk

Reads:  raw/timeline.jsonl, raw/manifest.json, raw/historical/**/*.js
Writes: findings/historical.jsonl
        findings/historical-summary.md
        diffs/<slug>_<timestamp>.diff
        findings/endpoints.jsonl (append historical-only leads)
        logs/jsdiff.log
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PATH_RE = re.compile(r"""[\"'`]((?:/[A-Za-z0-9_.~{}:@!$&*+,;=%-]+)+)[\"'`]""")
URL_RE = re.compile(r"https?://([A-Za-z0-9._-]+)(/[^\s\"'`<>]*)?")
PARAM_RE = re.compile(r"[?&]([A-Za-z0-9_]{2,40})=")
SENSITIVE_RE = re.compile(r"(admin|internal|debug|upload|payment|billing|graphql|oauth|token|invite|export|report|v[0-9]+)", re.I)


def log(root: Path, message: str) -> None:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with (logs / "jsdiff.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {message}\n")


def read_text(path: Path) -> str:
    try:
        if path.stat().st_size > 25 * 1024 * 1024:
            return path.read_text(encoding="utf-8", errors="replace")[: 25 * 1024 * 1024]
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def extract(text: str) -> tuple[set[str], set[str], set[str]]:
    paths = {m.group(1) for m in PATH_RE.finditer(text)}
    hosts: set[str] = set()
    for m in URL_RE.finditer(text):
        hosts.add(m.group(1).lower())
        paths.add(m.group(2) or "/")
    params = {m.group(1) for m in PARAM_RE.finditer(text)}
    return paths, hosts, params


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return (value.strip("_") or "js")[:80]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--domain", default="")
    ap.add_argument("--max-lines", type=int, default=400)
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    timeline_path = root / "raw" / "timeline.jsonl"
    manifest_path = root / "raw" / "manifest.json"
    if not timeline_path.exists():
        print(f"no timeline: {timeline_path} (run wayback_timeline.py first)")
        return 1

    timeline: dict[str, list[dict]] = {}
    for line in timeline_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("file"):
            timeline.setdefault(row["url"], []).append(row)
    for rows in timeline.values():
        rows.sort(key=lambda r: r["timestamp"])

    current: dict[str, dict] = {}
    manifest = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = []
    for entry in manifest:
        if not isinstance(entry, dict) or entry.get("category") != "external":
            continue
        for url in entry.get("all_urls", []) + entry.get("source_urls", []):
            if isinstance(url, str):
                current.setdefault(url, entry)

    findings = root / "findings"
    findings.mkdir(parents=True, exist_ok=True)
    diffs = root / "diffs"
    diffs.mkdir(parents=True, exist_ok=True)

    results = []
    endpoint_leads = []
    summary: list[str] = ["# Historical JS diff", ""]
    summary.append(f"- Run root: `{root}`")
    summary.append(f"- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    summary.append(f"- URL groups: {len(timeline)}")
    summary.append("")

    for url, rows in sorted(timeline.items()):
        latest = rows[-1]
        base_entry = current.get(url)
        base_file = root / base_entry["local_path"] if base_entry else None
        if base_file and base_file.exists():
            base_text = read_text(base_file)
            base_label = "current"
        else:
            base_text = read_text(root / latest["file"]) if latest.get("file") else ""
            base_label = f"latest-{latest['timestamp']}"
        base_paths, base_hosts, base_params = extract(base_text)

        for rec in rows:
            if not rec.get("file"):
                continue
            old_text = read_text(root / rec["file"])
            if not old_text:
                continue
            old_paths, old_hosts, old_params = extract(old_text)
            only_paths = sorted(old_paths - base_paths)
            only_hosts = sorted(old_hosts - base_hosts)
            only_params = sorted(old_params - base_params)
            ranked = sorted(
                only_paths,
                key=lambda p: (0 if SENSITIVE_RE.search(p) else 1, -len(p)),
            )[: args.max_lines]

            slug = slugify(url.replace("https://", "").replace("http://", ""))
            diff_file = diffs / f"{slug}_{rec['timestamp']}.diff"
            with diff_file.open("w", encoding="utf-8") as fh:
                fh.write(f"# {url}\n# snapshot {rec['timestamp']} vs {base_label}\n")
                fh.write("# '-' = only in archived version, '+' = only in current\n\n")
                for p in ranked:
                    fh.write(f"- {p}\n")
                for p in sorted(base_paths - old_paths)[: args.max_lines]:
                    fh.write(f"+ {p}\n")
                for h in only_hosts:
                    fh.write(f"- host {h}\n")

            results.append({
                "url": url,
                "snapshot": rec["timestamp"],
                "compared_to": base_label,
                "historical_only_paths": ranked,
                "historical_only_hosts": only_hosts,
                "historical_only_params": only_params,
                "diff_file": str(diff_file.relative_to(root)),
            })

            host = urlparse(url).netloc
            for path in ranked[:20]:
                endpoint_leads.append({
                    "method": "GET",
                    "path": path,
                    "host": host,
                    "evidence": f"historical {rec['timestamp']} {rec['file']}",
                })

        if rows:
            summary.append(f"## {url}")
            summary.append("")
            summary.append(f"- Snapshots diffed: {len(rows)}")
            last = results[-1] if results and results[-1]["url"] == url else None
            if last:
                summary.append(f"- Latest comparison: {last['snapshot']} vs {last['compared_to']}")
                summary.append(f"- Historical-only paths: {len(last['historical_only_paths'])}")
                for p in last["historical_only_paths"][:15]:
                    summary.append(f"  - `{p}`")
                if last["historical_only_hosts"]:
                    summary.append("- Historical-only hosts:")
                    for h in last["historical_only_hosts"][:10]:
                        summary.append(f"  - `{h}`")
            summary.append("")

    with (findings / "historical.jsonl").open("w", encoding="utf-8") as fh:
        for row in results:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    if endpoint_leads:
        endpoints = findings / "endpoints.jsonl"
        existing = set()
        if endpoints.exists():
            for line in endpoints.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                    existing.add((e.get("method"), e.get("host"), e.get("path")))
                except json.JSONDecodeError:
                    continue
        with endpoints.open("a", encoding="utf-8") as fh:
            for lead in endpoint_leads:
                key = (lead["method"], lead["host"], lead["path"])
                if key in existing:
                    continue
                existing.add(key)
                fh.write(json.dumps(lead, ensure_ascii=False) + "\n")

    (findings / "historical-summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    log(root, f"jsdiff: {len(results)} comparison(s), {len(endpoint_leads)} historical-only endpoint lead(s)")
    print(json.dumps({"comparisons": len(results), "endpoint_leads": len(endpoint_leads)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
