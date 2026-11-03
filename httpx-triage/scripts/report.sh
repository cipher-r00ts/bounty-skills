#!/usr/bin/env bash
# report.sh — build the priority report for a target.
#
#   report.sh --target 3hk
#   report.sh --target bigco --split-threshold 250
#   report.sh --target 3hk --single          # force one report
#
# Output (priority report lives at the target root, not deep in artifacts):
#   targets/<target>/PRIORITY.md                 small scope: one full report
#                                                large scope: index + links
#   targets/<target>/priority/tier<N>.md         large scope: one file per tier
#   targets/<target>/priority/tier<N>_<NNN>.md   ...chunked when a tier is huge
#
# A scope with `--split-threshold` hosts or fewer gets a single report; above
# that, each tier is written as its own report and PRIORITY.md becomes the index.
#
# Rules enforced here: no markdown tables, at most 250 hosts per file, every
# priority file linked from PRIORITY.md.

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

TARGET="" DOMAIN="" CHUNK=250 SPLIT_THRESHOLD=250 MODE=""
while (( $# )); do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --chunk)  CHUNK="${2:-}"; shift 2 ;;
    --split-threshold) SPLIT_THRESHOLD="${2:-}"; shift 2 ;;
    --single) MODE=single; shift ;;
    --split)  MODE=split; shift ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || recon_die "--target is required"
recon_need_target "$TARGET"

TDIR="$(recon_target_dir "$TARGET")"
DIR="$(recon_dir "$TARGET")"
CAND="$DIR/triage/candidates.tsv"
REP="$(recon_reports "$TARGET")"
PRIORITY="$TDIR/PRIORITY.md"
PRIORITY_DIR="$TDIR/priority"

[[ -f "$CAND" ]] || recon_die "no triage/candidates.tsv — run triage.sh first"

rm -rf "$REP/wildcard" "$REP/lists"

SUBSET="$(mktemp)"; trap 'rm -f "$SUBSET"' EXIT
if [[ -n "$DOMAIN" ]]; then
  awk -F'\t' -v d="$DOMAIN" '
    NR==1 { print; next }
    $3 == d || substr($3, length($3) - length(d)) == "." d
  ' "$CAND" > "$SUBSET"
else
  cat "$CAND" > "$SUBSET"
fi

total=$(($(grep -c '' "$SUBSET") - 1))
(( total > 0 )) || total=0

if [[ -z "$MODE" ]]; then
  if (( total > SPLIT_THRESHOLD )); then MODE=split; else MODE=single; fi
fi

md_clean() { printf '%s' "$1" | tr -d '|\n\r' | sed -e 's/[`]//g'; }
or_none() { [[ -z "$1" || "$1" == "-" ]] && printf 'none' || printf '%s' "$1"; }

tier_label() {
  case "$1" in
    0) printf 'Tier 0 — registration open (manual hunting)' ;;
    1) printf 'Tier 1 — portals (agent-assisted recon)' ;;
    2) printf 'Tier 2 — auth and API surfaces' ;;
    3) printf 'Tier 3 — standard applications' ;;
    *) printf 'Tier 4 — low priority' ;;
  esac
}

next_step() { # tier signals
  local tier="$1" sig="$2" extra=""
  case "$sig" in
    *api-docs*) extra=" · pull the OpenAPI/Swagger spec first" ;;
    *directory-listing*) extra=" · browse the listing before fuzzing" ;;
    *registration-open*) extra=" · registration is reachable, so authenticated testing is possible" ;;
  esac
  case "$tier" in
    0) printf 'register an account, map the authenticated surface, then test BOLA/IDOR on your own objects, mass assignment, stored XSS and uploads' ;;
    1) printf 'agent recon: default creds (admin:admin, admin:password), client-side auth checks, 403 bypass, content discovery — see recon-portal' ;;
    2) printf 'auth/API surface: login flow, password-reset tokens, OAuth redirect_uri, cookie flags, endpoint authorization' ;;
    3) printf 'standard app: IDOR on numeric IDs, reflected XSS, CORS, parameter tampering' ;;
    *) printf 'low priority: skim JS bundles for endpoints, then move on' ;;
  esac
  [[ -n "$extra" ]] && printf '%s' "$extra"
  return 0
}

declare -A B_URL=() B_PW=() B_FW=() B_FORMS=() B_TEXT=()
if [[ -f "$DIR/triage/browser.tsv" ]]; then
  while IFS=$'\t' read -r bh burl btitle bstatus bforms bpw blinks bjs bfw binputs btext; do
    [[ "$bh" == "host" || -z "$bh" ]] && continue
    B_URL["$bh"]="$burl"; B_PW["$bh"]="${bpw:-0}"; B_FW["$bh"]="$bfw"
    B_FORMS["$bh"]="${bforms:-0}"; B_TEXT["$bh"]="$btext"
  done < "$DIR/triage/browser.tsv"
fi

declare -A REG_URL=() REG_EV=()
if [[ -f "$DIR/triage/regprobe.tsv" ]]; then
  while IFS=$'\t' read -r rh rk ru rs re; do
    [[ "$rh" == "host" || -z "$rh" ]] && continue
    REG_URL["$rh"]="$ru"; REG_EV["$rh"]="$re"
  done < "$DIR/triage/regprobe.tsv"
fi

render_row() { # tier line
  local tier="$1" line="$2"
  local score host url status title server cdn words tech sig reg
  IFS=$'\t' read -r score tier host url status title server cdn words tech sig reg <<< "$line"
  printf -- '- **`%s`** — score %s · status `%s`\n' "$url" "$score" "$status"
  printf '  - title: “%s” · server `%s` · cdn `%s` · words %s\n' \
    "$(md_clean "$(or_none "${title:-}")")" "$(md_clean "$(or_none "${server:-}")")" "$(md_clean "$(or_none "${cdn:-}")")" "${words:-0}"
  printf '  - signals: %s\n' "$( [[ -n "$sig" && "$sig" != "-" ]] && printf '`%s`' "$(printf '%s' "$sig" | sed 's/ /`, `/g')" || printf 'none')"
  printf '  - tech: %s\n' "$( [[ -n "$tech" && "$tech" != "-" ]] && printf '`%s`' "$(printf '%s' "$tech" | sed 's/,/`, `/g')" || printf 'none')"
  if [[ -n "${B_URL[$host]:-}" ]]; then
    local burl="${B_URL[$host]}" bhost bsum
    bhost=$(printf '%s' "$burl" | sed -E 's#^[a-z]+://##; s#/.*##; s#:.*##')
    if [[ "$bhost" != "$host" ]]; then
      bsum="redirects off-scope to ${bhost}"
    else
      (( ${#burl} > 120 )) && burl="${burl:0:117}..."
      bsum="rendered: ${burl}"
    fi
    [[ "${B_FORMS[$host]}" != "0" ]] && bsum+=" · ${B_FORMS[$host]} form(s)"
    [[ "${B_PW[$host]}" != "0" ]] && bsum+=" · ${B_PW[$host]} password field(s)"
    [[ "${B_FW[$host]}" != "-" && -n "${B_FW[$host]}" ]] && bsum+=" · ${B_FW[$host]} app"
    printf '  - browser: %s\n' "$(md_clean "$bsum")"
  fi
  if (( tier <= 1 )) && [[ -n "${B_TEXT[$host]:-}" && "${B_TEXT[$host]}" != "-" ]]; then
    printf '  - page text: “%s…”\n' "$(md_clean "${B_TEXT[$host]:0:140}")"
  fi
  if [[ -n "${REG_URL[$host]:-}" ]]; then
    if [[ "$reg" == "registration" ]]; then
      printf '  - registration evidence: `%s` — %s\n' "${REG_URL[$host]}" "$(md_clean "${REG_EV[$host]:-}")"
    else
      printf '  - login evidence: `%s` — %s\n' "${REG_URL[$host]}" "$(md_clean "${REG_EV[$host]:-}")"
    fi
  fi
  printf '  - next: %s\n' "$(next_step "$tier" "$sig")"
}

tier_counts() {
  awk -F'\t' 'NR>1{c[$2]++} END{printf "T0 %d · T1 %d · T2 %d · T3 %d · T4 %d", c[0], c[1], c[2], c[3], c[4]}' "$SUBSET"
}

header_common() {
  printf -- '- Target: `%s`\n' "$TARGET"
  printf -- '- Generated: %s\n' "$(recon_now_utc)"
  printf -- '- Hosts: %s\n' "$total"
  printf -- '- Tiers: %s\n' "$(tier_counts)"
}

how_to() {
  printf '## How to use this report\n\n'
  printf -- '- Tier 0 is the manual queue: registration is reachable, so you can get a session and test authenticated behaviour.\n'
  printf -- '- Tier 1 is the agent queue: portals without registration. Start with `recon-portal` (403 bypass, CORS, client-side auth, one default-credential attempt per pair).\n'
  printf -- '- Tiers 2–4 are ordered by evidence, not by confirmed risk. Work down only after the two queues above.\n'
  printf -- '- Every host in this report appears exactly once, in its tier section.\n'
  printf -- '- Tiers are investigation priority, not confirmed vulnerabilities. Nothing here is a bug until you reproduce it.\n\n'
}

# ── single report: everything in one file ────────────────────────────────────

write_single() {
  {
    printf '# Priority report — %s\n\n' "$TARGET"
    header_common
    printf -- '- Mode: single report (%s hosts, split threshold %s)\n' "$total" "$SPLIT_THRESHOLD"
    printf -- '- Raw data: `artifacts/recon/live/httpx.jsonl`, `artifacts/recon/triage/candidates.tsv`\n\n'
    how_to
    for tier in 0 1 2 3 4; do
      mapfile -t rows < <(awk -F'\t' -v t="$tier" 'NR>1 && $2==t' "$SUBSET")
      printf '## %s\n\n' "$(tier_label "$tier")"
      if (( ${#rows[@]} == 0 )); then
        printf -- '- none\n\n'
        continue
      fi
      printf -- '- Hosts: %d\n\n' "${#rows[@]}"
      for line in "${rows[@]}"; do
        render_row "$tier" "$line"
      done
      printf '\n'
    done
  } > "$PRIORITY"
  rm -rf "$PRIORITY_DIR"
}

# ── split report: index + one file per tier ──────────────────────────────────

write_split() {
  rm -rf "$PRIORITY_DIR"
  mkdir -p "$PRIORITY_DIR"
  local -a LINKS=()
  local tier rows n parts p start file

  for tier in 0 1 2 3 4; do
    mapfile -t rows < <(awk -F'\t' -v t="$tier" 'NR>1 && $2==t' "$SUBSET")
    n=${#rows[@]}
    if (( n == 0 )); then
      LINKS+=("$tier|0|")
      continue
    fi
    parts=$(( (n + CHUNK - 1) / CHUNK ))
    for (( p = 0; p < parts; p++ )); do
      start=$(( p * CHUNK ))
      if (( parts == 1 )); then
        file="tier${tier}.md"
      else
        file=$(printf 'tier%d_%03d.md' "$tier" "$((p + 1))")
      fi
      {
        printf '# %s' "$(tier_label "$tier")"
        (( parts > 1 )) && printf ' — part %d of %d' "$((p + 1))" "$parts"
        printf '\n\n'
        printf -- '- Target: `%s`\n- Generated: %s\n' "$TARGET" "$(recon_now_utc)"
        printf -- '- Hosts in this file: %d of %d\n' "$(( n - start < CHUNK ? n - start : CHUNK ))" "$n"
        printf -- '- Tiers are investigation priority, not confirmed vulnerabilities.\n\n'
        for (( i = start; i < start + CHUNK && i < n; i++ )); do
          render_row "$tier" "${rows[$i]}"
        done
      } > "$PRIORITY_DIR/$file"
      LINKS+=("$tier|$n|$file")
    done
  done

  {
    printf '# Priority report — %s\n\n' "$TARGET"
    header_common
    printf -- '- Mode: split report (%s hosts, threshold %s)\n' "$total" "$SPLIT_THRESHOLD"
    printf -- '- Raw data: `artifacts/recon/live/httpx.jsonl`, `artifacts/recon/triage/candidates.tsv`\n\n'
    how_to

    printf '## Reports by tier\n\n'
    for entry in "${LINKS[@]}"; do
      IFS='|' read -r tier n file <<< "$entry"
      if (( n == 0 )); then
        printf -- '- %s — 0 hosts\n' "$(tier_label "$tier")"
      else
        printf -- '- [%s](priority/%s) — %d host(s)\n' "$(tier_label "$tier")" "$file" "$n"
      fi
    done
    printf '\n'

    printf '## Top picks\n\n'
    local picks=0
    while IFS=$'\t' read -r score tier host url status title rest; do
      (( picks >= 10 )) && break
      printf -- '- `%s` — tier %s · score %s · status `%s` · %s\n' "$url" "$tier" "$score" "$status" "$(md_clean "${title:--}")"
      picks=$((picks + 1))
    done < <(awk -F'\t' 'NR>1 && ($2==0 || $2==1)' "$SUBSET")
    (( picks == 0 )) && printf -- '- no tier 0 or tier 1 hosts\n'
    printf '\n'

    printf '## Notes\n\n'
    printf -- '- Status mix: %s\n' "$(awk -F'\t' 'NR>1{c[$5]++} END{for (k in c) printf "%s ×%d · ", k, c[k]}' "$SUBSET" | sed 's/ · $//')"
    printf -- '- CDN-fronted hosts: %s of %s\n' "$(awk -F'\t' 'NR>1 && $8 != "-" && $8 != ""' "$SUBSET" | grep -c '' || true)" "$total"
    printf -- '- Registration reachable: %s · login-only: %s\n' \
      "$(awk -F'\t' 'NR>1 && $12 == "registration"' "$SUBSET" | grep -c '' || true)" \
      "$(awk -F'\t' 'NR>1 && $12 == "login"' "$SUBSET" | grep -c '' || true)"
    printf -- '- Most common tech: %s\n' "$(awk -F'\t' 'NR>1 && $10 != "-" {split($10,a,","); for (i in a) if (a[i] != "") t[a[i]]++} END{for (k in t) print t[k], k}' "$SUBSET" | sort -rn | head -3 | awk '{c=$1; $1=""; sub(/^ /,""); printf "%s ×%s · ", $0, c}' | sed 's/ · $//')"
  } > "$PRIORITY"
}

# ── handoff for the single-host skill ────────────────────────────────────────

HO="$DIR/state/handoff"
mkdir -p "$HO"
awk -F'\t' 'NR>1 && $2 <= 2 {print $3}' "$CAND" | sort -u > "$HO/hosts.txt"

"$SELF_DIR/../../recon/scripts/recon.sh" index --target "$TARGET" >/dev/null

if [[ "$MODE" == "split" ]]; then
  write_split
  recon_log "priority:   $PRIORITY (index)"
  recon_log "tiers:      $PRIORITY_DIR/"
else
  write_single
  recon_log "priority:   $PRIORITY"
fi
recon_log "handoff:    $HO/hosts.txt"
