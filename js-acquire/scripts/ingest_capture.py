#!/usr/bin/env python3
"""Ingest a browser capture into a js-acquire run root.

The browser script writes raw/capture-<ts>.json (script sources + inline code)
and the page HTML. This tool downloads the external scripts, hashes everything,
writes inline blocks, and merges entries into raw/manifest.json.

Usage:
  ingest_capture.py --root <run-root> --capture <capture.json> --page-url <url>
                    [--proxy URL] [--auth-config PATH] [--max-files 200]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) recon-skill/js-acquire"
MAX_BYTES = 8 * 1024 * 1024
MULTI_SUFFIX = {
    "com.hk", "net.hk", "org.hk", "edu.hk", "gov.hk", "idv.hk",
    "com.cn", "com.tw", "com.au", "co.uk", "org.uk", "com.sg",
    "co.jp", "com.my", "co.id", "com.ph", "com.vn", "co.th", "com.br", "co.in",
}


def registrable(host: str) -> str:
    parts = (host or "").lower().strip(".").split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_SUFFIX:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else ".".join(parts)


def log(root: Path, message: str) -> None:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with (logs / "browser-collect.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {message}\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    base = Path(parsed.path).name or "index.js"
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in base)[:80]


def download(url: str, dest: Path, proxy: str | None, auth_config: str | None) -> tuple[bool, str]:
    cmd = ["curl", "-sSL", "--max-time", "45", "--max-filesize", str(MAX_BYTES), "-A", UA]
    if auth_config:
        cmd += ["-K", auth_config]
    elif proxy:
        cmd += ["-x", proxy, "-k"]
    cmd += ["-o", str(dest), "-w", "%{http_code} %{size_download}", url]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if out.returncode != 0:
        return False, (out.stderr or "curl failed").strip()[:200]
    code, _, size = out.stdout.partition(" ")
    if not code.startswith(("2", "3")):
        return False, f"http {code}"
    if dest.exists() and dest.stat().st_size > 0:
        return True, size
    return False, "empty response"


def load_capture(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    try:
        value = json.loads(raw)
        if isinstance(value, str):
            value = json.loads(value)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--capture", required=True)
    ap.add_argument("--page-url", required=True)
    ap.add_argument("--proxy", default="")
    ap.add_argument("--auth-config", default="")
    ap.add_argument("--max-files", type=int, default=200)
    ap.add_argument("--same-site-only", action="store_true", help="skip third-party scripts")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    for d in ("raw/external", "raw/inline", "raw/pages", "logs"):
        (root / d).mkdir(parents=True, exist_ok=True)

    capture = load_capture(Path(args.capture))
    srcs = [u for u in capture.get("src", []) if isinstance(u, str) and u.startswith(("http://", "https://"))]
    srcs = list(dict.fromkeys(srcs))

    # First-party bundles matter most; third-party tags must not consume the cap.
    page_reg = registrable(urllib.parse.urlparse(args.page_url).netloc)
    srcs.sort(key=lambda u: 0 if registrable(urllib.parse.urlparse(u).netloc) == page_reg else 1)
    if args.same_site_only:
        srcs = [u for u in srcs if registrable(urllib.parse.urlparse(u).netloc) == page_reg]
    srcs = srcs[: args.max_files]
    inline = [s for s in capture.get("inline", []) if isinstance(s, str) and s.strip()]

    manifest_path = root / "raw" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
        if not isinstance(manifest, list):
            manifest = []
    except json.JSONDecodeError:
        manifest = []

    known_hashes = {m.get("sha256") for m in manifest if isinstance(m, dict)}
    added = {"external": 0, "inline": 0, "duplicate": 0, "failed": 0}

    for url in srcs:
        with tempfile.NamedTemporaryFile(dir=root / "raw" / "external", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        ok, detail = download(url, tmp_path, args.proxy or None, args.auth_config or None)
        if not ok:
            added["failed"] += 1
            log(root, f"download failed {url} — {detail}")
            tmp_path.unlink(missing_ok=True)
            continue
        digest = sha256_file(tmp_path)
        if digest in known_hashes:
            added["duplicate"] += 1
            tmp_path.unlink(missing_ok=True)
            continue
        dest = root / "raw" / "external" / f"{digest[:12]}__{safe_name(url)}"
        shutil.move(str(tmp_path), dest)
        known_hashes.add(digest)
        manifest.append({
            "hash": f"sha256:{digest}",
            "sha256": digest,
            "local_path": str(dest.relative_to(root)),
            "all_urls": [url],
            "source_urls": [url],
            "method": "browser",
            "category": "external",
            "size_bytes": dest.stat().st_size,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        })
        added["external"] += 1

    for idx, code in enumerate(inline, start=1):
        payload = code.encode("utf-8")
        if len(payload) > MAX_BYTES:
            payload = payload[:MAX_BYTES]
        digest = hashlib.sha256(payload).hexdigest()
        if digest in known_hashes:
            added["duplicate"] += 1
            continue
        dest = root / "raw" / "inline" / f"inline_{idx:03d}_{digest[:8]}.js"
        dest.write_bytes(payload)
        known_hashes.add(digest)
        manifest.append({
            "hash": f"sha256:{digest}",
            "sha256": digest,
            "local_path": str(dest.relative_to(root)),
            "all_urls": [args.page_url],
            "source_urls": [args.page_url],
            "method": "browser-inline",
            "category": "inline",
            "size_bytes": len(payload),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        })
        added["inline"] += 1

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(root, f"capture {args.page_url}: {added['external']} external, {added['inline']} inline, "
              f"{added['duplicate']} duplicate, {added['failed']} failed")
    print(json.dumps({"root": str(root), **added, "manifest_entries": len(manifest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
