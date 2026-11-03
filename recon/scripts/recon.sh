#!/usr/bin/env bash
# recon.sh — entry point for the local recon skills.
#
#   recon.sh init   --target T [--scope-file F | --scope S]
#   recon.sh plan   --target T [--json]
#   recon.sh index  --target T
#   recon.sh status --target T
#
# `init` is idempotent: it never deletes recon output, it only creates the
# layout, snapshots the scope, and (re)writes the plan.

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SELF_DIR/lib.sh"

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

TARGET="" SCOPE_FILE="" SCOPE_ARG="" JSON=0 WRITE=0
CMD="${1:-}"
[[ -n "$CMD" ]] || usage 1
shift || true

while (( $# )); do
  case "$1" in
    --target)     TARGET="${2:-}"; shift 2 ;;
    --scope-file) SCOPE_FILE="${2:-}"; shift 2 ;;
    --scope)      SCOPE_ARG="${2:-}"; shift 2 ;;
    --json)       JSON=1; shift ;;
    --write)      WRITE=1; shift ;;
    -h|--help)    usage 0 ;;
    *)            recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || recon_die "--target is required"

# ── scope snapshot ───────────────────────────────────────────────────────────

write_scope_snapshot() {
  local t="$1" out
  out="$(recon_dir "$t")/scope/scope.txt"
  mkdir -p "$(dirname "$out")"
  {
    printf '# scope snapshot for %s — %s\n' "$t" "$(recon_now_utc)"
    if [[ -n "$SCOPE_FILE" ]]; then
      cat "$SCOPE_FILE"
    elif [[ -n "$SCOPE_ARG" ]]; then
      printf '%s\n' "$SCOPE_ARG"
    else
      recon_scope_lines "$t"
    fi
  } > "$out"
  printf '%s\n' "$out"
}

# ── plan ─────────────────────────────────────────────────────────────────────

plan_tsv() {
  local t="$1" snapshot
  snapshot="$(recon_dir "$t")/scope/scope.txt"
  if [[ -f "$snapshot" ]]; then
    local line kind value note
    while IFS= read -r line; do
      [[ "$line" =~ ^# ]] && continue
      [[ -z "${line//[[:space:]]/}" ]] && continue
      IFS=$'\t' read -r kind value note <<< "$(recon_classify "$line")"
      printf '%s\t%s\t%s\t%s\n' "$kind" "$value" "$line" "$note"
    done < "$snapshot"
  else
    recon_build_plan "$t"
  fi
}

render_plan_md() {
  local t="$1" tsv total wild domain host ip note
  tsv="$(plan_tsv "$t")"
  total=$(grep -c '' <<< "$tsv" || true)
  wild=$(grep -c '^wildcard' <<< "$tsv" || true)
  domain=$(grep -c '^domain' <<< "$tsv" || true)
  host=$(grep -c '^host' <<< "$tsv" || true)
  ip=$(grep -c '^ip' <<< "$tsv" || true)
  note=$(grep -c '^note' <<< "$tsv" || true)

  printf '# Recon plan — %s\n\n' "$t"
  printf -- '- Generated: %s\n' "$(recon_now_utc)"
  printf -- '- Target directory: `targets/%s`\n' "$t"
  printf -- '- Recon root: `targets/%s/artifacts/recon`\n' "$t"
  printf -- '- Scope items: %s (wildcard %s · domain root %s · host %s · IP %s · ignored %s)\n\n' \
    "$total" "$wild" "$domain" "$host" "$ip" "$note"

  if (( wild == 0 && domain == 0 && host == 0 )); then
    printf '> No actionable scope entries were found. Fix the target scope first:\n'
    printf '> `hackbot target update %s --scope-file scope.txt`\n\n' "$t"
  fi

  if (( wild > 0 )); then
    printf '## Wildcard entries — recon-wildcard\n\n'
    while IFS=$'\t' read -r kind value raw extra; do
      [[ "$kind" == "wildcard" ]] || continue
      printf -- '- `%s` — %s\n' "$raw" "$extra"
      printf '  - enumerate: `.opencode/skills/recon-wildcard/scripts/enum.sh --target %s --domain %s`\n' "$t" "$value"
    done <<< "$tsv"
    printf '\n'
  fi

  if (( domain > 0 )); then
    printf '## Apex domains — recon-wildcard (subdomains + apex)\n\n'
    while IFS=$'\t' read -r kind value raw extra; do
      [[ "$kind" == "domain" ]] || continue
      printf -- '- `%s` — %s\n' "$raw" "$extra"
      printf '  - enumerate: `.opencode/skills/recon-wildcard/scripts/enum.sh --target %s --domain %s --include-apex`\n' "$t" "$value"
    done <<< "$tsv"
    printf '\n'
  fi

  if (( host > 0 )); then
    printf '## Single hosts — recon-single-host\n\n'
    while IFS=$'\t' read -r kind value raw extra; do
      [[ "$kind" == "host" ]] || continue
      printf -- '- `%s` — %s\n' "$value" "$extra"
      printf '  - run: `.opencode/skills/recon-single-host/scripts/host-recon.sh --target %s --host %s`\n' "$t" "$value"
    done <<< "$tsv"
    printf '\n'
  fi

  if (( ip > 0 )); then
    printf '## IP / CIDR — not automated\n\n'
    printf 'These entries are recorded but no local skill covers IP space. Handle them manually.\n\n'
    while IFS=$'\t' read -r kind value raw extra; do
      [[ "$kind" == "ip" ]] || continue
      printf -- '- `%s` — %s\n' "$raw" "$extra"
    done <<< "$tsv"
    printf '\n'
  fi

  if (( note > 0 )); then
    printf '## Ignored scope lines\n\n'
    while IFS=$'\t' read -r kind value raw extra; do
      [[ "$kind" == "note" ]] || continue
      printf -- '- `%s` — %s\n' "$raw" "$extra"
    done <<< "$tsv"
    printf '\n'
  fi

  printf '## Pipeline\n\n'
  printf '1. Enumerate each wildcard/domain root and stream new hosts into httpx (`recon-wildcard`).\n'
  printf '2. Score live hosts and split them into registration-open and portal lists (`httpx-triage`).\n'
  printf '3. Run host-level recon on winners (`recon-single-host`).\n'
  printf '4. Probe portals with the agent workflow (`recon-portal`).\n'
  printf '5. Rebuild the report index (`recon.sh index --target %s`) and lint it (`report-lint.sh`).\n' "$t"
}

cmd_plan() {
  local t="$1"
  if (( JSON )); then
    plan_tsv "$t" | jq -Rn '
      [inputs
       | split("\t")
       | {kind: (.[0] // ""), value: (.[1] // ""), item: (.[2] // ""), note: (.[3] // "")}]
      | map(. + {handler: (
          if .kind == "wildcard" then "recon-wildcard"
          elif .kind == "domain" then "recon-wildcard"
          elif .kind == "host" then "recon-single-host"
          else "manual" end)})
    '
  else
    render_plan_md "$t"
  fi
}

cmd_init() {
  local t="$1" snap
  recon_need_target "$t"
  recon_ensure_layout "$t"
  snap="$(write_scope_snapshot "$t")"
  recon_log "scope snapshot: $snap"

  plan_tsv "$t" | jq -Rn '
    [inputs | split("\t") | {kind: (.[0] // ""), value: (.[1] // ""), item: (.[2] // ""), note: (.[3] // "")}]
  ' > "$(recon_state "$t")/plan.json"

  {
    printf '# Scope snapshot\n\n- Taken: %s\n- Source: `%s`\n' "$(recon_now_utc)" "$snap"
    printf '\n```text\n'
    grep -v '^#' "$snap" | sed '/^[[:space:]]*$/d'
    printf '\n```\n'
  } > "$(recon_state "$t")/scope.md"

  render_plan_md "$t" > "$(recon_state "$t")/plan.md"
  recon_log "plan: $(recon_state "$t")/plan.md"
  cmd_plan "$t"
}

# ── index ────────────────────────────────────────────────────────────────────

cmd_index() {
  local t="$1" rep rel dir file
  rep="$(recon_reports "$t")"
  mkdir -p "$rep"
  [[ -d "$rep" ]] || recon_die "no reports directory for '$t'"

  {
    printf '# Recon reports — %s\n\n' "$t"
    printf -- '- Generated: %s\n' "$(recon_now_utc)"
    printf -- '- Target: `%s`\n' "$t"
    printf -- '- Recon root: `targets/%s/artifacts/recon`\n' "$t"
    printf -- '- Report root: `artifacts/recon/reports`\n\n'
    printf 'Every report below is table-free by design. Large tiers are split into numbered parts; this index links all of them.\n\n'

    local sections=("wildcard" "hosts" "lists")
    for dir in "${sections[@]}"; do
      [[ -d "$rep/$dir" ]] || continue
      case "$dir" in
        wildcard) printf '## Wildcard and domain reports\n\n' ;;
        hosts)    printf '## Per-host reports\n\n' ;;
        lists)    printf '## Action lists\n\n' ;;
      esac
      while IFS= read -r file; do
        rel="${file#"$rep"/}"
        [[ "$rel" == "index.md" ]] && continue
        printf -- '- [%s](%s)\n' "$rel" "$rel"
      done < <(find "$rep/$dir" -type f -name '*.md' | sort)
      printf '\n'
    done

    if [[ -f "$(recon_target_dir "$t")/PRIORITY.md" ]]; then
      printf '## Priority\n\n'
      printf -- '- [PRIORITY.md](../../../PRIORITY.md) — the report to read first\n\n'
    fi

    printf '## Scope\n\n'
    if [[ -f "$(recon_dir "$t")/state/plan.md" ]]; then
      printf -- '- [Recon plan](../state/plan.md)\n'
      printf -- '- [Scope snapshot](../state/scope.md)\n'
    fi
  } > "$rep/index.md"

  recon_log "index: $rep/index.md"
}

# ── status ───────────────────────────────────────────────────────────────────

cmd_status() {
  local t="$1" d
  d="$(recon_dir "$t")"
  printf 'Target: %s\n' "$t"
  printf 'Recon root: %s\n' "$d"
  printf 'Scope items: %s\n' "$(plan_tsv "$t" | grep -c '' || true)"

  if [[ -d "$d/passive" ]] && find "$d/passive" -maxdepth 1 -type f -name '*.txt' | grep -q .; then
    printf 'Domains enumerated:\n'
    find "$d/passive" -maxdepth 1 -type f -name '*.txt' -printf '  %f\n' 2>/dev/null | sort || true
  fi

  [[ -f "$d/live/httpx.txt" ]] && printf 'Live httpx lines: %s\n' "$(grep -c '' "$d/live/httpx.txt" || true)"
  [[ -f "$d/triage/candidates.tsv" ]] && printf 'Triage candidates: %s\n' "$(($(grep -c '' "$d/triage/candidates.tsv" || true) - 1))"
  [[ -f "$d/triage/candidates.tsv" ]] && printf 'Tier counts: %s\n' \
    "$(awk -F'\t' 'NR>1{c[$2]++} END{for (k in c) printf "T%s=%s ", k, c[k]}' "$d/triage/candidates.tsv" | tr ' ' '\n' | sed '/^$/d' | sort | tr '\n' ' ')"
  [[ -f "$d/triage/regprobe.tsv" ]] && printf 'Registration probes: %s\n' "$(($(grep -c '' "$d/triage/regprobe.tsv" || true) - 1))"
  [[ -f "$d/triage/browser.tsv" ]] && printf 'Browser-probed hosts: %s\n' "$(($(grep -c '' "$d/triage/browser.tsv" || true) - 1))"
  if [[ -f "$(recon_target_dir "$t")/PRIORITY.md" ]]; then
    printf 'Priority report: %s\n' "$(recon_target_dir "$t")/PRIORITY.md"
    if [[ -d "$(recon_target_dir "$t")/priority" ]]; then
      printf 'Priority parts: %s file(s)\n' "$(find "$(recon_target_dir "$t")/priority" -type f -name '*.md' | grep -c '' || true)"
    fi
  fi
  return 0
}

case "$CMD" in
  init)   cmd_init "$TARGET" ;;
  plan)   cmd_plan "$TARGET" ;;
  index)  cmd_index "$TARGET" ;;
  status) cmd_status "$TARGET" ;;
  *)      usage 1 ;;
esac
