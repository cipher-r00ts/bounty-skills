#!/usr/bin/env bash
# collect-browser.sh — browser-first JS acquisition.
#
# Loads the page in agent-browser (through Caido by default), waits for JS to
# run, optionally scrolls to trigger lazy bundles, captures every script URL and
# inline block, then downloads the external files byte-for-byte.
#
#   collect-browser.sh --root targets/3hk/artifacts/recon/js --url https://www.three.com.hk/
#   collect-browser.sh ... --same-site-only     # skip third-party tags
#   collect-browser.sh --root ... --url ... --auth-config /tmp/caido/host/auth.cfg
#
# Writes: raw/capture-*.json, raw/pages/, raw/external/, raw/inline/,
#         raw/manifest.json, logs/browser-collect.log

set -euo pipefail

ROOT="" URL="" PROXY="http://127.0.0.1:8081" USE_PROXY=1 AUTH_CONFIG="" MAX=200 WAIT=4 SCROLL=1 SAME_SITE=0
SESSION=""
SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

while (( $# )); do
  case "$1" in
    --root)  ROOT="${2:-}"; shift 2 ;;
    --url)   URL="${2:-}"; shift 2 ;;
    --proxy) PROXY="${2:-}"; USE_PROXY=1; shift 2 ;;
    --no-proxy) USE_PROXY=0; shift ;;
    --auth-config) AUTH_CONFIG="${2:-}"; shift 2 ;;
    --max)   MAX="${2:-}"; shift 2 ;;
    --wait)  WAIT="${2:-}"; shift 2 ;;
    --same-site-only) SAME_SITE=1; shift ;;
    --scroll) SCROLL="${2:-}"; shift 2 ;;
    --session) SESSION="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$ROOT" && -n "$URL" ]] || { echo "--root and --url are required" >&2; exit 2; }

NODE_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)"
[[ -n "$NODE_BIN" ]] && export PATH="$NODE_BIN:$PATH"

command -v agent-browser >/dev/null 2>&1 || {
  echo "agent-browser not found: npm install -g agent-browser && agent-browser install" >&2
  exit 1
}
command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 1; }

mkdir -p "$ROOT"/{raw/{external,inline,pages},logs}
SESSION="${SESSION:-js-acquire-$(printf '%s' "$URL" | sed -E 's#^[a-z]+://##; s#[^A-Za-z0-9]+#_#g' | cut -c1-40)}"
export AGENT_BROWSER_SESSION="$SESSION"

LOG="$ROOT/logs/browser-collect.log"
stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
log() { printf '%s %s\n' "$(stamp)" "$*" >> "$LOG"; }
log "START url=$URL proxy=$([[ $USE_PROXY -eq 1 ]] && echo "$PROXY" || echo direct) max=$MAX scroll=$SCROLL"

launch=(--timeout 30)
(( USE_PROXY )) && launch+=(--proxy "$PROXY" --ignore-https-errors)
if [[ -n "${AGENT_BROWSER_EXECUTABLE_PATH:-}" ]]; then
  launch+=(--executable-path "$AGENT_BROWSER_EXECUTABLE_PATH")
elif [[ -x "$HOME/.local/bin/chrome-caido" ]]; then
  launch+=(--executable-path "$HOME/.local/bin/chrome-caido" --args "--no-sandbox")
fi

agent-browser close >/dev/null 2>&1 || true
if ! agent-browser open "$URL" "${launch[@]}" >/dev/null 2>&1; then
  log "FAIL browser launch"
  echo "browser failed to launch (try: agent-browser install --with-deps)" >&2
  exit 1
fi
sleep "$WAIT"

for ((i = 0; i < SCROLL; i++)); do
  agent-browser eval 'window.scrollTo(0, document.body.scrollHeight)' >/dev/null 2>&1 || true
  sleep 1
done

capture_js='JSON.stringify({
  src: [...new Set(
    [...document.scripts].map(function(s){return s.src}).filter(Boolean)
      .concat(performance.getEntriesByType("resource")
        .filter(function(e){return e.initiatorType==="script" || /\.js(\?|$)/i.test(e.name)})
        .map(function(e){return e.name}))
  )],
  inline: [...document.scripts].filter(function(s){return !s.src && s.textContent && s.textContent.trim().length>20}).map(function(s){return s.textContent.slice(0,500000)})
})'

TS="$(date -u +%Y%m%dT%H%M%SZ)"
CAPTURE="$ROOT/raw/capture-${TS}.json"
if ! agent-browser eval "$capture_js" 2>/dev/null | tail -n1 > "$CAPTURE"; then
  log "FAIL capture eval"
  echo "capture failed" >&2
  exit 1
fi

slug="$(printf '%s' "$URL" | sed -E 's#^[a-z]+://##; s#[^A-Za-z0-9._-]+#_#g' | cut -c1-80)"
agent-browser get html > "$ROOT/raw/pages/${slug}.html" 2>/dev/null || true
agent-browser close >/dev/null 2>&1 || true

count_src=$(jq -r 'if type=="string" then fromjson else . end | .src | length' "$CAPTURE" 2>/dev/null || echo 0)
count_inline=$(jq -r 'if type=="string" then fromjson else . end | .inline | length' "$CAPTURE" 2>/dev/null || echo 0)
log "CAPTURE scripts=$count_src inline=$count_inline page=$URL"

proxy_arg=(); auth_arg=(); site_arg=()
(( USE_PROXY )) && proxy_arg=(--proxy "$PROXY")
[[ -n "$AUTH_CONFIG" ]] && auth_arg=(--auth-config "$AUTH_CONFIG")
(( SAME_SITE )) && site_arg=(--same-site-only)

python3 "$SELF_DIR/ingest_capture.py" \
  --root "$ROOT" --capture "$CAPTURE" --page-url "$URL" --max "$MAX" \
  "${proxy_arg[@]}" "${auth_arg[@]}" "${site_arg[@]}" | tee -a "$LOG"

echo "capture: $CAPTURE"
echo "raw:     $ROOT/raw"
