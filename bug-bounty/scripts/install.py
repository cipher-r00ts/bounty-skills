#!/usr/bin/env python3
"""Expose this project's bug-bounty skills to local OpenCode and Codex clients."""
import argparse
from pathlib import Path
import sys

SKILLS = ("bug-bounty", "bug-bounty-map", "bug-bounty-access", "bug-bounty-walk", "bug-bounty-investigate",
          "bug-bounty-prerequisites", "bug-bounty-counterevidence", "bug-bounty-verify",
          "bug-bounty-triage", "bug-bounty-dedupe", "bug-bounty-report")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--opencode-dir", type=Path, default=Path.home() / ".config/opencode/skills")
    p.add_argument("--codex-dir", type=Path, default=Path.home() / ".codex/skills")
    p.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    a = p.parse_args()
    source = Path(__file__).resolve().parents[2]
    links = [(directory / name, source / name) for directory in (a.opencode_dir, a.codex_dir) for name in SKILLS]
    links.append((a.bin_dir / "bug-bounty", source / "bug-bounty/scripts/bug_bounty.py"))
    # Validate the entire installation before changing any destination.
    for dest, src in links:
        if not src.exists():
            p.error(f"missing source: {src}")
        if dest.exists() or dest.is_symlink():
            if not dest.is_symlink() or dest.resolve() != src.resolve():
                p.error(f"refusing to overwrite existing path: {dest}")
    # Retire only links created by the previous installation; leave unrelated files alone.
    legacy = [(directory / name.replace("bug-bounty", "pentest", 1),
               source / name.replace("bug-bounty", "pentest", 1))
              for directory in (a.opencode_dir, a.codex_dir) for name in SKILLS]
    legacy.append((a.bin_dir / "pentest", source / "pentest/scripts/pentest.py"))
    retired = [dest for dest, expected in legacy
               if dest.is_symlink() and dest.resolve() == expected.resolve()]
    (source / "bug-bounty/scripts/bug_bounty.py").chmod(0o755)
    for dest, src in links:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_symlink():
            dest.symlink_to(src, target_is_directory=src.is_dir())
        print(f"{dest} -> {src}")
    for dest in retired:
        dest.unlink()
        print(f"Retired old installation link: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
