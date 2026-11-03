#!/usr/bin/env bash
# enum.sh — incremental passive subdomain enumeration for one wildcard/domain root.
#
# Runs, in order: subfaster → subfinder → assetfinder → github-subdomains
# (optionally crt.sh). After every tool the new hosts are diffed against
# everything already seen and only that diff is sent to httpx (hx-append.sh),
# so the HTTP stage starts producing results immediately instead of waiting
# for all sources to finish.
#
#   enum.sh --target 3hk --domain three.com.hk
#   enum.sh --target 3hk --domain simworld.net --include-apex --with-crtsh
#
# Options: --tools a,b,c --with-crtsh --include-apex --no-http
#          --rate 200 --threads 100 --timeout 10 --source-timeout 900
#          --triage [--browse-limit 60] [--regprobe-limit 100]
#
# --triage runs the full priority pipeline after enumeration: triage, a real
# browser pass over the top candidates, the registration probe, re-triage, and
# the target-root PRIORITY.md report.
#
# State (resumable, safe to re-run):
#   artifacts/recon/state/<domain>/seen.txt
#   artifacts/recon/state/<domain>/batches/<n>-<tool>.new.txt
#   artifacts/recon/state/<domain>/summary.tsv

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

TARGET="" DOMAIN="" TOOLS="subfaster,subfinder,assetfinder,github"
WITH_CRTSH=0 INCLUDE_APEX=0 HTTP=1 RATE=200 THREADS=100 TIMEOUT=10 SOURCE_TIMEOUT=900
TRIAGE=0 BROWSE_LIMIT=60 REGPROBE_LIMIT=100

while (( $# )); do
  case "$1" in
    --target)       TARGET="${2:-}"; shift 2 ;;
    --domain)       DOMAIN="${2:-}"; shift 2 ;;
    --tools)        TOOLS="${2:-}"; shift 2 ;;
    --with-crtsh)   WITH_CRTSH=1; shift ;;
    --include-apex) INCLUDE_APEX=1; shift ;;
    --no-http)      HTTP=0; shift ;;
    --rate)         RATE="${2:-}"; shift 2 ;;
    --threads)      THREADS="${2:-}"; shift 2 ;;
    --timeout)      TIMEOUT="${2:-}"; shift 2 ;;
    --source-timeout) SOURCE_TIMEOUT="${2:-}"; shift 2 ;;
    --triage)       TRIAGE=1; shift ;;
    --browse-limit) BROWSE_LIMIT="${2:-}"; shift 2 ;;
    --regprobe-limit) REGPROBE_LIMIT="${2:-}"; shift 2 ;;
    -h|--help)      sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)              recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || recon_die "--target is required"
[[ -n "$DOMAIN" ]] || recon_die "--domain is required"
recon_need_target "$TARGET"
recon_ensure_layout "$TARGET"

D="${DOMAIN,,}"; D="${D#\*.}"; D="${D%.}"
[[ "$D" == *.* ]] || recon_die "not a registrable domain: $D"

DIR="$(recon_dir "$TARGET")"
PD="$DIR/passive/$D"
SD="$DIR/state/$D"
mkdir -p "$PD" "$SD/batches"
SEEN="$SD/seen.txt"
touch "$SEEN"
SUMMARY="$SD/summary.tsv"
[[ -f "$SUMMARY" ]] || printf 'run\tsource\traw\tnew\n' > "$SUMMARY"

RUN="$(recon_stamp)"
BATCH_SEQ=0

# Tools that are missing are skipped, not fatal — the pipeline is designed to
# still produce results with whatever is installed.
tool_cmd() { # tool -> prints shell command, exit 3 when unavailable
  case "$1" in
    subfaster)
      recon_have subfaster || return 3
      printf 'subfaster -d %q -silent -all -recursive -o %q' "$D" "$2" ;;
    subfinder)
      recon_have subfinder || return 3
      printf 'subfinder -d %q -silent -all -recursive -o %q' "$D" "$2" ;;
    assetfinder)
      recon_have assetfinder || return 3
      printf 'assetfinder --subs-only %q > %q' "$D" "$2" ;;
    github)
      recon_have github-subdomains || return 3
      [[ -n "${GITHUB_TOKEN:-}" ]] || return 4
      printf 'github-subdomains -d %q -o %q' "$D" "$2" ;;
    crtsh)
      recon_have curl || return 3
      recon_have jq || return 3
      printf 'curl -fsSL --max-time 60 -A recon-skill %q | jq -r %q > %q' \
        "https://crt.sh/?q=%25.$D&output=json" '.[].name_value // empty' "$2" ;;
    *) return 2 ;;
  esac
}

run_tool() { # tool -> 0 ran, 1 skipped
  local tool="$1" raw="$PD/$1.raw.txt" norm="$PD/$1.txt" cmd rc new_count raw_count

  cmd="$(tool_cmd "$tool" "$raw")"
  local trc=$?
  if (( trc != 0 )); then
    case $trc in
      4) recon_warn "$tool: GITHUB_TOKEN is not set — skipping (export it to enable this source)" ;;
      3) recon_warn "$tool: not installed — skipping" ;;
      *) recon_warn "$tool: not supported — skipping" ;;
    esac
    return 1
  fi

  rm -f "$raw"
  recon_log "running $tool on $D"
  local rc=0
  if recon_have timeout; then
    timeout "$SOURCE_TIMEOUT" bash -c "$cmd" || rc=$?
  else
    eval "$cmd" || rc=$?
  fi
  if (( rc == 124 )); then
    recon_warn "$tool: timed out after ${SOURCE_TIMEOUT}s — keeping partial output (raise with --source-timeout, or narrow --tools)"
  elif (( rc != 0 )); then
    recon_warn "$tool: exited $rc — keeping partial output"
  fi
  [[ -f "$raw" ]] || : > "$raw"

  recon_norm_hosts "$D" < "$raw" > "$norm"

  BATCH_SEQ=$((BATCH_SEQ + 1))
  local batch
  batch="$(printf '%s/batches/%02d-%s.new.txt' "$SD" "$BATCH_SEQ" "$tool")"
  comm -23 <(LC_ALL=C sort -u "$norm") <(LC_ALL=C sort -u "$SEEN") > "$batch"

  if (( INCLUDE_APEX )) && ! grep -qxF "$D" "$SEEN"; then
    printf '%s\n' "$D" >> "$batch"
  fi
  LC_ALL=C sort -u -o "$batch" "$batch"

  new_count=$(grep -c '' "$batch" || true)
  raw_count=$(grep -c '' "$norm" || true)
  printf '%s\t%s\t%s\t%s\n' "$RUN" "$tool" "$raw_count" "$new_count" >> "$SUMMARY"

  # seen = seen ∪ norm (plus apex when requested)
  {
    cat "$SEEN"
    cat "$norm"
    if (( INCLUDE_APEX )); then printf '%s\n' "$D"; fi
  } | sed '/^[[:space:]]*$/d' | LC_ALL=C sort -u > "$SEEN.tmp"
  mv "$SEEN.tmp" "$SEEN"

  recon_log "$tool: $raw_count in-scope hosts, $new_count new"
  if (( new_count > 0 && HTTP )); then
    "$SELF_DIR/../../recon/scripts/hx-append.sh" \
      --target "$TARGET" --input "$batch" --tag "$tool" \
      --rate "$RATE" --threads "$THREADS" --timeout "$TIMEOUT"
  fi
  return 0
}

IFS=, read -ra TOOL_LIST <<< "$TOOLS"
(( WITH_CRTSH )) && TOOL_LIST+=(crtsh)

RAN=0
for tool in "${TOOL_LIST[@]}"; do
  [[ -n "$tool" ]] || continue
  if run_tool "$tool"; then RAN=$((RAN + 1)); fi
done

# Final merged passive list (all sources, deduplicated).
cp "$SEEN" "$DIR/passive/$D.txt"

recon_log "done: $(grep -c '' "$SEEN" || true) unique in-scope hosts for $D"
recon_log "merged: $DIR/passive/$D.txt"
(( RAN > 0 )) || recon_warn "no enumeration tool ran — install the toolchain (see .opencode/skills/recon/references/workflow.md)"

printf '\n'
printf 'source\traw\tnew\n'
tail -n +2 "$SUMMARY" | awk -F'\t' '{raw[$2]+=$3; new[$2]+=$4} END {for (s in raw) printf "%s\t%s\t%s\n", s, raw[s], new[s]}' | sort

if (( TRIAGE )); then
  recon_log "priority pipeline: triage -> browser pass -> registration probe -> report"
  T="$SELF_DIR/../../httpx-triage/scripts"
  "$T/triage.sh" --target "$TARGET" || recon_warn "triage failed"
  "$SELF_DIR/browser-probe.sh" --target "$TARGET" --limit "$BROWSE_LIMIT" || recon_warn "browser pass failed"
  "$T/triage.sh" --target "$TARGET" || recon_warn "triage failed"
  "$T/regprobe.sh" --target "$TARGET" --limit "$REGPROBE_LIMIT" || recon_warn "registration probe failed"
  "$T/triage.sh" --target "$TARGET" || recon_warn "triage failed"
  "$T/report.sh" --target "$TARGET" || recon_warn "report failed"
  recon_log "priority report: $(recon_target_dir "$TARGET")/PRIORITY.md"
fi
