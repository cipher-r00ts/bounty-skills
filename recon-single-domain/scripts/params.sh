#!/usr/bin/env bash
# params.sh — parameter discovery for one host.
#
#   params.sh --run targets/<t>/artifacts/recon/hosts/<host> --url https://<host>/ \
#     [--headers /tmp/recon-auth/<host>/headers.txt] [--tool auto] [--paths 10]
#
# Tool: arjun when installed, otherwise an ffuf GET-parameter sweep using the
# same auth headers. Both are bounded; this is not a param-miner replacement.
#
# Writes: <run>/domain/params/{params.jsonl,arjun/,params.log}

set -euo pipefail

RUN="" URL="" HEADERS="" TOOL="auto" PATHS=10 PARAM_LIMIT=2000 RATE=20 THREADS=10 DRY=0
SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

while (( $# )); do
  case "$1" in
    --run) RUN="${2:-}"; shift 2 ;;
    --url) URL="${2:-}"; shift 2 ;;
    --headers) HEADERS="${2:-}"; shift 2 ;;
    --tool) TOOL="${2:-}"; shift 2 ;;
    --paths) PATHS="${2:-}"; shift 2 ;;
    --param-limit) PARAM_LIMIT="${2:-}"; shift 2 ;;
    --rate) RATE="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$RUN" && -n "$URL" ]] || { echo "--run and --url are required" >&2; exit 2; }

OUTDIR="$RUN/domain/params"
mkdir -p "$OUTDIR/arjun"
LOG="$OUTDIR/params.log"
: > "$OUTDIR/params.jsonl"
stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
log() { printf '%s %s\n' "$(stamp)" "$*" >> "$LOG"; }

WORDS="$RUN/domain/wordlists/params.txt"
[[ -f "$WORDS" ]] || { echo "missing param wordlist: $WORDS (run build_wordlists.sh)" >&2; exit 1; }
head -n "$PARAM_LIMIT" "$WORDS" > "$OUTDIR/params_head.txt"

mapfile -t path_list < <(
  {
    [[ -f "$RUN/domain/fuzz/endpoints.jsonl" ]] && jq -r 'select(.status==200 or .status==302 or .status==401 or .status==403) | .path // empty' "$RUN/domain/fuzz/endpoints.jsonl"
    [[ -f "$RUN/js/findings/endpoints.jsonl" ]] && jq -r '.path // empty' "$RUN/js/findings/endpoints.jsonl"
  } | grep '^/' | sort -u | head -n "$PATHS"
)

if (( ${#path_list[@]} == 0 )); then
  path_list=("/")
  log "no fuzz paths; testing the root only"
fi

hdr_args=()
if [[ -n "$HEADERS" ]]; then
  [[ -f "$HEADERS" ]] || { echo "headers file not found: $HEADERS" >&2; exit 1; }
  while IFS= read -r line; do [[ -n "$line" ]] && hdr_args+=(-H "$line"); done < "$HEADERS"
fi

if [[ "$TOOL" == "auto" ]]; then
  if command -v arjun >/dev/null 2>&1; then TOOL=arjun; else TOOL=ffuf; fi
fi
log "tool=$TOOL paths=${#path_list[@]} words=$(wc -l < "$OUTDIR/params_head.txt")"

if [[ "$TOOL" == "arjun" ]]; then
  command -v arjun >/dev/null 2>&1 || { echo "arjun not installed" >&2; exit 1; }
  hdr_string=""
  if [[ -n "$HEADERS" ]]; then
    hdr_string="$(awk 'BEGIN{ORS=""} NR>1{print "\\n"} {print}' "$HEADERS")"
  fi
  for path in "${path_list[@]}"; do
    target="${URL%/}$path"
    name="$(printf '%s' "$path" | sed -E 's#[^A-Za-z0-9]+#_#g' | cut -c1-60)"
    out="$OUTDIR/arjun/${name:-root}.json"
    if (( DRY )); then
      printf 'DRY: arjun -u %q -m GET -oJ %q %s\n' "$target" "$out" "$([[ -n $hdr_string ]] && echo '--headers <redacted>')"
      continue
    fi
    args=(arjun -u "$target" -m GET -oJ "$out" -q --stable --rate-limit "$RATE" -w "$OUTDIR/params_head.txt")
    [[ -n "$hdr_string" ]] && args+=(--headers "$hdr_string")
    "${args[@]}" >> "$LOG" 2>&1 || log "arjun failed: $target"
    if [[ -f "$out" ]]; then
      python3 "$SELF_DIR/parse_arjun.py" --json "$out" --path "$path" --out "$OUTDIR/params.jsonl" >> "$LOG" 2>&1 || true
    fi
  done
else
  command -v ffuf >/dev/null 2>&1 || { echo "ffuf not installed" >&2; exit 1; }
  for path in "${path_list[@]}"; do
    target="${URL%/}$path"
    name="$(printf '%s' "$path" | sed -E 's#[^A-Za-z0-9]+#_#g' | cut -c1-60)"
    json="$OUTDIR/ffuf_${name:-root}.json"
    cmd=(ffuf -u "${target}?FUZZ=1" -w "$OUTDIR/params_head.txt:FUZZ" -ac
      -mc 200,204,302,401,403 -t "$THREADS" -rate "$RATE" -timeout 10 -s
      -o "$json" -of json)
    (( ${#hdr_args[@]} )) && cmd+=("${hdr_args[@]}")
    if (( DRY )); then
      printf '%s\n' "DRY: ${cmd[*]}" | sed -E 's/(-H )[^ ]+ [^ ]+/\1<redacted>/g'
      continue
    fi
    log "ffuf params: $target"
    "${cmd[@]}" >> "$LOG" 2>&1 || log "ffuf failed: $target"
    [[ -f "$json" ]] && python3 "$SELF_DIR/parse_ffuf.py" --json "$json" --mode params --source "params:$path" \
      --with-input --out "$OUTDIR/params.jsonl" >> "$LOG" 2>&1 || true
  done
fi

count=0
[[ -f "$OUTDIR/params.jsonl" ]] && count=$(grep -c '' "$OUTDIR/params.jsonl" || true)
echo "tool: $TOOL"
echo "paths: ${#path_list[@]}"
echo "params found: $count"
