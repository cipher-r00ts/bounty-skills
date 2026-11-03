#!/usr/bin/env bash
# host-recon.sh — host-level recon for a single in-scope host.
#
#   host-recon.sh --target 3hk --host www.three.com.hk
#   host-recon.sh --target 3hk --host cs.sosimhk.com --crawl --nuclei
#
# Passive by default (DNS, TLS, HTTP metadata, well-known files, JS endpoints).
# `--crawl` adds a shallow katana crawl; `--nuclei` adds low-rate template
# checks (exposure/misconfig/tech/headers only).
#
# Writes artifacts/recon/hosts/<host>/ and reports/hosts/<host>.md

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

TARGET="" HOST="" URL="" CRAWL=0 NUCLEI=0 RATE=30 TIMEOUT=10 DEPTH=2 FORCE=0

while (( $# )); do
  case "$1" in
    --target)  TARGET="${2:-}"; shift 2 ;;
    --host)    HOST="${2:-}"; shift 2 ;;
    --url)     URL="${2:-}"; shift 2 ;;
    --crawl)   CRAWL=1; shift ;;
    --nuclei)  NUCLEI=1; shift ;;
    --rate)    RATE="${2:-}"; shift 2 ;;
    --timeout) TIMEOUT="${2:-}"; shift 2 ;;
    --depth)   DEPTH="${2:-}"; shift 2 ;;
    --force)   FORCE=1; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || recon_die "--target is required"
[[ -n "$HOST" ]]   || recon_die "--host is required"
recon_need_target "$TARGET"
recon_ensure_layout "$TARGET"

H="${HOST,,}"; H="${H#\*.}"; H="${H%%/*}"; H="${H%%:*}"
URL="${URL:-https://$H}"

# Scope guard: the host must appear in the plan, unless --force is given.
PLAN="$(recon_state "$TARGET")/plan.json"
if (( ! FORCE )) && [[ -f "$PLAN" ]] && recon_have jq; then
  if ! jq -e --arg h "$H" '[.[] | select(.kind=="host" or .kind=="wildcard" or .kind=="domain") | .value] | any(. as $v | $h == $v or ($h | endswith("." + $v)))' "$PLAN" >/dev/null; then
    recon_die "$H does not match the recorded scope (use --force only if you are certain it is in scope)"
  fi
fi

DIR="$(recon_dir "$TARGET")"
OUT="$DIR/hosts/$H"
REP="$(recon_reports "$TARGET")/hosts"
mkdir -p "$OUT/js" "$REP"

UA='Mozilla/5.0 (X11; Linux x86_64) recon-skill/1.0'
strip_ansi() { sed -r 's/\x1B\[[0-9;]*[A-Za-z]//g'; }
recon_log "host recon: $H ($URL)"

# ── DNS ──────────────────────────────────────────────────────────────────────
if recon_have dnsx; then
  printf '%s\n' "$H" | dnsx -silent -nc -a -resp -cname > "$OUT/dns.txt" 2>/dev/null || true
fi
if [[ ! -s "$OUT/dns.txt" ]]; then
  getent ahosts "$H" 2>/dev/null | awk '{print $1}' | sort -u > "$OUT/dns.txt" || true
fi

# ── TLS ──────────────────────────────────────────────────────────────────────
if recon_have tlsx; then
  # tlsx refuses -so together with the certificate probes; run them separately.
  printf '%s\n' "$H" | tlsx -silent -nc -san -cn > "$OUT/tls.txt" 2>/dev/null || true
  printf '%s\n' "$H" | tlsx -silent -nc -so >> "$OUT/tls.txt" 2>/dev/null || true
fi

# ── HTTP metadata ────────────────────────────────────────────────────────────
if recon_have httpx; then
  httpx -u "$URL" -silent -json -fr \
    -sc -cl -wc -title -server -tech-detect -ip -cname -cdn \
    -timeout "$TIMEOUT" -retries 2 -rate-limit "$RATE" > "$OUT/httpx.jsonl" 2>/dev/null || true
fi

# ── headers + landing page ───────────────────────────────────────────────────
curl -sSIL --max-time "$TIMEOUT" -A "$UA" "$URL" > "$OUT/headers.txt" 2>/dev/null || true
curl -sSL --max-time "$TIMEOUT" --max-filesize 2000000 -A "$UA" "$URL" \
  -o "$OUT/index.html" 2>/dev/null || true
[[ -f "$OUT/index.html" ]] || : > "$OUT/index.html"

# ── well-known files ─────────────────────────────────────────────────────────
: > "$OUT/well-known.txt"
for path in robots.txt sitemap.xml .well-known/security.txt humans.txt security.txt; do
  name="$(printf '%s' "$path" | tr '/' '_')"
  meta=$(curl -sSL --max-time "$TIMEOUT" -A "$UA" -o "$OUT/$name"     -w '%{http_code}\t%{content_type}\t%{size_download}' "$URL/$path" 2>/dev/null || printf '000\t\t0')
  printf '%s\t%s\n' "$path" "$meta" >> "$OUT/well-known.txt"
done

# ── JS + endpoint extraction (no execution) ──────────────────────────────────
if [[ -s "$OUT/index.html" ]]; then
  {
    grep -Eo '(src|href)="[^"]+"' "$OUT/index.html" | sed -E 's/^(src|href)="//; s/"$//'
    grep -Eo "(src|href)='[^']+'" "$OUT/index.html" | sed -E "s/^(src|href)='//; s/'$//"
  } | sort -u > "$OUT/refs.txt" || true

  # Fetch up to 25 script bundles (bounded, same-origin or root-relative only).
  n=0
  while IFS= read -r ref; do
    case "$ref" in
      *.js|*.js\?*) ;;
      *) continue ;;
    esac
    (( n >= 25 )) && break
    case "$ref" in
      //*) fetch="https:$ref" ;;
      /*)  fetch="${URL%%/}$(printf '%s' "$ref" | sed 's/?.*//')" ;;
      http*) fetch="$ref" ;;
      *) continue ;;
    esac
    file="$OUT/js/$(printf '%s' "$ref" | sed -E 's#^.*/##; s/[?].*//' | tr -c 'A-Za-z0-9._-' '_')"
    curl -sSL --max-time "$TIMEOUT" --max-filesize 2000000 -A "$UA" "$fetch" -o "$file" 2>/dev/null || continue
    n=$((n + 1))
  done < "$OUT/refs.txt"

  {
    grep -rhoE 'https?://[A-Za-z0-9._~:/?#@!$&*+,;=%-]+' "$OUT/js" 2>/dev/null || true
    grep -rhoE '"/[A-Za-z0-9_./{}$:-]{2,}"' "$OUT/js" 2>/dev/null | tr -d '"' || true
  } | sed '/^$/d' | grep -v '^[$][{]' | sort -u > "$OUT/endpoints.txt"
fi

# ── optional crawl ───────────────────────────────────────────────────────────
if (( CRAWL )) && recon_have katana; then
  recon_log "katana crawl (depth $DEPTH, rate $RATE)"
  katana -u "$URL" -d "$DEPTH" -silent -rl "$RATE" -timeout "$TIMEOUT" \
    -o "$OUT/katana.txt" >/dev/null 2>&1 || recon_warn "katana failed"
else
  : > "$OUT/katana.txt"
fi

# ── optional nuclei ──────────────────────────────────────────────────────────
if (( NUCLEI )); then
  if recon_have nuclei; then
    recon_log "nuclei (exposure/misconfig/tech/headers, rate $RATE)"
    nuclei -u "$URL" -silent -severity info,low,medium \
      -tags exposure,misconfig,tech,headers -rl "$RATE" -timeout "$TIMEOUT" \
      -o "$OUT/nuclei.txt" >/dev/null 2>&1 || recon_warn "nuclei failed"
  else
    recon_warn "nuclei not installed — skipping"
  fi
fi
[[ -f "$OUT/nuclei.txt" ]] || : > "$OUT/nuclei.txt"

# ── report draft ─────────────────────────────────────────────────────────────
serverbanner="$(grep -i '^server:' "$OUT/headers.txt" 2>/dev/null | head -n1 | cut -d: -f2- | sed 's/^ *//' || true)"
status="$(jq -r '.status_code // 0' "$OUT/httpx.jsonl" 2>/dev/null | head -n1 || true)"
title="$(jq -r '.title // ""' "$OUT/httpx.jsonl" 2>/dev/null | head -n1 || true)"
tech="$(jq -r '(.tech // []) | join(", ")' "$OUT/httpx.jsonl" 2>/dev/null | head -n1 || true)"
ip="$(jq -r '.host_ip // ""' "$OUT/httpx.jsonl" 2>/dev/null | head -n1 || true)"

missing_headers=()
for h in strict-transport-security content-security-policy x-frame-options x-content-type-options referrer-policy permissions-policy; do
  grep -qi "^$h:" "$OUT/headers.txt" 2>/dev/null || missing_headers+=("$h")
done

{
  printf '# Host recon — %s\n\n' "$H"
  printf -- '- Target: `%s`\n' "$TARGET"
  printf -- '- URL: `%s`\n' "$URL"
  printf -- '- Generated: %s\n' "$(recon_now_utc)"
  printf -- '- Status: `%s` · title: “%s”\n' "${status:-n/a}" "$(printf '%s' "${title:-none}" | tr -d '|\n')"
  printf -- '- Server: `%s` · IP: `%s`\n' "$(printf '%s' "${serverbanner:-none}" | tr -d '|\n')" "${ip:-n/a}"
  printf -- '- Tech: %s\n' "$( [[ -n "$tech" ]] && printf '`%s`' "$(printf '%s' "$tech" | sed 's/,/`, `/g')" || printf 'none')"
  printf -- '- Artifacts: `artifacts/recon/hosts/%s/`\n\n' "$H"

  printf '## DNS\n\n'
  if [[ -s "$OUT/dns.txt" ]]; then strip_ansi < "$OUT/dns.txt" | sed 's/^/- `/; s/$/`/'; else printf -- '- no records resolved\n'; fi
  printf '\n## TLS\n\n'
  if [[ -s "$OUT/tls.txt" ]]; then strip_ansi < "$OUT/tls.txt" | sed 's/^/- `/; s/$/`/'; else printf -- '- tlsx not available or no certificate data\n'; fi
  printf '\n## Missing security headers\n\n'
  if (( ${#missing_headers[@]} )); then
    for h in "${missing_headers[@]}"; do printf -- '- `%s` not set\n' "$h"; done
    printf -- '\nThese are hardening gaps, not vulnerabilities on their own. Confirm impact before reporting.\n'
  else
    printf -- '- none missing from the checked set\n'
  fi
  printf '\n## Well-known files\n\n'
  if [[ -s "$OUT/well-known.txt" ]]; then
    while IFS=$'\t' read -r path code ctype size; do
      note=""
      case "$path" in
        *.txt)
          if [[ "$code" =~ ^[23] && "$ctype" == text/html* ]]; then
            note=" · soft 200: the body is HTML (WAF or SPA fallback), not a real file"
          fi
          ;;
      esac
      printf -- '- `%s` — status %s · %s · %s bytes%s\n' "$path" "$code" "${ctype:-unknown}" "${size:-0}" "$note"
    done < "$OUT/well-known.txt"
  else
    printf -- '- none fetched\n'
  fi
  printf '\n## Endpoints seen in HTML/JS\n\n'
  if [[ -s "$OUT/endpoints.txt" ]]; then
    printf -- '- %s unique strings in `endpoints.txt`; first 40:\n' "$(grep -c '' "$OUT/endpoints.txt")"
    head -n 40 "$OUT/endpoints.txt" | sed 's/^/  - `/; s/$/`/'
  else
    printf -- '- none extracted\n'
  fi
  printf '\n## Crawl\n\n'
  printf -- '- katana URLs: %s (`katana.txt`)\n' "$(grep -c '' "$OUT/katana.txt" 2>/dev/null || echo 0)"
  printf '\n## Nuclei\n\n'
  if [[ -s "$OUT/nuclei.txt" ]]; then
    sed 's/^/- `/; s/$/`/' "$OUT/nuclei.txt" | head -n 60
  else
    printf -- '- no findings recorded (run with --nuclei to enable)\n'
  fi
  printf '\n## Next checks\n\n'
  printf -- '- Walk the authenticated flows if the host offers login or registration.\n'
  printf -- '- Pull the JS bundles listed in `refs.txt` and look for build-time secrets and internal hosts.\n'
  printf -- '- Test the endpoints in `endpoints.txt` for authorization gaps with two accounts you own.\n'
  printf -- '- If `well-known.txt` shows a 200 for `sitemap.xml`, mine it for hidden paths and parameters.\n'
} > "$REP/$H.md"

"$SELF_DIR/../../recon/scripts/recon.sh" index --target "$TARGET" >/dev/null

recon_log "artifacts: $OUT"
recon_log "report:    $REP/$H.md"
