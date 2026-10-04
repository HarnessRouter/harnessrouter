#!/usr/bin/env bash
# Start the three processes and keep them honest.
#
# If any one of them dies the container exits, rather than limping along serving a UI whose
# backend is gone — a half-dead container that still passes a TCP check is worse than one
# that restarts. `docker run --restart` then does the recovering.
set -euo pipefail

# ── privilege layout ──────────────────────────────────────────────────────────
# Three principals, and the distance between them is the product's security model:
#   root    this entrypoint and the runner. The runner switches to a per-session uid for every
#           agent process, which is the one thing that needs root. CAP_SETUID, CAP_SETGID and
#           CAP_CHOWN are in Docker's default set: no --privileged, no --cap-add.
#   agent   the product: the gateway, the console, the data volume. Its databases, blobs and
#           secret store are readable by it alone.
#   20000+  one uid per session, owning its session directory and nothing else. It cannot read or
#           write another session's workspace, the workspace parent, the databases, the blobs or
#           the secret store: a deliverable written to any of those paths fails at the write, while
#           the model is still there to choose the right one, instead of vanishing. Shared scratch
#           (/tmp, /var/tmp, /dev/shm) stays writable, because tools hardcode it — see the mode
#           below. See _isolate_session in runner/server.py.
if [ "$(id -u)" -ne 0 ]; then
  echo "[harnessrouter] ERROR: the container must start as root. It drops privileges itself: the product runs as 'agent', every agent process as its own session uid. Remove --user from docker run."
  exit 1
fi
PRODUCT=agent
AS_PRODUCT="setpriv --reuid=$PRODUCT --regid=$PRODUCT --init-groups"

DATA_DIR="${HR_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

# Session workspaces live on the volume so a restart doesn't discard work in flight. Created HERE
# rather than in the image: /data is a volume mount, and Docker only seeds a volume from the image
# when the volume is empty — so an image-time mkdir is invisible on every existing install.
export HARNESS_WORKSPACE="${HARNESS_WORKSPACE:-$DATA_DIR/workspaces}"
mkdir -p "$HARNESS_WORKSPACE"

# The write-wall, in file modes. Idempotent and non-recursive, so it costs nothing on a volume
# that already has it and repairs one that predates it. Session directories themselves are owned
# by their session's uid (0700); the runner sets that as it allocates them.
chown "$PRODUCT:$PRODUCT" "$DATA_DIR" "$HARNESS_WORKSPACE"
chmod 751 "$DATA_DIR" "$HARNESS_WORKSPACE"        # traversable by sessions, neither listable nor writable
# Environments (runner/environments.py): project layers built once and read by the sessions that
# name one. Root's, each environment readable by its own group and writable by none: that ownership
# is the read-only guarantee, so nothing here is handed to $PRODUCT. Both directories are
# traversable, not listable: a session reaches the environment it was told and enumerates none.
# /env holds the links sessions are told.
export HR_ENV_ROOT="${HR_ENV_ROOT:-$DATA_DIR/environments}"
mkdir -p "$HR_ENV_ROOT" /env
chmod 751 "$HR_ENV_ROOT" /env
# A login shell (`bash -lc`, which codex uses for its commands) runs /etc/profile, and Debian's
# sets PATH from scratch, which dropped the environment's venv and node_modules/.bin that the runner
# had put first (measured on 0.26.0-rc.1: `python3` was /usr/local's, not the venv's). The runner
# names the environment in HR_ENVIRONMENT, which a login shell keeps; this profile drop-in puts the
# environment back at the head of PATH after /etc/profile has had its say.
mkdir -p /etc/profile.d
cat > /etc/profile.d/hr-environment.sh <<'PROFILE'
# HarnessRouter: the task's environment (runner/environments.py) stays first on PATH in login shells.
if [ -n "$HR_ENVIRONMENT" ]; then
  # the same order runner/environments.py::apply_env sets: apt tools, then node_modules/.bin, then the venv first
  for d in "$HR_ENVIRONMENT/apt/bin" "$HR_ENVIRONMENT/apt/usr/local/bin" "$HR_ENVIRONMENT/apt/usr/bin"; do [ -d "$d" ] && PATH="$d:$PATH"; done
  [ -d "$HR_ENVIRONMENT/node_modules/.bin" ] && PATH="$HR_ENVIRONMENT/node_modules/.bin:$PATH"
  [ -d "$HR_ENVIRONMENT/.venv/bin" ] && PATH="$HR_ENVIRONMENT/.venv/bin:$PATH" && export VIRTUAL_ENV="$HR_ENVIRONMENT/.venv"
  export PATH
fi
PROFILE
chmod 644 /etc/profile.d/hr-environment.sh
for f in "$DATA_DIR"/*.db "$DATA_DIR"/*.db-* "$DATA_DIR"/selfhost-auth.json; do
  if [ -e "$f" ]; then chown "$PRODUCT:$PRODUCT" "$f"; chmod 600 "$f"; fi
done
for d in "$DATA_DIR/blobs" "$DATA_DIR/secrets"; do
  if [ -d "$d" ]; then chown "$PRODUCT:$PRODUCT" "$d"; chmod 700 "$d"; fi
done
# Shared scratch stays USABLE. Sessions get their own TMPDIR inside their workspace (see turn()
# in the runner), but a machine's scratch directories are a convention that tools hardcode, and a
# tool that cannot write /tmp does not fall back: LibreOffice puts its UNO pipe there and dies with
# "no valid pipe path found", which is every .docx/.xlsx/.pptx render and every PDF preview. Closed
# to sessions, one deck task on the demo box spent twenty minutes failing around it before finding
# a way through. Measured both ways under real conditions: closed, no output at all; open as below,
# a 524 KB PDF and its slide render.
#
# 1733, not 1777: a session can CREATE and use paths here (w+x) and the sticky bit stops it
# removing another session's files, but it cannot LIST the directory — so one session cannot
# enumerate another's scratch, which is what shared /tmp otherwise gives away. Deliverables are a
# different question and are answered by the workspace contract, not by this mode: the paths that
# silently swallowed one (the workspace parent, another session's directory) stay closed.
for d in /tmp /var/tmp /dev/shm; do
  if [ -d "$d" ]; then chown root:root "$d"; chmod 1733 "$d"; fi
done

# Our own processes must run on the image's interpreter, never on whatever a backend puts on
# PATH. Hermes installs into its own venv and that venv's bin joins PATH below so the runner can
# spawn `hermes` — but that venv has none of the gateway's dependencies, so resolving `python3`
# through PATH would start the gateway inside it and fail on the first import.
PY=/usr/local/bin/python3

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
# Image generation through the broker. Safe to default on HERE and nowhere else: self-hosted is
# bring-your-own-key, so the images an agent makes are billed to the operator's own provider
# account and there is nothing for us to meter.
export HR_BROKER_IMAGES="${HR_BROKER_IMAGES:-1}"
# codex runs through its app-server, the path the hosted service runs it on (it streams the
# assistant's text as it is written); this image never set the variable, so codex here ran
# `codex exec` instead and the two products diverged on the same code (2026-09-10). Flip to 0
# for an instant rollback to `codex exec`; CODEX_APPSERVER_SANDBOX is the sandbox enum.
export HARNESS_CODEX_APPSERVER="${HARNESS_CODEX_APPSERVER:-1}"

# The gateway signs its own internal calls. Generated per container if not supplied, so a
# default install has no shared secret and nothing to leak; it never leaves this process tree.
if [ -z "${HARNESS_INTERNAL_KEY:-}" ]; then
  export HARNESS_INTERNAL_KEY="$("$PY" -c 'import secrets; print(secrets.token_hex(32))')"
fi

# The console reaches the gateway over loopback; it is the only process that can, since only
# the console's port is published.
export HARNESS_GATEWAY_URL="${HARNESS_GATEWAY_URL:-http://127.0.0.1:8080}"
export NEXT_PUBLIC_HR_EDITION=selfhost

# ── console login ─────────────────────────────────────────────────────────────
# The console can create harnesses, read every transcript, and run an agent with your provider
# key, so an instance anyone can reach needs a gate. Defaults exist so the first run works; they
# are also published in the README, which makes them a placeholder rather than a secret.
# The Claude Code release this image was verified with; see install_backends.
export CLAUDE_CODE_VERSION="${CLAUDE_CODE_VERSION:-2.1.280}"
export HR_AUTH_USER="${HR_AUTH_USER:-harnessrouter}"
export HR_AUTH_PASSWORD="${HR_AUTH_PASSWORD:-harnessrouter}"
export HR_AUTH_STORE="${HR_AUTH_STORE:-/data/selfhost-auth.json}"

# Credentials changed from the profile page live in HR_AUTH_STORE and win over the environment:
# an env var set at `docker run` months ago must not silently undo a password change. The console
# signs its session cookie with HR_SESSION_KEY, which is derived from whichever source wins —
# so the key changes when the credentials do, and every existing session stops verifying.
#
# It is derived HERE, at boot, because the gate runs in Next.js middleware on the Edge runtime:
# no filesystem, and no visibility into environment changes made after start-up. That is why
# changing credentials restarts the console (below) instead of taking effect in place.
hr_session_key() {
  if [ -f "$HR_AUTH_STORE" ]; then
    "$PY" - "$HR_AUTH_STORE" <<'PYEOF' 2>/dev/null && return 0
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    if d.get("user") and d.get("hash"):
        print("%s:%s" % (d["user"], d["hash"]))
    else:
        raise ValueError
except Exception:
    raise SystemExit(1)
PYEOF
  fi
  printf '%s:%s\n' "$HR_AUTH_USER" "$HR_AUTH_PASSWORD"
}

hr_stored_user() {
  [ -f "$HR_AUTH_STORE" ] || { printf '%s\n' "$HR_AUTH_USER"; return 0; }
  "$PY" -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["user"])' "$HR_AUTH_STORE" 2>/dev/null \
    || printf '%s\n' "$HR_AUTH_USER"
}

if [ "${HR_AUTH_DISABLED:-}" = "1" ]; then
  echo "[harnessrouter] WARNING: login is DISABLED (HR_AUTH_DISABLED=1) — anyone who can reach this port has full control"
elif [ -f "$HR_AUTH_STORE" ]; then
  echo "[harnessrouter] sign in as '$(hr_stored_user)' (credentials set from the profile page)"
elif [ "$HR_AUTH_PASSWORD" = "harnessrouter" ]; then
  echo "[harnessrouter] WARNING: using the DEFAULT password. Set HR_AUTH_PASSWORD, or change it from the profile page, before exposing this instance."
fi
export PORT="${PORT:-3000}"
# Next binds to $HOSTNAME, and Docker sets that to the container id, which resolves to ONE of the
# container's addresses. That is fine with a single network and silently fatal with two: connect
# this container to a user-defined network — which is exactly what the README tells you to do to
# reach a database — and after the next restart Next comes up on that network's address while the
# published port still forwards to the bridge one. Nothing is listening where the port lands, so
# the console answers 502 while the container reports healthy and the log says "Ready".
# Measured on the test box 2026-08-16: LISTEN 172.18.0.5:3000, published 127.0.0.1:3000 -> the
# bridge ip. Binding every interface is the only answer that survives a second network.
export HOSTNAME=0.0.0.0

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
export HR_BACKENDS="${HR_BACKENDS:-claude,codex,hermes,pi,dsh,opencode,kilo,qwen,gemini,cline,omp,goose,kimi,minimax,grok,aider,openhands,agentzero,systemone,cheetahclaws}"

wanted()   { [[ ",$HR_BACKENDS," == *",$1,"* ]]; }
# The executable IS the definition of "installed" — an installer that exits 0 without producing
# one is still a failed install, and reporting it as success is how a backend silently vanishes
# from the console with no explanation.
backend_bin() {
  case "$1" in
    claude) echo "$TOOLS/bin/claude" ;;
    codex)  echo "$TOOLS/bin/codex" ;;
    hermes) echo "$TOOLS/venv/bin/hermes" ;;
    pi)     echo "$TOOLS/bin/pi" ;;
    dsh)    echo "$TOOLS/dsh-venv/bin/dsh-ready" ;;
    opencode) echo "$TOOLS/bin/opencode" ;;
    kilo)   echo "$TOOLS/kilo/kilo" ;;
    qwen)   echo "$TOOLS/bin/qwen" ;;
    gemini) echo "$TOOLS/bin/gemini" ;;
    cline)  echo "$TOOLS/bin/cline" ;;
    omp)    echo "$TOOLS/bin/omp" ;;
    goose)  echo "$TOOLS/bin/goose" ;;
    kimi)   echo "$TOOLS/bin/kimi" ;;
    minimax) echo "$TOOLS/bin/mcode" ;;
    grok)   echo "$TOOLS/bin/grok" ;;
    aider)  echo "$TOOLS/aider-venv/bin/aider" ;;
    openhands) echo "$TOOLS/openhands-venv/bin/python" ;;
    systemone) echo "$TOOLS/systemone-venv/bin/python" ;;
    cheetahclaws) echo "$TOOLS/cheetahclaws-venv/bin/cheetahclaws-ready" ;;
    agentzero) echo "$TOOLS/agentzero-venv/bin/agentzero-ready" ;;
  esac
}

# opencode ships prebuilt binaries on GitHub releases rather than npm, so fetch the asset directly.
# NOT the vendor's install script: it hardcodes INSTALL_DIR=$HOME/.opencode/bin with no override, so
# it cannot be pointed at the data volume, and piping a remote script into a shell inside an
# entrypoint is a supply-chain surface this product does not need. Pin with HR_OPENCODE_VERSION.
install_opencode() {
  case "$(uname -m)" in
    x86_64)        oc_arch="x64" ;;
    aarch64|arm64) oc_arch="arm64" ;;
    *) echo "unsupported architecture $(uname -m) for opencode"; return 1 ;;
  esac
  oc_ref="${HR_OPENCODE_VERSION:-latest}"
  if [ "$oc_ref" = "latest" ]; then
    oc_url="https://github.com/anomalyco/opencode/releases/latest/download/opencode-linux-$oc_arch.tar.gz"
  else
    oc_url="https://github.com/anomalyco/opencode/releases/download/v${oc_ref#v}/opencode-linux-$oc_arch.tar.gz"
  fi
  oc_tmp="$(mktemp -d)"
  curl -fsSL "$oc_url" -o "$oc_tmp/opencode.tar.gz" || { rm -rf "$oc_tmp"; return 1; }
  tar -xzf "$oc_tmp/opencode.tar.gz" -C "$oc_tmp" || { rm -rf "$oc_tmp"; return 1; }
  [ -f "$oc_tmp/opencode" ] || { echo "release archive contained no opencode binary"; rm -rf "$oc_tmp"; return 1; }
  mkdir -p "$TOOLS/bin" && mv "$oc_tmp/opencode" "$TOOLS/bin/opencode" && chmod 755 "$TOOLS/bin/opencode" \
    || { rm -rf "$oc_tmp"; return 1; }
  rm -rf "$oc_tmp"
}

# goose (Apache-2.0) ships one prebuilt binary per target on GitHub releases — the archive holds
# exactly ./goose — so it is fetched the same way opencode's is, and NOT through the vendor's
# download_cli.sh: piping a remote script into a shell inside an entrypoint is a supply-chain
# surface this product does not need, and that script installs to its own path anyway.
#
# Pinned EXACTLY, like every other backend here. Upstream ships weekly (1.49.0 -> 1.50.0 in five
# days) and 1.50.0 is the release runner/server.py's goose code was written against: the
# stream-json event schema, GOOSE_PATH_ROOT, the available_tools allowlist and -n/-r resume were
# all read out of THIS version's source. A silent `latest` re-gambles all of it.
#
# Note the repo moved from block/goose to aaif-goose/goose. Unlike omp this project publishes no
# SHA256SUMS.txt, so there is nothing to fetch and compare against — but that does not mean the
# download has to go unverified: the digests are pinned HERE instead, computed from the v1.50.0
# release assets (each archive holds exactly ./goose). That is strictly stronger than the tag
# alone, which can be moved and whose asset can be re-uploaded.
# Aider, Apache-2.0 (Aider-AI/aider), pinned to 0.86.2, plus the MCP bridge it needs.
#
# Its own venv, the dsh/hermes precedent: aider pins litellm and a large scientific stack, and must
# not share the runner's interpreter. The version is pinned exactly and aider's own wheel pins every
# dependency to a version, so the venv is the same one on every volume; there is no digest check
# here, the release is trusted the way the other PyPI installs (dsh) are.
#
# NOTE the Python floor: aider 0.86.2 declares Requires-Python <3.13,>=3.10. On an interpreter
# outside that range pip does not fail — it silently offers an OLDER aider (0.82.3 was the highest
# on 3.9), and every behaviour runner/aider_driver.py was written against would be absent without a
# single error. The explicit version pin below is what turns that into a hard failure.
#
# The official MCP SDK goes in beside it: upstream aider has no MCP client at all, so
# runner/aider_mcp_bridge.py is what lets a declared MCP server be reached and, therefore, measured.
# Installed in this venv rather than globally because no other backend uses it.
AIDER_PIN="${HR_AIDER_VERSION:-0.86.2}"
install_aider() {
  am_py="${HR_AIDER_BASE_PYTHON:-python3}"
  # The venv lives on the data volume, so a pin bump in the image must reach a volume that
  # already has one (the dsh precedent): aider-ready names the version the venv was built for,
  # and a mismatch rebuilds it. Sessions keep nothing in the venv.
  rm -rf "$TOOLS/aider-venv"
  "$am_py" -m venv "$TOOLS/aider-venv" || return 1
  "$TOOLS/aider-venv/bin/pip" install -q --disable-pip-version-check \
    "aider-chat==$AIDER_PIN" || return 1
  # The driver imports aider in process; prove the pinned version is importable before declaring the
  # install good, so a resolver that quietly picked another one fails HERE and not on a live turn.
  "$TOOLS/aider-venv/bin/python" -c '
import sys, aider
want = sys.argv[1]
if aider.__version__ != want:
    sys.exit("aider %s installed, wanted %s" % (aider.__version__, want))
'  "$AIDER_PIN" || return 1
  # aider's MCP client: the official MIT SDK, into the same venv. f/mcptools was the first choice
  # and is not usable here — it is a Go program that publishes NO binaries on any release (checked
  # through v0.7.1, every one has zero assets), so it would mean a Go toolchain in a python-slim
  # image for one command.
  "$TOOLS/aider-venv/bin/pip" install -q --disable-pip-version-check \
    "mcp==${HR_MCP_SDK_VERSION:-2.2.0}" || return 1
  # Written LAST, after both installs and the version check proved the venv good: the marker is
  # what the boot compares against the pin, so a half-built venv is rebuilt rather than trusted.
  printf '#!/bin/sh\necho %s\n' "$AIDER_PIN" > "$TOOLS/aider-venv/bin/aider-ready" \
    && chmod +x "$TOOLS/aider-venv/bin/aider-ready"
}

# CheetahClaws, Apache-2.0 (SAIL-Research-Lab/cheetahclaws, PyPI `cheetahclaws`), pinned to 3.5.88.
#
# Its own venv, the aider/openhands precedent: runner/cheetahclaws_driver.py drives the CLI's agent
# loop IN PROCESS, so this venv's interpreter is what the runner starts, and the package's own
# dependency tree (anthropic, openai, httpx, rich, pyte, prompt_toolkit) stays off the runner's.
# The BARE package: its `files` extra brings pymupdf, which is AGPL-3.0, and `browser` brings
# playwright with a Chromium of its own; the driver withholds the four tools those extras serve
# (WebBrowse, ReadPDF, ReadSpreadsheet, ReadImage) for as long as they are absent.
#
# VERIFIED, not only pinned. PyPI publishes the wheel's sha256, so the wheel is downloaded on its
# own, compared against the digest pinned here (computed from the 3.5.88 release's
# cheetahclaws-3.5.88-py3-none-any.whl, and equal to the one PyPI lists), and installed from that
# file; an index entry can be replaced, a digest cannot. An operator who overrides the version
# supplies HR_CHEETAHCLAWS_SHA256 for it, or is told the wheel is unverified (install_backends).
# The import check then asserts the symbols the driver reaches for, so an upstream refactor fails
# the install here rather than the first live turn.
CHEETAHCLAWS_PIN="${HR_CHEETAHCLAWS_VERSION:-3.5.88}"
if [ "$CHEETAHCLAWS_PIN" = "3.5.88" ]; then
  CHEETAHCLAWS_SHA256="${HR_CHEETAHCLAWS_SHA256:-6e9b46c0e2d125f700cc0b609464efe1a3fe0914cbd0ecad8e405a1c0fc4f9c0}"
else
  CHEETAHCLAWS_SHA256="${HR_CHEETAHCLAWS_SHA256:-}"
fi
install_cheetahclaws() {
  cc_py="${HR_CHEETAHCLAWS_BASE_PYTHON:-python3}"
  rm -rf "$TOOLS/cheetahclaws-venv"
  "$cc_py" -m venv "$TOOLS/cheetahclaws-venv" || return 1
  cc_tmp="$(mktemp -d)"
  "$TOOLS/cheetahclaws-venv/bin/pip" download -q --disable-pip-version-check --no-deps \
    --only-binary=:all: -d "$cc_tmp" "cheetahclaws==$CHEETAHCLAWS_PIN" || { rm -rf "$cc_tmp"; return 1; }
  cc_whl="$cc_tmp/cheetahclaws-$CHEETAHCLAWS_PIN-py3-none-any.whl"
  [ -f "$cc_whl" ] || { echo "cheetahclaws $CHEETAHCLAWS_PIN: no wheel was downloaded"; rm -rf "$cc_tmp"; return 1; }
  if [ -n "$CHEETAHCLAWS_SHA256" ]; then
    cc_have="$(sha256sum "$cc_whl" | awk '{print $1}')"
    if [ "$CHEETAHCLAWS_SHA256" != "$cc_have" ]; then
      echo "cheetahclaws $CHEETAHCLAWS_PIN: wheel digest mismatch (want $CHEETAHCLAWS_SHA256, have $cc_have)"
      rm -rf "$cc_tmp"; return 1
    fi
  fi
  "$TOOLS/cheetahclaws-venv/bin/pip" install -q --disable-pip-version-check "$cc_whl" \
    || { rm -rf "$cc_tmp"; return 1; }
  rm -rf "$cc_tmp"
  "$TOOLS/cheetahclaws-venv/bin/python" -c '
import sys, importlib.metadata as md
want = sys.argv[1]
have = md.version("cheetahclaws")
if have != want:
    sys.exit("cheetahclaws %s installed, wanted %s" % (have, want))
# every name runner/cheetahclaws_driver.py imports, from the modules it imports them from
from cheetahclaws.agent import AgentState, run, TextChunk, ThinkingChunk, ToolStart, ToolEnd, TurnDone, PermissionRequest  # noqa: F401
from cheetahclaws.commands.session import autosave_session, _migrate_session  # noqa: F401
from cheetahclaws.config import load_config, MR_SESSION_DIR  # noqa: F401
from cheetahclaws.context import build_system_prompt  # noqa: F401
from cheetahclaws.mcp_client.tools import initialize_mcp  # noqa: F401
from cheetahclaws.tool_registry import get_all_tools  # noqa: F401
import cheetahclaws.commands.session as s
if not hasattr(s, "_autosave_sid"):
    sys.exit("cheetahclaws %s: commands.session has no _autosave_sid" % have)
' "$CHEETAHCLAWS_PIN" || return 1
  # Written LAST, after the install and the checks proved the venv good: the marker is what the
  # boot compares against the pin, so a half-built venv is rebuilt rather than trusted.
  printf '#!/bin/sh\necho %s\n' "$CHEETAHCLAWS_PIN" > "$TOOLS/cheetahclaws-venv/bin/cheetahclaws-ready" \
    && chmod +x "$TOOLS/cheetahclaws-venv/bin/cheetahclaws-ready"
}

# Kimi Code CLI, MIT (MoonshotAI/kimi-code), pinned to 2.0.0.
#
# THIS IS THE SUCCESSOR, NOT Kimi CLI. 0.18.0 shipped MoonshotAI/kimi-cli 1.50.0, the Python
# predecessor whose own README says it "is evolving into Kimi Code CLI"; the product is the
# TypeScript rewrite in MoonshotAI/kimi-code, a single binary that is also called `kimi`. The pin
# below is compared against `kimi --version` on every start, so a volume that still holds the old
# binary ("kimi, version 1.50.0") is upgraded in place rather than left running the wrong product.
#
# The release archive, not the install script and not npm: the script pipes a moving target into a
# shell, while an asset under a tag can be pinned. Upstream publishes a per-asset .sha256 beside
# each archive; the digests are still pinned HERE rather than fetched, because a checksum served
# from the same origin as the artifact adds nothing against a compromised origin, while a digest
# in this file fails closed if the tag is moved or the asset re-uploaded. The values below were
# read from the 2.0.0 assets and agree with upstream's own .sha256 files. The release tag is
# "@moonshot-ai/kimi-code@<version>", which has to be percent-encoded in the download URL.
#
# Everything runner/server.py's kimi code relies on (the stream-json line shapes, the model defined
# from KIMI_MODEL_* alone, -r refusing an unknown session, agent files matching tool NAMES,
# $KIMI_CODE_HOME/mcp.json, the exit-1 failure line) was measured on THIS version.
KIMI_PIN="${HR_KIMI_VERSION:-2.0.0}"; KIMI_PIN="${KIMI_PIN#v}"
# MiniMax Code, MIT (MiniMax-AI/minimax-code; its sandbox-runtime part Apache-2.0), pinned to 0.5.4.
#
# The GitHub release archive, an npm package tarball (@minimax-ai/code, bin `mcode`) built from the
# tagged public source, installed with npm the way upstream's release notes say. Not the vendor's
# install script (it installs a launcher and a Node runtime of its own and follows the npm channel)
# and not the registry name: an asset under a tag can be pinned by digest. One archive for every
# platform, so one digest. Upstream publishes it three times (a .sha256 beside the asset, the release
# notes, GitHub's asset digest) and all three agree with the value below, which was computed from the
# downloaded archive (2026-09-26). It is pinned HERE for kimi's reason: a checksum served from the
# artifact's own origin adds nothing against a compromised origin.
#
# The digest covers the package. Its three dependencies (better-sqlite3 12.11.1, @vscode/ripgrep
# 1.18.0, @larksuiteoapi/node-sdk 1.73.3) are exact versions resolved from npm at install time; their
# own dependencies float within npm ranges, as for every npm-installed backend here. About 105 MB
# installed, so it is in the default set. Requires Node >= 22.19 (the image's nodesource 22.x).
#
# Everything runner/server.py's minimax code relies on (the exec stream-json schema, the
# custom_provider selector, --session refusing an unknown id, the sqlite session store, the config
# keys agents.default / skills.external, the two instruction files, the rm shim's trash) was
# measured on THIS version.
MINIMAX_PIN="${HR_MINIMAX_VERSION:-0.5.4}"; MINIMAX_PIN="${MINIMAX_PIN#v}"
# Kilo CLI (Kilo-Org/kilocode, MIT), an opencode fork, pinned to 7.8.1. The release archive from
# GitHub, not npm's launcher package and not the vendor's install script: the archive is one
# directory (the `kilo` binary beside bwrap, the sandbox helpers and the tree-sitter grammars it
# loads from its own directory), 65 MB down and 228 MB unpacked — under the 300 MB line, so it is in
# the default HR_BACKENDS. Upstream publishes kilo-cli-SHA256SUMS beside the assets; the digests are
# pinned HERE for kimi's reason (a checksum from the same origin adds nothing against that origin).
# The values below were read from the 7.8.1 assets and agree with both upstream's SHA256SUMS and
# GitHub's own asset digests. Everything runner/server.py's kilo code relies on (the run --format
# json events, KILO_CONFIG, enabled_providers, the env switches, the session table, the edit
# permission key) was measured on THIS version.
KILO_PIN="${HR_KILO_VERSION:-7.8.1}"; KILO_PIN="${KILO_PIN#v}"
# Grok Build, Apache-2.0 (xai-org/grok-build), pinned to 1.0.41.
#
# The GitHub repository is source only — no tags, no releases — so the artifact is the one the
# publisher's own installer (SpaceXAI's, https://x.ai/cli/install.sh) downloads: a single static binary per platform at
# https://x.ai/cli/grok-<version>-linux-<arch>, a Cloudflare front for the public bucket
# storage.googleapis.com/grok-build-public-artifacts/cli, which is the fallback here as it is there.
# NOT the install script: it resolves "latest" from a channel pointer, installs a self-updating
# launcher layout under ~/.grok, and verifies nothing but that the binary runs.
#
# UPSTREAM PUBLISHES NO CHECKSUMS (no .sha256 beside the assets; the installer checks none), so the
# digests below were computed here from the 1.0.41 assets (2026-09-26) — the goose contract: a
# moved pointer or a re-uploaded asset fails closed. The bucket's own md5 headers agreed with the
# downloaded bytes. ~166 MB on x86_64, one file, well under the 300 MB default-set bar.
#
# Everything runner/server.py's grok code relies on (the stream-json shape, errors[] on a failed
# result, the side calls and the switches that stop them, -r's remote restore and the registry
# switch that stops it, the shell's internal tool id) was measured on THIS version. The binary
# updates itself only through its managed install; the runner also sets GROK_DISABLE_AUTOUPDATER=1.
GROK_PIN="${HR_GROK_VERSION:-1.0.41}"; GROK_PIN="${GROK_PIN#v}"
# OpenHands V1, MIT (OpenHands/agent-sdk), pinned to 1.49.2 — the AGENT SERVER, not the CLI.
#
# PyPI `openhands` is OpenHands/openhands-cli, whose README opens with "This project is no longer
# actively maintained" and whose last release is 1.16.0 of 2026-05-08. This is the interface its
# vendor does maintain: `openhands-agent-server`, released 1.49.2 on 2026-09-17.
#
# THE THREE PINS GO IN ONE pip INVOCATION, and that is not cosmetic. `openhands-agent-server`
# imports `openhands.tools` and `libtmux` at module level and declares NEITHER; `openhands-tools`
# is what brings both. Installed one at a time, pip resolves each call on its own and lands on
# browser-use 0.13.10, which pins `openai==2.26.0` against the server's own `openai>=2.33.0` — a
# set `pip check` refuses. Given all three at once it backtracks to browser-use 0.11.13 and the
# environment is consistent (verified: `No broken requirements found`, and the same resolution uv
# reaches). The 1.34.0 set the OpenHands platform itself declares does not resolve at all
# (`ResolutionImpossible`, lmnr against openhands-sdk), so 1.49.2 is the floor as well as the pin.
#
# THE FOURTH PIN IS litellm, HELD BELOW 1.95.0, and it decides whether a follow-up turn survives.
# The SDK asks only for `litellm>=1.93.0`, so pip takes the newest — and from 1.95.0 litellm's
# PromptTokensDetailsWrapper mirrors an assignment between `cache_write_tokens` and
# `cache_creation_tokens`, which puts BOTH names into `model_fields_set` and then drops the unset
# attribute from __dict__. The SDK's telemetry (llm/utils/telemetry.py, _cache_buckets) reads
# `"cache_creation_tokens" in details.model_fields_set` as its existence test, so it asks for an
# attribute that is no longer there: `AttributeError: 'PromptTokensDetailsWrapper' object has no
# attribute 'cache_creation_tokens'`. Each side is self-consistent; together they are not, and
# 1.49.2 is the newest SDK, so there is nothing to upgrade to.
#
# It only fires once a response carries prompt_tokens_details — a prompt-cache hit, which a FIRST
# turn cannot have — so it reads as "follow-ups fail and first turns do not". The agent-server
# publishes no error event for it (see the driver's fallback), tenacity retries it five times, and
# the record shows a 150-200 s turn that ended for no stated reason. Measured on gemini-3-flash-preview,
# same command and image, litellm the only difference: 1.101.0 gave first ok / follow-up FAIL 145 s /
# switch ok / artifact FAIL 175 s / recycle FAIL 148 s, and 1.94.3 gave five of five in 10-14 s each.
#
# Own venv, the dsh/hermes precedent: it pins litellm, fastmcp, pydantic and a browser stack, and
# must not share the runner's interpreter.
# The System One Harness (github.com/HarnessRouter/SystemOneHarness, Apache-2.0): a loop over a
# decision model, pinned by git tag. Its own venv on the data volume like openhands and aider: three
# small dependencies (httpx, pyyaml, the MCP SDK), installed once and rebuilt when the pin moves.
# The executable is the venv's python, which the runner hands runner/systemone_driver.py.
SYSTEMONE_PIN="${HR_SYSTEMONE_VERSION:-0.4.0}"; SYSTEMONE_PIN="${SYSTEMONE_PIN#v}"
# HR_SYSTEMONE_SPEC overrides where pip takes the package from (a mirror, a fork, a local tree
# copied into a derived image); the version proven below is the pin either way. The browser extra
# brings Browser Use, and with it the page and game environments; the Chromium they drive is
# installed beside the venv on the data volume (Playwright's, world-readable), because the image
# ships no browser and a session process cannot read root's cache.
SYSTEMONE_SPEC="${HR_SYSTEMONE_SPEC:-systemone-harness[browser] @ git+https://github.com/HarnessRouter/SystemOneHarness@v${SYSTEMONE_PIN}}"
export PLAYWRIGHT_BROWSERS_PATH="$TOOLS/ms-playwright"
# The libraries that Chromium links against live in the container, not on the volume the browser
# is on, so a container recreated over a volume that already holds the browser has the binary and
# none of its libraries (measured: libatk, libatspi, libXcomposite "not found", and every launch
# died before CDP came up). They are installed per container, keyed on a marker in the container's
# own filesystem: on the first install, and on every start that finds the venv already there.
CHROMIUM_LIBS_MARK=/var/lib/harnessrouter/chromium-libs
chromium_libs() {
  [ -f "$CHROMIUM_LIBS_MARK" ] && return 0
  echo "[harnessrouter]   installing the system libraries Chromium links against (this container)…"
  "$TOOLS/systemone-venv/bin/playwright" install-deps chromium >/dev/null 2>&1 || return 1
  mkdir -p "$(dirname "$CHROMIUM_LIBS_MARK")" && : > "$CHROMIUM_LIBS_MARK"
}
install_systemone() {
  # A failed install leaves NO venv behind: the executable is the definition of installed, and a
  # venv whose pip step failed reported the base as available on a box where it could not run.
  "${HR_SYSTEMONE_BASE_PYTHON:-python3}" -m venv "$TOOLS/systemone-venv" || { rm -rf "$TOOLS/systemone-venv"; return 1; }
  "$TOOLS/systemone-venv/bin/pip" install -q --disable-pip-version-check "$SYSTEMONE_SPEC" playwright \
    || { rm -rf "$TOOLS/systemone-venv"; return 1; }
  if ! ls "$PLAYWRIGHT_BROWSERS_PATH"/chromium-*/chrome-linux*/chrome >/dev/null 2>&1; then
    echo "[harnessrouter]   installing a Chromium for the System One base (Playwright's) under $PLAYWRIGHT_BROWSERS_PATH …"
    "$TOOLS/systemone-venv/bin/playwright" install chromium \
      || { rm -rf "$TOOLS/systemone-venv"; return 1; }
    chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || true
  fi
  chromium_libs || { rm -rf "$TOOLS/systemone-venv"; return 1; }
  # Prove the loop imports and the version is the pin, the way every other installer here proves
  # its executable: an install that cannot import is a base that dies on its first turn.
  "$TOOLS/systemone-venv/bin/python" -c '
import sys
import systemone_harness, systemone_harness.envs.mcp, systemone_harness.envs.browser  # noqa: F401 - the loop, the MCP adapter, the browser
import browser_use  # noqa: F401 - the browser extra
have = systemone_harness.__version__
if have != sys.argv[1]:
    print(f"systemone-harness {have} installed, {sys.argv[1]} pinned", file=sys.stderr); sys.exit(1)
' "$SYSTEMONE_PIN" || { rm -rf "$TOOLS/systemone-venv"; return 1; }
}

# Agent Zero, MIT (agent0ai/agent-zero), pinned to v2.13 — a FRAMEWORK, not a CLI.
#
# Agent Zero ships as a Docker image with a web UI; it has no CLI and no headless mode, and upstream
# publishes no package on PyPI and no release assets (v2.13's release has none). So the install is
# the tagged SOURCE archive, verified against a digest pinned HERE (the goose pattern: upstream
# publishes no checksums, so they were computed from the v2.13 archive — it is byte-identical
# whether fetched from github.com/.../archive or codeload, and its tree is identical to the tag's
# git checkout, e3051fb). runner/agentzero_driver.py imports the framework from that tree and runs
# one message per turn in process; see its docstring.
#
# THE DEPENDENCIES ARE UPSTREAM'S OWN requirements.txt, with its exact pins, MINUS the packages that
# serve only what this base switches off (the driver's DISABLED_PLUGINS and ALWAYS_BLOCKED): local
# embeddings and speech (sentence-transformers, kokoro and openai-whisper, which bring torch — GBs),
# document parsing (unstructured, liteparse, faiss, pdf and OCR tooling), the browser (patchright),
# search (duckduckgo), the integrations (email, exchange, boto3, docker, tunnels) and Windows' pty.
# Nothing is added but ipython, which the terminal's python runtime calls by name.
# models.py imports sentence_transformers at the top; the driver stubs that one module (and the
# check below does the same), because the only thing that would call it is the memory plugin.
#
# Own venv on the data volume like openhands and aider. Measured on Linux arm64 (python:3.12-slim):
# 83 s, venv 569 MB + source 69 MB — over the 300 MB bar, and in the DEFAULT set all the same, the
# decision aider and openhands already carry: the console offers every base the gateway's catalogue
# lists, so a base left out of the default install is a base whose first task fails. An operator who
# does not want the 638 MB leaves it out of HR_BACKENDS, the switch every backend has.
AGENTZERO_PIN="${HR_AGENTZERO_VERSION:-2.13}"; AGENTZERO_PIN="${AGENTZERO_PIN#v}"
AGENTZERO_EXCLUDE='^(kokoro|openai-whisper|sentence-transformers|unstructured|unstructured-client|langchain-unstructured|faiss-cpu|liteparse|newspaper3k|patchright|docker|duckduckgo-search|pyreqwest-impersonate|exchangelib|imapclient|boto3|flaredantic|pypdf|pymupdf|pytesseract|pdf2image|soundfile|pywinpty)([=<>~!; []|$)'
install_agentzero() {
  az_sha="ac9e1b319cb75ae52c4309123d893e1925ad83464cf1c0d5ad9e1db0e2f25e9e"
  if [ "$AGENTZERO_PIN" != "2.13" ]; then
    # The goose contract: an operator who overrides the version supplies the digest for it, or is
    # TOLD the archive is unverified. ${VAR:-} because this script runs under `set -euo pipefail`.
    if [ -n "${HR_AGENTZERO_SHA256:-}" ]; then
      az_sha="$HR_AGENTZERO_SHA256"
    else
      echo "[harnessrouter] WARN: HR_AGENTZERO_VERSION=$AGENTZERO_PIN overrides the pinned 2.13, and no"
      echo "[harnessrouter]       HR_AGENTZERO_SHA256 was given — this Agent Zero archive is UNVERIFIED."
      az_sha=""
    fi
  fi
  az_tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/agent0ai/agent-zero/archive/refs/tags/v${AGENTZERO_PIN}.tar.gz" \
      -o "$az_tmp/a0.tar.gz" || { rm -rf "$az_tmp"; return 1; }
  if [ -n "$az_sha" ]; then
    az_have="$(sha256sum "$az_tmp/a0.tar.gz" | awk '{print $1}')"
    if [ "$az_sha" != "$az_have" ]; then
      echo "Agent Zero $AGENTZERO_PIN: archive digest mismatch (want $az_sha, have $az_have)"
      rm -rf "$az_tmp"; return 1
    fi
  fi
  mkdir "$az_tmp/x" && tar -xzf "$az_tmp/a0.tar.gz" -C "$az_tmp/x" --strip-components=1 \
    || { rm -rf "$az_tmp"; return 1; }
  [ -f "$az_tmp/x/agent.py" ] && [ -f "$az_tmp/x/requirements.txt" ] \
    || { echo "the Agent Zero archive holds no agent.py/requirements.txt"; rm -rf "$az_tmp"; return 1; }
  grep -vE '^[[:space:]]*(#|$)' "$az_tmp/x/requirements.txt" | sed 's/[[:space:]]*#.*$//' \
    | grep -viE "$AGENTZERO_EXCLUDE" > "$az_tmp/requirements.harness.txt"
  echo "ipython==${HR_AGENTZERO_IPYTHON_VERSION:-9.17.1}" >> "$az_tmp/requirements.harness.txt"
  rm -rf "$TOOLS/agentzero-venv" "$TOOLS/agentzero-src"
  "${HR_AGENTZERO_BASE_PYTHON:-python3}" -m venv "$TOOLS/agentzero-venv" \
    || { rm -rf "$az_tmp" "$TOOLS/agentzero-venv"; return 1; }
  # The measured tree, not whatever the index resolves today: upstream floors a third of its
  # requirements and pins no transitive dependency. The constraints describe 2.13 and nothing else,
  # so an overridden version resolves freely (and says so).
  az_constraints=()
  if [ "$AGENTZERO_PIN" = "2.13" ] && [ -f /app/runner/agentzero-constraints.txt ]; then
    az_constraints=(-c /app/runner/agentzero-constraints.txt)
  else
    echo "[harnessrouter]       Agent Zero's dependencies resolve unconstrained (no measured set for $AGENTZERO_PIN)."
  fi
  "$TOOLS/agentzero-venv/bin/pip" install -q --no-cache-dir --disable-pip-version-check \
      -r "$az_tmp/requirements.harness.txt" "${az_constraints[@]}" \
    || { rm -rf "$az_tmp" "$TOOLS/agentzero-venv"; return 1; }
  mv "$az_tmp/x" "$TOOLS/agentzero-src" && rm -rf "$az_tmp"
  # Turns run as the session's uid, which cannot write here: compile now, or every turn pays for it.
  "$TOOLS/agentzero-venv/bin/python" -m compileall -q "$TOOLS/agentzero-src" >/dev/null 2>&1 || true
  chmod -R a+rX "$TOOLS/agentzero-src" "$TOOLS/agentzero-venv"
  # Prove the framework imports from the tree the way the driver imports it — the core, the
  # terminal tool the base's work goes through, the MCP client — before declaring the install good.
  # An excluded package that a kept module still needed fails HERE, not on a live turn.
  ( cd "$TOOLS/agentzero-src" && "$TOOLS/agentzero-venv/bin/python" -c '
import sys, types
st = types.ModuleType("sentence_transformers"); st.SentenceTransformer = object
sys.modules["sentence_transformers"] = st
sys.path.insert(0, ".")
sys.argv = [sys.argv[0], "--dockerized=true"]
import agent, initialize  # noqa: F401 - the loop and its config
import helpers.mcp_handler, helpers.persist_chat, helpers.tool_policy  # noqa: F401
import plugins._code_execution.tools.code_execution_tool  # noqa: F401 - paramiko, the pty
import plugins._text_editor.tools.text_editor  # noqa: F401
import IPython  # noqa: F401 - the python runtime
' ) || { rm -rf "$TOOLS/agentzero-venv" "$TOOLS/agentzero-src"; return 1; }
  # A check that left state behind in the shared tree (a usr/ from an import) would become every
  # workspace's; the driver gives each workspace its own usr/.
  rm -rf "$TOOLS/agentzero-src/usr" "$TOOLS/agentzero-src/tmp"
  # Written LAST, the aider pattern: the marker is what the boot compares against the pin, so a
  # half-built install is rebuilt rather than trusted.
  printf '#!/bin/sh\necho %s\n' "$AGENTZERO_PIN" > "$TOOLS/agentzero-venv/bin/agentzero-ready" \
    && chmod 755 "$TOOLS/agentzero-venv/bin/agentzero-ready"
}

install_openhands() {
  oh_py="${HR_OPENHANDS_BASE_PYTHON:-python3}"
  "$oh_py" -m venv "$TOOLS/openhands-venv" || return 1
  "$TOOLS/openhands-venv/bin/pip" install -q --disable-pip-version-check \
    "openhands-agent-server==${HR_OPENHANDS_VERSION:-1.49.2}" \
    "openhands-tools==${HR_OPENHANDS_VERSION:-1.49.2}" \
    "openhands-sdk==${HR_OPENHANDS_VERSION:-1.49.2}" \
    "litellm==${HR_OPENHANDS_LITELLM_VERSION:-1.94.3}" || return 1
  # Prove the server can actually START, and that the litellm pin still buys what it is for, before
  # declaring the install good. Importing its api module is what catches the undeclared dependencies
  # above: the failure they cause is an import error at the first live turn, not a pip error here.
  "$TOOLS/openhands-venv/bin/python" -c '
import sys
import libtmux  # noqa: F401 — undeclared by the server, brought by openhands-tools
import openhands.agent_server.api  # noqa: F401 — the module the server boots from
import importlib.metadata as md
want = sys.argv[1]
have = md.version("openhands-agent-server")
if have != want:
    sys.exit("openhands-agent-server %s installed, wanted %s" % (have, want))
# The litellm pin is asserted by BEHAVIOUR, not by version, because the version is only how this
# pair happens to be broken today: build the wrapper the way a cached prompt does and check that
# the existence test the SDK uses still agrees with the attribute. A pin bumped past 1.95.0 fails the
# image here instead of failing every follow-up turn on a provider that reports prompt caching.
from litellm.types.utils import PromptTokensDetailsWrapper
details = PromptTokensDetailsWrapper(cached_tokens=1)
if "cache_creation_tokens" in details.model_fields_set and not hasattr(
        details, "cache_creation_tokens"):
    sys.exit("litellm %s and openhands-sdk %s disagree about cache_creation_tokens; "
             "hold litellm below 1.95.0" % (md.version("litellm"), md.version("openhands-sdk")))
' "${HR_OPENHANDS_VERSION:-1.49.2}" || return 1
  command -v tmux >/dev/null 2>&1 || { echo "openhands: the tmux binary is missing"; return 1; }
}

install_kimi() {
  case "$(uname -m)" in
    x86_64)        km_arch="x64";   km_sha="ebc1ad504e458d66f0cc57d4e9d709a2060647f5b89d4e21026903b96204c3ed" ;;
    aarch64|arm64) km_arch="arm64"; km_sha="870fdb2fc45622fed92753bc4995ff80ba02e15a6304b396b5a70df1c7a23174" ;;
    *) echo "unsupported architecture $(uname -m) for kimi"; return 1 ;;
  esac
  if [ "$KIMI_PIN" != "2.0.0" ]; then
    # Same contract as goose's: an operator who overrides the version supplies the digest for the
    # version they chose, or is TOLD the archive is unverified. Read as ${VAR:-} because this
    # script runs under `set -euo pipefail`.
    if [ -n "${HR_KIMI_SHA256:-}" ]; then
      km_sha="$HR_KIMI_SHA256"
    else
      echo "[harnessrouter] WARN: HR_KIMI_VERSION=$KIMI_PIN overrides the pinned 2.0.0, and no"
      echo "[harnessrouter]       HR_KIMI_SHA256 was given — this kimi archive is UNVERIFIED."
      km_sha=""
    fi
  fi
  km_url="https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai%2Fkimi-code%40${KIMI_PIN}/kimi-code-linux-${km_arch}.tar.gz"
  km_tmp="$(mktemp -d)"
  curl -fsSL "$km_url" -o "$km_tmp/kimi.tar.gz" || { rm -rf "$km_tmp"; return 1; }
  if [ -n "$km_sha" ]; then
    km_have="$(sha256sum "$km_tmp/kimi.tar.gz" | awk '{print $1}')"
    if [ "$km_sha" != "$km_have" ]; then
      echo "kimi $KIMI_PIN: archive digest mismatch for $km_arch (want $km_sha, have $km_have)"
      rm -rf "$km_tmp"; return 1
    fi
  fi
  mkdir "$km_tmp/x" && tar -xzf "$km_tmp/kimi.tar.gz" -C "$km_tmp/x" || { rm -rf "$km_tmp"; return 1; }
  km_bin="$(find "$km_tmp/x" -type f -name kimi -perm -u+x | head -n 1)"
  [ -n "$km_bin" ] || { echo "release archive contained no kimi binary"; rm -rf "$km_tmp"; return 1; }
  mkdir -p "$TOOLS/bin" && install -m 755 "$km_bin" "$TOOLS/bin/kimi" \
    || { rm -rf "$km_tmp"; return 1; }
  rm -rf "$km_tmp"
}


install_minimax() {
  mm_sha="b83a27e2f8373c755f26a1dc02cf8ba1c1f1a1a9d889d752ff5527fb5af2f1c0"
  if [ "$MINIMAX_PIN" != "0.5.4" ]; then
    # kimi's contract: an operator who overrides the version supplies the digest, or is TOLD the
    # archive is unverified. ${VAR:-} because this script runs under `set -euo pipefail`.
    if [ -n "${HR_MINIMAX_SHA256:-}" ]; then
      mm_sha="$HR_MINIMAX_SHA256"
    else
      echo "[harnessrouter] WARN: HR_MINIMAX_VERSION=$MINIMAX_PIN overrides the pinned 0.5.4, and no"
      echo "[harnessrouter]       HR_MINIMAX_SHA256 was given — this MiniMax Code archive is UNVERIFIED."
      mm_sha=""
    fi
  fi
  mm_tmp="$(mktemp -d)"
  mm_tgz="$mm_tmp/minimax-code-${MINIMAX_PIN}.tar.gz"
  curl -fsSL --proto '=https' \
    "https://github.com/MiniMax-AI/minimax-code/releases/download/v${MINIMAX_PIN}/minimax-code-${MINIMAX_PIN}.tar.gz" \
    -o "$mm_tgz" || { rm -rf "$mm_tmp"; return 1; }
  if [ -n "$mm_sha" ]; then
    mm_have="$(sha256sum "$mm_tgz" | awk '{print $1}')"
    if [ "$mm_sha" != "$mm_have" ]; then
      echo "minimax $MINIMAX_PIN: archive digest mismatch (want $mm_sha, have $mm_have)"
      rm -rf "$mm_tmp"; return 1
    fi
  fi
  # Upstream's install form: optional deps included, install scripts allowed for better-sqlite3 (its
  # prebuilt native binding; the CLI's session store is sqlite). An npm that predates allow-scripts
  # warns about the flag and runs scripts anyway.
  npm install -g --prefix "$TOOLS" --no-audit --no-fund --include=optional \
    --allow-scripts=better-sqlite3 "$mm_tgz" || { rm -rf "$mm_tmp"; return 1; }
  rm -rf "$mm_tmp"
}

install_kilo() {
  case "$(uname -m)" in
    x86_64)        kl_arch="x64";   kl_sha="6d48503b000d3d904d15950b63e254653c450800647344ac0f3de4e8a7f98835" ;;
    aarch64|arm64) kl_arch="arm64"; kl_sha="516f81a81d3605cecae61dddf4da548da403b9f8993a06bb799d12b6fc6e7ac4" ;;
    *) echo "unsupported architecture $(uname -m) for kilo"; return 1 ;;
  esac
  if [ "$KILO_PIN" != "7.8.1" ]; then
    # kimi's contract: an operator who overrides the version supplies the digest, or is TOLD the
    # archive is unverified. ${VAR:-} because this script runs under `set -euo pipefail`.
    if [ -n "${HR_KILO_SHA256:-}" ]; then
      kl_sha="$HR_KILO_SHA256"
    else
      echo "[harnessrouter] WARN: HR_KILO_VERSION=$KILO_PIN overrides the pinned 7.8.1, and no"
      echo "[harnessrouter]       HR_KILO_SHA256 was given — this kilo archive is UNVERIFIED."
      kl_sha=""
    fi
  fi
  kl_url="https://github.com/Kilo-Org/kilocode/releases/download/v${KILO_PIN}/kilo-linux-${kl_arch}.tar.gz"
  kl_tmp="$(mktemp -d)"
  curl -fsSL "$kl_url" -o "$kl_tmp/kilo.tar.gz" || { rm -rf "$kl_tmp"; return 1; }
  if [ -n "$kl_sha" ]; then
    kl_have="$(sha256sum "$kl_tmp/kilo.tar.gz" | awk '{print $1}')"
    if [ "$kl_sha" != "$kl_have" ]; then
      echo "kilo $KILO_PIN: archive digest mismatch for $kl_arch (want $kl_sha, have $kl_have)"
      rm -rf "$kl_tmp"; return 1
    fi
  fi
  # Unpacked BESIDE its destination, on the tools volume, so the swap below is a rename and not a
  # 228 MB copy across filesystems that a full disk or a kill could leave half done with the old
  # install already gone. Root's tar keeps the archive's owners and modes; a session uid must be
  # able to read the helpers, so neither is trusted.
  kl_stage="$(mktemp -d -p "$TOOLS" .kilo-stage.XXXXXX)" || { rm -rf "$kl_tmp"; return 1; }
  tar -xzf "$kl_tmp/kilo.tar.gz" --no-same-owner -C "$kl_stage" || { rm -rf "$kl_tmp" "$kl_stage"; return 1; }
  rm -rf "$kl_tmp"; kl_tmp="$kl_stage"
  [ -f "$kl_stage/kilo" ] || { echo "release archive contained no kilo binary"; rm -rf "$kl_stage"; return 1; }
  chmod -R a+rX "$kl_stage" && chmod 755 "$kl_stage" "$kl_stage/kilo" || { rm -rf "$kl_stage"; return 1; }
  # The whole directory, replaced as a unit: the binary finds its helpers beside itself.
  rm -rf "$TOOLS/kilo" && mv "$kl_stage" "$TOOLS/kilo" || { rm -rf "$kl_stage"; return 1; }
  # On PATH as `kilo` through a wrapper rather than a symlink, so the binary's own path (and with it
  # the helpers beside it) is the real directory whatever the runtime makes of a link.
  mkdir -p "$TOOLS/bin" && printf '#!/bin/sh\nexec "%s/kilo/kilo" "$@"\n' "$TOOLS" > "$TOOLS/bin/kilo" \
    && chmod 755 "$TOOLS/bin/kilo" || { rm -rf "$kl_tmp"; return 1; }
  rm -rf "$kl_tmp"
}

install_grok() {
  case "$(uname -m)" in
    x86_64)        gk_arch="x86_64";  gk_sha="9ce03ed23e16ea01072b4496263d6213a27899e1e3e107f008d36edf82e70407" ;;
    aarch64|arm64) gk_arch="aarch64"; gk_sha="7c0b8c973af6a78e2037f19ed93033471b8c5e722f9ff04b86b092e066e60d74" ;;
    *) echo "unsupported architecture $(uname -m) for grok"; return 1 ;;
  esac
  if [ "$GROK_PIN" != "1.0.41" ]; then
    # The goose/kimi contract: an override brings the digest for the version it chose, or is TOLD
    # the binary is unverified. ${VAR:-} because this script runs under `set -euo pipefail`.
    if [ -n "${HR_GROK_SHA256:-}" ]; then
      gk_sha="$HR_GROK_SHA256"
    else
      echo "[harnessrouter] WARN: HR_GROK_VERSION=$GROK_PIN overrides the pinned 1.0.41, and no"
      echo "[harnessrouter]       HR_GROK_SHA256 was given — this grok binary is UNVERIFIED."
      gk_sha=""
    fi
  fi
  gk_tmp="$(mktemp -d)"
  curl -fsSL "https://x.ai/cli/grok-${GROK_PIN}-linux-${gk_arch}" -o "$gk_tmp/grok" \
    || curl -fsSL "https://storage.googleapis.com/grok-build-public-artifacts/cli/grok-${GROK_PIN}-linux-${gk_arch}" -o "$gk_tmp/grok" \
    || { rm -rf "$gk_tmp"; return 1; }
  if [ -n "$gk_sha" ]; then
    gk_have="$(sha256sum "$gk_tmp/grok" | awk '{print $1}')"
    if [ "$gk_sha" != "$gk_have" ]; then
      echo "grok $GROK_PIN: binary digest mismatch for $gk_arch (want $gk_sha, have $gk_have)"
      rm -rf "$gk_tmp"; return 1
    fi
  fi
  mkdir -p "$TOOLS/bin" && install -m 755 "$gk_tmp/grok" "$TOOLS/bin/grok" \
    || { rm -rf "$gk_tmp"; return 1; }
  rm -rf "$gk_tmp"
}


install_goose() {
  case "$(uname -m)" in
    x86_64)        gs_arch="x86_64";  gs_sha="6389eea4440178de006fa148d466ac411021315ff7f72b1014beae2d445851e2" ;;
    aarch64|arm64) gs_arch="aarch64"; gs_sha="febd71a6a25c3aff7dbcf566f78d2864e87d886c33c4ef1fee2f67fedd334063" ;;
    *) echo "unsupported architecture $(uname -m) for goose"; return 1 ;;
  esac
  gs_ver="${HR_GOOSE_VERSION:-1.50.0}"; gs_ver="${gs_ver#v}"
  if [ "$gs_ver" != "1.50.0" ]; then
    # The pinned digests describe 1.50.0 and nothing else. An operator overriding the version
    # supplies the digest for the version they chose, or is TOLD the download is unverified —
    # silently skipping the check while the code above advertises one is the dishonest option.
    if [ -n "${HR_GOOSE_SHA256:-}" ]; then
      gs_sha="$HR_GOOSE_SHA256"
    else
      echo "[harnessrouter] WARN: HR_GOOSE_VERSION=$gs_ver overrides the pinned 1.50.0, and no"
      echo "[harnessrouter]       HR_GOOSE_SHA256 was given — this goose archive is UNVERIFIED."
      gs_sha=""
    fi
  fi
  gs_url="https://github.com/aaif-goose/goose/releases/download/v${gs_ver}/goose-${gs_arch}-unknown-linux-gnu.tar.gz"
  gs_tmp="$(mktemp -d)"
  curl -fsSL "$gs_url" -o "$gs_tmp/goose.tar.gz" || { rm -rf "$gs_tmp"; return 1; }
  if [ -n "$gs_sha" ]; then
    gs_have="$(sha256sum "$gs_tmp/goose.tar.gz" | awk '{print $1}')"
    if [ "$gs_sha" != "$gs_have" ]; then
      echo "goose $gs_ver: archive digest mismatch for $gs_arch (want $gs_sha, have $gs_have)"
      rm -rf "$gs_tmp"; return 1
    fi
  fi
  tar -xzf "$gs_tmp/goose.tar.gz" -C "$gs_tmp" || { rm -rf "$gs_tmp"; return 1; }
  [ -f "$gs_tmp/goose" ] || { echo "release archive contained no goose binary"; rm -rf "$gs_tmp"; return 1; }
  mkdir -p "$TOOLS/bin" && install -m 755 "$gs_tmp/goose" "$TOOLS/bin/goose" \
    || { rm -rf "$gs_tmp"; return 1; }
  rm -rf "$gs_tmp"
}

# omp (Oh My Pi, MIT) ships standalone prebuilt binaries on GitHub releases, with a SHA256SUMS.txt
# beside them. Pinned EXACTLY, like every other backend here: upstream releases almost daily
# (18.1.8 through 18.1.13 in five days), and 18.1.13 is the release the runner's omp code was
# measured against (flags, the JSON event stream, the agent-dir env, resume by id, --tools). A
# silent `latest` re-gambles all of it; the checksum makes the download the release's own bytes.
install_omp() {
  case "$(uname -m)" in
    x86_64)        omp_arch="x64" ;;
    aarch64|arm64) omp_arch="arm64" ;;
    *) echo "unsupported architecture $(uname -m) for omp"; return 1 ;;
  esac
  omp_ver="${HR_OMP_VERSION:-18.1.13}"; omp_ver="${omp_ver#v}"
  omp_base="https://github.com/can1357/oh-my-pi/releases/download/v${omp_ver}"
  omp_tmp="$(mktemp -d)"
  curl -fsSL "$omp_base/omp-linux-$omp_arch" -o "$omp_tmp/omp" || { rm -rf "$omp_tmp"; return 1; }
  curl -fsSL "$omp_base/SHA256SUMS.txt" -o "$omp_tmp/SHA256SUMS.txt" || { rm -rf "$omp_tmp"; return 1; }
  want="$(grep " omp-linux-$omp_arch\$" "$omp_tmp/SHA256SUMS.txt" | awk '{print $1}')"
  have="$(sha256sum "$omp_tmp/omp" | awk '{print $1}')"
  if [ -z "$want" ] || [ "$want" != "$have" ]; then
    echo "omp $omp_ver: checksum mismatch for omp-linux-$omp_arch (want ${want:-none}, have $have)"; rm -rf "$omp_tmp"; return 1
  fi
  mkdir -p "$TOOLS/bin" && install -m 755 "$omp_tmp/omp" "$TOOLS/bin/omp"; rm -rf "$omp_tmp"
}

# Run an install and, if it fails, SAY WHY.
#
# This was `>/dev/null 2>&1 || true`, and the silence cost a day of someone's life: a root-owned
# npm cache baked into the image made every `npm install` fail with EACCES, and the only trace was
# the "requested but not installed" line further down — which reads like a configuration choice,
# not a broken install. An optional step may fail without stopping start-up; it may not fail
# without leaving the reason where the person looking will find it.
try_install() {
  label="$1"; shift
  log="$(mktemp)"
  if "$@" >"$log" 2>&1; then rm -f "$log"; return 0; fi
  echo "[harnessrouter] WARN: could not install $label — it will not be available:"
  tail -n 12 "$log" | sed 's/^/[harnessrouter]   /'
  rm -f "$log"
  return 1
}

install_backends() {
  mkdir -p "$TOOLS"

  # -g is what creates $TOOLS/bin/<cmd>; --prefix alone just drops a node_modules tree with no
  # entry point, which npm reports as success.
  # Claude Code is installed at a PINNED version and moved to it when the volume holds another:
  # a model can require a minimum CLI (Claude Opus 5.5 needs 2.1.280; the API refuses older ones
  # with "version 2.1.280 or newer is required"), and a volume that installed the CLI once, months
  # ago, would otherwise never learn that. The pin is what this release was verified with.
  if wanted claude; then
    have=""
    [ -x "$(backend_bin claude)" ] && have="$("$(backend_bin claude)" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    if [ "$have" != "$CLAUDE_CODE_VERSION" ]; then
      echo "[harnessrouter] installing Claude Code $CLAUDE_CODE_VERSION (Anthropic's terms apply)${have:+, replacing $have}…"
      try_install "Claude Code" npm install -g --prefix "$TOOLS" --no-audit --no-fund "@anthropic-ai/claude-code@$CLAUDE_CODE_VERSION" || true
    fi
  fi

  # opencode is MIT, so unlike Claude Code and hermes it COULD be baked into the image. It is
  # installed here anyway so that every backend has ONE install path.
  if wanted opencode && [ ! -x "$(backend_bin opencode)" ]; then
    echo "[harnessrouter] installing opencode (MIT)…"
    try_install "opencode" install_opencode || true
  fi

  # `kilo --version` prints the bare version, so a volume holding another one is replaced in place.
  if wanted kilo && [ "$("$(backend_bin kilo)" --version 2>/dev/null | head -n 1)" != "$KILO_PIN" ]; then
    echo "[harnessrouter] installing Kilo CLI $KILO_PIN (MIT, version-pinned)…"
    try_install "Kilo CLI" install_kilo || true
  fi

  if wanted qwen && [ ! -x "$(backend_bin qwen)" ]; then
    echo "[harnessrouter] installing Qwen Code (Apache-2.0)…"
    try_install "Qwen Code" npm install -g --prefix "$TOOLS" --no-audit --no-fund @qwen-code/qwen-code || true
  fi

  if wanted gemini && [ ! -x "$(backend_bin gemini)" ]; then
    echo "[harnessrouter] installing Gemini CLI (Apache-2.0)…"
    # Pinned, same rationale as cline's: 0.58.0 is the release runner/server.py's gemini code was
    # verified against — the real stream-json field names (tool_name/tool_id/parameters, not the
    # guessed id/name/input a first pass shipped with), --approval-mode/--skip-trust being
    # load-bearing, and --resume latest's semantics all came from reading THIS version's own
    # source. A silent bump to `latest` re-gambles all of it on a release nobody has checked.
    try_install "Gemini CLI" npm install -g --prefix "$TOOLS" --no-audit --no-fund "@google/gemini-cli@${HR_GEMINI_VERSION:-0.58.0}" || true
  fi

  if wanted cline && [ ! -x "$(backend_bin cline)" ]; then
    echo "[harnessrouter] installing Cline (Apache-2.0)…"
    # Pinned: 3.0.60 is the release every behavior in runner/server.py was verified against —
    # the settings-file auth wiring, the one-word-prompt parse, and the broken --json --id resume
    # this port deliberately does not use. A silent major bump would re-gamble all three.
    try_install "Cline" npm install -g --prefix "$TOOLS" --no-audit --no-fund "cline@${HR_CLINE_VERSION:-3.0.60}" || true
  fi

  # Pinned, and re-pinned on every start: an install from a fresh volume used to take whatever
  # npm served that day (an August volume ran 0.147, a September one 0.154, on the same image), so
  # the runner's codex behaviour was measured against a version the operator could not name.
  # The pin is the version the support matrix ran on; bumping it is a PR with a matrix rerun.
  CODEX_PIN="${HR_CODEX_VERSION:-0.154.0}"
  if wanted codex && [ "$("$(backend_bin codex)" --version 2>/dev/null | awk '{print $2}')" != "$CODEX_PIN" ]; then
    echo "[harnessrouter] installing Codex $CODEX_PIN (Apache-2.0, version-pinned)…"
    try_install "Codex" npm install -g --prefix "$TOOLS" --no-audit --no-fund "@openai/codex@$CODEX_PIN" || true
  fi

  if wanted pi && [ ! -x "$(backend_bin pi)" ]; then
    echo "[harnessrouter] installing Pi (MIT)…"
    # --ignore-scripts is pi's own documented install form.
    try_install "Pi" npm install -g --prefix "$TOOLS" --no-audit --no-fund --ignore-scripts \
        @earendil-works/pi-coding-agent || true
  fi
  # The MCP adapter is a pi extension (github.com/nicobailon/pi-mcp-adapter): pi deliberately
  # ships without MCP, and the runner mounts this adapter via -e only on turns that configure MCP
  # servers. PINNED, and re-pinned on every start, because the adapter's major decides which file
  # it reads: 2.x read <agent dir>/mcp.json, 3.x reads <agent dir>/mcp-adapter.json and not the
  # old name at all (its README). The runner writes the 3.x name; a volume that first booted on
  # 2.x is moved here, and a fresh volume no longer takes whatever npm serves that day.
  PI_MCP_PIN="${HR_PI_MCP_ADAPTER_VERSION:-3.1.0}"
  if wanted pi && [ -x "$(backend_bin pi)" ]; then
    have_adapter="$(node -e "console.log(require('$TOOLS/lib/node_modules/pi-mcp-adapter/package.json').version)" 2>/dev/null || true)"
    if [ "$have_adapter" != "$PI_MCP_PIN" ]; then
      echo "[harnessrouter] installing pi-mcp-adapter $PI_MCP_PIN (MIT, version-pinned)${have_adapter:+, replacing $have_adapter}…"
      try_install "pi-mcp-adapter" npm install -g --prefix "$TOOLS" --no-audit --no-fund --ignore-scripts "pi-mcp-adapter@$PI_MCP_PIN" || true
    fi
  fi

  if wanted omp && [ ! -x "$(backend_bin omp)" ]; then
    echo "[harnessrouter] installing Oh My Pi (MIT)…"
    try_install "Oh My Pi" install_omp || true
  fi

  if wanted goose && [ ! -x "$(backend_bin goose)" ]; then
    echo "[harnessrouter] installing goose (Apache-2.0)…"
    try_install "goose" install_goose || true
  fi

  # `kimi --version` prints the bare version on Kimi Code CLI ("2.0.0") and "kimi, version 1.50.0" on
  # its predecessor, so comparing it to the pin both installs a missing binary and replaces the old
  # product on a volume that was first started by 0.18.0.
  # In the default set, for the reason aider is: the console offers every base the gateway's
  # catalogue lists, and a listed base that is not installed fails on its first task. An operator
  # who does not want the 666 MB leaves it out of HR_BACKENDS, the switch every backend has.
  #
  # THE GUARD COMPARES THE VERSION, not the file, for the reason dsh's venv already carries: the
  # venv lives on the data volume and outlives the image. A volume first started by an earlier
  # build of this branch held an `openhands-venv` whose python was perfectly executable and whose
  # contents were the DEPRECATED CLI's stack — openhands 1.16.0 pinning openhands-sdk 1.21.0 — so
  # an existence check skipped the install and every turn died on
  # `No module named 'openhands.sdk.marketplace.registration'`. Caught by the first column, not by
  # a test. A mismatch rebuilds the venv from scratch; conversations live in the workspace, not in
  # it, so nothing of a session is lost.
  OPENHANDS_PIN="${HR_OPENHANDS_VERSION:-1.49.2}"
  # BOTH pins are compared, because the venv outlives the image in the same way for each: a volume
  # whose openhands-venv was built before litellm was pinned holds the right agent-server and the
  # wrong litellm, and an agent-server-only comparison would skip the install and hand that volume
  # back the follow-up failures the pin exists to remove.
  OPENHANDS_LITELLM_PIN="${HR_OPENHANDS_LITELLM_VERSION:-1.94.3}"
  # Probed only when there IS something to probe: asking a path that does not exist for its version
  # is a 127 that takes the whole entrypoint down with it, which is how this line first shipped.
  oh_have=""
  if [ -x "$(backend_bin openhands)" ]; then
    oh_have="$("$(backend_bin openhands)" -c \
      'import importlib.metadata as m; print(m.version("openhands-agent-server"), m.version("litellm"))' 2>/dev/null || true)"
  fi
  if wanted openhands && [ "$oh_have" != "$OPENHANDS_PIN $OPENHANDS_LITELLM_PIN" ]; then
    rm -rf "$TOOLS/openhands-venv"
    echo "[harnessrouter] installing OpenHands agent-server $OPENHANDS_PIN (MIT) — ~666 MB, this takes a minute…"
    try_install "OpenHands" install_openhands || true
  fi

  s1_have=""
  if [ -x "$(backend_bin systemone)" ]; then
    s1_have="$("$(backend_bin systemone)" -c 'import systemone_harness as s; print(s.__version__)' 2>/dev/null || true)"
  fi
  if wanted systemone && [ "$s1_have" != "$SYSTEMONE_PIN" ]; then
    rm -rf "$TOOLS/systemone-venv"
    echo "[harnessrouter] installing System One Harness $SYSTEMONE_PIN (Apache-2.0)…"
    try_install "System One Harness" install_systemone || true
  fi
  if wanted systemone && [ -x "$TOOLS/systemone-venv/bin/playwright" ]; then
    chromium_libs || echo "[harnessrouter]   WARNING: Chromium's system libraries could not be installed; the System One base's browser environments will not start until they are (retried on the next start)"
  fi

  # In the default set, for the reason aider is: the console offers every base the gateway's
  # catalogue lists, and a listed base that is not installed fails on its first task. ~90 MB.
  # The marker names the version the venv was built for, so a pin bump rebuilds it on a volume
  # that already has one; the session lives in the workspace, not in the venv.
  if wanted cheetahclaws && [ "$("$(backend_bin cheetahclaws)" 2>/dev/null)" != "$CHEETAHCLAWS_PIN" ]; then
    echo "[harnessrouter] installing CheetahClaws $CHEETAHCLAWS_PIN (Apache-2.0)…"
    if [ -z "$CHEETAHCLAWS_SHA256" ]; then
      # Said HERE, outside try_install, which keeps an installer's output only when it fails.
      echo "[harnessrouter] WARN: HR_CHEETAHCLAWS_VERSION=$CHEETAHCLAWS_PIN overrides the pinned 3.5.88, and no"
      echo "[harnessrouter]       HR_CHEETAHCLAWS_SHA256 was given — this cheetahclaws wheel is UNVERIFIED."
    fi
    try_install "CheetahClaws" install_cheetahclaws || true
  fi
  [ -x "$TOOLS/cheetahclaws-venv/bin/python" ] && export HR_CHEETAHCLAWS_PYTHON="$TOOLS/cheetahclaws-venv/bin/python"
  if wanted agentzero && [ "$("$TOOLS/agentzero-venv/bin/agentzero-ready" 2>/dev/null)" != "$AGENTZERO_PIN" ]; then
    echo "[harnessrouter] installing Agent Zero $AGENTZERO_PIN (MIT) — ~640 MB, this takes a minute or two…"
    try_install "Agent Zero" install_agentzero || true
  fi

  if wanted kimi && [ "$("$(backend_bin kimi)" --version 2>/dev/null | head -n 1)" != "$KIMI_PIN" ]; then
    echo "[harnessrouter] installing Kimi Code CLI $KIMI_PIN (MIT, version-pinned)…"
    try_install "Kimi Code CLI" install_kimi || true
  fi

  # `mcode --version` prints the bare version ("0.5.4"), so a volume holding another one is moved
  # to the pin in place.
  if wanted minimax && [ "$("$(backend_bin minimax)" --version 2>/dev/null | head -n 1)" != "$MINIMAX_PIN" ]; then
    echo "[harnessrouter] installing MiniMax Code $MINIMAX_PIN (MIT, version-pinned)…"
    try_install "MiniMax Code" install_minimax || true
  fi

  # `grok --version` prints "grok 1.0.41 (4220f3b224a6)"; comparing the version word both installs a
  # missing binary and replaces one a pin bump left behind on the volume.
  if wanted grok && [ "$("$(backend_bin grok)" --version 2>/dev/null | head -n 1 | awk '{print $2}')" != "$GROK_PIN" ]; then
    echo "[harnessrouter] installing Grok Build $GROK_PIN (Apache-2.0, version- and digest-pinned)…"
    try_install "Grok Build" install_grok || true
  fi

  # The largest install of the set: ~735 MB and about ninety seconds on a fresh volume
  # (tree-sitter-language-pack 351 MB, scipy 100, numpy 57). In the default list all the same,
  # because the console offers every base the gateway's catalogue lists and a base that is listed
  # but not installed fails on its first task; an operator who does not want it leaves it out of
  # HR_BACKENDS, the same switch every backend has.
  if wanted aider && [ "$("$TOOLS/aider-venv/bin/aider-ready" 2>/dev/null)" != "$AIDER_PIN" ]; then
    echo "[harnessrouter] installing Aider $AIDER_PIN (Apache-2.0) — ~735 MB, this takes a minute…"
    try_install "Aider" install_aider || true
  fi

  # The dsh venv lives on the data volume, so a pin bump in the image must reach a volume that
  # already has a venv: dsh-ready names the version it was built for, and a mismatch rebuilds
  # the venv (sessions live under ~/.dsh, not in it). The 0.1.0rc7 -> 0.1.2rc1 move is where
  # this was learned: the image changed and every existing volume would have kept rc7.
  DSH_PIN="0.1.2rc1"
  if wanted dsh && [ "$("$(backend_bin dsh)" 2>/dev/null)" != "$DSH_PIN" ]; then
    echo "[harnessrouter] installing DeepSeek Harness $DSH_PIN (MIT, developer preview — version-pinned)…"
    # Pinned EXACTLY, not 'latest': upstream is a developer preview that warns of breaking
    # changes, and the runner's driver/normalizer are written against these bytes. An upgrade
    # is an adapter-compatibility change that lands through a PR, never through a fresh volume
    # pulling a newer wheel. Own venv: its dependency tree must not fight hermes's.
    rm -rf "$TOOLS/dsh-venv"
    try_install "DeepSeek Harness" sh -c "\"$PY\" -m venv \"$TOOLS/dsh-venv\" \
        && \"$TOOLS/dsh-venv/bin/pip\" install --no-cache-dir -q \
             'deepseek-harness-sdk==$DSH_PIN' 'deepseek-harness-runtime-bin==$DSH_PIN' pyyaml \
        && \"$TOOLS/dsh-venv/bin/python\" -c 'import deepseek_harness, deepseek_harness_runtime, yaml; deepseek_harness_runtime.bundled_runtime_path()' \
        && printf '#!/bin/sh\necho %s\n' '$DSH_PIN' > \"$TOOLS/dsh-venv/bin/dsh-ready\" \
        && chmod +x \"$TOOLS/dsh-venv/bin/dsh-ready\"" || true
    # dsh-ready exists ONLY after the import check proved the runtime executable resolves —
    # a venv whose pip half-failed must not report the backend as available.
  fi

  if wanted hermes && [ ! -x "$(backend_bin hermes)" ]; then
    echo "[harnessrouter] installing Hermes (check its upstream license before use)…"
    # [anthropic]: hermes's own pin of the Anthropic SDK (0.87.0 for 0.19.0). A bare `anthropic`
    # resolved to the newest SDK, whose 1.x line moved to httpx2 while hermes still builds its
    # client with httpx.Timeout, so a fresh volume died on every Claude turn with "Invalid timeout
    # argument ... this SDK uses httpx2" (a customer benchmark, 2026-09-30).
    # boto3: hermes's bedrock provider imports it at call time, and lazy installs are sealed
    # below — without it baked in, every hermes turn on a bedrock-served model died with
    # "The 'boto3' package is required" after 3 retries, while the README advertised
    # bedrock -> "Claude Code, Hermes" (issue #37, measured 2026-08-27 on a fresh volume).
    try_install "Hermes" sh -c "\"$PY\" -m venv \"$TOOLS/venv\" \
        && \"$TOOLS/venv/bin/pip\" install --no-cache-dir -q \
             'hermes-agent[anthropic]==0.19.0' boto3 '$HERMES_MCP_PIN'" || true
  fi

  [ -d "$TOOLS/venv/bin" ] && export PATH="$TOOLS/venv/bin:$PATH"
  # Hermes otherwise tries to install its own dependencies mid-turn.
  export HERMES_DISABLE_LAZY_INSTALLS=1
  # `wanted hermes && verify_hermes_mcp` looks equivalent and is not: as the LAST command in the
  # function it becomes the function's exit status, so under `set -e` an instance that did not ask
  # for hermes aborted the whole entrypoint — exit 1, no message, the log ending on an install line
  # so it read as if the install had killed it. HR_BACKENDS=claude, =codex and =claude,codex were
  # all unusable, which is exactly the choice the licence note above asks people to make.
  # Where the runner finds the MCP extension to mount (-e) on pi turns with MCP servers.
  [ -d "$TOOLS/lib/node_modules/pi-mcp-adapter" ] && export HR_PI_MCP_EXT="$TOOLS/lib/node_modules/pi-mcp-adapter"
  [ -x "$TOOLS/dsh-venv/bin/python" ] && export HR_DSH_PYTHON="$TOOLS/dsh-venv/bin/python"
  if wanted hermes; then verify_hermes_mcp; fi
}

# hermes 0.19.0 gates HTTP MCP on importing `streamablehttp_client`, the name the mcp SDK
# deprecated and REMOVED in 2.0.0. With an unpinned `mcp`, pip resolves 2.0.0, that import fails,
# and hermes disables HTTP MCP entirely — every remote MCP server a user configures is dropped with
# only a line in a log file inside the workspace. The agent then answers "I can't access that tool",
# which reads as a model refusal rather than a broken install.
#
# So the SDK is pinned below 2.0, and the pin is VERIFIED rather than assumed: lazy installs are
# sealed, so hermes cannot repair this itself, and a volume provisioned before the pin still has
# the broken version. Checking the exact symbol hermes checks turns a silent capability loss into
# one line on start-up — and repairs it in place.
HERMES_MCP_PIN="${HERMES_MCP_PIN:-mcp>=1.9,<2}"

verify_hermes_bedrock() {
  # Volumes installed before boto3 joined the hermes install (issue #37) get it on next start,
  # the same repair-in-place contract verify_hermes_mcp established.
  [ -x "$TOOLS/venv/bin/python" ] || return 0
  "$TOOLS/venv/bin/python" -c "import boto3" 2>/dev/null && return 0
  echo "[harnessrouter] repairing Hermes bedrock support (boto3 missing from an older install)…"
  "$TOOLS/venv/bin/pip" install --no-cache-dir -q boto3 >/dev/null 2>&1 || true
  if "$TOOLS/venv/bin/python" -c "import boto3" 2>/dev/null; then
    echo "[harnessrouter] Hermes bedrock support restored"
  else
    echo "[harnessrouter] WARNING: Hermes cannot use the bedrock provider — boto3 could not be installed"
  fi
}

verify_hermes_mcp() {
  [ -x "$TOOLS/venv/bin/python" ] || return 0
  "$TOOLS/venv/bin/python" - <<'PYEOF' && return 0
try:
    from mcp.client.streamable_http import streamablehttp_client  # noqa: F401
except Exception:
    raise SystemExit(1)
PYEOF
  echo "[harnessrouter] repairing Hermes MCP support (installed mcp SDK lacks the transport it needs)…"
  "$TOOLS/venv/bin/pip" install --no-cache-dir -q "$HERMES_MCP_PIN" >/dev/null 2>&1 || true
  if "$TOOLS/venv/bin/python" -c "from mcp.client.streamable_http import streamablehttp_client" 2>/dev/null; then
    echo "[harnessrouter] Hermes MCP support restored"
  else
    echo "[harnessrouter] WARNING: Hermes cannot use HTTP MCP servers — remote tools will be unavailable on that backend"
  fi
}

install_backends
if wanted hermes; then verify_hermes_bedrock; fi

pids=()
cleanup() { trap - TERM INT; for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup TERM INT EXIT

avail=""; missing=""
# Derived from HR_BACKENDS, not a second hardcoded list. The literal list here missed opencode and
# reported "backends available: none" on an instance that had it installed and working.
for b in ${HR_BACKENDS//,/ }; do
  wanted "$b" || continue
  if [ -x "$(backend_bin "$b")" ]; then avail="$avail $b"; else missing="$missing $b"; fi
done
echo "[harnessrouter] data=$DATA_DIR  backends available:${avail:- none}"
if [ -n "$missing" ]; then
  echo "[harnessrouter] WARN: requested but not installed:$missing — those backends cannot run"
fi

# runner (loopback only). Root, for the per-session uid switch; HR_SESSION_UIDS=1 is the
# declaration the runner fails closed without. The console's credentials and the secret-store key
# are the product's and are not in its environment at all.
( cd /app/runner && exec env -u HR_AUTH_USER -u HR_AUTH_PASSWORD -u HR_AUTH_STORE -u HR_SECRET_KEY \
    HR_SESSION_UIDS=1 "$PY" -m uvicorn server:app --host 127.0.0.1 --port 8081 --log-level warning ) &
pids+=($!)

# gateway (loopback only), as the product. umask 077: what it creates on the volume (databases,
# blobs, the secret store) is its alone.
( cd /app/gateway && exec $AS_PRODUCT sh -c 'umask 077; exec "$0" -m uvicorn app:app --host 127.0.0.1 --port 8080 --log-level warning' "$PY" ) &
pids+=($!)

# Wait for the gateway before the UI starts serving, so a first page load never races a
# backend that is still binding.
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:8080/healthz" >/dev/null 2>&1 && break
  sleep 1
done

# UI (the only published port).
#
# Supervised, unlike the other two: changing the console password has to take effect in the
# middleware, which only reads its signing key at boot — so the profile route writes the new
# credentials and exits, and this loop brings the console back with them about a second later.
# The gateway and runner are untouched, so a task mid-turn keeps running through the blip.
#
# A crash-loop is not silent: the console is the only published port, so a UI that cannot start
# is immediately visible, and the message below says how many times it has restarted.
(
  cd /app/ui
  restarts=0
  while :; do
    HR_SESSION_KEY="$(hr_session_key)" \
    HR_AUTH_USER="$(hr_stored_user)" \
      $AS_PRODUCT sh -c 'umask 077; exec node server.js'
    status=$?
    # A clean exit is the credential change asking for a restart. Anything else is a real
    # failure, and repeating it forever would hide it — so give up and let the container die.
    if [ "$status" -ne 0 ]; then
      echo "[harnessrouter] console exited with status $status — not restarting"
      exit "$status"
    fi
    restarts=$((restarts + 1))
    echo "[harnessrouter] console restarting to pick up new credentials (restart #$restarts)"
    sleep 1
  done
) &
pids+=($!)

echo "[harnessrouter] ready on :$PORT"

# Exit as soon as ANY child exits, carrying its status out to the restart policy.
wait -n "${pids[@]}"
status=$?
echo "[harnessrouter] a process exited (status $status) — shutting down"
exit "$status"
