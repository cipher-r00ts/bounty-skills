#!/usr/bin/env bash
# triage.sh — score live hosts and split them into hunting tiers.
#
# Reads the merged httpx JSON from the wildcard stage plus the interactivity
# probe, then writes `triage/candidates.tsv`:
#
#   score  tier  host  url  status  title  server  cdn  words  tech  signals  reg
#
# Tier 0 is registration-open (manual hunting), tier 1 is portal/agent recon,
# tier 2 auth/API surfaces, tier 3 standard apps, tier 4 static/low value.
#
#   triage.sh --target 3hk
#
# No network access: this step only reads artifacts.

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

TARGET=""
while (( $# )); do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || recon_die "--target is required"
recon_need_target "$TARGET"
recon_require jq

DIR="$(recon_dir "$TARGET")"
LIVE="$DIR/live/httpx.jsonl"
REG="$DIR/triage/regprobe.tsv"
BROWSER="$DIR/triage/browser.tsv"
OUT="$DIR/triage/candidates.tsv"
mkdir -p "$DIR/triage"

[[ -f "$LIVE" ]] || recon_die "no live/httpx.jsonl — run recon-wildcard first"
[[ -f "$REG" ]] || printf 'host\tkind\turl\tstatus\tevidence\n' > "$REG"
[[ -f "$BROWSER" ]] || printf 'host\turl\ttitle\tstatus\tforms\tpassword\tlinks\tjs\tframework\tinputs\ttext\n' > "$BROWSER"

WORK="$(mktemp)"; trap 'rm -f "$WORK"' EXIT

# One row per host: prefer non-404, then 200, then https.
jq -r -s '
  def rank:
    (.status_code // 0) as $s
    | if $s == 200 then 10
      elif ($s >= 300 and $s < 400) then 9
      elif ($s == 401 or $s == 403) then 8
      elif $s == 404 then 3
      elif $s >= 500 then 2
      elif $s == 400 then 1
      else 5 end;
  [ .[] | select(.failed != true) ]
  | group_by(.host)
  | map(max_by([
      rank,
      (if ((.url // "") | startswith("https")) then 1 else 0 end),
      (if (.port // "") == "443" then 1 else 0 end)
    ]))
  | .[]
  | [ .host, (.url // ""), (.status_code // 0), (.content_length // 0), (.words // 0),
      (.title // ""), (.webserver // ""), (.cdn_name // ""),
      ((.tech // []) | join(",")) ]
  | @tsv
' "$LIVE" > "$WORK"

awk -F'\t' -v OFS='\t' '
function has(s, re) { return s ~ re }
BEGIN {
  print "score", "tier", "host", "url", "status", "title", "server", "cdn", "words", "tech", "signals", "reg"
}

# ── pass 1: interactivity probe ───────────────────────────────────────────────
FILENAME ~ /regprobe/ {
  if (FNR == 1) next
  regkind[$1] = $2; regurl[$1] = $3
  next
}

# ── pass 2: browser observations ──────────────────────────────────────────────
FILENAME ~ /browser/ {
  if (FNR == 1) next
  bfinal[$1] = $2; btitle[$1] = $3; bstatus[$1] = $4
  bforms[$1] = $5 + 0; bpw[$1] = $6 + 0
  bjs[$1] = $8 + 0; bfw[$1] = $9; btext[$1] = $11
  bf = $2
  sub(/^https?:\/\//, "", bf); sub(/\/.*/, "", bf); sub(/:.*/, "", bf)
  if (bf != "-" && bf != $1) boff[$1] = 1
  next
}

{
  host = tolower($1); url = $2; st = $3 + 0; clen = $4 + 0; words = $5 + 0
  title = $6; server = $7; cdn = $8; tech = $9

  # Prefer the rendered title from the browser. httpx sees the pre-JS shell,
  # which is where most SPAs show an empty title.
  if (!boff[host] && btitle[host] != "" && btitle[host] != "-") title = btitle[host]
  lt = tolower(title); ls = tolower(server); lc = tolower(tech); lh = tolower(host)

  score = 0; sig = ""

  # ── subdomain keywords ─────────────────────────────────────────────────────
  # Only labels left of the registrable domain are meaningful. Otherwise a
  # domain like demo.test scores for "demo" and "test" on every host.
  nlab = split(lh, lab, ".")
  apex = 2
  if (nlab >= 3 && (lab[nlab-1] "." lab[nlab]) ~ /^(com|net|org|edu|gov|idv)\.(hk|cn|tw|au|uk|sg|jp|my|id|ph|vn|th|br|in)$/) apex = 3
  limit = nlab - apex
  if (limit < 1) limit = 0
  kw = ""
  for (i = 1; i <= limit; i++) {
    l = lab[i]
    if (l ~ /^(admin|administrator|adm)/) kw = kw " admin"
    if (l ~ /^(api|apis)([-._0-9]|$)/) kw = kw " api"
    if (l ~ /^(staging|stage|stg)([-._0-9]|$)/) kw = kw " staging"
    if (l ~ /^(dev|develop|developer)([-._0-9]|$)/) kw = kw " dev"
    if (l ~ /^(test|testing|qa|uat)([-._0-9]|$)/) kw = kw " test"
    if (l ~ /^(internal|intranet|corp)([-._0-9]|$)/) kw = kw " internal"
    if (l ~ /^(vpn|remote|citrix)([-._0-9]|$)/) kw = kw " vpn"
    if (l ~ /^(login|auth|sso|oauth)([-._0-9]|$)/) kw = kw " auth"
    if (l ~ /^(portal|dashboard|panel|analytics|console|ops|bi|manage)([-._0-9]|$)/) kw = kw " portal"
    if (l ~ /^(jenkins|jira|confluence|gitlab|github|bitbucket)/) kw = kw " devops"
    if (l ~ /^(grafana|kibana|elastic|splunk|datadog)/) kw = kw " monitoring"
    if (l ~ /^(sonarqube|nexus|artifactory)/) kw = kw " artifacts"
    if (l ~ /^(mail|smtp|webmail|exchange)/) kw = kw " mail"
    if (l ~ /^(ftp|sftp|upload)/) kw = kw " upload"
    if (l ~ /^(backup|bak|old|legacy)/) kw = kw " legacy"
    if (l ~ /^(beta|preview|demo|sandbox)/) kw = kw " beta"
    if (l ~ /^(payment|payments|pay|checkout|billing)/) kw = kw " payments"
    if (l ~ /^(cdn|assets|static|media|files)/) kw = kw " static"
    if (l ~ /^(docs|documentation|wiki)/) kw = kw " docs"
    if (l ~ /^(help|support|status)/) kw = kw " support"
  }
  if (kw ~ /admin/)      score += 30
  if (kw ~ / api/)       score += 25
  if (kw ~ / staging/)   score += 25
  if (kw ~ / dev/)       score += 25
  if (kw ~ / test/)      score += 20
  if (kw ~ / internal/)  score += 25
  if (kw ~ / vpn/)       score += 20
  if (kw ~ / auth/)      score += 25
  if (kw ~ / portal/)    score += 20
  if (kw ~ / devops/)    score += 30
  if (kw ~ / monitoring/)score += 28
  if (kw ~ / artifacts/) score += 28
  if (kw ~ / mail/)      score += 15
  if (kw ~ / upload/)    score += 20
  if (kw ~ / legacy/)    score += 22
  if (kw ~ / beta/)      score += 18
  if (kw ~ / payments/)  score += 25
  if (kw ~ / static/)    score += 5
  if (kw ~ / docs/)      score += 8
  if (kw ~ / support/)   score += 5

  # ── status ─────────────────────────────────────────────────────────────────
  if (st == 200)      { score += 10; sig = sig " status-200" }
  else if (st == 301 || st == 302) { score += 5;  sig = sig " redirect" }
  else if (st == 401) { score += 20; sig = sig " status-401" }
  else if (st == 403) { score += 18; sig = sig " status-403" }
  else if (st == 404) { score -= 5;  sig = sig " status-404" }
  else if (st == 500) { score += 15; sig = sig " status-500" }
  else if (st == 503) { score += 5;  sig = sig " status-503" }

  # ── CDN / origin exposure ───────────────────────────────────────────────────
  if (cdn == "") { score += 15; sig = sig " no-cdn" } else { score -= 5; sig = sig " cdn:" cdn }

  # ── server / tech ──────────────────────────────────────────────────────────
  sp = 0
  if (server == "") sp = 5
  if (server ~ /[0-9]+\.[0-9]+/) sp = 10
  if (ls ~ /iis/) sp = (sp > 8 ? sp : 8)
  if (ls ~ /apache/) sp = (sp > 5 ? sp : 5)
  if (ls ~ /express|node/) sp = (sp > 8 ? sp : 8)
  if (ls ~ /werkzeug/) sp = 12
  if (ls ~ /jetty|tomcat/) sp = (sp > 10 ? sp : 10)
  score += sp
  if (server ~ /[0-9]+\.[0-9]+/) sig = sig " versioned-server"

  # ── title ──────────────────────────────────────────────────────────────────
  tp = 0
  if (lt ~ /index of|directory listing/) tp = 35
  if (lt ~ /swagger|openapi|redoc|api docs/) tp = (tp > 25 ? tp : 25)
  if (lt ~ /jenkins|gitlab|grafana|kibana|jira/) tp = (tp > 30 ? tp : 30)
  if (lt ~ /dashboard|admin|panel|console/) tp = (tp > 20 ? tp : 20)
  if (lt ~ /login|sign in|sign-in|登入|登录/) tp = (tp > 15 ? tp : 15)
  if (lt ~ /error|exception|debug|stack trace/) tp = (tp > 20 ? tp : 20)
  if (lt == "" || lt ~ /forbidden/) tp = (tp > 5 ? tp : 5)
  score += tp
  if (lt ~ /login|sign in|登入/) sig = sig " title-login"
  if (lt ~ /dashboard|admin|panel/) sig = sig " title-portal"
  if (lt ~ /swagger|openapi|redoc/) sig = sig " api-docs"
  if (lt ~ /index of|directory listing/) sig = sig " directory-listing"

  # ── size ───────────────────────────────────────────────────────────────────
  if (words == 0) score -= 5
  else if (words <= 20) { score += 5; sig = sig " sparse" }
  else if (words > 500) { score += 8; sig = sig " rich-page" }

  # ── browser evidence ───────────────────────────────────────────────────────
  if (bfw[host] != "" && bfw[host] != "-") { score += 10; sig = sig " browser-" bfw[host] }
  if (bpw[host] > 0) sig = sig " browser-login-form"
  if ((btext[host] == "-" || btext[host] == "") && bjs[host] > 2) sig = sig " browser-js-only"
  if (boff[host]) sig = sig " offsite-redirect"
  if (boff[host] && tolower(btitle[host]) ~ /sign in|log in|登入|登录/) {
    score += 15; sig = sig " browser-sso-login"
  }

  # ── interactivity (highest weight) ─────────────────────────────────────────
  rk = regkind[host]
  if (rk == "" && bpw[host] > 0) rk = "login"
  if (rk == "registration") { score += 50; sig = sig " registration-open" }
  else if (rk == "login")   { score += 20; sig = sig " login-only" }

  if (score < 0) score = 0

  portal = (kw ~ /admin|portal|internal|support/) || (lt ~ /admin|dashboard|analytics|portal|console|support|panel|管理|後台/)
  authlike = (st == 401 || st == 403) || (kw ~ / auth/) || (kw ~ / api/)

  if (rk == "registration")  tier = 0
  else if (portal || score >= 70) tier = 1
  else if (authlike || rk == "login" || score >= 45) tier = 2
  else if (score >= 20) tier = 3
  else tier = 4

  gsub(/^ +/, "", sig)
  if (title == "")  title  = "-"
  if (server == "") server = "-"
  if (cdn == "")    cdn    = "-"
  if (tech == "")   tech   = "-"
  if (sig == "")    sig    = "-"
  if (rk == "")     rk     = "-"
  printf "%d\t%d\t%s\t%s\t%d\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n", \
    score, tier, host, url, st, title, server, cdn, words, tech, sig, rk
}
' "$REG" "$BROWSER" "$WORK" > "$OUT"

# Sort: tier ascending, score descending (header stays first).
{ head -n1 "$OUT"; tail -n +2 "$OUT" | sort -t$'\t' -k2,2n -k1,1nr -k3,3; } > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"

recon_log "candidates: $(($(grep -c '' "$OUT") - 1))"
awk -F'\t' 'NR>1 {c[$2]++} END {printf "T0=%d T1=%d T2=%d T3=%d T4=%d\n", c[0], c[1], c[2], c[3], c[4]}' "$OUT"
awk -F'\t' 'NR>1 && $2==0 {print "  registration-open: " $3 " " $4}' "$OUT" | head -20
