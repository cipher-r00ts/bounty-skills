#!/usr/bin/env bash
# build_wordlists.sh — build the wordlists for one host.
#
#   build_wordlists.sh --run targets/<t>/artifacts/recon/hosts/<host> \
#     --host <host> --url https://<host>/ --profile standard [--crawl]
#
# Sources: SecLists profiles, the API wordlist set, and custom paths harvested
# from sitemap/robots, the host map, JS endpoints and an optional crawl.
#
# Writes: <run>/domain/wordlists/{dirs.txt,params.txt,manifest.json,crawl-urls.txt}

set -euo pipefail

RUN="" HOST="" URL=""
SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"
 PROFILE="standard" CRAWL=0 MAX_CUSTOM=5000
SECLISTS_ROOT="${SECLISTS_ROOT:-$HOME/wordlists/SecLists}"
API_ROOT="${API_ROOT:-$HOME/wordlists/api}"

while (( $# )); do
  case "$1" in
    --run) RUN="${2:-}"; shift 2 ;;
    --host) HOST="${2:-}"; shift 2 ;;
    --url) URL="${2:-}"; shift 2 ;;
    --profile) PROFILE="${2:-}"; shift 2 ;;
    --crawl) CRAWL=1; shift ;;
    --max-custom) MAX_CUSTOM="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$RUN" && -n "$HOST" ]] || { echo "--run and --host are required" >&2; exit 2; }
URL="${URL:-https://$HOST/}"
WD="$RUN/domain/wordlists"
LOG="$RUN/domain/logs/wordlists.log"
mkdir -p "$WD" "$(dirname "$LOG")"
stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
log() { printf '%s %s\n' "$(stamp)" "$*" >> "$LOG"; }

norm_paths() {
  sed -E 's#^[[:space:]]+##; s#[[:space:]]+$##; s#^[a-z]+://[^/]+##; s#[?#].*$##; s#^/+##; s#/+$##' \
    | grep -vE '^$' \
    | grep -vE '[[:space:]]' \
    | grep -E '^[A-Za-z0-9._~%{}=:+@-]+(/[A-Za-z0-9._~%{}=:+@-]+)*$' \
    | awk 'length($0) < 200' \
    | sort -u
}

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
: > "$tmp"

dirs=()
case "$PROFILE" in
  light)    dirs+=("$SECLISTS_ROOT/Discovery/Web-Content/common.txt") ;;
  standard) dirs+=("$SECLISTS_ROOT/Discovery/Web-Content/raft-medium-directories.txt") ;;
  deep)     dirs+=("$SECLISTS_ROOT/Discovery/Web-Content/raft-small-words.txt" "$SECLISTS_ROOT/Discovery/Web-Content/raft-medium-files.txt") ;;
  *) echo "unknown profile: $PROFILE" >&2; exit 2 ;;
esac
dirs+=("$SECLISTS_ROOT/Discovery/Web-Content/api/api-endpoints.txt")
[[ -f "$API_ROOT/endpoints.txt" ]] && dirs+=("$API_ROOT/endpoints.txt")

for f in "${dirs[@]}"; do
  if [[ -f "$f" ]]; then
    norm_paths < "$f" >> "$tmp"
    log "base: $f ($(wc -l < "$f") lines)"
  else
    log "missing base wordlist: $f"
  fi
done

# Custom paths from the host map, sitemap, robots and JS endpoints.
custom_sources=("$RUN/sitemap.xml" "$RUN/robots.txt" "$RUN/endpoints.txt" "$RUN/refs.txt")
for f in "${custom_sources[@]}"; do
  [[ -f "$f" ]] || continue
  case "$f" in
    */sitemap.xml) grep -oE '<loc>[^<]+' "$f" | sed 's/<loc>//' | norm_paths >> "$tmp" ;;
    */robots.txt)  grep -iE '^(allow|disallow):' "$f" | sed -E 's/^[A-Za-z]+:[[:space:]]*//' | norm_paths >> "$tmp" ;;
    *)             norm_paths < "$f" >> "$tmp" ;;
  esac
  log "custom: $f"
done

if [[ -f "$RUN/js/findings/endpoints.jsonl" ]]; then
  jq -r '.path // .url // empty' "$RUN/js/findings/endpoints.jsonl" 2>/dev/null | norm_paths >> "$tmp"
  log "custom: js/findings/endpoints.jsonl"
fi

if (( CRAWL )); then
  if command -v katana >/dev/null 2>&1; then
    katana -u "$URL" -d 2 -silent -rl 20 -timeout 10 -o "$WD/crawl-urls.txt" >/dev/null 2>&1 || true
    [[ -f "$WD/crawl-urls.txt" ]] && norm_paths < "$WD/crawl-urls.txt" >> "$tmp"
    log "crawl: katana ($(grep -c '' "$WD/crawl-urls.txt" 2>/dev/null || echo 0) URLs)"
  else
    log "crawl requested but katana is missing"
  fi
fi

sort -u "$tmp" | awk -v n="$MAX_CUSTOM" 'NR <= n' > "$WD/dirs.txt"
api_count=$(grep -c '' "$WD/dirs.txt" || true)

PARAM_SRC="$SECLISTS_ROOT/Discovery/Web-Content/burp-parameter-names.txt"
if [[ -f "$PARAM_SRC" ]]; then
  head -n 5000 "$PARAM_SRC" | sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' | sort -u > "$WD/params.txt"
else
  head -n 3000 "$API_ROOT/query_parameters.txt" 2>/dev/null | sort -u > "$WD/params.txt" || : > "$WD/params.txt"
fi
param_count=$(grep -c '' "$WD/params.txt" || true)

jq -n --arg profile "$PROFILE" --argjson dirs "$api_count" --argjson params "$param_count" \
  --argjson custom "$(grep -c '' "$WD/dirs.txt" 2>/dev/null || echo 0)" \
  --arg generated "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  '{profile: $profile, dirs_lines: $dirs, params_lines: $params, generated: $generated}' > "$WD/manifest.json"

log "DONE dirs=$api_count params=$param_count profile=$PROFILE"
echo "dirs:   $WD/dirs.txt ($api_count words)"
echo "params: $WD/params.txt ($param_count words)"
