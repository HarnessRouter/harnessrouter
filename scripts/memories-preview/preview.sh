#!/usr/bin/env bash
# Local design preview of the Memories pages, with sample data. Not part of the product:
# remove this folder before the branch becomes a pull request.
#
#   ./scripts/memories-preview/preview.sh
#
# Starts the gateway with sample memory services, the console on http://localhost:3000 (PORT to
# change it), fills in sample memories, then pulls this branch every few seconds so a pushed change
# shows on the next refresh. Ctrl+C stops everything.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KIT="$ROOT/scripts/memories-preview"
CACHE="${HOME}/.cache/hr-memories-preview"
PORT="${PORT:-3000}"
GW_PORT="${GW_PORT:-8790}"
# sample memory services keep records in memory only, so every start begins clean and is seeded again
rm -rf "$CACHE/data"; mkdir -p "$CACHE/data"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

# ── Python 3.11 or newer for the gateway ─────────────────────────────────────────────────────
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  say "Python 3.11 or newer is needed. Install it with:  brew install python@3.12   then run this again."
  exit 1
fi
if [ ! -x "$CACHE/venv/bin/python" ]; then
  say "Setting up the gateway (first run only, about a minute)…"
  "$PY" -m venv "$CACHE/venv"
  "$CACHE/venv/bin/pip" install -q --upgrade pip
  "$CACHE/venv/bin/pip" install -q -r "$ROOT/gateway/requirements.txt"
fi

# ── the console's packages ─────────────────────────────────────────────────────────────────
if [ ! -d "$ROOT/ui/node_modules" ]; then
  say "Installing the console's packages (first run only, a few minutes)…"
  (cd "$ROOT/ui" && npm ci --no-audit --no-fund --loglevel=error)
fi

# ── run ────────────────────────────────────────────────────────────────────────────────────
export HR_BACKING=local HR_DATA_DIR="$CACHE/data" HR_IDENTITY_MODE=off HR_CREDIT_GATE=off HR_POOL_AUTH=none HR_SANDBOX_TRUST=owner
export HARNESS_INTERNAL_KEY="${HARNESS_INTERNAL_KEY:-$("$PY" -c 'import secrets; print(secrets.token_hex(32))')}"
export HR_SECRET_KEY="${HR_SECRET_KEY:-$("$PY" -c 'import secrets; print(secrets.token_hex(24))')}"
export HARNESS_GATEWAY_URL="http://127.0.0.1:$GW_PORT" NEXT_PUBLIC_HR_EDITION=selfhost HR_AUTH_DISABLED=1
export HR_AUTH_STORE="$CACHE/data/auth.json" HR_GW_PORT="$GW_PORT"

pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

"$CACHE/venv/bin/python" "$KIT/devgw.py" > "$CACHE/gateway.log" 2>&1 & pids+=($!)
(cd "$ROOT/ui" && exec npx next dev -p "$PORT") > "$CACHE/console.log" 2>&1 & pids+=($!)

say "Starting… (logs: $CACHE)"
# wait for the gateway (it answers 401 to a request without a workspace), then for the console's
# first compile to reach it, so the sample data goes in only once both are up
H=(-H 'x-harness-org: local' -H 'x-harness-member: local@localhost' -H 'x-harness-workspace: default' -H 'x-harness-workspace-default: 1')
for _ in $(seq 1 180); do
  [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$GW_PORT/v1/memories")" = 401 ] && break
  sleep 1
done
for _ in $(seq 1 300); do
  [ "$(curl -s -m 20 -o /dev/null -w '%{http_code}' "${H[@]}" "http://localhost:$PORT/api/harness/v1/memories")" = 200 ] && break
  sleep 1
done
HR_CONSOLE="http://localhost:$PORT" "$CACHE/venv/bin/python" "$KIT/seed.py" || say "Sample data could not be added; see $CACHE/gateway.log"
say "Open http://localhost:$PORT/memories   (Ctrl+C to stop)"

# follow the branch: a change pushed to it shows on the next refresh
BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
while true; do
  if git -C "$ROOT" fetch -q origin "$BRANCH" 2>/dev/null; then
    if [ "$(git -C "$ROOT" rev-parse HEAD)" != "$(git -C "$ROOT" rev-parse FETCH_HEAD)" ]; then
      git -C "$ROOT" merge -q --ff-only FETCH_HEAD && say "Updated: $(git -C "$ROOT" log -1 --format=%s)"
    fi
  fi
  sleep 4
done
