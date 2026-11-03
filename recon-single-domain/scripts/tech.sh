#!/usr/bin/env bash
# tech.sh — technology-specific exposure checks for one host.
#
#   tech.sh --run targets/<t>/artifacts/recon/hosts/<host> --url https://<host>/ \
#     [--headers /tmp/recon-auth/<host>/headers.txt] [--rate 0.4]
#
# Read-only GETs against well-known stack paths (Spring actuator, Grafana,
# Jenkins, Tomcat, Swagger/OpenAPI, .git/.env). No exploitation, no POST.
#
# Writes: <run>/domain/checks/{tech.jsonl,tech.log}

set -euo pipefail

RUN="" URL="" HEADERS="" RATE=0.4 DRY=0
SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../recon/scripts/lib.sh
source "$SELF_DIR/../../recon/scripts/lib.sh"

while (( $# )); do
  case "$1" in
    --run) RUN="${2:-}"; shift 2 ;;
    --url) URL="${2:-}"; shift 2 ;;
    --headers) HEADERS="${2:-}"; shift 2 ;;
    --rate) RATE="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$RUN" && -n "$URL" ]] || { echo "--run and --url are required" >&2; exit 2; }

OUTDIR="$RUN/domain/checks"
mkdir -p "$OUTDIR"
LOG="$OUTDIR/tech.log"
stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
log() { printf '%s %s\n' "$(stamp)" "$*" >> "$LOG"; }

tech=""
ws=""
if [[ -f "$RUN/httpx.jsonl" ]]; then
  tech="$(jq -r '(.tech // []) | join(" ")' "$RUN/httpx.jsonl" 2>/dev/null | head -n1)"
  ws="$(jq -r '.webserver // ""' "$RUN/httpx.jsonl" 2>/dev/null | head -n1)"
fi
tech_l="$(printf '%s %s' "$tech" "$ws" | tr '[:upper:]' '[:lower:]')"
log "tech: $tech_l"

hdr_args=()
if [[ -n "$HEADERS" ]]; then
  [[ -f "$HEADERS" ]] || { echo "headers file not found: $HEADERS" >&2; exit 1; }
  while IFS= read -r line; do [[ -n "$line" ]] && hdr_args+=(-H "$line"); done < "$HEADERS"
fi

# tag | path | body pattern | label
checks=(
  "always|/.git/HEAD|ref:|git HEAD"
  "always|/.env|(APP_KEY|DB_PASSWORD|SECRET_KEY|AWS_)=|env file"
  "always|/server-status|Apache Server Status|apache status"
  "always|/phpinfo.php|PHP Version|phpinfo"
  "always|/swagger-ui.html|swagger|swagger ui"
  "always|/v2/api-docs|\"swagger\"|swagger v2 spec"
  "always|/openapi.json|\"openapi\"|openapi spec"
  "always|/api-docs|\"openapi\"|api docs"
  "spring|/actuator|\"_links\"|\"status\"|actuator root"
  "spring|/actuator/health|\"status\"|actuator health"
  "spring|/actuator/env|\"propertySources\"|actuator env"
  "spring|/actuator/mappings|\"mappings\"|actuator mappings"
  "grafana|/api/health|\"database\"|grafana health"
  "grafana|/public/build/manifest.json|\"files\"|grafana manifest"
  "grafana|/api/dashboards/home|\"dashboard\"|grafana home"
  "jenkins|/api/json|_class|jenkins api"
  "jenkins|/manage|Jenkins|jenkins manage"
  "tomcat|/manager/html|Tomcat|tomcat manager"
  "tomcat|/host-manager/html|Tomcat|tomcat host-manager"
)

printf '' > "$OUTDIR/tech.jsonl"
tested=0
hits=0

for row in "${checks[@]}"; do
  IFS='|' read -r tag path pattern label <<< "$row"
  case "$tag" in
    spring) [[ "$tech_l" == *spring* || "$tech_l" == *java* ]] || continue ;;
    grafana) [[ "$tech_l" == *grafana* ]] || continue ;;
    jenkins) [[ "$tech_l" == *jenkins* ]] || continue ;;
    tomcat) [[ "$tech_l" == *tomcat* || "$tech_l" == *jetty* ]] || continue ;;
  esac

  target="${URL%/}$path"
  tested=$((tested + 1))
  if (( DRY )); then
    echo "DRY: curl $target"
    continue
  fi

  body="$(mktemp)"
  meta=$(curl -sS -o "$body" --max-time 10 --max-filesize 300000 -A 'Mozilla/5.0 recon-skill' \
    -w '%{http_code}\t%{size_download}\t%{content_type}' "${hdr_args[@]}" "$target" 2>/dev/null || printf '000\t0\t')
  code="$(printf '%s' "$meta" | cut -f1)"
  size="$(printf '%s' "$meta" | cut -f2)"
  ctype="$(printf '%s' "$meta" | cut -f3)"
  hit=false
  evidence=""
  if [[ "$code" =~ ^[23] ]] && grep -Eqi "$pattern" "$body" 2>/dev/null; then
    hit=true
    hits=$((hits + 1))
    evidence="$(grep -Eoi "$pattern" "$body" | head -n1 | cut -c1-80)"
  fi
  jq -cn --arg path "$path" --arg label "$label" --arg code "$code" --arg size "$size" \
    --arg ctype "$ctype" --arg hit "$hit" --arg evidence "$evidence" \
    '{path:$path,label:$label,status:($code|tonumber),size:($size|tonumber),content_type:$ctype,hit:($hit=="true"),evidence:$evidence}' \
    >> "$OUTDIR/tech.jsonl"
  rm -f "$body"
  awk -v r="$RATE" 'BEGIN{exit !(r > 0)}' && sleep "$RATE" || true
done

log "DONE tested=$tested hits=$hits"
echo "tested: $tested"
echo "hits:   $hits"
