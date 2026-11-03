#!/usr/bin/env bash
# run.sh — single-domain recon orchestrator: map, JS, wordlists, fuzz, params,
# technology checks, report. Authenticated or unauthenticated.
#
#   run.sh --target 3hk --host corp.portal.three.com.hk
#   run.sh --target 3hk --host corp.portal.three.com.hk \
#     --auth-config /tmp/caido/corp.portal.three.com.hk/auth.cfg --mode auth
#   run.sh --target 3hk --host mlp.three.com.hk --profile light --dry-run
#   run.sh ... --force        # only for a host you have confirmed by hand
#
# Auth config is a Caido `export-curl --config` file. Headers are copied to
# /tmp/recon-auth/<host>/headers.txt (mode 600), never into the repo.

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

TARGET="" HOST="" URL="" MODE="auto" AUTH_CONFIG="${CAIDO_AUTH_CONFIG:-}"
PROFILE="standard" CRAWL=0 JS=1 WAYBACK=0 JS_MAX=80
RATE=40 THREADS=20 EXT="php,asp,aspx,jsp,json,js,txt,bak,old,zip" WORDLIST_MAX=0
DO_MAP=1 DO_FUZZ=1 DO_PARAMS=1 DO_TECH=1 DRY=0 FORCE=0

while (( $# )); do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --host) HOST="${2:-}"; shift 2 ;;
    --url) URL="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --auth-config) AUTH_CONFIG="${2:-}"; shift 2 ;;
    --profile) PROFILE="${2:-}"; shift 2 ;;
    --crawl) CRAWL=1; shift ;;
    --no-js) JS=0; shift ;;
    --wayback) WAYBACK=1; shift ;;
    --js-max) JS_MAX="${2:-}"; shift 2 ;;
    --rate) RATE="${2:-}"; shift 2 ;;
    --threads) THREADS="${2:-}"; shift 2 ;;
    --extensions) EXT="${2:-}"; shift 2 ;;
    --wordlist-max) WORDLIST_MAX="${2:-}"; shift 2 ;;
    --skip-map) DO_MAP=0; shift ;;
    --skip-fuzz) DO_FUZZ=0; shift ;;
    --skip-params) DO_PARAMS=0; shift ;;
    --skip-tech) DO_TECH=0; shift ;;
    --dry-run) DRY=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" && -n "$HOST" ]] || recon_die "--target and --host are required"
recon_need_target "$TARGET"
H="${HOST,,}"; H="${H#\*.}"; H="${H%%/*}"; H="${H%%:*}"
URL="${URL:-https://$H}"
URL="${URL%/}"

# Scope guard, same rule as the single-host skill.
PLAN="$(recon_state "$TARGET")/plan.json"
if (( ! FORCE )) && [[ -f "$PLAN" ]] && recon_have jq; then
  if ! jq -e --arg h "$H" '[.[] | select(.kind=="host" or .kind=="wildcard" or .kind=="domain") | .value] | any(. as $v | $h == $v or ($h | endswith("." + $v)))' "$PLAN" >/dev/null; then
    recon_die "$H does not match the recorded scope (use the single-host skill with --force only if you are certain)"
  fi
fi

RUN="$(recon_dir "$TARGET")/hosts/$H"
mkdir -p "$RUN/domain"/{logs,wordlists,fuzz,params,checks}
LOG="$RUN/domain/logs/run.log"
stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
log() { printf '%s %s\n' "$(stamp)" "$*" >> "$LOG"; }

say() { printf '[*] %s\n' "$*"; }

log "START host=$H url=$URL mode=$MODE profile=$PROFILE js=$JS wayback=$WAYBACK dry=$DRY"

# ── passive map ──────────────────────────────────────────────────────────────

if (( DO_MAP )); then
  if [[ ! -f "$RUN/httpx.jsonl" || "$DRY" == "0" ]]; then
    say "map: $H"
    if (( DRY )); then
      printf 'DRY: host-recon.sh --target %q --host %q\n' "$TARGET" "$H"
    else
      "$SELF_DIR/../../recon-single-host/scripts/host-recon.sh" --target "$TARGET" --host "$H" || recon_warn "host map failed"
    fi
  fi
fi

# ── auth resolution ──────────────────────────────────────────────────────────

AUTH_VALID="unknown"
HEADERS=""
if [[ -n "$AUTH_CONFIG" ]]; then
  if [[ ! -f "$AUTH_CONFIG" ]]; then
    recon_die "auth config not found: $AUTH_CONFIG"
  fi
  AUTH_DIR="/tmp/recon-auth/$H"
  mkdir -p "$AUTH_DIR"
  python3 "$SELF_DIR/auth_headers.py" --config "$AUTH_CONFIG" --out "$AUTH_DIR/headers.txt" >/dev/null
  chmod 600 "$AUTH_DIR/headers.txt"
  HEADERS="$AUTH_DIR/headers.txt"
  say "auth: headers extracted ($(wc -l < "$HEADERS") header(s), values redacted)"
fi

if [[ -n "$HEADERS" ]]; then
  hdr=()
  while IFS= read -r line; do [[ -n "$line" ]] && hdr+=(-H "$line"); done < "$HEADERS"
  meta=$(curl -sS -o /dev/null -w '%{http_code}\t%{url_effective}' --max-time 15 "${hdr[@]}" "$URL/" 2>/dev/null || printf '000\t')
  code="${meta%%$'\t'*}"; final="${meta#*$'\t'}"
  if [[ "$code" =~ ^[23] ]] && ! printf '%s' "$final" | grep -Eqi 'login|signin|sign-in|auth/'; then
    AUTH_VALID="true"
  else
    AUTH_VALID="false"
    recon_warn "auth session check failed (status $code, final $final)"
  fi
fi

case "$MODE" in
  auth)
    [[ -n "$HEADERS" ]] || recon_die "--mode auth needs --auth-config"
    [[ "$AUTH_VALID" == "true" ]] || recon_die "auth session is not valid; refresh the Caido export"
    ;;
  unauth) HEADERS="" ;;
  auto)
    if [[ "$AUTH_VALID" == "true" ]]; then MODE=auth; else MODE=unauth; fi
    ;;
  *) recon_die "--mode must be auto, auth or unauth" ;;
esac

jq -n --arg host "$H" --arg url "$URL" --arg mode "$MODE" --arg valid "$AUTH_VALID" \
  --arg generated "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  '{host:$host,url:$url,mode:$mode,auth_valid:$valid,auth_config_used:($valid!="unknown"),generated:$generated}' \
  > "$RUN/domain/mode.json"
log "mode=$MODE auth_valid=$AUTH_VALID"

# ── JavaScript ───────────────────────────────────────────────────────────────

if (( JS )); then
  JSRUN="$RUN/js"
  say "js: browser capture"
  if (( DRY )); then
    printf 'DRY: js-acquire init + collect-browser + extract_hosts for %s\n' "$URL"
  else
    [[ -f "$JSRUN/checklist.md" ]] || "$SELF_DIR/../../js-acquire/scripts/init-run.sh" --root "$JSRUN" >/dev/null
    "$SELF_DIR/../../js-acquire/scripts/collect-browser.sh" --root "$JSRUN" --url "$URL/" \
      --max "$JS_MAX" --same-site-only --scroll 1 || recon_warn "JS capture failed"
    labels="$(recon_apex_labels "$H")"
    APEX="$(printf '%s' "$H" | awk -F. -v n="$labels" '{s=$(NF-n+1); for(i=NF-n+2;i<=NF;i++) s=s"."$i; print s}')"
    python3 "$SELF_DIR/../../js-security-analysis/scripts/extract_hosts.py" \
      --root "$JSRUN" --domain "$APEX" || recon_warn "host extraction failed"
    if (( WAYBACK )); then
      python3 "$SELF_DIR/../../js-wayback-diff/scripts/wayback_timeline.py" --root "$JSRUN" \
        --domain "$APEX" --months 24 --max-urls 15 --max-snapshots 4 || recon_warn "wayback timeline failed"
      python3 "$SELF_DIR/../../js-wayback-diff/scripts/jsdiff.py" --root "$JSRUN" --domain "$APEX" || recon_warn "history diff failed"
    fi
  fi
fi

# ── wordlists ────────────────────────────────────────────────────────────────

say "wordlists: profile $PROFILE"
if (( DRY )); then
  printf 'DRY: build_wordlists.sh --run %q --host %q --url %q --profile %q%s\n' "$RUN" "$H" "$URL" "$PROFILE" "$([[ $CRAWL -eq 1 ]] && echo ' --crawl')"
else
  crawl_arg=(); (( CRAWL )) && crawl_arg=(--crawl)
  "$SELF_DIR/build_wordlists.sh" --run "$RUN" --host "$H" --url "$URL" --profile "$PROFILE" "${crawl_arg[@]}" || recon_die "wordlist build failed"
fi

# ── fuzz ─────────────────────────────────────────────────────────────────────

fuzz_mode() { # mode headers
  local m="$1" hdr="$2"
  if (( DRY )); then
    printf 'DRY: fuzz.sh --run %q --url %q --mode %q%s%s\n' "$RUN" "$URL/" "$m" \
      "$([[ -n $hdr ]] && echo " --headers $hdr")" " --extensions $EXT --rate $RATE --threads $THREADS"
    return 0
  fi
  "$SELF_DIR/fuzz.sh" --run "$RUN" --url "$URL/" --mode "$m" \
    ${hdr:+--headers "$hdr"} --extensions "$EXT" --rate "$RATE" --threads "$THREADS" \
    --max-lines "$WORDLIST_MAX" || recon_warn "fuzz ($m) failed"
}

if (( DO_FUZZ )); then
  say "fuzz: unauthenticated"
  fuzz_mode unauth ""
  if [[ "$MODE" == "auth" ]]; then
    say "fuzz: authenticated"
    fuzz_mode auth "$HEADERS"
    if (( ! DRY )); then
      jq -r 'select(.mode=="auth") | .path' "$RUN/domain/fuzz/endpoints.jsonl" 2>/dev/null | sort -u > /tmp/auth_paths.$$
      jq -r 'select(.mode=="unauth") | .path' "$RUN/domain/fuzz/endpoints.jsonl" 2>/dev/null | sort -u > /tmp/unauth_paths.$$
      comm -23 /tmp/auth_paths.$$ /tmp/unauth_paths.$$ > "$RUN/domain/fuzz/auth-only.txt" || true
      rm -f /tmp/auth_paths.$$ /tmp/unauth_paths.$$
      say "auth-only paths: $(($(grep -c '' "$RUN/domain/fuzz/auth-only.txt" || true)))"
    fi
  fi
fi

# ── parameters ───────────────────────────────────────────────────────────────

if (( DO_PARAMS )); then
  say "params"
  if (( DRY )); then
    printf 'DRY: params.sh --run %q --url %q --tool auto%s\n' "$RUN" "$URL/" "$([[ -n $HEADERS ]] && echo " --headers $HEADERS")"
  else
    "$SELF_DIR/params.sh" --run "$RUN" --url "$URL/" --tool auto ${HEADERS:+--headers "$HEADERS"} || recon_warn "params failed"
  fi
fi

# ── technology checks ────────────────────────────────────────────────────────

if (( DO_TECH )); then
  say "tech checks"
  if (( DRY )); then
    printf 'DRY: tech.sh --run %q --url %q\n' "$RUN" "$URL/"
  else
    "$SELF_DIR/tech.sh" --run "$RUN" --url "$URL/" ${HEADERS:+--headers "$HEADERS"} || recon_warn "tech checks failed"
  fi
fi

# ── report ───────────────────────────────────────────────────────────────────

if (( DRY )); then
  printf 'DRY: report.sh --target %q --host %q\n' "$TARGET" "$H"
  say "dry run complete"
  exit 0
fi

"$SELF_DIR/report.sh" --target "$TARGET" --host "$H" || recon_warn "report failed"
"$SELF_DIR/../../recon/scripts/report-lint.sh" --target "$TARGET" || recon_warn "report lint failed"

log "DONE"
say "done: $RUN"
say "report: $(recon_reports "$TARGET")/hosts/$H-domain.md"
