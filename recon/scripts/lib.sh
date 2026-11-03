#!/usr/bin/env bash
# lib.sh — shared helpers for the local BugBounty recon skills.
# Source this file; do not execute it directly.
#
# Everything is rooted at the hackbot data root (default ~/BugBounty), so the
# skills work from any working directory.

set -euo pipefail

# ProjectDiscovery / go-installed tools are not in the default PATH on this box.
export PATH="${HOME}/go/bin:${HOME}/.pdtm/go/bin:${HOME}/.local/bin:${PATH}"

# Python tools live in the repo venv (arjun, future helpers).
_LIB_REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../.." 2>/dev/null && pwd || true)"
[[ -n "$_LIB_REPO" && -d "$_LIB_REPO/.venv/bin" ]] && export PATH="$_LIB_REPO/.venv/bin:${PATH}"

# ── paths ────────────────────────────────────────────────────────────────────

recon_root() {
  local d="${RECON_ROOT:-}"
  if [[ -n "$d" ]]; then printf '%s\n' "$d"; return 0; fi
  d="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  local probe="$d"
  while [[ "$probe" != "/" ]]; do
    if [[ -d "$probe/.hackbot" && -d "$probe/targets" ]]; then
      printf '%s\n' "$probe"
      return 0
    fi
    probe="$(dirname -- "$probe")"
  done
  printf '%s\n' "${HACKBOT_ROOT:-$HOME/BugBounty}"
}

recon_target_dir() { printf '%s/targets/%s' "$(recon_root)" "${1:?target required}"; }
recon_dir()        { printf '%s/artifacts/recon' "$(recon_target_dir "$1")"; }
recon_state()      { printf '%s/state'   "$(recon_dir "$1")"; }
recon_reports()    { printf '%s/reports' "$(recon_dir "$1")"; }

recon_now_utc() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
recon_stamp()   { date -u '+%Y%m%dT%H%M%SZ'; }

# ── logging ──────────────────────────────────────────────────────────────────

recon_log()  { printf '[*] %s\n' "$*" >&2; }
recon_warn() { printf '[!] %s\n' "$*" >&2; }
recon_die()  { printf '[x] %s\n' "$*" >&2; exit 1; }

recon_have() { command -v "$1" >/dev/null 2>&1; }

recon_require() { # command...
  local missing=() c
  for c in "$@"; do recon_have "$c" || missing+=("$c"); done
  (( ${#missing[@]} == 0 )) || recon_die "missing required tool(s): ${missing[*]} (install with pdtm/go; see .opencode/skills/recon/references/workflow.md)"
}

# ── target / scope ───────────────────────────────────────────────────────────

recon_need_target() {
  local t="$1" dir
  dir="$(recon_target_dir "$t")"
  [[ -d "$dir" ]] || recon_die "target '$t' has no directory at $dir (create it with: hackbot target add $t --scope-file scope.txt)"
  recon_have hackbot || recon_die "hackbot not found on PATH"
  hackbot target show "$t" --json >/dev/null 2>&1 \
    || recon_die "target '$t' is not registered in hackbot"
}

recon_scope_lines() { # target -> one raw scope item per line
  local t="$1"
  hackbot target show "$t" --json \
    | jq -r '.scope // ""' \
    | tr -d '\r' \
    | sed -e 's/[[:space:]]*#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
    | grep -Ev '^(|[-*=]+)$' || true
}

recon_is_ipv4() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; }

# Registrable-domain label count, with the multi-label suffixes this program set
# actually uses (HK first, then the usual suspects).
recon_apex_labels() {
  local host="$1" suffix s
  local -a multi=(
    com.hk net.hk org.hk edu.hk gov.hk idv.hk
    com.cn com.tw com.au co.uk org.uk com.sg co.jp
    com.my co.id com.ph com.vn co.th com.br co.in
  )
  for suffix in "${multi[@]}"; do
    if [[ "$host" == *".$suffix" ]]; then
      local -a parts
      IFS=. read -ra parts <<< "$suffix"
      printf '%s\n' $(( ${#parts[@]} + 1 ))
      return 0
    fi
  done
  printf '2\n'
}

recon_is_apex() {
  local host="$1"
  local -a labels
  IFS=. read -ra labels <<< "$host"
  (( ${#labels[@]} == $(recon_apex_labels "$host") ))
}

# recon_classify "<scope item>" -> "kind<TAB>value<TAB>note"
#   kind: wildcard | domain | host | ip | note
recon_classify() {
  local item host
  item="$(printf '%s' "$1" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  [[ -z "$item" ]] && { printf 'empty\t\t\n'; return 0; }

  if [[ "$item" == \*.* ]]; then
    host="${item#\*.}"; host="${host,,}"; host="${host%.}"
    printf 'wildcard\t%s\twildcard entry\n' "$host"
    return 0
  fi

  if [[ "$item" =~ ^[A-Za-z][A-Za-z0-9+.-]*:// ]]; then
    host="${item#*://}"
    host="${host%%/*}"; host="${host%%\?*}"; host="${host%%#*}"
    host="${host##*@}"        # drop userinfo
    host="${host%%:*}"        # drop port
    host="${host,,}"; host="${host%.}"
    if [[ -z "$host" ]]; then printf 'note\t%s\tunparsable URL\n' "$item"; return 0; fi
    if recon_is_ipv4 "$host"; then printf 'ip\t%s\tIP URL\n' "$host"; return 0; fi
    if recon_is_apex "$host"; then
      printf 'host\t%s\tapex URL (exact host only)\n' "$host"
    else
      printf 'host\t%s\tURL\n' "$host"
    fi
    return 0
  fi

  if [[ "$item" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}(/[0-9]{1,2})?$ ]]; then
    printf 'ip\t%s\tIP or CIDR\n' "$item"
    return 0
  fi

  host="${item,,}"; host="${host%.}"; host="${host%%:*}"
  if [[ "$host" == *.* ]]; then
    if recon_is_apex "$host"; then
      printf 'domain\t%s\tapex domain (wildcard root)\n' "$host"
    else
      printf 'host\t%s\tbare host\n' "$host"
    fi
    return 0
  fi
  printf 'note\t%s\tnot a host or URL\n' "$item"
}

# recon_build_plan <target> -> TSV: kind, value, raw item, note
recon_build_plan() {
  local t="$1" line kind value note
  while IFS= read -r line; do
    IFS=$'\t' read -r kind value note <<< "$(recon_classify "$line")"
    printf '%s\t%s\t%s\t%s\n' "$kind" "$value" "$line" "$note"
  done < <(recon_scope_lines "$t")
}

recon_ensure_layout() {
  local t="$1"
  mkdir -p \
    "$(recon_dir "$t")/scope" \
    "$(recon_dir "$t")/state" \
    "$(recon_dir "$t")/passive" \
    "$(recon_dir "$t")/live" \
    "$(recon_dir "$t")/live/jsonl" \
    "$(recon_dir "$t")/hosts" \
    "$(recon_dir "$t")/triage" \
    "$(recon_reports "$t")/wildcard" \
    "$(recon_reports "$t")/hosts" \
    "$(recon_reports "$t")/lists"
}

# ── misc ─────────────────────────────────────────────────────────────────────

recon_tool_versions() {
  local t
  for t in subfaster subfinder assetfinder github-subdomains httpx dnsx tlsx katana nuclei ffuf; do
    if recon_have "$t"; then
      printf '%s %s\n' "$t" "$("$t" -version 2>/dev/null | head -n1 | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' || echo present)"
    else
      printf '%s missing\n' "$t"
    fi
  done
}

# Normalize arbitrary tool output to bare in-scope hostnames.
# recon_norm_hosts <domain> (stdin -> stdout)
recon_norm_hosts() {
  local d="$1"
  tr -d '\r' \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's#^[a-z][a-z0-9+.-]*://##; s#/.*$##; s#^[^@/]*@##; s#:.*$##; s#^[.]+##; s#[.]+$##; s#^\*\.##' \
    | grep -E "(^|\.)${d//./\\.}$" \
    | grep -v '^$' \
    | sort -u || true
}
