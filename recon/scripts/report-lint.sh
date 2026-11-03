#!/usr/bin/env bash
# report-lint.sh — enforce the report contract for a target.
#
#   report-lint.sh --target 3hk
#
# Checks both report trees:
#   targets/<target>/PRIORITY.md + targets/<target>/priority/*.md
#   targets/<target>/artifacts/recon/reports/**
#
# Fails on markdown tables (a pipe outside a fenced code block), broken relative
# links, reports missing from their index, and unreasonably large files.

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SELF_DIR/lib.sh"

TARGET=""
while (( $# )); do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) recon_die "unknown argument: $1" ;;
  esac
done

[[ -n "$TARGET" ]] || recon_die "--target is required"
TDIR="$(recon_target_dir "$TARGET")"
REP="$(recon_dir "$TARGET")/reports"
[[ -d "$REP" ]] || recon_die "no reports directory: $REP"
INDEX="$REP/index.md"
[[ -f "$INDEX" ]] || recon_die "missing $INDEX (run recon.sh index --target $TARGET)"

PRIORITY="$TDIR/PRIORITY.md"
errors=0
warnings=0
checked=0

check_file() { # file, label, index-file-for-coverage, rel-in-index
  local f="$1" rel="$2" idx="$3" linkrel="$4" piped
  checked=$((checked + 1))

  piped=$(awk '
    BEGIN { fence = 0 }
    /^[[:space:]]*```/ { fence = !fence; next }
    !fence && index($0, "|") { printf "%d: %s\n", NR, $0 }
  ' "$f")
  if [[ -n "$piped" ]]; then
    printf 'TABLE in %s\n%s\n' "$rel" "$piped"
    errors=$((errors + 1))
  fi

  while IFS= read -r link; do
    [[ -z "$link" ]] && continue
    [[ "$link" =~ ^(https?:|mailto:|#) ]] && continue
    target="${link%%#*}"
    target="${target%%\?*}"
    [[ -z "$target" ]] && continue
    if [[ ! -e "$(dirname "$f")/$target" ]]; then
      printf 'BROKEN LINK in %s -> %s\n' "$rel" "$link"
      errors=$((errors + 1))
    fi
  done < <(grep -Eo '\]\([^)]+\)' "$f" | sed -e 's/^](//' -e 's/)$//' || true)

  if [[ -n "$idx" && -n "$linkrel" ]]; then
    if [[ -f "$idx" ]] && ! grep -qF "]($linkrel)" "$idx"; then
      printf 'UNLINKED report (not in %s): %s\n' "$(basename "$idx")" "$rel"
      errors=$((errors + 1))
    fi
  fi

  local size
  size=$(stat -c %s "$f")
  if (( size > 307200 )); then
    printf 'LARGE report (%.0f KB): %s — split it further\n' "$(awk -v s="$size" 'BEGIN{print s/1024}')" "$rel"
    warnings=$((warnings + 1))
  fi

  if [[ ! -s "$f" ]]; then
    printf 'EMPTY report: %s\n' "$rel"
    warnings=$((warnings + 1))
  fi
}

# ── detailed reports (hosts, etc.) ───────────────────────────────────────────

while IFS= read -r f; do
  rel="${f#"$REP"/}"
  if [[ "$rel" == "index.md" ]]; then
    check_file "$f" "$rel" "" ""
  else
    check_file "$f" "$rel" "$INDEX" "$rel"
  fi
done < <(find "$REP" -type f -name '*.md' | sort)

# ── priority report (target root) ────────────────────────────────────────────

if [[ -f "$PRIORITY" ]]; then
  check_file "$PRIORITY" "PRIORITY.md" "" ""
  if [[ -d "$TDIR/priority" ]]; then
    while IFS= read -r f; do
      rel="priority/${f##*/}"
      check_file "$f" "$rel" "$PRIORITY" "$rel"
    done < <(find "$TDIR/priority" -type f -name '*.md' | sort)
  fi
else
  printf 'MISSING priority report: %s (run report.sh --target %s)\n' "$PRIORITY" "$TARGET"
  warnings=$((warnings + 1))
fi

printf 'checked %d report(s): %d error(s), %d warning(s)\n' "$checked" "$errors" "$warnings"
(( errors == 0 ))
