#!/usr/bin/env bash
# browser-probe.sh — browse the live apps with agent-browser and record what the
# HTTP metadata alone cannot tell you: rendered titles, login forms, SPA
# frameworks, off-scope redirects, and a text snapshot of the landing page.
#
#   browser-probe.sh --target 3hk
#   browser-probe.sh --target 3hk --limit 100 --all
#   browser-probe.sh --target 3hk --hosts-file state/handoff/hosts.txt
#
# Traffic goes through the Caido proxy by default (127.0.0.1:8081) so every page
# lands in the project's HTTP history. Use --no-proxy to browse directly.
#
# Writes: triage/browser.tsv
#   host  url(final)  title  status  forms  password  links  js  framework  inputs  text

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

TARGET="" LIMIT=60 HOSTS_FILE="" ALL=0
PROXY="http://127.0.0.1:8081" USE_PROXY=1
SESSION="" TIMEOUT=25 CASE_TIMEOUT=45

while (( $# )); do
  case "$1" in
    --target)      TARGET="${2:-}"; shift 2 ;;
    --limit)       LIMIT="${2:-}"; shift 2 ;;
    --hosts-file)  HOSTS_FILE="${2:-}"; shift 2 ;;
    --all)         ALL=1; shift ;;
    --proxy)       PROXY="${2:-}"; USE_PROXY=1; shift 2 ;;
    --no-proxy)    USE_PROXY=0; shift ;;
    --session)     SESSION="${2:-}"; shift 2 ;;
    --timeout)     TIMEOUT="${2:-}"; shift 2 ;;
    -h|--help)     sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)             recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || recon_die "--target is required"
recon_need_target "$TARGET"

# node/agent-browser usually live under nvm and are not on the default PATH.
NODE_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)"
[[ -n "$NODE_BIN" ]] && export PATH="$NODE_BIN:$PATH"

recon_have agent-browser || recon_die "agent-browser not found (npm install -g agent-browser && agent-browser install)"

DIR="$(recon_dir "$TARGET")"
OUT="$DIR/triage/browser.tsv"
TMPOUT="$OUT.new"
HOSTLIST="$DIR/triage/browser-hosts.txt"
mkdir -p "$DIR/triage"
SESSION="${SESSION:-recon-$(printf '%s' "$TARGET" | tr -c 'A-Za-z0-9._-' '_')}"
export AGENT_BROWSER_SESSION="$SESSION"

# ── who to browse ────────────────────────────────────────────────────────────

if [[ -n "$HOSTS_FILE" ]]; then
  [[ -f "$HOSTS_FILE" ]] || recon_die "hosts file not found: $HOSTS_FILE"
  sed -e 's#^[a-z][a-z0-9+.-]*://##' -e 's#/.*##' -e 's#:.*##' "$HOSTS_FILE" \
    | tr '[:upper:]' '[:lower:]' | sort -u > "$HOSTLIST"
elif [[ -f "$DIR/triage/candidates.tsv" ]]; then
  # Priority order across every tier (candidates.tsv is already sorted by
  # tier then score), deduplicated by host.
  awk -F'\t' 'NR>1 && !seen[$3]++ {print $3}' "$DIR/triage/candidates.tsv" > "$HOSTLIST"
else
  [[ -f "$DIR/live/httpx_simple.txt" ]] || recon_die "no candidates.tsv and no live/httpx_simple.txt — run the wildcard stage first"
  sed -E 's#^[a-z]+://##; s#/.*##; s#:.*##' "$DIR/live/httpx_simple.txt" | sort -u > "$HOSTLIST"
fi

if (( ! ALL )); then
  head -n "$LIMIT" "$HOSTLIST" > "$HOSTLIST.tmp" && mv "$HOSTLIST.tmp" "$HOSTLIST"
fi
count=$(grep -c '' "$HOSTLIST" || true)
(( count > 0 )) || recon_die "no hosts selected for the browser pass"

# ── browser launch flags ─────────────────────────────────────────────────────

launch=()
launch+=(--timeout "$TIMEOUT")

if (( USE_PROXY )); then
  launch+=(--proxy "$PROXY" --ignore-https-errors)
fi

# This box has no root and Chrome's runtime libs live under ~/.local/chromelibs.
# A wrapper handles both LD_LIBRARY_PATH and the executable path.
if [[ -n "${AGENT_BROWSER_EXECUTABLE_PATH:-}" ]]; then
  launch+=(--executable-path "$AGENT_BROWSER_EXECUTABLE_PATH")
elif [[ -x "$HOME/.local/bin/chrome-caido" ]]; then
  launch+=(--executable-path "$HOME/.local/bin/chrome-caido" --args "--no-sandbox")
elif [[ "${AGENT_BROWSER_NO_SANDBOX:-0}" == "1" ]]; then
  launch+=(--args "--no-sandbox")
fi

if (( USE_PROXY )); then
  recon_log "browser pass: $count host(s) via $PROXY"
else
  recon_log "browser pass: $count host(s) direct (no proxy)"
fi

# Launch once with the flags; later commands attach to the running session.
agent-browser close >/dev/null 2>&1 || true
if ! agent-browser open "${launch[@]}" >/dev/null 2>&1; then
  recon_warn "could not launch agent-browser (try: agent-browser install --with-deps)"
  exit 1
fi

cleanup() { agent-browser close >/dev/null 2>&1 || true; }
trap cleanup EXIT

# ── page facts ───────────────────────────────────────────────────────────────

eval_js='JSON.stringify({u:location.href,t:document.title,s:(performance.getEntriesByType("navigation")[0]||{}).responseStatus||0,forms:document.forms.length,pw:document.querySelectorAll("input[type=password]").length,inputs:[...document.querySelectorAll("input")].slice(0,12).map(function(i){return i.name||i.id||i.type||"?"}),links:document.links.length,js:document.scripts.length,fw:(window.React?"react":(window.angular?"angular":(window.Vue?"vue":(window.__NEXT_DATA__?"nextjs":"")))),text:(document.body?document.body.innerText.replace(/\s+/g," ").slice(0,220):"")})'

printf 'host\turl\ttitle\tstatus\tforms\tpassword\tlinks\tjs\tframework\tinputs\ttext\n' > "$TMPOUT"

n=0
while IFS= read -r host; do
  [[ -n "$host" ]] || continue
  n=$((n + 1))
  if ! timeout "$CASE_TIMEOUT" agent-browser open "https://$host/" >/dev/null 2>&1; then
    printf '%s\t-\t-\t-\t-\t-\t-\t-\t-\t-\t(open failed)\n' "$host" >> "$TMPOUT"
    printf '  %-32s open failed\n' "$host"
    continue
  fi
  info=$(timeout "$CASE_TIMEOUT" agent-browser eval "$eval_js" 2>/dev/null | tail -n1 || true)
  row=$(printf '%s' "$info" | jq -r --arg h "$host" '
    (if type == "string" then (fromjson? // {}) else . end) as $j
    | [ $h,
        ($j.u // "-"),
        ($j.t // "-"),
        (($j.s // 0) | tostring),
        (($j.forms // 0) | tostring),
        (($j.pw // 0) | tostring),
        (($j.links // 0) | tostring),
        (($j.js // 0) | tostring),
        (($j.fw // "") | if . == "" then "-" else . end),
        (($j.inputs // []) | join(",") | if . == "" then "-" else . end),
        (($j.text // "") | if . == "" then "-" else . end)
      ]
    | map(if . == "" then "-" else . end)
    | @tsv' 2>/dev/null || true)
  if [[ -z "$row" ]]; then
    printf '%s\t-\t-\t-\t-\t-\t-\t-\t-\t-\t(eval failed)\n' "$host" >> "$TMPOUT"
    printf '  %-32s eval failed\n' "$host"
    continue
  fi
  printf '%s\n' "$row" >> "$TMPOUT"
  title=$(printf '%s' "$row" | cut -f3)
  fw=$(printf '%s' "$row" | cut -f9)
  pw=$(printf '%s' "$row" | cut -f6)
  printf '  %-32s %-38s fw=%-7s pw=%s\n' "$host" "$(printf '%s' "$title" | cut -c1-38)" "$fw" "$pw"
  sleep 0.25
done < "$HOSTLIST"

# Merge with any earlier browser run: the newest row per host wins, so a small
# --limit run does not erase observations from a bigger one.
{
  head -n1 "$TMPOUT"
  {
    [[ -f "$OUT" ]] && tail -n +2 "$OUT"
    tail -n +2 "$TMPOUT"
  } | tac | awk -F'\t' '!seen[$1]++' | sort -t$'\t' -k1,1
} > "$OUT.merged"
mv "$OUT.merged" "$OUT"
rm -f "$TMPOUT"

recon_log "wrote $n host(s) to $OUT"
