#!/usr/bin/env bash
# report.sh — write the per-host domain report (table-free).
#
#   report.sh --target 3hk --host corp.portal.three.com.hk
#
# Reads <run>/domain/** and <run>/js/findings/**, writes
# reports/hosts/<host>-domain.md and refreshes the report index.

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

TARGET="" HOST=""
while (( $# )); do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --host) HOST="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" && -n "$HOST" ]] || recon_die "--target and --host are required"
recon_need_target "$TARGET"

RUN="$(recon_dir "$TARGET")/hosts/$HOST"
REP="$(recon_reports "$TARGET")/hosts"
mkdir -p "$REP"
OUT="$REP/$HOST-domain.md"

MODE="unauth"; URL="https://$HOST"; AUTH_VALID="unknown"
if [[ -f "$RUN/domain/mode.json" ]]; then
  MODE=$(jq -r '.mode // "unauth"' "$RUN/domain/mode.json")
  URL=$(jq -r '.url // "https://'"$HOST"'"' "$RUN/domain/mode.json")
  AUTH_VALID=$(jq -r '.auth_valid // "unknown"' "$RUN/domain/mode.json")
fi

endpoints="$RUN/domain/fuzz/endpoints.jsonl"
params="$RUN/domain/params/params.jsonl"
tech="$RUN/domain/checks/tech.jsonl"
jsdir="$RUN/js"
[[ -f "$endpoints" ]] || : > "$endpoints"
[[ -f "$params" ]] || : > "$params"
[[ -f "$tech" ]] || : > "$tech"

clean() { printf '%s' "$1" | tr -d '|\n\r' | sed 's/[`]//g'; }

{
  printf '# Domain recon — %s\n\n' "$HOST"
  printf -- '- Target: `%s`\n' "$TARGET"
  printf -- '- URL: `%s`\n' "$URL"
  printf -- '- Mode: `%s` · session valid: `%s`\n' "$MODE" "$AUTH_VALID"
  printf -- '- Generated: %s\n' "$(recon_now_utc)"
  printf -- '- Run root: `artifacts/recon/hosts/%s/domain/`\n\n' "$HOST"

  printf '## Content discovery\n\n'
  printf -- '- Endpoint records: %s\n' "$(grep -c '' "$endpoints" || true)"
  printf -- '- Responses by status: %s\n' "$(jq -r '.status' "$endpoints" 2>/dev/null | sort -n | uniq -c | awk '{printf "%s ×%s · ", $2, $1}' | sed 's/ · $//')"
  printf '\n'
  if [[ -s "$endpoints" ]]; then
    printf 'Highest-signal responses:\n\n'
    jq -r 'select(.status != 404) | [.mode, (.status|tostring), (.length//0|tostring), .path] | @tsv' "$endpoints" 2>/dev/null \
      | sort -t$'\t' -k2,2n -k3,3n | awk -F'\t' '!seen[$4]++' | head -30 \
      | while IFS=$'\t' read -r m st len path; do
          printf -- '- `%s` — status %s · %s bytes · mode %s\n' "$path" "$st" "$len" "$m"
        done
  else
    printf -- '- No endpoints discovered (wordlist/rate may be too small).\n'
  fi
  printf '\n'

  printf '## Parameters\n\n'
  if [[ -s "$params" ]]; then
    jq -r '[(.path // "?"), (.method // "GET"), (.input.FUZZ // .param // "?"), ((.status // 0)|tostring)] | @tsv' "$params" 2>/dev/null \
      | sort -u | head -60 | while IFS=$'\t' read -r path method param st; do
          printf -- '- `%s` — `%s` parameter `%s` (status %s)\n' "$path" "$method" "$param" "$st"
        done
  else
    printf -- '- No parameter results. arjun may be missing and the ffuf fallback found nothing.\n'
  fi
  printf '\n'

  printf '## Technology checks\n\n'
  if [[ -s "$tech" ]]; then
    hits=$(jq -r 'select(.hit==true)' "$tech" 2>/dev/null || true)
    if [[ -n "$hits" ]]; then
      printf 'Exposures confirmed by response body:\n\n'
      jq -r 'select(.hit==true) | [.path, (.status|tostring), .label, .evidence] | @tsv' "$tech" \
        | while IFS=$'\t' read -r p st label ev; do
            printf -- '- `%s` — %s (status %s) — %s\n' "$p" "$(clean "$label")" "$st" "$(clean "$ev")"
          done
    else
      printf -- '- No confirmed exposure from the checked paths.\n'
    fi
    printf '\nChecked paths: %s\n' "$(jq -rs '[.[].path] | join(", ")' "$tech" 2>/dev/null | cut -c1-600)"
  else
    printf -- '- Technology checks did not run.\n'
  fi
  printf '\n'

  printf '## JavaScript\n\n'
  if [[ -d "$jsdir" ]]; then
    js_count=$(jq -r 'length' "$jsdir/raw/manifest.json" 2>/dev/null || echo 0)
    printf -- '- Acquired JS entries: %s\n' "$js_count"
    [[ -f "$jsdir/findings/subdomains.txt" ]] && printf -- '- Hosts in JS: %s (in-scope: %s)\n' \
      "$(grep -c '' "$jsdir/findings/subdomains.txt" || true)" \
      "$(grep -c '' "$jsdir/findings/subdomains-scope.txt" || true)"
    if [[ -s "$jsdir/findings/historical.jsonl" ]]; then
      printf -- '- Historical-only paths: %s\n' "$(jq -r '[.historical_only_paths[]?] | length' "$jsdir/findings/historical.jsonl" 2>/dev/null | paste -sd+ - | bc 2>/dev/null || echo 0)"
    fi
    printf -- '- Details: `hosts/%s/js/findings/`\n' "$HOST"
  else
    printf -- '- JS acquisition did not run.\n'
  fi
  printf '\n'

  printf '## Next steps\n\n'
  printf -- '- Review the endpoint list, then test the ones with 200/401/403 for authorization gaps.\n'
  printf -- '- Try discovered parameters with two accounts you own; check mass assignment and IDOR.\n'
  printf -- '- Re-run authenticated to diff against the anonymous surface.\n'
  printf -- '- Feed JS endpoints and historical paths into the request collection.\n'
} > "$OUT"

"$SELF_DIR/../../recon/scripts/recon.sh" index --target "$TARGET" >/dev/null
recon_log "report: $OUT"
