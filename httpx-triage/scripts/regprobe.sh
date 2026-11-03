#!/usr/bin/env bash
# regprobe.sh — interactivity probe: can a stranger create an account?
#
# Two passes:
#   1. a fixed set of common account paths, probed with httpx (fast, wide)
#   2. same-host links whose URL looks account-related, harvested from the
#      homepage and sitemap.xml (catches custom flows like /SoSim/main/tc/login)
#
# Classification needs structural evidence — a password field, a registration
# form, or a registration title — so a "Register" link in the navigation does
# not count.
#
#   regprobe.sh --target 3hk
#   regprobe.sh --target 3hk --limit 100 --hosts-file state/handoff/hosts.txt
#   regprobe.sh --target 3hk --no-discover
#
# Writes: triage/regprobe_raw.jsonl, triage/regprobe.tsv, state/regprobe/paths.txt

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

TARGET="" LIMIT=300 THREADS=30 RATE=100 TIMEOUT=10 HOSTS_FILE="" REFRESH=0
DISCOVER=1 DISCOVER_LIMIT=12

while (( $# )); do
  case "$1" in
    --target)        TARGET="${2:-}"; shift 2 ;;
    --limit)         LIMIT="${2:-}"; shift 2 ;;
    --threads)       THREADS="${2:-}"; shift 2 ;;
    --rate)          RATE="${2:-}"; shift 2 ;;
    --timeout)       TIMEOUT="${2:-}"; shift 2 ;;
    --hosts-file)    HOSTS_FILE="${2:-}"; shift 2 ;;
    --refresh-paths) REFRESH=1; shift ;;
    --no-discover)   DISCOVER=0; shift ;;
    --discover-limit) DISCOVER_LIMIT="${2:-}"; shift 2 ;;
    -h|--help)       sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)               recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || recon_die "--target is required"
recon_need_target "$TARGET"
recon_require httpx jq curl
recon_ensure_layout "$TARGET"

DIR="$(recon_dir "$TARGET")"
LIVE="$DIR/live/httpx.jsonl"
STATE="$DIR/state/regprobe"
PATHS="$STATE/paths.txt"
RAW="$DIR/triage/regprobe_raw.jsonl"
OUT="$DIR/triage/regprobe.tsv"
mkdir -p "$STATE"

if (( REFRESH )) || [[ ! -f "$PATHS" ]]; then
  cat > "$PATHS" <<'EOF'
/register
/signup
/sign-up
/signup.html
/register.html
/account/register
/user/register
/users/sign_up
/member/register
/membership/register
/create-account
/join
/en/register
/zh/register
/tc/register
/register-account
/new-account
/login
/signin
/account
/myaccount
EOF
fi

HOSTS="$STATE/hosts.txt"
if [[ -n "$HOSTS_FILE" ]]; then
  [[ -f "$HOSTS_FILE" ]] || recon_die "hosts file not found: $HOSTS_FILE"
  sed -e 's#^[a-z][a-z0-9+.-]*://##' -e 's#/.*##' -e 's#:.*##' "$HOSTS_FILE" \
    | tr '[:upper:]' '[:lower:]' | sort -u | head -n "$LIMIT" > "$HOSTS"
else
  [[ -f "$LIVE" ]] || recon_die "no live/httpx.jsonl — run the wildcard skill first"
  jq -r 'select(.failed != true) | .host // empty' "$LIVE" \
    | sort -u | head -n "$LIMIT" > "$HOSTS"
fi

count=$(grep -c '' "$HOSTS" || true)
: > "$OUT"
printf 'host\tkind\turl\tstatus\tevidence\n' > "$OUT"
if (( count == 0 )); then
  recon_warn "no hosts to probe"
  exit 0
fi

BASE_PATH="/_recon_baseline_$(recon_stamp)"
grep -v '^/_recon_baseline_' "$PATHS" > "$PATHS.tmp" || true
printf '%s\n' "$BASE_PATH" >> "$PATHS.tmp"
mv "$PATHS.tmp" "$PATHS"

recon_log "probing $count hosts x $(grep -c '' "$PATHS") generic account paths (rate $RATE)"
httpx -l "$HOSTS" -path "$PATHS" -silent -json -fr \
  -sc -cl -wc -title -location -timeout "$TIMEOUT" -retries 1 \
  -threads "$THREADS" -rate-limit "$RATE" -o "$RAW" >/dev/null 2>&1 || true
[[ -f "$RAW" ]] || : > "$RAW"

UA='Mozilla/5.0 (X11; Linux x86_64) recon-skill/1.0'
declare -A B_STATUS=() B_TITLE=() B_LEN=()
declare -A BEST_KIND=() BEST_URL=() BEST_ST=() BEST_EV=()
declare -A VISITED=()

while IFS=$'\t' read -r h p st ti cl; do
  [[ "$p" == "$BASE_PATH"* ]] || continue
  B_STATUS["$h"]="$st"; B_TITLE["$h"]="$ti"; B_LEN["$h"]="$cl"
done < <(jq -r 'select(.failed != true) | [.host, (.path // "/"), (.status_code // 0), (.title // ""), (.content_length // 0)] | @tsv' "$RAW")

store() { # host kind url status evidence
  local host="$1" kind="$2" url="$3" status="$4" evidence="$5" prev
  prev="${BEST_KIND[$host]:-}"
  if [[ "$kind" == "registration" || -z "$prev" ]]; then
    BEST_KIND["$host"]="$kind"
    BEST_URL["$host"]="$url"
    BEST_ST["$host"]="$status"
    BEST_EV["$host"]="${evidence:0:160}"
  fi
}

classify_html() { # host url status title html
  local host="$1" url="$2" status="$3" title="$4" html="$5"
  [[ -n "$html" ]] || return 0

  local lt reg login news has_pw=0 formreg=0 title_reg=0 kind="" evidence=""
  lt="$(printf '%s' "$4" | tr '[:upper:]' '[:lower:]')"

  # Real-name registration (SIM KYC) and documentation pages are not account
  # creation. They are common in HK telco sites and otherwise dominate the list.
  if printf '%s' "$url" | grep -Eqi 'real-?name|realname|rnr|實名|kyc'; then return 0; fi
  if printf '%s' "$url" | grep -Eqi '(/|^)(guide|help|faq|support|tnc|terms|article|blog|news)(/|\.|$)'; then return 0; fi

  reg="$(printf '%s' "$html" | grep -Eoi 'register|sign[ -]?up|signup|create (an )?account|open an account|join (now|free)|new (user|account)|註冊|登记|登記|開設賬戶|開設帳戶|建立帳戶|新用戶|新客戶|申請帳戶' | sort -u | paste -sd, - || true)"
  login="$(printf '%s' "$html" | grep -Eoi 'sign[ -]?in|log[ -]?in|登入|登录|forgot (your )?password' | sort -u | paste -sd, - || true)"
  news="$(printf '%s' "$html" | grep -Eoi 'newsletter|subscribe|mailing list|電子報|通訊' | sort -u | paste -sd, - || true)"

  printf '%s' "$html" | grep -Eqi 'type=["'"'"']password["'"'"']' && has_pw=1
  printf '%s' "$html" | grep -Eqi '<form[^>]*(register|signup|sign-up|account|join)' && formreg=1
  [[ "$lt" =~ (register|sign.?up|註冊|登記|開設|create.{0,4}account) ]] && title_reg=1

  # A registration page either says so in its title, lives at a
  # registration-looking path, or has a form that posts to one. A password
  # field alone is not enough: login pages have those too.
  local url_reg=0
  printf '%s' "$url" | grep -Eqi 'register|signup|sign-up|sign_up|create-account|new-account|open-account|join' && url_reg=1

  if [[ -n "$reg" ]]; then
    if { (( title_reg || url_reg )) && (( has_pw || formreg )); } || (( formreg && url_reg )); then
      kind="registration"; evidence="$reg"
    elif (( has_pw )) && [[ -n "$login" ]]; then
      kind="login"; evidence="$login"
    elif [[ -n "$news" ]]; then
      kind="login"; evidence="$news"
    fi
  elif [[ -n "$login" && $has_pw -eq 1 ]]; then
    kind="login"; evidence="$login"
  fi

  [[ -n "$kind" ]] || return 0
  store "$host" "$kind" "$url" "$status" "$evidence"
}

probe_candidate() { # host path status title clen url final_url
  local host="$1" path="$2" status="$3" title="$4" clen="$5" url="$6" final_url="$7"
  local bs="${B_STATUS[$host]:-}" bt="${B_TITLE[$host]:-}" bl="${B_LEN[$host]:-0}"

  [[ -n "$url" ]] || return 0
  [[ -n "${VISITED[$url]:-}" ]] && return 0
  VISITED["$url"]=1

  (( status >= 200 && status < 400 )) || return 0
  if [[ -n "$bs" && "$bs" == "$status" && "$title" == "$bt" ]]; then
    local diff=$(( clen > bl ? clen - bl : bl - clen ))
    (( diff < 200 )) && return 0
  fi

  local ltitle fpath fhost
  ltitle="$(printf '%s' "$title" | tr '[:upper:]' '[:lower:]')"
  fpath="$path"
  if [[ -n "$final_url" ]]; then
    fpath="${final_url#*://}"
    if [[ "$fpath" == */* ]]; then fpath="/${fpath#*/}"; else fpath="/"; fi
    fpath="${fpath%%\?*}"
    fhost="${final_url#*://}"; fhost="${fhost%%/*}"
    if [[ "$fhost" != "$host" ]]; then
      [[ "$ltitle" =~ (register|sign.?up|註冊|登記|開設) ]] || return 0
    fi
    case "$fpath" in
      /|/index.html|/home|/home.html|/404.html|*/404.html|/not-found|/error)
        [[ "$ltitle" =~ (register|sign.?up|註冊|登記|開設) ]] || return 0 ;;
    esac
  fi

  local html
  html="$(curl -sSL --max-time 10 --max-filesize 400000 -A "$UA" "$url" 2>/dev/null | head -c 400000 || true)"
  classify_html "$host" "$url" "$status" "$title" "$html"
}

while IFS=$'\t' read -r host path status title clen url final_url; do
  [[ "$path" == "$BASE_PATH"* ]] && continue
  probe_candidate "$host" "$path" "$status" "$title" "$clen" "$url" "$final_url"
done < <(jq -r 'select(.failed != true) | [.host, (.path // "/"), (.status_code // 0), (.title // ""), (.content_length // 0), (.url // ""), (.final_url // "")] | @tsv' "$RAW")

# ── pass 2: host-specific account links ──────────────────────────────────────

visit_url() { # host url
  local host="$1" u="$2" resp code html title
  [[ -n "${VISITED[$u]:-}" ]] && return 0
  VISITED["$u"]=1
  resp="$(curl -sSL --max-time 10 --max-filesize 400000 -A "$UA" -w $'\n%{http_code}' "$u" 2>/dev/null | tr -d '\0' || true)"
  [[ -n "$resp" ]] || return 0
  code="${resp##*$'\n'}"
  html="${resp%$'\n'*}"
  [[ "$code" =~ ^[23] ]] || return 0
  title="$(printf '%s' "$html" | grep -oEi '<title>[^<]*' | head -n1 | sed -E 's/<title>//I' || true)"
  classify_html "$host" "$u" "$code" "$title" "$html"
}

resolve_link() { # host ref -> absolute url or empty
  local host="$1" ref="$2"
  case "$ref" in
    \#*|javascript:*|mailto:*|tel:*|data:*) return 0 ;;
    //*)  printf 'https:%s' "$ref" ;;
    http://*|https://*) printf '%s' "$ref" ;;
    /*)   printf 'https://%s%s' "$host" "$ref" ;;
    *)    printf 'https://%s/%s' "$host" "$ref" ;;
  esac
}

discover_host() { # host
  local host="$1" home links ref url n=0 seen_local=" "
  home="$(curl -sSL --max-time "$TIMEOUT" --max-filesize 1500000 -A "$UA" "https://$host/" 2>/dev/null || true)"

  links="$(printf '%s' "$home" | grep -oE '(href|src)="[^"]+"' | sed -E 's/^(href|src)="//; s/"$//' | sort -u || true)"

  if recon_have curl; then
    links+=$'\n'
    links+="$(curl -sSL --max-time "$TIMEOUT" --max-filesize 3000000 -A "$UA" "https://$host/sitemap.xml" 2>/dev/null \
      | grep -oE '<loc>[^<]+</loc>' | sed -E 's#</?loc>##g' | tr -d ' ' | sort -u || true)"
  fi

  local -a candidates=()
  while IFS= read -r ref; do
    [[ -n "$ref" ]] || continue
    url="$(resolve_link "$host" "$ref")"
    [[ -n "$url" ]] || continue
    [[ "$(printf '%s' "$url" | sed -E 's#^[a-z]+://##; s#/.*##')" == "$host" ]] || continue
    printf '%s' "$url" | grep -Eqi 'regist|signup|sign-up|join|create|account|member|login|passport|my3|dashboard|登入|註冊|登記|開設' || continue
    [[ "$seen_local" == *" $url "* ]] && continue
    seen_local+="$url "
    candidates+=("$url")
  done <<< "$links"

  local i=0
  for url in "${candidates[@]}"; do
    (( i >= DISCOVER_LIMIT )) && break
    i=$((i + 1))
    visit_url "$host" "$url"
  done
  (( i > 0 )) && recon_log "  $host: checked $i discovered account link(s)"
  return 0
}

if (( DISCOVER )); then
  recon_log "discovering host-specific account links"
  while IFS= read -r host; do
    [[ -n "$host" ]] || continue
    discover_host "$host"
  done < "$HOSTS"
fi

for host in "${!BEST_KIND[@]}"; do
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$host" "${BEST_KIND[$host]}" "${BEST_URL[$host]}" "${BEST_ST[$host]}" "${BEST_EV[$host]}" >> "$OUT"
done

if (( ${#BEST_KIND[@]} > 0 )); then
  { head -n1 "$OUT"; tail -n +2 "$OUT" | sort -t$'\t' -k2,2 -k1,1; } > "$OUT.tmp"
  mv "$OUT.tmp" "$OUT"
fi

reg=$(awk -F'\t' 'NR>1 && $2=="registration"' "$OUT" | wc -l)
log=$(awk -F'\t' 'NR>1 && $2=="login"' "$OUT" | wc -l)
recon_log "registration open: $reg · login only: $log · see $OUT"
