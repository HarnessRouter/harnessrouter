#!/usr/bin/env bash
# Start the three processes and keep them honest.
#
# If any one of them dies the container exits, rather than limping along serving a UI whose
# backend is gone — a half-dead container that still passes a TCP check is worse than one
# that restarts. `docker run --restart` then does the recovering.
set -euo pipefail

DATA_DIR="${HR_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

# ── configuration: self-contained defaults ────────────────────────────────────
# Local storage: SQLite + files on the mounted volume. No external services.
export HR_BACKING="${HR_BACKING:-local}"
export HR_DATA_DIR="$DATA_DIR"

# No auth: single-tenant box, identity is a constant supplied by the UI.
export HR_IDENTITY_MODE="${HR_IDENTITY_MODE:-off}"

# No billing or metering: these are hosted concerns and no-op when their URLs are unset.
export HR_CREDIT_GATE="${HR_CREDIT_GATE:-off}"

# The runner is right here, so there is no pool to authenticate to.
export POOL_MGMT_ENDPOINT="${POOL_MGMT_ENDPOINT:-http://127.0.0.1:8081}"
export HR_POOL_AUTH="${HR_POOL_AUTH:-none}"

# Bring your own key: the operator owns the box, the agent and the key, so the key is handed
# to the runner directly instead of being brokered. See _auth_from_conn in gateway/app.py for
# why this is an explicit mode and never a fallback.
export HR_SANDBOX_TRUST="${HR_SANDBOX_TRUST:-owner}"

# The gateway signs its own internal calls. Generated per container if not supplied, so a
# default install has no shared secret and nothing to leak; it never leaves this process tree.
if [ -z "${HARNESS_INTERNAL_KEY:-}" ]; then
  export HARNESS_INTERNAL_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
fi

export GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
export PORT="${PORT:-3000}"

# ── agent CLIs: installed here, not shipped in the image ──────────────────────
# Claude Code is distributed under Anthropic's own terms and hermes-agent declares no license,
# so neither can be redistributed inside a public image. Installing them on first run means the
# operator installs them under those terms, and the image stays redistributable.
#
# They go in the data volume, so this is once per volume rather than once per start. A failure
# to install one backend is not fatal: the others still work, and the gateway's catalog is what
# the UI offers, so an unavailable backend simply isn't listed.
TOOLS="$DATA_DIR/agent-tools"
export PATH="$TOOLS/bin:$PATH"
export NODE_PATH="$TOOLS/lib/node_modules"
export HR_BACKENDS="${HR_BACKENDS:-claude,codex,hermes}"

install_backends() {
  mkdir -p "$TOOLS"
  local want="$HR_BACKENDS"

  if [[ ",$want," == *",claude,"* ]] && [ ! -x "$TOOLS/bin/claude" ]; then
    echo "[harnessrouter] installing Claude Code (Anthropic's terms apply)…"
    npm install --prefix "$TOOLS" --global-style --no-audit --no-fund \
      @anthropic-ai/claude-code >/dev/null 2>&1 \
      || echo "[harnessrouter] WARN: Claude Code install failed — that backend is unavailable"
  fi

  if [[ ",$want," == *",codex,"* ]] && [ ! -x "$TOOLS/bin/codex" ]; then
    echo "[harnessrouter] installing Codex (Apache-2.0)…"
    npm install --prefix "$TOOLS" --global-style --no-audit --no-fund \
      @openai/codex >/dev/null 2>&1 \
      || echo "[harnessrouter] WARN: Codex install failed — that backend is unavailable"
  fi

  if [[ ",$want," == *",hermes,"* ]] && [ ! -x "$TOOLS/venv/bin/hermes" ]; then
    echo "[harnessrouter] installing Hermes (check its upstream license before use)…"
    python3 -m venv "$TOOLS/venv" >/dev/null 2>&1 \
      && "$TOOLS/venv/bin/pip" install --no-cache-dir -q \
           "hermes-agent==0.19.0" anthropic mcp >/dev/null 2>&1 \
      || echo "[harnessrouter] WARN: Hermes install failed — that backend is unavailable"
  fi
  [ -d "$TOOLS/venv/bin" ] && export PATH="$TOOLS/venv/bin:$PATH"
  # Hermes otherwise tries to install its own dependencies mid-turn.
  export HERMES_DISABLE_LAZY_INSTALLS=1
}

install_backends

pids=()
cleanup() { trap - TERM INT; for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup TERM INT EXIT

avail=""
for b in claude codex hermes; do
  case "$b" in
    claude) [ -x "$TOOLS/bin/claude" ] && avail="$avail claude" ;;
    codex)  [ -x "$TOOLS/bin/codex" ]  && avail="$avail codex" ;;
    hermes) [ -x "$TOOLS/venv/bin/hermes" ] && avail="$avail hermes" ;;
  esac
done
echo "[harnessrouter] data=$DATA_DIR  backends available:${avail:- none}"

# runner (loopback only)
( cd /app/runner && exec python3 -m uvicorn server:app --host 127.0.0.1 --port 8081 --log-level warning ) &
pids+=($!)

# gateway (loopback only)
( cd /app/gateway && exec python3 -m uvicorn app:app --host 127.0.0.1 --port 8080 --log-level warning ) &
pids+=($!)

# Wait for the gateway before the UI starts serving, so a first page load never races a
# backend that is still binding.
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:8080/healthz" >/dev/null 2>&1 && break
  sleep 1
done

# UI (the only published port)
( cd /app/ui && exec node server.js ) &
pids+=($!)

echo "[harnessrouter] ready on :$PORT"

# Exit as soon as ANY child exits, carrying its status out to the restart policy.
wait -n "${pids[@]}"
status=$?
echo "[harnessrouter] a process exited (status $status) — shutting down"
exit "$status"
