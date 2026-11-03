#!/usr/bin/env python3
"""Build a Wayback Machine timeline for a target's JavaScript and download the
sampled snapshots.

Usage:
  wayback_timeline.py --root targets/3hk/artifacts/recon/js --domain three.com.hk
  wayback_timeline.py ... --months 36 --step-days 90 --max-snapshots 8 --host-scan
  wayback_timeline.py ... --dry-run

Writes:
  raw/historical/<host>/<timestamp>__<name>.js
  raw/timeline.jsonl
  logs/wayback.log

No traffic is sent to the target; only web.archive.org is contacted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

UA = "recon-skill/js-wayback-diff (authorized research)"
CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK = "https://web.archive.org/web"


def log(root: Path, message: str) -> None:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with (logs / "wayback.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {message}\n")


def fetch(url: str, timeout: int = 60, retries: int = 3) -> bytes | None:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 503):
                time.sleep(5 * (attempt + 1))
                continue
            return None
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    if last:
        print(f"  ! {last}")
    return None


def cdx_rows(url: str, start: str, end: str, limit: int = 2000) -> list[dict]:
    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp,original,statuscode,digest",
        "filter": "statuscode:200",
        "collapse": "digest",
        "from": start,
        "to": end,
        "limit": str(limit),
    }
    body = fetch(f"{CDX}?{urllib.parse.urlencode(params, safe=':/*')}")
    if not body:
        return []
    try:
        rows = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    if not rows:
        return []
    header = rows[0]
    out = []
    for row in rows[1:]:
        rec = dict(zip(header, row))
        if rec.get("timestamp") and rec.get("original"):
            out.append(rec)
    return out


def host_js_urls(host: str, start: str, end: str, limit: int = 400) -> list[str]:
    params = {
        "url": f"{host}/*",
        "output": "json",
        "fl": "original",
        "filter": ["statuscode:200", "urlkey:.*\\.js.*"],
        "collapse": "urlkey",
        "from": start,
        "to": end,
        "limit": str(limit),
    }
    qs = urllib.parse.urlencode(params, doseq=True, safe=":/*")
    body = fetch(f"{CDX}?{qs}")
    if not body:
        return []
    try:
        rows = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    if not rows:
        return []
    header = rows[0]
    urls = []
    for row in rows[1:]:
        rec = dict(zip(header, row))
        if rec.get("original"):
            urls.append(rec["original"])
    return urls


def sample(records: list[dict], step_days: int, max_snapshots: int) -> list[dict]:
    if not records:
        return []
    records = sorted(records, key=lambda r: r["timestamp"])
    buckets: dict[int, dict] = {}
    for rec in records:
        try:
            day = datetime.strptime(rec["timestamp"][:8], "%Y%m%d").date()
        except ValueError:
            continue
        key = day.toordinal() // max(step_days, 1)
        buckets.setdefault(key, rec)  # oldest snapshot in each window
    chosen = [buckets[k] for k in sorted(buckets)]
    if records[-1] not in chosen:
        chosen.append(records[-1])
    if len(chosen) > max_snapshots:
        if max_snapshots == 1:
            return [chosen[-1]]
        stride = (len(chosen) - 1) / (max_snapshots - 1)
        chosen = [chosen[round(i * stride)] for i in range(max_snapshots)]
    return chosen


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--domain", default="")
    ap.add_argument("--urls-file", default="", help="one JS URL per line; overrides manifest URLs")
    ap.add_argument("--include-third-party", action="store_true", help="keep third-party hosts when --domain is set")
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--step-days", type=int, default=90)
    ap.add_argument("--max-snapshots", type=int, default=6)
    ap.add_argument("--max-urls", type=int, default=40)
    ap.add_argument("--rate", type=float, default=1.0, help="seconds between archive.org requests")
    ap.add_argument("--host-scan", action="store_true", help="also discover old .js URLs via CDX")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"run root not found: {root}")
        return 2
    (root / "raw" / "historical").mkdir(parents=True, exist_ok=True)

    end = date.today()
    start = end - timedelta(days=args.months * 31)
    start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    manifest_path = root / "raw" / "manifest.json"
    manifest = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = []

    urls: list[str] = []
    if args.urls_file:
        for line in Path(args.urls_file).expanduser().read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(("http://", "https://")) and line not in urls:
                urls.append(line)
    for entry in ([] if args.urls_file else manifest):
        if not isinstance(entry, dict) or entry.get("category") != "external":
            continue
        for u in entry.get("all_urls", []) + entry.get("source_urls", []):
            if isinstance(u, str) and u.startswith(("http://", "https://")) and u not in urls:
                urls.append(u)

    if args.domain and not args.include_third_party:
        d = args.domain.lower().strip(".")
        urls = [u for u in urls if (lambda h: h == d or h.endswith("." + d))(urllib.parse.urlparse(u).netloc.lower())]

    hosts = sorted({urllib.parse.urlparse(u).netloc for u in urls if urllib.parse.urlparse(u).netloc})
    if args.domain:
        hosts = sorted(set(hosts) | {args.domain})

    if args.host_scan:
        for host in hosts[:5]:
            found = host_js_urls(host, start_s, end_s)
            log(root, f"host-scan {host}: {len(found)} archived .js URL(s)")
            for u in found:
                if u not in urls:
                    urls.append(u)

    urls = urls[: args.max_urls]
    log(root, f"START domain={args.domain or '-'} window={start_s}-{end_s} step={args.step_days}d urls={len(urls)} host_scan={args.host_scan}")

    timeline = []
    downloaded = 0
    for idx, url in enumerate(urls, start=1):
        rows = cdx_rows(url, start_s, end_s)
        picks = sample(rows, args.step_days, args.max_snapshots)
        if not picks:
            log(root, f"no snapshots: {url}")
            continue
        log(root, f"[{idx}/{len(urls)}] {url}: {len(rows)} captures, {len(picks)} sampled")
        host = urllib.parse.urlparse(url).netloc or "unknown"
        folder = root / "raw" / "historical" / host.replace(":", "_")
        folder.mkdir(parents=True, exist_ok=True)
        for rec in picks:
            ts = rec["timestamp"]
            original = rec["original"]
            archive = f"{WAYBACK}/{ts}id_/{original}"
            base = Path(urllib.parse.urlparse(original).path).name or "index.js"
            base = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)[:80]
            dest = folder / f"{ts}__{base}"
            if args.dry_run:
                timeline.append({"url": url, "timestamp": ts, "archive_url": archive, "file": "", "sha256": rec.get("digest", "")})
                continue
            if dest.exists() and dest.stat().st_size > 0:
                data = dest.read_bytes()
            else:
                if args.rate:
                    time.sleep(args.rate)
                data = fetch(archive)
                if not data:
                    log(root, f"download failed: {archive}")
                    continue
                dest.write_bytes(data)
                downloaded += 1
            digest = sha256(data)
            timeline.append({
                "url": url,
                "timestamp": ts,
                "archive_url": archive,
                "file": str(dest.relative_to(root)),
                "sha256": digest,
                "size_bytes": len(data),
            })

    timeline_path = root / "raw" / "timeline.jsonl"
    with timeline_path.open("w", encoding="utf-8") as fh:
        for row in timeline:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    if not args.dry_run and timeline:
        known = {e.get("sha256") for e in manifest if isinstance(e, dict)}
        for row in timeline:
            if row["sha256"] in known:
                continue
            known.add(row["sha256"])
            manifest.append({
                "hash": f"sha256:{row['sha256']}",
                "sha256": row["sha256"],
                "local_path": row["file"],
                "all_urls": [row["url"], row["archive_url"]],
                "source_urls": [row["url"]],
                "method": "wayback",
                "category": "historical",
                "size_bytes": row["size_bytes"],
                "captured_at": datetime.now(timezone.utc).isoformat(),
            })
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log(root, f"DONE timeline entries={len(timeline)} downloaded={downloaded} dry_run={args.dry_run}")
    print(json.dumps({"urls": len(urls), "timeline_entries": len(timeline), "downloaded": downloaded, "dry_run": args.dry_run}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
