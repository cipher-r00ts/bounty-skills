#!/usr/bin/env bash
# init-run.sh — create a js-acquire run root and its checklist.
#
#   init-run.sh --root targets/3hk/artifacts/recon/js
#
# The checklist uses stable log names (logs/<technique>.log); each log entry is
# timestamped, so re-runs append instead of creating a new file every time.

set -euo pipefail

ROOT=""
while (( $# )); do
  case "$1" in
    --root) ROOT="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$ROOT" ]] || { echo "--root is required" >&2; exit 2; }

mkdir -p "$ROOT"/{raw/{external,inline,historical,sourcemaps,pages},logs}

if [[ ! -f "$ROOT/checklist.md" ]]; then
  cat > "$ROOT/checklist.md" <<'EOF'
# JS acquisition checklist

A row is complete only when it is checked, its artifact is non-empty, and its
log exists with a timestamp. A technique that found nothing still needs a
non-empty log saying so.

- [ ] Browser capture (agent-browser) | artifact: raw/external/ | log: logs/browser-collect.log
- [ ] Inline snippet extraction | artifact: raw/inline/ | log: logs/browser-collect.log
- [ ] Live crawl (katana) | artifact: raw/external/ | log: logs/katana.log
- [ ] Historical JS (waymore / gau / waybackurls) | artifact: raw/external/ | log: logs/historical.log
- [ ] Sourcemap recovery | artifact: raw/sourcemaps/ | log: logs/sourcemaps.log
- [ ] JSLuice chained discovery | artifact: raw/external/ | log: logs/jsluice.log
- [ ] Deduplication and manifest | artifact: raw/manifest.json | log: logs/manifest.log
EOF
fi

echo "run root: $ROOT"
echo "checklist: $ROOT/checklist.md"
find "$ROOT" -maxdepth 2 -type d | sort
