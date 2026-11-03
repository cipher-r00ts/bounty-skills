#!/usr/bin/env python3
"""Verify a js-acquire / js-security-analysis checklist.

Every checklist row looks like:

  - [ ] label | artifact: path[, path] | log: path

A row is only complete when it is checked AND every artifact exists and is
non-empty AND its log exists, is non-empty, and looks timestamped. Rows with
`None found` still need a non-empty log.

Usage:
  python3 verify_checklist.py <run-root> [--checklist PATH] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROW_RE = re.compile(r"^\s*-\s*\[(?P<state>[ xX])\]\s*(?P<body>.*)$")
ART_RE = re.compile(r"artifact:\s*(?P<value>[^|]+?)(?=\s*\|\s*log:|$)")
LOG_RE = re.compile(r"log:\s*(?P<value>[^|]+?)\s*$")
TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2})|(T\d{6}Z)|(\d{8}T\d{6}Z)")


def split_paths(value: str) -> list[str]:
    value = value.strip().strip("`").strip()
    if not value:
        return []
    parts = [p.strip().strip("`").strip() for p in value.split(",")]
    return [p for p in parts if p]


def resolve(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p)


def is_nonempty(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    if path.is_dir():
        files = [f for f in path.rglob("*") if f.is_file() and f.stat().st_size > 0]
        return (True, f"{len(files)} file(s)") if files else (False, "directory is empty")
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, f"unreadable: {exc}"
    return (size > 0, f"{size} bytes") if size > 0 else (False, "empty file")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--checklist", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"error: run root does not exist: {root}", file=sys.stderr)
        return 2

    candidates = [args.checklist] if args.checklist else [
        root / "checklist.md",
        root / "analysis" / "checklist.md",
    ]
    checklist = next((Path(c) for c in candidates if c and Path(c).exists()), None)
    if checklist is None:
        print(f"error: no checklist found under {root}", file=sys.stderr)
        return 2
    checklist = checklist if checklist.is_absolute() else Path.cwd() / checklist

    problems: list[str] = []
    rows: list[dict] = []
    seen = 0

    for lineno, raw in enumerate(checklist.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = ROW_RE.match(raw)
        if not m:
            continue
        seen += 1
        checked = m.group("state").strip().lower() == "x"
        body = m.group("body").strip()
        label = body.split("|")[0].strip()

        am = ART_RE.search(body)
        lm = LOG_RE.search(body)
        artifacts = split_paths(am.group("value")) if am else []
        logs = split_paths(lm.group("value")) if lm else []

        row = {
            "line": lineno,
            "label": label,
            "checked": checked,
            "artifacts": [],
            "logs": [],
            "ok": True,
        }

        if not checked:
            row["ok"] = False
            problems.append(f"line {lineno}: unchecked — {label}")

        if not artifacts and not logs:
            row["ok"] = False
            problems.append(f"line {lineno}: no artifact or log path — {label}")
        elif not artifacts:
            row["ok"] = False
            problems.append(f"line {lineno}: no artifact recorded — {label}")
        elif not logs:
            row["ok"] = False
            problems.append(f"line {lineno}: no log recorded — {label}")

        for a in artifacts:
            apath = resolve(root, a)
            ok, detail = is_nonempty(apath)
            row["artifacts"].append({"path": a, "ok": ok, "detail": detail})
            if not ok:
                row["ok"] = False
                problems.append(f"line {lineno}: artifact {a} — {detail}")

        for l in logs:
            lpath = resolve(root, l)
            ok, detail = is_nonempty(lpath)
            timestamped = False
            if ok and lpath.is_file():
                head = lpath.read_text(encoding="utf-8", errors="replace")[:4000]
                timestamped = bool(TS_RE.search(head) or TS_RE.search(lpath.name))
            row["logs"].append({"path": l, "ok": ok, "detail": detail, "timestamped": timestamped})
            if not ok:
                row["ok"] = False
                problems.append(f"line {lineno}: log {l} — {detail}")
            elif not timestamped:
                row["ok"] = False
                problems.append(f"line {lineno}: log {l} has no UTC timestamp")

        rows.append(row)

    report = root / "verification_report.md"
    status = "PASS" if not problems else "FAIL"
    with report.open("w", encoding="utf-8") as fh:
        fh.write(f"# Verification — {root.name}\n\n")
        fh.write(f"- Checklist: `{checklist}`\n")
        fh.write(f"- Rows: {seen}\n")
        fh.write(f"- Status: **{status}**\n")
        fh.write(f"- Problems: {len(problems)}\n\n")
        if problems:
            fh.write("## Problems\n\n")
            for p in problems:
                fh.write(f"- {p}\n")
        else:
            fh.write("All checklist rows are checked, artifacts are non-empty, and logs are timestamped.\n")
        fh.write("\n## Rows\n\n")
        for r in rows:
            mark = "x" if r["ok"] else " "
            fh.write(f"- [{mark}] line {r['line']}: {r['label']}\n")

    if args.json:
        print(json.dumps({"status": status, "rows": rows, "problems": problems}, indent=2))
    else:
        print(f"{status}: {seen} row(s), {len(problems)} problem(s) — {report}")
        for p in problems:
            print(f"  - {p}")

    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
