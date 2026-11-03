#!/usr/bin/env bash
# hx-append.sh — incremental httpx stage for the recon skills.
#
# Runs the same httpx profile as the user's `hx` wrapper, but in JSON mode so
# the triage skill gets structured data. Each call appends a batch; the merged
# `live/httpx.jsonl`, `live/httpx.txt` and `live/httpx_simple.txt` are rebuilt
# with per-URL deduplication so re-runs never duplicate hosts.
#
#   hx-append.sh --target T --input hosts.txt --tag subfaster
#   printf '%s\n' host.example.com | hx-append.sh --target T --tag manual --input -
#
# Options: --rate 200 --threads 100 --timeout 10 --ports 80,443,... --no-merge

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SELF_DIR/lib.sh"

TARGET="" INPUT="" TAG="manual" RATE=200 THREADS=100 TIMEOUT=10 MERGE=1
PORTS="80,443,8080,8000,8443,9443"

while (( $# )); do
  case "$1" in
    --target)  TARGET="${2:-}"; shift 2 ;;
    --input)   INPUT="${2:-}"; shift 2 ;;
    --tag)     TAG="${2:-}"; shift 2 ;;
    --rate)    RATE="${2:-}"; shift 2 ;;
    --threads) THREADS="${2:-}"; shift 2 ;;
    --timeout) TIMEOUT="${2:-}"; shift 2 ;;
    --ports)   PORTS="${2:-}"; shift 2 ;;
    --no-merge) MERGE=0; shift ;;
    -h|--help) sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || recon_die "--target is required"
[[ -n "$INPUT"  ]] || recon_die "--input is required (use - for stdin)"
recon_need_target "$TARGET"
recon_have httpx || recon_die "httpx not found on PATH (expected ~/.pdtm/go/bin/httpx)"

DIR="$(recon_dir "$TARGET")"
LIVE="$DIR/live"
JSONL_DIR="$LIVE/jsonl"
mkdir -p "$JSONL_DIR"

TMP="$(mktemp)"
trap 'rm -f "$TMP" "$TMP.batch"' EXIT

if [[ "$INPUT" == "-" ]]; then
  cat > "$TMP.batch"
else
  [[ -f "$INPUT" ]] || recon_die "input file not found: $INPUT"
  cp "$INPUT" "$TMP.batch"
fi

if ! grep -q '[^[:space:]]' "$TMP.batch"; then
  recon_log "no hosts to probe (tag: $TAG)"
  exit 0
fi

recon_log "httpx: $(grep -c '[^[:space:]]' "$TMP.batch") hosts (tag: $TAG)"

# Same profile as hx: status, length, words, title, server, tech, ip, cname, cdn.
# JSON mode keeps every field so the txt view can be regenerated losslessly.
httpx \
  -l "$TMP.batch" \
  -silent -json \
  -follow-redirects \
  -sc -cl -wc -title -server -tech-detect \
  -ip -cname -cdn \
  -threads "$THREADS" \
  -rate-limit "$RATE" \
  -timeout "$TIMEOUT" \
  -retries 2 \
  -p "$PORTS" \
  -o "$TMP" >/dev/null 2>&1 || true

if grep -q '[^[:space:]]' "$TMP"; then
  cp "$TMP" "$JSONL_DIR/$(recon_stamp)-$(printf '%s' "$TAG" | tr -c 'A-Za-z0-9._-' '_').jsonl"
fi

merge_views() {
  local all="$LIVE/httpx.jsonl"
  : > "$all"
  if compgen -G "$JSONL_DIR/*.jsonl" > /dev/null; then
    cat "$JSONL_DIR"/*.jsonl > "$all.raw"
    # Keep the last observation per URL, preserving first-seen order.
    awk '
      {
        u = $0
        if (match($0, /"url":"[^"]*"/)) u = substr($0, RSTART + 7, RLENGTH - 8)
        line[u] = $0
        if (!(u in order)) { n++; order[u] = n; keys[n] = u }
      }
      END { for (i = 1; i <= n; i++) print line[keys[i]] }
    ' "$all.raw" > "$all"
    rm -f "$all.raw"
  fi

  # hx-style one-liner view.
  jq -r '
    select(.failed != true)
    | (.title // "" | gsub("\\]"; ")")) as $title
    | (.webserver // "" | gsub("\\]"; ")")) as $server
    | (.cdn_name // "") as $cdn
    | "\(.url) [\(.status_code // 0)] [\(.content_length // 0)] [\($title)] [\(if .cdn then "CDN:" + (if $cdn == "" then "yes" else $cdn end) else "" end)] [wc:\(.words // 0)] [\($server)]"
  ' "$all" > "$LIVE/httpx.txt"

  jq -r 'select(.failed != true) | .url' "$all" | awk '!seen[$0]++' > "$LIVE/httpx_simple.txt"
}

if (( MERGE )); then
  merge_views
  recon_log "live: $(grep -c '' "$LIVE/httpx_simple.txt" || true) urls · $(grep -c '' "$LIVE/httpx.txt" || true) observations"
fi
