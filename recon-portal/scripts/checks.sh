#!/usr/bin/env bash
# checks.sh — non-destructive probe set for portal-class hosts.
#
#   checks.sh --target 3hk --url https://admin.example.com --all
#   checks.sh --target 3hk --url https://admin.example.com --403 --cors
#
# Flags: --403 --cors --client-auth --all --timeout 10
#
# Writes artifacts under hosts/<host>/portal/ and a markdown report at
# reports/hosts/<host>-portal.md. Never attempts logins or credentials.
# Credential testing stays manual and is documented in recon-portal/SKILL.md.

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

TARGET="" URL="" DO403=0 DOCORS=0 DOCLIENT=0 TIMEOUT=10

while (( $# )); do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --url)    URL="${2:-}"; shift 2 ;;
    --403)    DO403=1; shift ;;
    --cors)   DOCORS=1; shift ;;
    --client-auth) DOCLIENT=1; shift ;;
    --all)    DO403=1; DOCORS=1; DOCLIENT=1; shift ;;
    --timeout) TIMEOUT="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || recon_die "--target is required"
[[ -n "$URL" ]]    || recon_die "--url is required"
recon_need_target "$TARGET"
recon_require curl

H="$(printf '%s' "$URL" | sed -E 's#^[a-z]+://##; s#/.*##; s#:.*##' | tr '[:upper:]' '[:lower:]')"
DIR="$(recon_dir "$TARGET")/hosts/$H/portal"
REP="$(recon_reports "$TARGET")/hosts"
mkdir -p "$DIR" "$REP"

UA='Mozilla/5.0 (X11; Linux x86_64) recon-skill/1.0'
probe() { # url [curl args...] -> "code size redirect"
  local u="$1"; shift
  curl -sS -o /dev/null --max-time "$TIMEOUT" -A "$UA" \
    -w '%{http_code} %{size_download} %{redirect_url}' "$@" "$u" 2>/dev/null || printf '000 0 '
}

BASE="$(probe "$URL")"
B_CODE="${BASE%% *}"; rest="${BASE#* }"; B_SIZE="${rest%% *}"

recon_log "baseline $URL -> $B_CODE ($B_SIZE bytes)"

# ── 403 bypass ───────────────────────────────────────────────────────────────
if (( DO403 )); then
  : > "$DIR/bypass-header.txt"
  : > "$DIR/bypass-hits.txt"
  while IFS='|' read -r name value; do
    [[ -n "$name" ]] || continue
    r="$(probe "$URL" -H "$name: $value")"
    printf '%s\t%s\t%s\n' "$name" "$value" "$r" >> "$DIR/bypass-header.txt"
    [[ "${r%% *}" != "$B_CODE" ]] && printf 'DIFF header %s -> %s\n' "$name" "$r" >> "$DIR/bypass-hits.txt"
  done <<'EOF'
X-Forwarded-For|127.0.0.1
X-Originating-IP|127.0.0.1
X-Remote-IP|127.0.0.1
X-Client-IP|127.0.0.1
X-Forwarded-Host|127.0.0.1
X-Original-URL|/
X-Rewrite-URL|/
X-Custom-IP-Authorization|127.0.0.1
X-Forwarded-Prefix|/
EOF

  : > "$DIR/bypass-path.txt"
  base_url="${URL%/}"
  for p in "//" "/./" "/%2e/" "/..;/" "/%2e%2e/" "/;" "/.json" "/%20" "/%09" "/." ; do
    u="${base_url}${p}"
    r="$(probe "$u")"
    printf '%s\t%s\n' "$p" "$r" >> "$DIR/bypass-path.txt"
    [[ "${r%% *}" != "$B_CODE" ]] && printf 'DIFF path %s -> %s\n' "$p" "$r" >> "$DIR/bypass-hits.txt"
  done
  [[ -f "$DIR/bypass-hits.txt" ]] || : > "$DIR/bypass-hits.txt"
fi

# ── CORS ─────────────────────────────────────────────────────────────────────
if (( DOCORS )); then
  curl -sS -o /dev/null -D "$DIR/cors.headers" --max-time "$TIMEOUT" -A "$UA" \
    -H 'Origin: https://recon.invalid' "$URL" 2>/dev/null || true
  {
    grep -i '^access-control-allow-origin:' "$DIR/cors.headers" 2>/dev/null || echo 'no ACAO header'
    grep -i '^access-control-allow-credentials:' "$DIR/cors.headers" 2>/dev/null || true
  } > "$DIR/cors.txt"
fi

# ── client-side auth smells ──────────────────────────────────────────────────
if (( DOCLIENT )); then
  mkdir -p "$DIR/js"
  curl -sSL --max-time "$TIMEOUT" --max-filesize 2000000 -A "$UA" "$URL" -o "$DIR/index.html" 2>/dev/null || true
  : > "$DIR/client-auth-hits.txt"
  if [[ -s "$DIR/index.html" ]]; then
    grep -nEi 'localstorage|sessionstorage|document\.cookie|isadmin|isloggedin|role ?===|jwt|bearer' \
      "$DIR/index.html" | head -n 60 >> "$DIR/client-auth-hits.txt" || true
    grep -Eo '(src|href)="[^"]+\.js[^"]*"' "$DIR/index.html" | sed -E 's/^(src|href)="//; s/"$//' | head -n 10 \
      | while IFS= read -r ref; do
          case "$ref" in
            //*) u="https:$ref" ;;
            /*)  u="${URL%%/}$ref" ;;
            http*) u="$ref" ;;
            *) continue ;;
          esac
          f="$DIR/js/$(printf '%s' "$ref" | sed -E 's#^.*/##; s/[?].*//' | tr -c 'A-Za-z0-9._-' '_')"
          curl -sSL --max-time "$TIMEOUT" --max-filesize 2000000 -A "$UA" "$u" -o "$f" 2>/dev/null || continue
          grep -nEi 'isadmin|isloggedin|role ?===|localstorage|sessionstorage' "$f" | head -n 20 \
            | sed "s#^#$f:#" >> "$DIR/client-auth-hits.txt" || true
        done
  fi
fi

# ── report ───────────────────────────────────────────────────────────────────
{
  printf '# Portal checks — %s\n\n' "$H"
  printf -- '- Target: `%s`\n- URL: `%s`\n- Generated: %s\n' "$TARGET" "$URL" "$(recon_now_utc)"
  printf -- '- Baseline: status `%s`, %s bytes\n' "$B_CODE" "$B_SIZE"
  printf -- '- Artifacts: `artifacts/recon/hosts/%s/portal/`\n\n' "$H"
  printf 'These are observations from unauthenticated requests. A differing status or header is a lead to verify, not a vulnerability.\n\n'

  if (( DO403 )); then
    printf '## 403 / access-control bypass attempts\n\n'
    if [[ -s "$DIR/bypass-hits.txt" ]]; then
      printf 'Responses that differed from the baseline:\n\n'
      sed 's/^/- `/; s/$/`/' "$DIR/bypass-hits.txt"
      printf '\nFollow up manually: if a header or path variant returns 200 and the protected content, capture the full request/response pair.\n'
    else
      printf -- '- No header or path variant changed the response.\n'
    fi
    printf '\nFull attempt log: `bypass-header.txt`, `bypass-path.txt`.\n'
  fi

  if (( DOCORS )); then
    printf '\n## CORS\n\n'
    if [[ -s "$DIR/cors.txt" ]]; then sed 's/^/- `/; s/$/`/' "$DIR/cors.txt"; else printf -- '- no response captured\n'; fi
    printf '\nA reflected `Origin` with credentials enabled is worth a manual confirmation with two browsers.\n'
  fi

  if (( DOCLIENT )); then
    printf '\n## Client-side auth signals\n\n'
    if [[ -s "$DIR/client-auth-hits.txt" ]]; then
      sed 's/^/- `/; s/$/`/' "$DIR/client-auth-hits.txt" | head -n 60
      printf '\nCheck whether any of these flags are the only thing gating a route or API call. Test by replaying the API directly with your own account.\n'
    else
      printf -- '- no obvious client-side auth flags in the landing page or first 10 scripts\n'
    fi
  fi

  printf '\n## Manual follow-up (see recon-portal skill)\n\n'
  printf -- '- Try the small default-credential set once per form, logging each attempt.\n'
  printf -- '- Look for verbose errors, exposed API docs, and debug routes.\n'
  printf -- '- Compare the anonymous and authenticated responses for the same object IDs.\n'
} > "$REP/$H-portal.md"

"$SELF_DIR/../../recon/scripts/recon.sh" index --target "$TARGET" >/dev/null

recon_log "report: $REP/$H-portal.md"
