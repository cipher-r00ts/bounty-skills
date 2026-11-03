#!/usr/bin/env bash
# setup.sh — store Gmail IMAP credentials outside the repo.
#
# Gmail requirements (one-time, in the Google account):
#   1. enable 2-Step Verification
#   2. Google Account > Security > App passwords > create one for "Mail"
#   3. keep IMAP enabled (Gmail settings > Forwarding and POP/IMAP)
#
# The app password is 16 characters; spaces are stripped. A normal account
# password will not work. Use a dedicated account, never a personal mailbox.
#
#   setup.sh --address 'recon.example@gmail.com'
#   GMAIL_APP_PASSWORD='abcd efgh ijkl mnop' setup.sh --address ... --no-check
#   setup.sh --config ~/.config/opencode/secrets.json
#
# Writes {"gmail": {address, app_password, imap_host, imap_port}} with mode 0600
# into the config file (default ~/.claude/config/secrets.json) and then runs a
# live connection check.

set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${GMAIL_CONFIG:-$HOME/.claude/config/secrets.json}"
ADDRESS="${GMAIL_ADDRESS:-}"
HOST="imap.gmail.com"
PORT="993"
CHECK=1

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while (( $# )); do
  case "$1" in
    --address)  ADDRESS="${2:-}"; shift 2 ;;
    --config)   CONFIG="${2:-}"; shift 2 ;;
    --host)     HOST="${2:-}"; shift 2 ;;
    --port)     PORT="${2:-}"; shift 2 ;;
    --no-check) CHECK=0; shift ;;
    -h|--help)  usage; exit 0 ;;
    *)          echo "setup: unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$ADDRESS" ]]; then
  printf 'Gmail address (dedicated account): '
  read -r ADDRESS
fi
[[ -n "$ADDRESS" ]] || { echo "setup: address is required" >&2; exit 2; }

if [[ -n "${GMAIL_APP_PASSWORD:-}" ]]; then
  PASSWORD="$GMAIL_APP_PASSWORD"
else
  printf 'App password (16 chars, hidden): '
  read -rs PASSWORD
  printf '\n'
fi
[[ -n "$PASSWORD" ]] || { echo "setup: app password is required" >&2; exit 2; }

BB_MAILBOX_PW="$PASSWORD" python3 - "$CONFIG" "$ADDRESS" "$HOST" "$PORT" <<'PY'
import json
import os
import sys
import tempfile

path = os.path.expanduser(sys.argv[1])
address = sys.argv[2].strip()
host = sys.argv[3].strip()
port = int(sys.argv[4])
password = os.environ["BB_MAILBOX_PW"].replace(" ", "")

data = {}
if os.path.exists(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
if not isinstance(data, dict):
    raise SystemExit(f"{path} does not contain a JSON object")

gmail = data.get("gmail")
if not isinstance(gmail, dict):
    gmail = {}
gmail.update(
    {
        "address": address,
        "app_password": password,
        "imap_host": host,
        "imap_port": port,
        "backend": "imap",
    }
)
data["gmail"] = gmail

directory = os.path.dirname(path) or "."
os.makedirs(directory, exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=directory, prefix=".secrets-")
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2)
    handle.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print(f"stored gmail credentials in {path} (mode 0600)")
PY

unset PASSWORD

if (( CHECK )); then
  "$SELF_DIR/mailbox.py" check --config "$CONFIG"
  echo
  echo "next: mailbox.py alias --tag <target> --json"
fi
