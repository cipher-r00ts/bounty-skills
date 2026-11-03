#!/usr/bin/env bash
# fuzz.sh — ffuf content discovery for one host and one auth mode.
#
#   fuzz.sh --run targets/<t>/artifacts/recon/hosts/<host> --url https://<host>/ \
#     --mode unauth [--headers /tmp/recon-auth/<host>/headers.txt] \
#     [--extensions php,json,bak] [--rate 40] [--threads 20] [--dry-run]
#
# Writes: <run>/domain/fuzz/<mode>/{ffuf.json,endpoints.jsonl,ffuf.log}
# Requests go direct by default; use --proxy only for small targeted passes.

set -euo pipefail

RUN="" URL="" MODE="unauth" HEADERS="" EXT="" RATE=40 THREADS=20 MAX_LINES=0 DRY=0 PROXY=""
SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

while (( $# )); do
  case "$1" in
    --run) RUN="${2:-}"; shift 2 ;;
    --url) URL="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --headers) HEADERS="${2:-}"; shift 2 ;;
    --extensions) EXT="${2:-}"; shift 2 ;;
    --rate) RATE="${2:-}"; shift 2 ;;
    --threads) THREADS="${2:-}"; shift 2 ;;
    --max-lines) MAX_LINES="${2:-}"; shift 2 ;;
    --proxy) PROXY="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$RUN" && -n "$URL" ]] || { echo "--run and --url are required" >&2; exit 2; }
command -v ffuf >/dev/null 2>&1 || { echo "ffuf not found (expected ~/go/bin/ffuf)" >&2; exit 1; }

LIST="$RUN/domain/wordlists/dirs.txt"
[[ -f "$LIST" ]] || { echo "missing wordlist: $LIST (run build_wordlists.sh)" >&2; exit 1; }
if (( MAX_LINES > 0 )); then
  head -n "$MAX_LINES" "$LIST" > "$LIST.tmp" && mv "$LIST.tmp" "$LIST"
fi

OUTDIR="$RUN/domain/fuzz/$MODE"
mkdir -p "$OUTDIR"
: > "$OUTDIR/endpoints.jsonl"
LOG="$OUTDIR/ffuf.log"
stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
log() { printf '%s %s\n' "$(stamp)" "$*" >> "$LOG"; }

hdr_args=()
if [[ -n "$HEADERS" ]]; then
  [[ -f "$HEADERS" ]] || { echo "headers file not found: $HEADERS" >&2; exit 1; }
  while IFS= read -r line; do
    [[ -n "$line" ]] && hdr_args+=(-H "$line")
  done < "$HEADERS"
  log "auth headers: $(wc -l < "$HEADERS") (values redacted)"
fi

proxy_args=()
[[ -n "$PROXY" ]] && proxy_args=(-x "$PROXY")

run_pass() { # label, extra ffuf args...
  local label="$1"; shift
  local json="$OUTDIR/ffuf_${label}.json"
  local cmd=(ffuf -u "${URL%/}/FUZZ" -w "$LIST:FUZZ"
    -mc 200,204,301,302,307,401,403,405 -fc 404
    -rate "$RATE" -t "$THREADS" -timeout 10 -s
    -o "$json" -of json)
  (( ${#hdr_args[@]} )) && cmd+=("${hdr_args[@]}")
  (( ${#proxy_args[@]} )) && cmd+=("${proxy_args[@]}")
  cmd+=("$@")

  if (( DRY )); then
    printf '%s\n' "DRY: ${cmd[*]}" | sed -E 's/(-H )[^ ]+ [^ ]+/\1<redacted>/g'
    return 0
  fi

  log "RUN $label ffuf rate=$RATE threads=$THREADS"
  if ! "${cmd[@]}" 2>>"$LOG"; then
    log "ffuf failed: $label"
  fi
  if [[ -f "$json" ]]; then
    python3 "$SELF_DIR/parse_ffuf.py" --json "$json" --mode "$MODE" --source "$label" \
      --out "$OUTDIR/endpoints.jsonl" >> "$LOG"
  fi
}

run_pass "dirs"
if [[ -n "$EXT" ]]; then
  run_pass "ext" -e "$EXT"
fi

echo "mode:   $MODE"
echo "out:    $OUTDIR"
# Merge the per-mode files; each mode is rebuilt fresh on its own run.
merged="$RUN/domain/fuzz/endpoints.jsonl"
: > "$merged"
for f in "$RUN"/domain/fuzz/*/endpoints.jsonl; do
  [[ -f "$f" ]] && cat "$f" >> "$merged"
done
sort -u "$merged" -o "$merged" || true
echo "hits:   $(grep -c '' "$merged" 2>/dev/null || echo 0)"
