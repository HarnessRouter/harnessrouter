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
# Root must never read or run anything the product user can change, or a bug in the gateway or the
# console (which run as that user) becomes root at the next start (reported privately,
# GHSA-mm72-wr37-26pv). So: the image's /app is root's; root has its own HOME, where npm, pip and
# Python look for their settings; the python root runs is -I, so neither its current directory nor
# the environment can add a module; and on the volume, below, what root keeps is root's, in a
# directory where the product can create its own files but cannot move anyone else's.
export HOME=/root
AS_PRODUCT="env HOME=/home/agent setpriv --reuid=$PRODUCT --regid=$PRODUCT --init-groups"

DATA_DIR="${HR_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

# A directory root keeps on the volume. A link or a file in its place was put there by the product,
# on this image or an older one, and is removed rather than followed. Only ever called before the
# product's first process starts, so nothing can change it between the check and the use.
root_dir() {
  if [ -L "$1" ] || { [ -e "$1" ] && [ ! -d "$1" ]; }; then rm -f -- "$1"; fi
  mkdir -p "$1"
  chown root:root "$1"
}
# The same for a file root reads or writes there: root's own regular file, with no other name, or nothing.
root_file() {
  if [ -L "$1" ] || [ -e "$1" ]; then
    if [ -L "$1" ] || [ ! -f "$1" ] || [ "$(stat -c %u "$1")" != 0 ] || [ "$(stat -c %h "$1")" != 1 ]; then rm -rf -- "$1"; fi
  fi
}

# Session workspaces live on the volume so a restart doesn't discard work in flight. Created HERE
# rather than in the image: /data is a volume mount, and Docker only seeds a volume from the image
# when the volume is empty — so an image-time mkdir is invisible on every existing install.
export HARNESS_WORKSPACE="${HARNESS_WORKSPACE:-$DATA_DIR/workspaces}"
root_dir "$HARNESS_WORKSPACE"
# Which checkpoint each workspace holds, on the volume beside them: in /tmp a restart forgot it, and
# the next turn restored the last checkpoint over a workspace that had survived (#505). Beside the
# workspace root, not in it: the idle-workspace reaper treats every directory there as a session.
# The runner's own (root), like the markers it writes.
export HR_WS_MARKER_DIR="${HR_WS_MARKER_DIR:-$DATA_DIR/ws-markers}"
root_dir "$HR_WS_MARKER_DIR"
chmod 700 "$HR_WS_MARKER_DIR"

# The write-wall, in file modes. Idempotent and non-recursive, so it costs nothing on a volume
# that already has it and repairs one that predates it. Session directories themselves are owned
# by their session's uid (0700); the runner sets that as it allocates them.
# The volume's top level is root's and the product's group's, with the sticky bit: the product makes
# its databases and its stores here, and cannot rename or replace what it does not own (the tools,
# the environments, the workspaces, all of which root acts on). Sessions can pass through and no more.
chown "root:$PRODUCT" "$DATA_DIR"
chmod 1771 "$DATA_DIR"
chmod 751 "$HARNESS_WORKSPACE"                    # traversable by sessions, neither listable nor writable
# Environments (runner/environments.py): project layers built once and read by the sessions that
# name one. Root's, each environment readable by its own group and writable by none: that ownership
# is the read-only guarantee, so nothing here is handed to $PRODUCT. Both directories are
# traversable, not listable: a session reaches the environment it was told and enumerates none.
# /env holds the links sessions are told.
export HR_ENV_ROOT="${HR_ENV_ROOT:-$DATA_DIR/environments}"
root_dir "$HR_ENV_ROOT"
mkdir -p /env
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
# These are the product's, in a directory it can write, so a name here can be a link to anything, or
# a second name for a file of root's: chown and chmod would follow the one and reach the other. Only
# a real file with one name, and only a real directory, is handed over.
find "$DATA_DIR" -maxdepth 1 -type f -links 1 \( -name '*.db' -o -name '*.db-*' -o -name selfhost-auth.json \) \
  -exec chown "$PRODUCT:$PRODUCT" {} + -exec chmod 600 {} +
find "$DATA_DIR" -maxdepth 1 -type d \( -name blobs -o -name secrets \) -exec chown "$PRODUCT:$PRODUCT" {} + -exec chmod 700 {} +
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
  export HARNESS_INTERNAL_KEY="$("$PY" -I -c 'import secrets; print(secrets.token_hex(32))')"
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
    "$PY" -I - "$HR_AUTH_STORE" <<'PYEOF' 2>/dev/null && return 0
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
  "$PY" -I -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["user"])' "$HR_AUTH_STORE" 2>/dev/null \
    || printf '%s\n' "$HR_AUTH_USER"
}

# A published password is no password, and the console is reachable from more than the network: every agent
# turn runs in this container and can open 127.0.0.1:3000 (GHSA-r37g). So the default is never accepted. An
# instance whose credentials were never set gets a random password at its first boot, kept where only root and
# the operator (docker exec) can read it, and the log says where, not what.
HR_INITIAL_PASSWORD_FILE="$DATA_DIR/selfhost-initial-password"
root_file "$HR_INITIAL_PASSWORD_FILE"
if [ "${HR_AUTH_DISABLED:-}" != "1" ] && [ ! -f "$HR_AUTH_STORE" ] && [ "$HR_AUTH_PASSWORD" = "harnessrouter" ]; then
  if [ ! -s "$HR_INITIAL_PASSWORD_FILE" ]; then
    ( umask 077; "$PY" -I -c 'import secrets; print(secrets.token_urlsafe(18))' > "$HR_INITIAL_PASSWORD_FILE" )
    chmod 600 "$HR_INITIAL_PASSWORD_FILE"
  fi
  HR_AUTH_PASSWORD="$(cat "$HR_INITIAL_PASSWORD_FILE")"
  export HR_AUTH_PASSWORD
  echo "[harnessrouter] the default password is not accepted. Sign in as '$HR_AUTH_USER' with the password in $HR_INITIAL_PASSWORD_FILE (docker exec <container> cat $HR_INITIAL_PASSWORD_FILE), then change it from the profile page, or set HR_AUTH_PASSWORD."
fi

# Secrets at rest (#624). The secret store encrypts only under HR_SECRET_KEY, and nothing set it:
# an install that followed the README kept its provider keys and MCP tokens in plain text under
# /data/secrets, behind a file mode. So an instance given no key gets one at its first boot, kept
# like the initial password: root's, 0600, on the volume. An operator who sets HR_SECRET_KEY keeps
# the key apart from the data, which this cannot do, and the guide says so; one who set it once
# keeps setting it, since the records are sealed under it. The gateway re-encrypts what was
# stored before the key existed at its start.
HR_SECRET_KEY_FILE="$DATA_DIR/secret-key"
# A volume restored without its owners brings this file back as someone else's, and it is the only
# copy of the key the records were sealed under: removing it would lose every stored credential. So
# a real file with one name is taken, and what it holds only ever becomes the gateway's key, which
# the product has anyway. A link or a second name is still removed by root_file, never followed.
if [ -f "$HR_SECRET_KEY_FILE" ] && [ ! -L "$HR_SECRET_KEY_FILE" ] && [ "$(stat -c %h "$HR_SECRET_KEY_FILE")" = 1 ]; then
  chown root:root "$HR_SECRET_KEY_FILE"
  chmod 600 "$HR_SECRET_KEY_FILE"
fi
root_file "$HR_SECRET_KEY_FILE"
GATEWAY_SECRET_KEY="${HR_SECRET_KEY:-}"
if [ -z "$GATEWAY_SECRET_KEY" ]; then
  if [ ! -s "$HR_SECRET_KEY_FILE" ]; then
    ( umask 077; "$PY" -I -c 'import secrets; print(secrets.token_urlsafe(32))' > "$HR_SECRET_KEY_FILE" )
    chmod 600 "$HR_SECRET_KEY_FILE"
    echo "[harnessrouter] stored secrets are encrypted under a key generated now and kept in $HR_SECRET_KEY_FILE; set HR_SECRET_KEY to keep the key away from the data"
  fi
  GATEWAY_SECRET_KEY="$(cat "$HR_SECRET_KEY_FILE")"
fi
# Only the gateway opens the store, so only the gateway is handed the key, at its launch below. The
# installers, the runner and the console start from this environment and never need it.
unset HR_SECRET_KEY

if [ "${HR_AUTH_DISABLED:-}" = "1" ]; then
  echo "[harnessrouter] WARNING: login is DISABLED (HR_AUTH_DISABLED=1) — anyone who can reach this port has full control"
elif [ -f "$HR_AUTH_STORE" ]; then
  echo "[harnessrouter] sign in as '$(hr_stored_user)' (credentials set from the profile page)"
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
# Root installs these and runs their version checks at every start, and every session runs them, so
# they are root's and written by nobody else. A volume from before this was the product's in places,
# and an installer leaves what its archive says: tar as root keeps the packer's uid and modes. So this
# runs at every start, before anything here runs a tool, and again when the installers are done.
# It changes only what is wrong, so on a settled volume it is one walk of the tree. There is no mark to
# trust: a mark written before the installers ran is how a fresh install kept its archives' modes.
seal_tools() {
  root_dir "$TOOLS"
  find "$TOOLS" -xdev \( ! -user root -o ! -group root \) -exec chown -h root:root {} +
  find "$TOOLS" -xdev ! -type l \( -perm /022 -o ! -perm -444 -o \( -type d ! -perm -111 \) \) -exec chmod go-w,a+rX {} +
}
seal_tools
export PATH="$TOOLS/bin:$PATH"
export NODE_PATH="$TOOLS/lib/node_modules"
# The four added in this batch are in the DEFAULT set rather than opt-in, for the reason
# agentzero's PR settled: the console lists every base in the catalog, so a base the operator
# did not opt into is a row that fails on its first turn with no explanation. Disk is the
# trade — jcode is a ~127 MB static Rust binary and the two Python bases bring their own venvs —
# and an operator who wants them out sets HR_BACKENDS.
export HR_BACKENDS="${HR_BACKENDS:-claude,codex,hermes,pi,dsh,opencode,kilo,qwen,gemini,cline,omp,goose,kimi,minimax,grok,aider,openhands,agentzero,systemone,cheetahclaws,mimo,jcode,opensquilla,nanobot,zeroclaw,qoder,vibe,docker-agent,fast-agent,dcode}"

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
    # qoder has no binary of its own: its runtime is Qoder's cloud, and the turn process is
    # runner/qoder_driver.py on Qoder's SDK, in a venv of its own (install_qoder). The venv's
    # interpreter is what "installed" means here.
    qoder) echo "$TOOLS/qoder-venv/bin/python" ;;
    mimo)   echo "$TOOLS/bin/mimo" ;;
    roder)  echo "$TOOLS/bin/roder" ;;
    jcode)  echo "$TOOLS/bin/jcode" ;;
    opensquilla) echo "$TOOLS/opensquilla-venv/bin/opensquilla" ;;
    vibe) echo "$TOOLS/vibe-venv/bin/vibe" ;;
    docker-agent) echo "$TOOLS/bin/docker-agent" ;;
    fast-agent) echo "$TOOLS/fast-agent-venv/bin/fast-agent-acp" ;;
    dcode) echo "$TOOLS/dcode-venv/bin/dcode" ;;
    nanobot) echo "$TOOLS/nanobot-venv/bin/nanobot" ;;
    zeroclaw) echo "$TOOLS/bin/zeroclaw" ;;
  esac
}

# ── what each base is, written down, and compared at every start without running it ─────────────
# A base's identity is its pin and the digest its bytes were checked against (or the lock it was
# installed from). Root writes it to $TOOLS/.versions/<base> once an install has proved itself, and
# every later start compares that file with what this script pins. Nothing installed is RUN to learn
# its version: a tampered binary can print the right answer, and asking it was nineteen root
# executions of third-party code per start. A stamp that is missing or names anything else is a
# reinstall, so a pin bump reaches a volume that already holds the base, and a volume from before
# stamps existed (whose opencode, qwen or pi came from whatever `latest` was that day) is replaced
# once with what is pinned here. seal_tools keeps .versions root's like the rest of $TOOLS.
STAMPS="$TOOLS/.versions"
case "$(uname -m)" in
  x86_64|amd64)  HR_ARCH=amd64 ;;
  aarch64|arm64) HR_ARCH=arm64 ;;
  *)             HR_ARCH="$(uname -m)" ;;
esac
# by_arch <amd64 value> <arm64 value>: this machine's one, or nothing on another architecture.
by_arch() { case "$HR_ARCH" in amd64) echo "$1" ;; arm64) echo "$2" ;; *) echo "" ;; esac; }
# pin_sha <NAME> <pinned version> <chosen version> <digest of the pinned one>: the digest to check
# the chosen version against. The committed digest describes the pin and nothing else, so an
# operator who overrides HR_<NAME>_VERSION brings HR_<NAME>_SHA256 for it, or gets nothing, and the
# stamp then says "unverified" and the start says so (install_base).
pin_sha() {
  if [ "$3" = "$2" ]; then echo "$4"; return; fi
  ps_var="HR_$1_SHA256"; echo "${!ps_var:-}"
}
# ident <version> <sha256 or empty>: the stamp line for a digest-checked base.
ident() { if [ -n "$2" ]; then echo "$1 sha256:$2"; else echo "$1 unverified"; fi; }
# check_sha <label> <file> <want>: the file is the bytes the digest names. An empty <want> is an
# override with no digest, already announced by install_base, and passes.
check_sha() {
  [ -n "$3" ] || return 0
  cs_have="$(sha256sum "$2" | awk '{print $1}')"
  [ "$cs_have" = "$3" ] && return 0
  echo "$1: digest mismatch for $(basename "$2") on $HR_ARCH (want $3, have $cs_have)"
  return 1
}
# file_sha <path>: a lock or patch that ships in the image, as part of an identity.
file_sha() { sha256sum "$1" 2>/dev/null | awk '{print $1}'; }

declare -A STAMP_WANT=()
# current <base> <identity>: the volume holds this base as pinned. Reads two things and runs none.
current() {
  STAMP_WANT[$1]="$2"
  [ -x "$(backend_bin "$1")" ] && [ -f "$STAMPS/$1" ] && [ ! -L "$STAMPS/$1" ] \
    && [ "$(cat "$STAMPS/$1" 2>/dev/null)" = "$2" ]
}
# install_base <base> <label> <command…>: replace whatever the volume holds with <command>'s install,
# and stamp it only once that succeeded and left the executable. The old stamp goes first, so an
# install that dies halfway is retried on the next start. A failed install also takes the old
# executable away: it was unverified or stale, which is why this ran, and a base that is not there
# is reported as missing, where one left in place would keep running bytes nobody checked.
install_base() {
  ib_base="$1"; ib_label="$2"; shift 2
  ib_want="${STAMP_WANT[$ib_base]}"
  root_dir "$STAMPS"; rm -f -- "$STAMPS/$ib_base"
  case "$ib_want" in
    *unverified*) echo "[harnessrouter] WARN: $ib_label is an override ($ib_want) with no digest or lock here — NOT verified" ;;
  esac
  if try_install "$ib_label" "$@" && [ -x "$(backend_bin "$ib_base")" ]; then
    printf '%s\n' "$ib_want" > "$STAMPS/$ib_base"
    return 0
  fi
  [ -x "$(backend_bin "$ib_base")" ] && echo "[harnessrouter]   removing the previous $ib_label: it is not the one pinned"
  rm -f -- "$(backend_bin "$ib_base")"
  return 1
}

# opencode ships prebuilt binaries on GitHub releases rather than npm, so fetch the asset directly.
# NOT the vendor's install script: it hardcodes INSTALL_DIR=$HOME/.opencode/bin with no override, so
# it cannot be pointed at the data volume, and piping a remote script into a shell inside an
# entrypoint is a supply-chain surface this product does not need.
#
# Pinned EXACTLY, with the digests committed here. This was `releases/latest` with no check, and the
# guard was the file existing, so whatever upstream's latest was on the day a volume was created is
# what that volume ran from then on, unverified (#623). 1.18.23 is the release the support matrix
# last ran real turns on. The digests were computed from its two assets (2026-11-07) and agree with
# GitHub's own asset digests.
OPENCODE_PIN="${HR_OPENCODE_VERSION:-1.18.23}"; OPENCODE_PIN="${OPENCODE_PIN#v}"
OPENCODE_SHA="$(pin_sha OPENCODE 1.18.23 "$OPENCODE_PIN" "$(by_arch \
  ab7015cd8113e011a461f30a0c2b77d8299a144ff688cb62e93e8802835d7288 \
  86d3afaf4e8784f9adab189be2a315c12b27ec40a04b70defbe70595c3cc7c65)")"
install_opencode() {
  case "$HR_ARCH" in
    amd64) oc_arch="x64" ;;
    arm64) oc_arch="arm64" ;;
    *) echo "unsupported architecture $HR_ARCH for opencode"; return 1 ;;
  esac
  oc_url="https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_PIN}/opencode-linux-$oc_arch.tar.gz"
  oc_tmp="$(mktemp -d)"
  curl -fsSL "$oc_url" -o "$oc_tmp/opencode.tar.gz" || { rm -rf "$oc_tmp"; return 1; }
  check_sha "opencode $OPENCODE_PIN" "$oc_tmp/opencode.tar.gz" "$OPENCODE_SHA" || { rm -rf "$oc_tmp"; return 1; }
  tar -xzf "$oc_tmp/opencode.tar.gz" --no-same-owner -C "$oc_tmp" || { rm -rf "$oc_tmp"; return 1; }
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
# Note the repo moved from block/goose to aaif-goose/goose. This project publishes no checksums;
# the digests are pinned HERE, computed from the v1.50.0 release assets (each archive holds exactly
# ./goose). That is strictly stronger than the tag alone, which can be moved and whose asset can be
# re-uploaded — and it is how every release asset in this script is checked.
# Aider, Apache-2.0 (Aider-AI/aider), pinned to 0.86.2, plus the MCP bridge it needs.
#
# Its own venv, the dsh/hermes precedent: aider pins litellm and a large scientific stack, and must
# not share the runner's interpreter. Installed from docker/locks/aider.lock.txt, every file hashed.
#
# NOTE the Python floor: aider 0.86.2 declares Requires-Python <3.13,>=3.10. On an interpreter
# outside that range pip does not fail — it silently offers an OLDER aider (0.82.3 was the highest
# on 3.9), and every behaviour runner/aider_driver.py was written against would be absent without a
# single error. The explicit version pin below is what turns that into a hard failure.
#
# The official MCP SDK goes in beside it: upstream aider has no MCP client at all, so
# runner/aider_mcp_bridge.py is what lets a declared MCP server be reached and, therefore, measured.
# Installed in this venv rather than globally because no other backend uses it. aider pins
# idna==3.11 and the SDK needs idna>=3.18: the venv has always held the SDK's (it was installed second
# and replaced it), and docker/locks/aider.overrides writes that down.
AIDER_PIN="${HR_AIDER_VERSION:-0.86.2}"
AIDER_MCP_PIN="${HR_MCP_SDK_VERSION:-2.2.0}"
AIDER_REQS=("aider-chat==$AIDER_PIN" "mcp==$AIDER_MCP_PIN")
install_aider() {
  am_py="${HR_AIDER_BASE_PYTHON:-python3}"
  # Sessions keep nothing in the venv, so a reinstall starts from an empty one.
  if is_locked aider "${AIDER_REQS[@]}"; then
    install_locked_venv aider "$am_py" "$TOOLS/aider-venv" aider.lock.txt || return 1
  else
    # An override, unlocked, in the order the overrides above describe: aider, then the SDK over it.
    install_unlocked_venv aider "$am_py" "$TOOLS/aider-venv" "aider-chat==$AIDER_PIN" || return 1
    "$TOOLS/aider-venv/bin/pip" install -q --disable-pip-version-check --no-cache-dir \
      "mcp==$AIDER_MCP_PIN" || return 1
  fi
  # The driver imports aider in process; prove the pinned version is importable before declaring the
  # install good, so a resolver that quietly picked another one fails HERE and not on a live turn.
  "$TOOLS/aider-venv/bin/python" -c '
import sys, aider
want = sys.argv[1]
if aider.__version__ != want:
    sys.exit("aider %s installed, wanted %s" % (aider.__version__, want))
'  "$AIDER_PIN" || return 1
  # aider's MCP client is the official MIT SDK, in the same venv. f/mcptools was the first choice
  # and is not usable here — it is a Go program that publishes NO binaries on any release (checked
  # through v0.7.1, every one has zero assets), so it would mean a Go toolchain in a python-slim
  # image for one command.
  "$TOOLS/aider-venv/bin/python" -c 'from mcp import StdioServerParameters; from mcp.client.client import Client' || return 1
}

# Qoder Cloud Agents' Python SDK, MIT (QoderAI/qoder-cloud-agents-sdk-python, PyPI `qca-sdk`), pinned
# to 0.6.0. The qoder backend's runtime is Qoder's cloud; what this box needs is the client the
# driver (runner/qoder_driver.py) speaks it with, in a venv of its own so its httpx/pydantic/anyio
# stay off the runner's. Installed from docker/locks/qoder.lock.txt, which holds the wheel's digest
# (PyPI's sha256 for qca_sdk-0.6.0-py3-none-any.whl, the one this script used to check by hand) and
# its dependencies'. The import check asserts the client and the methods the driver reaches for, so
# an SDK refactor fails the install here rather than the first live turn.
QODER_PIN="${HR_QODER_SDK_VERSION:-0.6.0}"
QODER_REQS=("qca-sdk==$QODER_PIN")
install_qoder() {
  install_pinned_venv qoder "${HR_QODER_BASE_PYTHON:-python3}" "$TOOLS/qoder-venv" "" "${QODER_REQS[@]}" || return 1
  "$TOOLS/qoder-venv/bin/python" -c '
import sys, importlib.metadata as md
want = sys.argv[1]
have = md.version("qca-sdk")
if have != want:
    sys.exit("qca-sdk %s installed, wanted %s" % (have, want))
# every call runner/qoder_driver.py makes, on the client it makes them on
import qca
from qca.managed import Managed
for name in ("APIStatusError", "APIConnectionError", "APITimeoutError", "APIResponseValidationError", "APIError"):
    getattr(qca, name)
m = Managed(pat="probe", base_url="http://127.0.0.1:9/")
for path in ("environments.create", "environments.delete", "environments.archive",
             "vaults.create", "vaults.delete", "vaults.credentials.create", "vaults.credentials.list", "vaults.credentials.archive",
             "agents.create", "agents.retrieve", "agents.update", "agents.archive",
             "sessions.create", "sessions.retrieve", "sessions.update", "sessions.cancel", "sessions.delete",
             "sessions.resources.add", "sessions.events.send", "sessions.events.list", "sessions.events.stream",
             "files.upload", "files.download", "files.delete",
             "skills.create", "skills.versions.create", "skills.delete"):
    obj = m
    for part in path.split("."):
        obj = getattr(obj, part)
    if not callable(obj):
        sys.exit("qca-sdk %s: %s is not callable" % (have, path))
' "$QODER_PIN" || return 1
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
# VERIFIED, not only pinned: installed from docker/locks/cheetahclaws.lock.txt, which holds the
# wheel's digest (the one this script used to check by hand, equal to PyPI's) and its dependencies'.
# The import check then asserts the symbols the driver reaches for, so an upstream refactor fails
# the install here rather than the first live turn.
CHEETAHCLAWS_PIN="${HR_CHEETAHCLAWS_VERSION:-3.5.88}"
CHEETAHCLAWS_REQS=("cheetahclaws==$CHEETAHCLAWS_PIN")
install_cheetahclaws() {
  install_pinned_venv cheetahclaws "${HR_CHEETAHCLAWS_BASE_PYTHON:-python3}" "$TOOLS/cheetahclaws-venv" "" "${CHEETAHCLAWS_REQS[@]}" || return 1
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
KIMI_SHA="$(pin_sha KIMI 2.0.0 "$KIMI_PIN" "$(by_arch \
  ebc1ad504e458d66f0cc57d4e9d709a2060647f5b89d4e21026903b96204c3ed \
  870fdb2fc45622fed92753bc4995ff80ba02e15a6304b396b5a70df1c7a23174)")"
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
# It installs from docker/locks/npm/minimax like the other npm bases: the lock names the archive by
# URL and sha512 (the same bytes the digest above named; the archive's sha256 is
# b83a27e2f8373c755f26a1dc02cf8ba1c1f1a1a9d889d752ff5527fb5af2f1c0), and its dependencies
# (better-sqlite3 12.11.1, @vscode/ripgrep 1.18.0, @larksuiteoapi/node-sdk 1.73.3) with their whole
# trees. About 105 MB installed, so it is in the default set. Requires Node >= 22.19 (the image's
# nodesource 22.x).
#
# Everything runner/server.py's minimax code relies on (the exec stream-json schema, the
# custom_provider selector, --session refusing an unknown id, the sqlite session store, the config
# keys agents.default / skills.external, the two instruction files, the rm shim's trash) was
# measured on THIS version.
MINIMAX_PIN="${HR_MINIMAX_VERSION:-0.5.4}"; MINIMAX_PIN="${MINIMAX_PIN#v}"
MINIMAX_URL="https://github.com/MiniMax-AI/minimax-code/releases/download/v${MINIMAX_PIN}/minimax-code-${MINIMAX_PIN}.tar.gz"
MINIMAX_SPEC="@minimax-ai/code@$MINIMAX_URL"
# better-sqlite3's native binding (the CLI's session store is sqlite). Its install script is
# `prebuild-install`, which fetches this same archive from the project's GitHub release and checks
# nothing; with scripts off, it is fetched here and checked against a digest committed here. The
# archive holds one file, build/Release/better_sqlite3.node, and it is the file prebuild-install
# left in main's tree (measured: same sha256). It is built for one Node ABI (127 is Node 22), so a
# new Node major in the image fails this install loudly instead of loading a mismatched binding.
MINIMAX_SQLITE_PIN="12.11.1"
MINIMAX_SQLITE_ABI="127"
MINIMAX_SQLITE_SHA="$(by_arch \
  94ce113ea2d9347fcd1cf8e46445cc271d1dbd02d05a64aa460442222f023b11 \
  00f8035f4322c14ab4dbb3ee6f4b6c9ca25209fe2a77ac2759cd09dd42587d48)"
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
KILO_SHA="$(pin_sha KILO 7.8.1 "$KILO_PIN" "$(by_arch \
  6d48503b000d3d904d15950b63e254653c450800647344ac0f3de4e8a7f98835 \
  516f81a81d3605cecae61dddf4da548da403b9f8993a06bb799d12b6fc6e7ac4)")"
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
GROK_SHA="$(pin_sha GROK 1.0.41 "$GROK_PIN" "$(by_arch \
  9ce03ed23e16ea01072b4496263d6213a27899e1e3e107f008d36edf82e70407 \
  7c0b8c973af6a78e2037f19ed93033471b8c5e722f9ff04b86b092e066e60d74)")"
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
# decision model. Its own venv on the data volume like openhands and aider, from
# docker/locks/systemone.lock.txt, rebuilt when the pin or the lock moves. The executable is the
# venv's python, which the runner hands runner/systemone_driver.py.
SYSTEMONE_PIN="${HR_SYSTEMONE_VERSION:-0.4.0}"; SYSTEMONE_PIN="${SYSTEMONE_PIN#v}"
# The COMMIT the v0.4.0 tag pointed at (2026-11-07), not the tag: a tag can be moved, a commit
# cannot, and the tag is ours to move by mistake. An overridden version is fetched by its tag. It is
# GitHub's source archive of that commit, not a git checkout, because --require-hashes takes a file
# with a digest and no VCS requirement; the lock holds the archive's sha256, and it is the one
# distribution of this lock that is built here (setuptools, from build.lock.txt). A wheel published
# with the release would remove even that.
if [ "$SYSTEMONE_PIN" = "0.4.0" ]; then SYSTEMONE_REF=3266a17537e283dc5539439835c0b4cab02bf5c0; else SYSTEMONE_REF="v$SYSTEMONE_PIN"; fi
# Playwright drives the browser environments; the version a fresh volume resolved on 0.38.2.
SYSTEMONE_PLAYWRIGHT_PIN="${HR_SYSTEMONE_PLAYWRIGHT_VERSION:-1.64.1}"
# HR_SYSTEMONE_SPEC overrides where pip takes the package from (a mirror, a fork, a local tree
# copied into a derived image), unlocked; the version proven below is the pin either way. The browser extra
# brings Browser Use, and with it the page and game environments; the Chromium they drive is
# installed beside the venv on the data volume (Playwright's, world-readable), because the image
# ships no browser and a session process cannot read root's cache.
SYSTEMONE_SPEC="${HR_SYSTEMONE_SPEC:-systemone-harness[browser] @ https://github.com/HarnessRouter/SystemOneHarness/archive/${SYSTEMONE_REF}.tar.gz}"
SYSTEMONE_REQS=("$SYSTEMONE_SPEC" "playwright==$SYSTEMONE_PLAYWRIGHT_PIN")
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
  install_pinned_venv systemone "${HR_SYSTEMONE_BASE_PYTHON:-python3}" "$TOOLS/systemone-venv" systemone-harness "${SYSTEMONE_REQS[@]}" \
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
AGENTZERO_SHA="$(pin_sha AGENTZERO 2.13 "$AGENTZERO_PIN" ac9e1b319cb75ae52c4309123d893e1925ad83464cf1c0d5ad9e1db0e2f25e9e)"
AGENTZERO_EXCLUDE='^(kokoro|openai-whisper|sentence-transformers|unstructured|unstructured-client|langchain-unstructured|faiss-cpu|liteparse|newspaper3k|patchright|docker|duckduckgo-search|pyreqwest-impersonate|exchangelib|imapclient|boto3|flaredantic|pypdf|pymupdf|pytesseract|pdf2image|soundfile|pywinpty)([=<>~!; []|$)'
install_agentzero() {
  az_tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/agent0ai/agent-zero/archive/refs/tags/v${AGENTZERO_PIN}.tar.gz" \
      -o "$az_tmp/a0.tar.gz" || { rm -rf "$az_tmp"; return 1; }
  check_sha "Agent Zero $AGENTZERO_PIN" "$az_tmp/a0.tar.gz" "$AGENTZERO_SHA" || { rm -rf "$az_tmp"; return 1; }
  mkdir "$az_tmp/x" && tar -xzf "$az_tmp/a0.tar.gz" --no-same-owner -C "$az_tmp/x" --strip-components=1 \
    || { rm -rf "$az_tmp"; return 1; }
  [ -f "$az_tmp/x/agent.py" ] && [ -f "$az_tmp/x/requirements.txt" ] \
    || { echo "the Agent Zero archive holds no agent.py/requirements.txt"; rm -rf "$az_tmp"; return 1; }
  grep -vE '^[[:space:]]*(#|$)' "$az_tmp/x/requirements.txt" | sed 's/[[:space:]]*#.*$//' \
    | grep -viE "$AGENTZERO_EXCLUDE" > "$az_tmp/requirements.harness.txt"
  echo "ipython==${HR_AGENTZERO_IPYTHON_VERSION:-9.17.1}" >> "$az_tmp/requirements.harness.txt"
  rm -rf "$TOOLS/agentzero-src"
  # The measured tree, not whatever the index resolves today: upstream floors a third of its
  # requirements and pins no transitive dependency. docker/locks/agentzero.in is the list just built
  # from 2.13's archive, so the lock compiled from it (under runner/agentzero-constraints.txt, the
  # tree the support matrix measured) is used only when this archive yields exactly that list. Two of
  # its distributions publish no wheel and are built here. An overridden version resolves freely, and
  # its stamp says so.
  mapfile -t az_reqs < "$az_tmp/requirements.harness.txt"
  install_pinned_venv agentzero "${HR_AGENTZERO_BASE_PYTHON:-python3}" "$TOOLS/agentzero-venv" crontab,flask-basicauth "${az_reqs[@]}" \
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

# BOTH openhands pins are the identity: a venv built before litellm was pinned holds the right
# agent-server and the wrong litellm, which is the follow-up failure the litellm pin removes. One of
# the lock's distributions (func-timeout) publishes no wheel and is built here.
OPENHANDS_PIN="${HR_OPENHANDS_VERSION:-1.49.2}"
OPENHANDS_LITELLM_PIN="${HR_OPENHANDS_LITELLM_VERSION:-1.94.3}"
OPENHANDS_REQS=("openhands-agent-server==$OPENHANDS_PIN" "openhands-tools==$OPENHANDS_PIN" "openhands-sdk==$OPENHANDS_PIN" "litellm==$OPENHANDS_LITELLM_PIN")
install_openhands() {
  install_pinned_venv openhands "${HR_OPENHANDS_BASE_PYTHON:-python3}" "$TOOLS/openhands-venv" func-timeout "${OPENHANDS_REQS[@]}" || return 1
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
' "$OPENHANDS_PIN" || return 1
  command -v tmux >/dev/null 2>&1 || { echo "openhands: the tmux binary is missing"; return 1; }
}

install_kimi() {
  case "$HR_ARCH" in
    amd64) km_arch="x64" ;;
    arm64) km_arch="arm64" ;;
    *) echo "unsupported architecture $HR_ARCH for kimi"; return 1 ;;
  esac
  km_url="https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai%2Fkimi-code%40${KIMI_PIN}/kimi-code-linux-${km_arch}.tar.gz"
  km_tmp="$(mktemp -d)"
  curl -fsSL "$km_url" -o "$km_tmp/kimi.tar.gz" || { rm -rf "$km_tmp"; return 1; }
  check_sha "kimi $KIMI_PIN" "$km_tmp/kimi.tar.gz" "$KIMI_SHA" || { rm -rf "$km_tmp"; return 1; }
  mkdir "$km_tmp/x" && tar -xzf "$km_tmp/kimi.tar.gz" -C "$km_tmp/x" || { rm -rf "$km_tmp"; return 1; }
  km_bin="$(find "$km_tmp/x" -type f -name kimi -perm -u+x | head -n 1)"
  [ -n "$km_bin" ] || { echo "release archive contained no kimi binary"; rm -rf "$km_tmp"; return 1; }
  mkdir -p "$TOOLS/bin" && install -m 755 "$km_bin" "$TOOLS/bin/kimi" \
    || { rm -rf "$km_tmp"; return 1; }
  rm -rf "$km_tmp"
}


install_minimax() {
  if ! npm_is_locked minimax "$MINIMAX_SPEC"; then
    # An override: upstream's install form, optional deps included, install scripts allowed for
    # better-sqlite3. An npm that predates allow-scripts warns about the flag and runs scripts anyway.
    npm_unlocked minimax --include=optional --allow-scripts=better-sqlite3 "$MINIMAX_URL"
    return
  fi
  npm_locked minimax || return 1
  mm_bs="$TOOLS/npm/minimax/node_modules/better-sqlite3"
  mm_fail() { [ -z "$1" ] || echo "$1"; rm -rf "${mm_tmp:-}" "$TOOLS/npm/minimax"; return 1; }
  mm_abi="$(node -p process.versions.modules)"
  [ "$mm_abi" = "$MINIMAX_SQLITE_ABI" ] \
    || mm_fail "better-sqlite3 $MINIMAX_SQLITE_PIN: the digest here is for Node ABI $MINIMAX_SQLITE_ABI, this Node is $mm_abi" || return 1
  [ -n "$MINIMAX_SQLITE_SHA" ] || mm_fail "better-sqlite3: no digest for $HR_ARCH" || return 1
  [ "$(node -p 'require(process.argv[1]).version' "$mm_bs/package.json")" = "$MINIMAX_SQLITE_PIN" ] \
    || mm_fail "the lock's better-sqlite3 is not $MINIMAX_SQLITE_PIN, which the digest here is for" || return 1
  case "$HR_ARCH" in amd64) mm_arch="x64" ;; arm64) mm_arch="arm64" ;; esac
  mm_tmp="$(mktemp -d)"
  curl -fsSL --proto '=https' \
    "https://github.com/WiseLibs/better-sqlite3/releases/download/v${MINIMAX_SQLITE_PIN}/better-sqlite3-v${MINIMAX_SQLITE_PIN}-node-v${mm_abi}-linux-${mm_arch}.tar.gz" \
    -o "$mm_tmp/binding.tar.gz" || mm_fail "could not fetch better-sqlite3's binding" || return 1
  check_sha "better-sqlite3 $MINIMAX_SQLITE_PIN" "$mm_tmp/binding.tar.gz" "$MINIMAX_SQLITE_SHA" || mm_fail "" || return 1
  tar -xzf "$mm_tmp/binding.tar.gz" --no-same-owner -C "$mm_bs" build/Release/better_sqlite3.node \
    || mm_fail "better-sqlite3's archive holds no build/Release/better_sqlite3.node" || return 1
  rm -rf "$mm_tmp"
  # The proof: the binding loads and answers a query.
  ( cd "$TOOLS/npm/minimax" && node -e 'new (require("better-sqlite3"))(":memory:").prepare("select 1").get()' ) \
    || mm_fail "better-sqlite3's binding does not load" || return 1
}

install_kilo() {
  case "$HR_ARCH" in
    amd64) kl_arch="x64" ;;
    arm64) kl_arch="arm64" ;;
    *) echo "unsupported architecture $HR_ARCH for kilo"; return 1 ;;
  esac
  kl_url="https://github.com/Kilo-Org/kilocode/releases/download/v${KILO_PIN}/kilo-linux-${kl_arch}.tar.gz"
  kl_tmp="$(mktemp -d)"
  curl -fsSL "$kl_url" -o "$kl_tmp/kilo.tar.gz" || { rm -rf "$kl_tmp"; return 1; }
  check_sha "kilo $KILO_PIN" "$kl_tmp/kilo.tar.gz" "$KILO_SHA" || { rm -rf "$kl_tmp"; return 1; }
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
  case "$HR_ARCH" in
    amd64) gk_arch="x86_64" ;;
    arm64) gk_arch="aarch64" ;;
    *) echo "unsupported architecture $HR_ARCH for grok"; return 1 ;;
  esac
  gk_tmp="$(mktemp -d)"
  curl -fsSL "https://x.ai/cli/grok-${GROK_PIN}-linux-${gk_arch}" -o "$gk_tmp/grok" \
    || curl -fsSL "https://storage.googleapis.com/grok-build-public-artifacts/cli/grok-${GROK_PIN}-linux-${gk_arch}" -o "$gk_tmp/grok" \
    || { rm -rf "$gk_tmp"; return 1; }
  check_sha "grok $GROK_PIN" "$gk_tmp/grok" "$GROK_SHA" || { rm -rf "$gk_tmp"; return 1; }
  mkdir -p "$TOOLS/bin" && install -m 755 "$gk_tmp/grok" "$TOOLS/bin/grok" \
    || { rm -rf "$gk_tmp"; return 1; }
  rm -rf "$gk_tmp"
}


GOOSE_PIN="${HR_GOOSE_VERSION:-1.50.0}"; GOOSE_PIN="${GOOSE_PIN#v}"
GOOSE_SHA="$(pin_sha GOOSE 1.50.0 "$GOOSE_PIN" "$(by_arch \
  6389eea4440178de006fa148d466ac411021315ff7f72b1014beae2d445851e2 \
  febd71a6a25c3aff7dbcf566f78d2864e87d886c33c4ef1fee2f67fedd334063)")"
install_goose() {
  case "$HR_ARCH" in
    amd64) gs_arch="x86_64" ;;
    arm64) gs_arch="aarch64" ;;
    *) echo "unsupported architecture $HR_ARCH for goose"; return 1 ;;
  esac
  gs_url="https://github.com/aaif-goose/goose/releases/download/v${GOOSE_PIN}/goose-${gs_arch}-unknown-linux-gnu.tar.gz"
  gs_tmp="$(mktemp -d)"
  curl -fsSL "$gs_url" -o "$gs_tmp/goose.tar.gz" || { rm -rf "$gs_tmp"; return 1; }
  check_sha "goose $GOOSE_PIN" "$gs_tmp/goose.tar.gz" "$GOOSE_SHA" || { rm -rf "$gs_tmp"; return 1; }
  tar -xzf "$gs_tmp/goose.tar.gz" --no-same-owner -C "$gs_tmp" || { rm -rf "$gs_tmp"; return 1; }
  [ -f "$gs_tmp/goose" ] || { echo "release archive contained no goose binary"; rm -rf "$gs_tmp"; return 1; }
  mkdir -p "$TOOLS/bin" && install -m 755 "$gs_tmp/goose" "$TOOLS/bin/goose" \
    || { rm -rf "$gs_tmp"; return 1; }
  rm -rf "$gs_tmp"
}

# zeroclaw (Apache-2.0, zeroclaw-labs/zeroclaw) ships prebuilt Rust binaries on GitHub releases, with
# a SHA256SUMS beside them. Pinned EXACTLY to the release runner/zeroclaw_driver.py was measured
# against (its ACP methods, the session/update shapes, the session store, the config schema), and
# verified against digests pinned HERE, read off that release's own SHA256SUMS on 2026-10-13 — the
# goose pattern, which does not trust a checksum file that can be re-uploaded beside the asset it
# describes. The archive also carries zerocode, zerorelay and a web bundle; only zeroclaw is kept.
ZEROCLAW_PIN="${HR_ZEROCLAW_VERSION:-0.8.5}"; ZEROCLAW_PIN="${ZEROCLAW_PIN#v}"
ZEROCLAW_SHA="$(pin_sha ZEROCLAW 0.8.5 "$ZEROCLAW_PIN" "$(by_arch \
  9dbb53af95132e3a934ab61b229fb7aec3565f1c9bf31851f1698be9160655f9 \
  aaa7e2c656dedf651217a70ea487e1e65f51b4ca771d114e60bf409165700986)")"
install_zeroclaw() {
  case "$HR_ARCH" in
    amd64) zc_arch="x86_64" ;;
    arm64) zc_arch="aarch64" ;;
    *) echo "unsupported architecture $HR_ARCH for zeroclaw"; return 1 ;;
  esac
  zc_url="https://github.com/zeroclaw-labs/zeroclaw/releases/download/v${ZEROCLAW_PIN}/zeroclaw-${zc_arch}-unknown-linux-gnu.tar.gz"
  zc_tmp="$(mktemp -d)"
  curl -fsSL "$zc_url" -o "$zc_tmp/zeroclaw.tar.gz" || { rm -rf "$zc_tmp"; return 1; }
  check_sha "zeroclaw $ZEROCLAW_PIN" "$zc_tmp/zeroclaw.tar.gz" "$ZEROCLAW_SHA" || { rm -rf "$zc_tmp"; return 1; }
  tar -xzf "$zc_tmp/zeroclaw.tar.gz" --no-same-owner -C "$zc_tmp" zeroclaw || { rm -rf "$zc_tmp"; return 1; }
  [ -f "$zc_tmp/zeroclaw" ] || { echo "release archive contained no zeroclaw binary"; rm -rf "$zc_tmp"; return 1; }
  mkdir -p "$TOOLS/bin" && install -m 755 "$zc_tmp/zeroclaw" "$TOOLS/bin/zeroclaw" \
    || { rm -rf "$zc_tmp"; return 1; }
  rm -rf "$zc_tmp"
}

# omp (Oh My Pi, MIT) ships standalone prebuilt binaries on GitHub releases. Pinned EXACTLY, like
# every other backend here: upstream releases almost daily (18.1.8 through 18.1.13 in five days),
# and 18.1.13 is the release the runner's omp code was measured against (flags, the JSON event
# stream, the agent-dir env, resume by id, --tools). A silent `latest` re-gambles all of it.
#
# The digests are committed HERE, not read from the SHA256SUMS.txt beside the binary at install: a
# sums file fetched from the same release proves the transfer and not the build, since a replaced
# release ships with a matching one (#623; kilo and zeroclaw already work this way). The values were
# computed from the 18.1.13 assets (2026-11-07) and agree with that release's SHA256SUMS.txt and
# with GitHub's asset digests.
OMP_PIN="${HR_OMP_VERSION:-18.1.13}"; OMP_PIN="${OMP_PIN#v}"
OMP_SHA="$(pin_sha OMP 18.1.13 "$OMP_PIN" "$(by_arch \
  3be5a308cc91e6f6bba148175fbe651d3583ff6d32ae221cb931dc08a64e1f39 \
  06fc72183ca0c5b3add7d1dcc1a3005e17b9b67b679f04b5c646b08bfe763cb6)")"
install_omp() {
  case "$HR_ARCH" in
    amd64) omp_arch="x64" ;;
    arm64) omp_arch="arm64" ;;
    *) echo "unsupported architecture $HR_ARCH for omp"; return 1 ;;
  esac
  omp_tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/can1357/oh-my-pi/releases/download/v${OMP_PIN}/omp-linux-$omp_arch" \
    -o "$omp_tmp/omp" || { rm -rf "$omp_tmp"; return 1; }
  check_sha "omp $OMP_PIN" "$omp_tmp/omp" "$OMP_SHA" || { rm -rf "$omp_tmp"; return 1; }
  mkdir -p "$TOOLS/bin" && install -m 755 "$omp_tmp/omp" "$TOOLS/bin/omp" || { rm -rf "$omp_tmp"; return 1; }
  rm -rf "$omp_tmp"
}

# ── this batch's five ─────────────────────────────────────────────────────────────────────────
# Each is pinned EXACTLY to the release its runner code was measured against (the flags, the event
# schema, the resume mechanism, the tool ids and the config shape were all read out of THAT
# version), and each download is verified rather than trusted to a tag: the release assets against
# digests committed here, and the two PyPI-ish ones pinned by version and proven by an import of
# the symbol the runner actually uses.

# MiMo Code (MIT, XiaomiMiMo/MiMo-Code) ships on npm as @mimo-ai/cli with the binary `mimo`.
# 0.1.15 is the release _build_mimo was measured against. The npm registry serves an integrity
# digest with every tarball and npm verifies it, which is why this one is an npm install rather
# than a release-asset fetch with a digest of our own.
install_mimo() {
  # Its install script only caches the platform binary's path; the launcher finds the binary
  # without it (measured: `mimo --version` answers from an --ignore-scripts tree).
  install_npm mimo "$MIMO_SPEC" || return 1
  # MiMo performs a ONE-TIME SQLite migration and fetches an npm tree of ai-sdk packages on its
  # first run. Measured: the first turn on a fresh home took over nine minutes and printed nothing
  # before it was killed; the second, warm, answered in about twenty seconds. A turn is not where
  # that cost belongs, so a throwaway home is warmed here, at install, and then removed.
  mimo_warm="$(mktemp -d)"
  mimo_got="$(HOME="$mimo_warm" "$TOOLS/bin/mimo" --version 2>/dev/null | head -n 1)"
  rm -rf "$mimo_warm"
  # The warm-up doubles as the proof: an npm install can land a tree with no working entry point.
  if [ "$mimo_got" != "$MIMO_PIN" ]; then
    echo "mimo installed but reports '${mimo_got:-nothing}', wanted $MIMO_PIN"; return 1
  fi
}

# Pin the release archives independently of the download host's checksum files.
RODER_PIN="${HR_RODER_VERSION:-0.4.8}"
RODER_SHA="$(pin_sha RODER 0.4.8 "$RODER_PIN" "$(by_arch \
  de6a8a642894164004d4fd434c6a6f44ec08657083bf2b1420a97f7f4fd00a31 \
  978a84c872d22301036dd6f3d707559d1b9648bd9e6aa4149dd52c6456c68af5)")"
install_roder() {
  case "$(uname -m)" in
    x86_64) rd_arch="x86_64" ;;
    aarch64|arm64) rd_arch="aarch64" ;;
    *) echo "unsupported architecture for Roder: $(uname -m)"; return 1 ;;
  esac
  # An operator selecting a different release must supply that archive's trusted checksum.
  rd_expected="$RODER_SHA"
  if [[ ! "$rd_expected" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Roder: set HR_RODER_SHA256 for version $RODER_PIN"; return 1
  fi
  rd_asset="roder-$rd_arch-unknown-linux-gnu"
  rd_tmp="$(mktemp -d)"
  rd_base="https://github.com/RoderAI/roder/releases/download/roder/v$RODER_PIN"
  curl -fsSL "$rd_base/$rd_asset.tar.gz" -o "$rd_tmp/archive.tar.gz" || { rm -rf "$rd_tmp"; return 1; }
  rd_have="$(sha256sum "$rd_tmp/archive.tar.gz" | awk '{print $1}')"
  if [ "$rd_expected" != "$rd_have" ]; then
    echo "Roder: checksum mismatch for $rd_asset"; rm -rf "$rd_tmp"; return 1
  fi
  tar -xzf "$rd_tmp/archive.tar.gz" -C "$rd_tmp" "$rd_asset/roder" || { rm -rf "$rd_tmp"; return 1; }
  install -m 755 "$rd_tmp/$rd_asset/roder" "$TOOLS/bin/roder" || { rm -rf "$rd_tmp"; return 1; }
  rm -rf "$rd_tmp"
}

# jcode (MIT, 1jehuang/jcode) publishes one prebuilt archive per target. v0.90.0 is the release
# _build_jcode and _jcode_to_claude were measured against — the NDJSON event names, the per-request
# `tokens` accounting, the resume error text and the tool ids all came out of this build. The
# digests are committed here for omp's reason; computed from the v0.90.0 assets (2026-11-07), they
# agree with the release's SHA256SUMS and GitHub's asset digests.
JCODE_PIN="${HR_JCODE_VERSION:-0.90.0}"; JCODE_PIN="${JCODE_PIN#v}"
JCODE_SHA="$(pin_sha JCODE 0.90.0 "$JCODE_PIN" "$(by_arch \
  b963b7cd53ec0dc39c805c4549e9752ab194d4e1bd338b536d587c9bf8851516 \
  8b44b717e1085950cf1fc5b1a5005e087c9e38c1e0293b6009fee1ab0b2c451f)")"
install_jcode() {
  case "$HR_ARCH" in
    amd64) jc_arch="x86_64" ;;
    arm64) jc_arch="aarch64" ;;
    *) echo "unsupported architecture $HR_ARCH for jcode"; return 1 ;;
  esac
  jc_ver="$JCODE_PIN"
  jc_tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/1jehuang/jcode/releases/download/v${jc_ver}/jcode-linux-$jc_arch.tar.gz" \
    -o "$jc_tmp/jcode.tar.gz" || { rm -rf "$jc_tmp"; return 1; }
  check_sha "jcode $jc_ver" "$jc_tmp/jcode.tar.gz" "$JCODE_SHA" || { rm -rf "$jc_tmp"; return 1; }
  tar -xzf "$jc_tmp/jcode.tar.gz" --no-same-owner -C "$jc_tmp" || { rm -rf "$jc_tmp"; return 1; }
  # THE LINUX ARCHIVE IS A PAIR, NOT A BINARY: `jcode-linux-<arch>` is a 505-byte sh launcher that
  # puts its own directory on LD_LIBRARY_PATH and execs `jcode-linux-<arch>.bin` beside it. The
  # macOS archive is a single binary with no launcher, so a probe on a developer's Mac shows one
  # layout and the image gets the other — installing "the file called jcode*" picked the launcher,
  # left its .bin behind, and produced an executable that is on PATH and dies on its first turn.
  # Both layouts are handled, the pair is kept together in its own directory, and `bin/jcode` is a
  # symlink (the launcher resolves `readlink -f` itself, which is what makes that safe).
  jc_dir="$TOOLS/jcode"
  rm -rf "$jc_dir"; mkdir -p "$jc_dir" "$TOOLS/bin"
  if [ -f "$jc_tmp/jcode-linux-$jc_arch.bin" ]; then
    install -m 755 "$jc_tmp/jcode-linux-$jc_arch" "$jc_tmp/jcode-linux-$jc_arch.bin" "$jc_dir/" \
      || { rm -rf "$jc_tmp" "$jc_dir"; return 1; }
    ln -sf "$jc_dir/jcode-linux-$jc_arch" "$TOOLS/bin/jcode"
  elif [ -f "$jc_tmp/jcode-linux-$jc_arch" ]; then
    install -m 755 "$jc_tmp/jcode-linux-$jc_arch" "$TOOLS/bin/jcode" \
      || { rm -rf "$jc_tmp" "$jc_dir"; return 1; }
  else
    echo "release archive held neither jcode-linux-$jc_arch nor its .bin"; rm -rf "$jc_tmp" "$jc_dir"; return 1
  fi
  rm -rf "$jc_tmp"
  # PROVE IT RUNS, and that it is the version that was pinned. An installer that exits 0 without a
  # working executable is how a base reaches the console and fails on its first task with nothing to
  # read — which is exactly what the launcher-without-its-.bin produced.
  jc_got="$("$TOOLS/bin/jcode" --version 2>/dev/null | awk '{print $2}')"
  if [ "$jc_got" != "v$jc_ver" ]; then
    echo "jcode installed but reports '${jc_got:-nothing}', wanted v$jc_ver"; rm -rf "$jc_dir" "$TOOLS/bin/jcode"; return 1
  fi
}

# OpenSquilla (Apache-2.0, TokenRhythm/opensquilla). Its own venv, the aider/openhands precedent:
# it pins a large dependency set and must not share the runner's interpreter.
#
# THE WHEEL COMES FROM THE GITHUB RELEASE, NOT FROM PyPI. PyPI's `opensquilla` is stale at 0.3.0
# while upstream ships 0.5.6, and 0.5.6 is the release the runner's code was measured against — the
# agent CLI's flags, the v1 progress-event envelope, the transcript shape and the config keys. The
# lock (docker/locks/opensquilla.lock.txt) names the release asset by URL with its digest, for omp's
# reason; computed from the v0.5.6 asset (2026-11-07), it agrees with the release's SHA256SUMS and
# GitHub's asset digest. The lock holds its dependencies' digests too.
OPENSQUILLA_PIN="${HR_OPENSQUILLA_VERSION:-0.5.6}"; OPENSQUILLA_PIN="${OPENSQUILLA_PIN#v}"
OPENSQUILLA_REQS=("opensquilla @ https://github.com/TokenRhythm/opensquilla/releases/download/v${OPENSQUILLA_PIN}/opensquilla-${OPENSQUILLA_PIN}-py3-none-any.whl")
install_opensquilla() {
  sq_ver="$OPENSQUILLA_PIN"
  install_pinned_venv opensquilla "${HR_OPENSQUILLA_BASE_PYTHON:-python3}" "$TOOLS/opensquilla-venv" "" "${OPENSQUILLA_REQS[@]}" \
    || { rm -rf "$TOOLS/opensquilla-venv"; return 1; }
  # A failed install leaves NO venv behind, and the version is PROVEN rather than assumed: the
  # wheel's name could be anything, and a base that reports installed and dies on its first turn is
  # the failure mode every installer here is written to avoid.
  "$TOOLS/opensquilla-venv/bin/python" -c '
import sys, importlib.metadata as md
have = md.version("opensquilla")
if have != sys.argv[1]:
    sys.exit("opensquilla %s installed, wanted %s" % (have, sys.argv[1]))
import opensquilla.cli.main  # noqa: F401 - the module `opensquilla agent` boots from
' "$sq_ver" || { rm -rf "$TOOLS/opensquilla-venv"; return 1; }
}

# nanobot (MIT, HKUDS/nanobot) from PyPI as nanobot-ai, pinned to the release the driver was written
# against. Its own venv, for opensquilla's reason, from docker/locks/nanobot.lock.txt.
NANOBOT_PIN="${HR_NANOBOT_VERSION:-0.3.5}"; NANOBOT_PIN="${NANOBOT_PIN#v}"
NANOBOT_REQS=("nanobot-ai==$NANOBOT_PIN")
install_nanobot() {
  nb_ver="$NANOBOT_PIN"
  install_pinned_venv nanobot "${HR_NANOBOT_BASE_PYTHON:-python3}" "$TOOLS/nanobot-venv" "" "${NANOBOT_REQS[@]}" \
    || { rm -rf "$TOOLS/nanobot-venv"; return 1; }
  # Prove the SDK SURFACE the driver uses, not just that the package imports: the driver depends on
  # Nanobot.from_config and on seven STREAM_EVENT_* constants, and a release that renamed one of
  # them would otherwise fail at the first live turn with an ImportError the user would see as a
  # dead base. The version is asserted beside them.
  "$TOOLS/nanobot-venv/bin/python" -c '
import sys, importlib.metadata as md
have = md.version("nanobot-ai")
if have != sys.argv[1]:
    sys.exit("nanobot-ai %s installed, wanted %s" % (have, sys.argv[1]))
import nanobot
for name in ("Nanobot", "STREAM_EVENT_TEXT_DELTA", "STREAM_EVENT_REASONING_DELTA",
             "STREAM_EVENT_TOOL_STARTED", "STREAM_EVENT_TOOL_COMPLETED",
             "STREAM_EVENT_TOOL_FAILED", "STREAM_EVENT_RUN_COMPLETED", "STREAM_EVENT_RUN_FAILED"):
    if not hasattr(nanobot, name):
        sys.exit("nanobot-ai %s does not export %s, which runner/nanobot_driver.py needs" % (have, name))
' "$nb_ver" || { rm -rf "$TOOLS/nanobot-venv"; return 1; }
}

# Every Python base installs from a LOCK FILE that ships inside this image (/app/locks, written by
# scripts/lock-pypi.sh from the .in file beside it): every distribution of the whole dependency tree
# pinned by version AND by the sha256 of each of its files, installed with `pip --require-hashes
# --no-deps --only-binary=:all:`. A file whose bytes differ, or a dependency the lock does not name,
# fails the install, and a base that failed to install is not offered. Wheels only, so no package's
# build code runs here, except for the few distributions a base names that publish no wheel (an sdist,
# or systemone's source archive); those are built with --no-build-isolation against setuptools from
# build.lock.txt, because pip's isolated build would fetch its backend fresh and unhashed. The pins
# are part of the reviewed, digest-pinned image; nothing about them is fetched at boot except the
# files themselves (#623, step 2).
HR_LOCKS_DIR="${HR_LOCKS_DIR:-/app/locks}"

# install_locked_venv <label> <python> <venv> <lock> [<sdists>]: a venv from <python>, filled from
# <lock> only. <sdists> (comma-separated) are the distributions of <lock> that are built here.
install_locked_venv() {
  lv_label="$1"; lv_py="$2"; lv_venv="$3"; lv_lock="$HR_LOCKS_DIR/$4"; lv_sdists="${5:-}"
  [ -f "$lv_lock" ] || { echo "$lv_label: no lock file at $lv_lock"; return 1; }
  rm -rf "$lv_venv"
  "$lv_py" -I -m venv "$lv_venv" || { rm -rf "$lv_venv"; return 1; }
  lv_build=()
  if [ -n "$lv_sdists" ]; then
    "$lv_venv/bin/pip" install -q --disable-pip-version-check --no-cache-dir \
        --require-hashes --no-deps --only-binary=:all: -r "$HR_LOCKS_DIR/build.lock.txt" \
      || { rm -rf "$lv_venv"; return 1; }
    lv_build=(--no-binary="$lv_sdists" --no-build-isolation)
  fi
  "$lv_venv/bin/pip" install -q --disable-pip-version-check --no-cache-dir \
      --require-hashes --no-deps --only-binary=:all: "${lv_build[@]}" -r "$lv_lock" \
    || { rm -rf "$lv_venv"; return 1; }
}

# install_unlocked_venv <label> <python> <venv> <requirement…>: an operator's version override,
# which no lock here covers. Its stamp says "unverified", and install_base says so at the start
# rather than pretending the check ran; the version check after it still runs.
install_unlocked_venv() {
  uv_label="$1"; uv_py="$2"; uv_venv="$3"; shift 3
  rm -rf "$uv_venv"
  "$uv_py" -I -m venv "$uv_venv" || { rm -rf "$uv_venv"; return 1; }
  "$uv_venv/bin/pip" install -q --disable-pip-version-check --no-cache-dir "$@" \
    || { rm -rf "$uv_venv"; return 1; }
}

# lock_reqs <base>: the requirements <base>.lock.txt was compiled from, as one line.
lock_reqs() { grep -vE '^[[:space:]]*(#|$)' "$HR_LOCKS_DIR/$1.in" 2>/dev/null | tr '\n' ' ' | sed 's/ *$//'; }
# is_locked <base> <requirement…>: these are exactly the requirements <base>'s lock was compiled
# from. Anything else is an operator's override, which no lock here covers.
is_locked() { il_base="$1"; shift; [ -n "$*" ] && [ "$*" = "$(lock_reqs "$il_base")" ]; }
# install_pinned_venv <base> <python> <venv> <sdists> <requirement…>: <base>'s lock for its own
# pins, install_unlocked_venv for an override.
install_pinned_venv() {
  pv_base="$1"; pv_py="$2"; pv_venv="$3"; pv_sdists="$4"; shift 4
  if is_locked "$pv_base" "$@"; then
    install_locked_venv "$pv_base" "$pv_py" "$pv_venv" "$pv_base.lock.txt" "$pv_sdists"
  else
    install_unlocked_venv "$pv_base" "$pv_py" "$pv_venv" "$@"
  fi
}
# pinned_ident <base> <requirement…>: the stamp line of a locked base. The lock's digest is in it, so
# a regenerated lock in a new image reaches a volume that holds the base.
pinned_ident() {
  pi_base="$1"; shift
  if is_locked "$pi_base" "$@"; then echo "$* lock:$(file_sha "$HR_LOCKS_DIR/$pi_base.lock.txt")"; else echo "$* unverified"; fi
}

# Mistral Vibe (Apache-2.0, mistralai/mistral-vibe) from PyPI, pinned to the release the runner's
# code was measured against: the programmatic flags, the session-journal entry shapes, the export
# fields and the agent-profile door that carries a turn's model. Its own venv, for opensquilla's
# reason. 3.0.2's `vibe` is the bundled Rust CLI (vibe-rs); the wheels are platform-specific
# (cp312-abi3), and the lock carries the hash of each.
VIBE_LOCKED="3.0.2"
install_vibe() {
  vb_ver="${HR_VIBE_VERSION:-$VIBE_LOCKED}"; vb_ver="${vb_ver#v}"
  if [ "$vb_ver" = "$VIBE_LOCKED" ]; then
    install_locked_venv "vibe" "${HR_VIBE_BASE_PYTHON:-python3}" "$TOOLS/vibe-venv" vibe.lock.txt || return 1
  else
    install_unlocked_venv "vibe" "${HR_VIBE_BASE_PYTHON:-python3}" "$TOOLS/vibe-venv" "mistral-vibe==$vb_ver" || return 1
  fi
  # RUN WHAT WAS INSTALLED and compare the version it REPORTS: an installer that exits 0 without a
  # working executable is the same lie as a check with no input (jcode's 505-byte shim).
  vb_got="$("$TOOLS/vibe-venv/bin/vibe" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
  if [ "$vb_got" != "$vb_ver" ]; then
    echo "vibe installed but reports '${vb_got:-nothing}', wanted $vb_ver"
    rm -rf "$TOOLS/vibe-venv"; return 1
  fi
}

# fast-agent (Apache-2.0, evalstate/fast-agent) from PyPI as fast-agent-mcp, pinned to the release
# the runner's code was measured against. Its own venv, for opensquilla's reason: it pins a large
# dependency set (mcp, anthropic, openai, google-genai, a2a-sdk) and must not share the runner's
# interpreter.
FAST_AGENT_LOCKED="0.10.47"
install_fast_agent() {
  fa_ver="${HR_FAST_AGENT_VERSION:-$FAST_AGENT_LOCKED}"; fa_ver="${fa_ver#v}"
  if [ "$fa_ver" = "$FAST_AGENT_LOCKED" ]; then
    install_locked_venv "fast-agent" "${HR_FAST_AGENT_BASE_PYTHON:-python3}" "$TOOLS/fast-agent-venv" fast-agent.lock.txt || return 1
  else
    install_unlocked_venv "fast-agent" "${HR_FAST_AGENT_BASE_PYTHON:-python3}" "$TOOLS/fast-agent-venv" "fast-agent-mcp==$fa_ver" || return 1
  fi
  # RUN what was installed and compare the version it REPORTS, and prove the two surfaces this
  # backend depends on: the generic client's own env-var names and the ACP server the runner drives.
  "$TOOLS/fast-agent-venv/bin/python" -c '
import sys, importlib.metadata as md
have = md.version("fast-agent-mcp")
if have != sys.argv[1]:
    sys.exit("fast-agent-mcp %s installed, wanted %s" % (have, sys.argv[1]))
from fast_agent.llm.provider.openai import llm_generic
src = open(llm_generic.__file__).read()
for name in ("GENERIC_BASE_URL",):
    if name not in src:
        sys.exit("fast-agent-mcp %s no longer reads %s, which the runner sets" % (have, name))
if not any(e.name == "fast-agent-acp" for e in md.distribution("fast-agent-mcp").entry_points):
    sys.exit("fast-agent-mcp %s has no fast-agent-acp, which the runner drives" % have)
' "$fa_ver" || { rm -rf "$TOOLS/fast-agent-venv"; return 1; }
}

# Docker Agent (Apache-2.0, docker/docker-agent) from its GitHub release: one static binary per
# platform, ~150 MB, and UPSTREAM PUBLISHES NO CHECKSUM FILE beside them — so the digests are
# computed here and pinned, which is install_goose's arrangement rather than install_omp's. They
# were compared against the real assets, and against GitHub's own per-asset digest, before being
# written down. v1.152.0 upgrades its session database one way (migration 31): a volume that ran it
# cannot go back to an older pin without its resumed sessions failing.
DOCKER_AGENT_LOCKED="1.152.0"
DOCKER_AGENT_PIN="${HR_DOCKER_AGENT_VERSION:-$DOCKER_AGENT_LOCKED}"; DOCKER_AGENT_PIN="${DOCKER_AGENT_PIN#v}"
DOCKER_AGENT_SHA="$(pin_sha DOCKER_AGENT "$DOCKER_AGENT_LOCKED" "$DOCKER_AGENT_PIN" "$(by_arch \
  bb591b3b73e6ce06b24a19732371fefb5a99f001813c94e146a4b1474135c8e8 \
  a048a1b5da4d57b1e9669e72460e16153ea7185722b74a411ea0a9b5341ec94f)")"
install_docker_agent() {
  da_ver="$DOCKER_AGENT_PIN"
  case "$HR_ARCH" in
    amd64) da_asset="docker-agent-linux-amd64" ;;
    arm64) da_asset="docker-agent-linux-arm64" ;;
    *) echo "docker-agent: no binary pinned for $HR_ARCH"; return 1 ;;
  esac
  da_tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/docker/docker-agent/releases/download/v${da_ver}/${da_asset}" \
    -o "$da_tmp/docker-agent" || { rm -rf "$da_tmp"; return 1; }
  check_sha "docker-agent $da_ver" "$da_tmp/docker-agent" "$DOCKER_AGENT_SHA" || { rm -rf "$da_tmp"; return 1; }
  mkdir -p "$TOOLS/bin"
  install -m 0755 "$da_tmp/docker-agent" "$TOOLS/bin/docker-agent" || { rm -rf "$da_tmp"; return 1; }
  rm -rf "$da_tmp"
  # RUN it and compare the version it REPORTS: `docker-agent version` prints
  # "docker-agent version v<version>" — there is no --version flag.
  da_got="$("$TOOLS/bin/docker-agent" version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
  if [ "$da_got" != "$da_ver" ]; then
    echo "docker-agent installed but reports '${da_got:-nothing}', wanted $da_ver"
    rm -f "$TOOLS/bin/docker-agent"; return 1
  fi
}

# CPython 3.14 for dcode alone: deepagents-code 0.2.0 requires Python >=3.14,<3.15 and this image's
# interpreter is 3.12. It is python-build-standalone's install_only_stripped build (MPL-2.0 build
# scripts; CPython itself is PSF-2.0, its LICENSE.txt ships in the tree), checked against the
# sha256 that release publishes in its SHA256SUMS. It lives beside dcode's venv because the venv's
# python3 links into it: the two are installed, and replaced, together.
DCODE_PY_RELEASE="20261021"
DCODE_PY_VERSION="3.14.9"
install_dcode_python() {
  case "$(uname -m)" in
    x86_64|amd64)
      dp_asset="cpython-${DCODE_PY_VERSION}+${DCODE_PY_RELEASE}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
      dp_want="561e91c1cadf30e84aec94d1917384ae3267e5f3e6e135e51fd1578bb19f4064" ;;
    aarch64|arm64)
      dp_asset="cpython-${DCODE_PY_VERSION}+${DCODE_PY_RELEASE}-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz"
      dp_want="6f77731d85a14ed848dd4041478cd3ed511523caa3d896b84b436a7edf13cf62" ;;
    *) echo "dcode: no Python 3.14 pinned for $(uname -m)"; return 1 ;;
  esac
  dp_tmp="$(mktemp -d)"
  # "+" is written %2B in the URL path (what the download was verified with).
  curl -fsSL "https://github.com/astral-sh/python-build-standalone/releases/download/${DCODE_PY_RELEASE}/$(printf '%s' "$dp_asset" | sed 's/+/%2B/')" \
    -o "$dp_tmp/py.tar.gz" || { rm -rf "$dp_tmp"; return 1; }
  dp_have="$(sha256sum "$dp_tmp/py.tar.gz" | awk '{print $1}')"
  if [ "$dp_want" != "$dp_have" ]; then
    echo "dcode: checksum mismatch for $dp_asset (want $dp_want, have $dp_have)"
    rm -rf "$dp_tmp"; return 1
  fi
  rm -rf "$TOOLS/dcode-python"; mkdir -p "$TOOLS/dcode-python"
  tar -xzf "$dp_tmp/py.tar.gz" -C "$TOOLS/dcode-python" --strip-components=1 --no-same-owner \
    || { rm -rf "$dp_tmp" "$TOOLS/dcode-python"; return 1; }
  rm -rf "$dp_tmp"
  dp_got="$("$TOOLS/dcode-python/bin/python3" -c 'import platform; print(platform.python_version())' 2>/dev/null)"
  [ "$dp_got" = "$DCODE_PY_VERSION" ] || { echo "dcode: Python reports '${dp_got:-nothing}', wanted $DCODE_PY_VERSION"; rm -rf "$TOOLS/dcode-python"; return 1; }
}

# Deep Agents Code (MIT, langchain-ai/deepagents) from PyPI, driven through `dcode --acp`, which
# imports deepagents-acp (a dependency of deepagents-code since 0.2.0, pinned in the lock with the
# rest of its tree: the deepagents SDK, langchain, agent-client-protocol).
DCODE_LOCKED="0.2.1"
install_dcode() {
  dc_ver="${HR_DCODE_VERSION:-$DCODE_LOCKED}"; dc_ver="${dc_ver#v}"
  dc_py="${HR_DCODE_BASE_PYTHON:-}"
  if [ -z "$dc_py" ]; then
    install_dcode_python || return 1
    dc_py="$TOOLS/dcode-python/bin/python3"
  fi
  if [ "$dc_ver" = "$DCODE_LOCKED" ]; then
    # forbiddenfruit publishes no wheel, so it is the one distribution built here.
    install_locked_venv "dcode" "$dc_py" "$TOOLS/dcode-venv" dcode.lock.txt forbiddenfruit || return 1
  else
    install_unlocked_venv "dcode" "$dc_py" "$TOOLS/dcode-venv" "deepagents-code==$dc_ver" || return 1
  fi
  # The managed ripgrep, fetched HERE and not inside a turn: this CLI downloads a pinned,
  # SHA-256-verified `rg` of its own the first time `grep` is called, and a turn is not the place
  # for a download. With DEEPAGENTS_CODE_OFFLINE=1 (which the runner sets on every turn) it would
  # instead fall back to "the slow Python regex path" its own documentation names. Not fatal: that
  # fallback is a working search, so a failure here costs speed and nothing else.
  HOME="$TOOLS/dcode-venv" "$TOOLS/dcode-venv/bin/dcode" tools install --json >/dev/null 2>&1 \
    || echo "[harnessrouter] note: dcode's managed ripgrep was not installed; its grep uses the slower Python path"
  # RUN what was installed and compare the version it REPORTS, and prove the surface this backend
  # is driven through: the ACP server mode, whose absence `dcode --acp` reports as an exit rather
  # than as a missing feature.
  "$TOOLS/dcode-venv/bin/python" -c '
import sys, importlib.metadata as md
have = md.version("deepagents-code")
if have != sys.argv[1]:
    sys.exit("deepagents-code %s installed, wanted %s" % (have, sys.argv[1]))
from deepagents_acp.server import AgentServerACP           # what `dcode --acp` imports
from acp import run_agent                                  # and the protocol package under it
import inspect
src = inspect.getsource(AgentServerACP.__init__)
if "load_sessions" not in src:
    sys.exit("deepagents-acp %s no longer takes load_sessions, which is how a turn resumes"
             % md.version("deepagents-acp"))
' "$dc_ver" || { rm -rf "$TOOLS/dcode-venv"; return 1; }
}

# ── the bases installed from npm or PyPI by version ──────────────────────────────────────────────
# Pinned EXACTLY, and each base's whole tree is in its lock: the npm bases' in docker/locks/npm (see
# npm_locked below), the PyPI bases' in docker/locks/<base>.lock.txt (see install_locked_venv).
#
# Qwen Code and Pi were installed with no version at all, once per volume: what npm served on the day
# the volume was created is what it ran (#623). Qwen Code 0.26.3 is the release #609 and #614 ran
# real turns on, and the runner's refusal handling was written against. Pi 1.5.0 is what a volume
# created since 2026-10-01 already runs (npm's latest then), so the pin moves no such volume back a
# major; real turns on it (2026-11-08): a session made on 0.84.2 resumed, and new sessions on a chat
# completions and a Responses connection wrote a file and recalled it. --ignore-scripts is pi's own
# documented install form.
QWEN_PIN="${HR_QWEN_VERSION:-0.26.3}"; QWEN_PIN="${QWEN_PIN#v}"
PI_PIN="${HR_PI_VERSION:-1.5.0}"; PI_PIN="${PI_PIN#v}"
# Pinned: 0.58.0 is the release runner/server.py's gemini code was verified against — the real
# stream-json field names (tool_name/tool_id/parameters), --approval-mode/--skip-trust being
# load-bearing, and --resume latest's semantics all came from reading THIS version's own source.
GEMINI_PIN="${HR_GEMINI_VERSION:-0.58.0}"; GEMINI_PIN="${GEMINI_PIN#v}"
# Pinned: 3.0.60 is the release every behaviour in runner/server.py was verified against — the
# settings-file auth wiring, the one-word-prompt parse, and the broken --json --id resume this port
# deliberately does not use.
CLINE_PIN="${HR_CLINE_VERSION:-3.0.60}"; CLINE_PIN="${CLINE_PIN#v}"
# An install from a fresh volume used to take whatever npm served that day (an August volume ran
# 0.147, a September one 0.154, on the same image). The pin is the version the support matrix ran
# on; bumping it is a PR with a matrix rerun.
CODEX_PIN="${HR_CODEX_VERSION:-0.154.0}"; CODEX_PIN="${CODEX_PIN#v}"
MIMO_PIN="${HR_MIMO_VERSION:-0.1.15}"; MIMO_PIN="${MIMO_PIN#v}"
# The MCP adapter is a pi extension (github.com/nicobailon/pi-mcp-adapter): pi deliberately ships
# without MCP, and the runner mounts it via -e only on turns that configure MCP servers. Its major
# decides which file it reads (2.x mcp.json, 3.x mcp-adapter.json, which the runner writes), so it is
# part of pi's identity: a volume with another adapter is reinstalled with this one.
PI_MCP_PIN="${HR_PI_MCP_ADAPTER_VERSION:-3.1.0}"; PI_MCP_PIN="${PI_MCP_PIN#v}"
npm_g() { npm install -g --prefix "$TOOLS" --no-audit --no-fund "$@"; }

# The npm bases install from a LOCKFILE that ships in this image (/app/locks/npm/<name>/, a
# package.json and the package-lock.json scripts/lock-npm.sh writes from it): the whole tree, every
# package by version, by the URL it comes from and by the sha512 npm checks it against, installed
# with `npm ci --ignore-scripts` into $TOOLS/npm/<name>. A tarball whose bytes differ, or a
# dependency the lock does not name, fails the install. With scripts off, no package's install code
# runs as root; the one that is needed is named where it is used (Claude Code's, which hard-links its
# native binary out of a platform package the lock already holds).
#
# Measured (2026-11-08, amd64): for each of the nine, `npm ci` from its lock lands the same packages
# at the same versions as main's `npm install -g` did that day. The differences are the packages npm
# -g dropped on its own: musl builds (the lock carries their `libc`, so they are skipped the same way)
# and gemini's node-pty 1.0.0, which has no prebuild and failed to compile with no compiler here, so
# npm removed it; it is now in the tree unbuilt, and gemini loads @lydell/node-pty (prebuilt) first.
#
# An override (any version but the lock's) installs as before, with `npm install -g`, and its stamp
# says "unverified".
# npm_lock_spec <name>: the lock's direct dependencies as name@version, in package.json order.
npm_lock_spec() {
  node -e 'const d=require(process.argv[1]).dependencies||{};console.log(Object.entries(d).map(([k,v])=>k+"@"+v).join(" "))' \
    "$HR_LOCKS_DIR/npm/$1/package.json" 2>/dev/null
}
npm_is_locked() { [ -n "$2" ] && [ "$2" = "$(npm_lock_spec "$1")" ]; }
# npm_ident <name> <spec>: the stamp line for an npm base. A regenerated lock in a new image reaches
# a volume that holds the base, the way a PyPI lock does.
npm_ident() {
  if npm_is_locked "$1" "$2"; then echo "npm $2 lock:$(file_sha "$HR_LOCKS_DIR/npm/$1/package-lock.json")"
  else echo "npm $2 unverified"; fi
}
# npm_link_bins <dir>: $TOOLS/bin/<command> for each command a direct dependency declares, as npm -g
# links them (relative symlinks). npm ci links bins into node_modules/.bin, not onto PATH.
npm_link_bins() {
  node -e '
const fs = require("fs"), path = require("path");
const [dir, bin] = process.argv.slice(1);
fs.mkdirSync(bin, { recursive: true });
for (const dep of Object.keys(require(path.join(dir, "package.json")).dependencies || {})) {
  const pd = path.join(dir, "node_modules", dep), p = require(path.join(pd, "package.json"));
  const b = typeof p.bin === "string" ? { [p.name.replace(/^@[^/]+\//, "")]: p.bin } : (p.bin || {});
  for (const [cmd, file] of Object.entries(b)) {
    const target = path.join(pd, file), link = path.join(bin, cmd);
    fs.chmodSync(target, 0o755);
    fs.rmSync(link, { force: true });
    fs.symlinkSync(path.relative(bin, target), link);
  }
}' "$1" "$TOOLS/bin"
}
# npm_locked <name> [<package whose install script runs>…]: $TOOLS/npm/<name> from its lock. What a
# previous `npm install -g` of the same packages left under $TOOLS/lib goes first.
npm_locked() {
  nl_name="$1"; shift
  nl_src="$HR_LOCKS_DIR/npm/$nl_name"; nl_dir="$TOOLS/npm/$nl_name"
  [ -f "$nl_src/package-lock.json" ] || { echo "$nl_name: no lockfile at $nl_src"; return 1; }
  for nl_dep in $(npm_lock_spec "$nl_name"); do
    nl_pkg="${nl_dep%@*}"; rm -rf "$TOOLS/lib/node_modules/$nl_pkg"
    case "$nl_pkg" in @*/*) rmdir "$TOOLS/lib/node_modules/${nl_pkg%%/*}" 2>/dev/null || true ;; esac
  done
  rm -rf "$nl_dir"; mkdir -p "$nl_dir"
  cp "$nl_src/package.json" "$nl_src/package-lock.json" "$nl_dir/" || { rm -rf "$nl_dir"; return 1; }
  ( cd "$nl_dir" && npm ci --ignore-scripts --no-audit --no-fund ) || { rm -rf "$nl_dir"; return 1; }
  if [ $# -gt 0 ]; then
    ( cd "$nl_dir" && npm rebuild --foreground-scripts "$@" ) || { rm -rf "$nl_dir"; return 1; }
  fi
  npm_link_bins "$nl_dir" || { rm -rf "$nl_dir"; return 1; }
}
# npm_unlocked <name> <npm install -g arguments…>: an override, installed the way it always was.
npm_unlocked() {
  find "$TOOLS/bin" -maxdepth 1 -type l -lname "../npm/$1/*" -delete 2>/dev/null || true
  rm -rf "$TOOLS/npm/$1"; shift
  npm_g "$@"
}
# install_npm <name> <spec> [<package whose install script runs>…]
install_npm() {
  in_name="$1"; in_spec="$2"; shift 2
  if npm_is_locked "$in_name" "$in_spec"; then npm_locked "$in_name" "$@"; else npm_unlocked "$in_name" "$in_spec"; fi
}

CLAUDE_SPEC="@anthropic-ai/claude-code@$CLAUDE_CODE_VERSION"
QWEN_SPEC="@qwen-code/qwen-code@$QWEN_PIN"
GEMINI_SPEC="@google/gemini-cli@$GEMINI_PIN"
CLINE_SPEC="cline@$CLINE_PIN"
CODEX_SPEC="@openai/codex@$CODEX_PIN"
PI_SPEC="@earendil-works/pi-coding-agent@$PI_PIN"
PI_MCP_SPEC="pi-mcp-adapter@$PI_MCP_PIN"
MIMO_SPEC="@mimo-ai/cli@$MIMO_PIN"
# Claude Code's install script copies its platform's native binary over the bin/claude.exe stub;
# without it the command prints "native binary not installed". The binary comes from the lock.
install_claude() { install_npm claude "$CLAUDE_SPEC" @anthropic-ai/claude-code; }
install_pi() {
  if npm_is_locked pi "$PI_SPEC"; then npm_locked pi || return 1
  else npm_unlocked pi --ignore-scripts "$PI_SPEC" || return 1; fi
  if npm_is_locked pi-mcp-adapter "$PI_MCP_SPEC"; then npm_locked pi-mcp-adapter || return 1
  else npm_unlocked pi-mcp-adapter --ignore-scripts "$PI_MCP_SPEC" || return 1; fi
}

# DeepSeek Harness, pinned EXACTLY, not 'latest': upstream is a developer preview that warns of
# breaking changes, and the runner's driver/normalizer are written against these bytes. Own venv: its
# dependency tree must not fight hermes's. pyyaml is the version a fresh volume resolved on 0.38.2.
# From docker/locks/dsh.lock.txt; the runtime is a platform wheel, and the lock holds both.
DSH_PIN="0.1.2rc1"
DSH_PYYAML_PIN="6.0.3"
DSH_REQS=("deepseek-harness-sdk==$DSH_PIN" "deepseek-harness-runtime-bin==$DSH_PIN" "pyyaml==$DSH_PYYAML_PIN")
install_dsh() {
  install_pinned_venv dsh "$PY" "$TOOLS/dsh-venv" "" "${DSH_REQS[@]}" || return 1
  # dsh-ready exists ONLY after the import check proved the runtime executable resolves — a venv
  # whose pip half-failed must not report the backend as available.
  "$TOOLS/dsh-venv/bin/python" -c 'import deepseek_harness, deepseek_harness_runtime, yaml; deepseek_harness_runtime.bundled_runtime_path()' || return 1
  printf '#!/bin/sh\necho %s\n' "$DSH_PIN" > "$TOOLS/dsh-venv/bin/dsh-ready" && chmod 755 "$TOOLS/dsh-venv/bin/dsh-ready"
}

# Hermes. [anthropic] is hermes's own pin of the Anthropic SDK (0.87.0 for 0.19.0): a bare
# `anthropic` resolved to the newest SDK, whose 1.x line moved to httpx2 while hermes still builds its
# client with httpx.Timeout, so a fresh volume died on every Claude turn (2026-09-30).
#
# boto3: hermes's bedrock provider imports it at call time, and lazy installs are sealed, so without
# it every hermes turn on a bedrock-served model died with "The 'boto3' package is required" (#37).
# Pinned to the version a fresh volume resolved on 0.38.2.
#
# mcp: hermes 0.19.0 gates HTTP MCP on importing `streamablehttp_client`, which the SDK REMOVED in
# 2.0.0; with 2.x installed hermes silently drops every remote MCP server. 1.30.0 is the last 1.x and
# the floor four advisories against older versions set.
#
# All of it, and hermes's whole tree, installs from docker/locks/hermes.lock.txt.
#
# These used to be repaired at every start (a `pip install` whenever an import failed); a stamp that
# does not match now reinstalls from these pins instead, and the install proves both imports, so there
# is no start-time pip at all. The breaker patch is part of the install for the same reason, and its
# digest is part of hermes's identity, so a changed patch reaches a volume that holds hermes.
HERMES_PIN="0.19.0"
HERMES_BOTO3_PIN="1.43.126"
# HR_HERMES_MCP_VERSION is a version. (HERMES_MCP_PIN, which it replaces, was a range.)
if [ -n "${HERMES_MCP_PIN:-}" ]; then
  echo "[harnessrouter] WARN: HERMES_MCP_PIN is no longer read; Hermes gets mcp ${HR_HERMES_MCP_VERSION:-1.30.0}. Set HR_HERMES_MCP_VERSION to an exact version to choose another."
fi
HERMES_MCP_PIN="${HR_HERMES_MCP_VERSION:-1.30.0}"
HERMES_REQS=("hermes-agent[anthropic]==$HERMES_PIN" "boto3==$HERMES_BOTO3_PIN" "mcp==$HERMES_MCP_PIN")
HERMES_BREAKER=/app/runner/patches/hermes_mcp_breaker.py
install_hermes() {
  install_pinned_venv hermes "$PY" "$TOOLS/venv" "" "${HERMES_REQS[@]}" || return 1
  "$TOOLS/venv/bin/python" -c '
import boto3  # noqa: F401 - the bedrock provider
from mcp.client.streamable_http import streamablehttp_client  # noqa: F401 - the name hermes gates HTTP MCP on
' || { echo "hermes: boto3 or mcp's streamablehttp_client does not import"; return 1; }
  hermes_breaker
}
# hermes 0.19.0 counts a tool's own error answer ("no such document") as its MCP server failing:
# three in a row and every tool of that server is refused for 60 s as "unreachable", so an agent that
# guessed three ids wrong reports the service down (runner/patches/hermes_mcp_breaker.py). Idempotent,
# and it writes nothing unless the result compiles; a hermes whose source is not the one it was written
# for is left as it is, with one line saying so. That line is kept in HERMES_BREAKER_NOTE and said
# after the install, because try_install shows an installer's output only when it fails.
HERMES_BREAKER_NOTE=""
hermes_breaker() {
  _hmt=$("$TOOLS/venv/bin/python" -c "import importlib.metadata as m; d = m.distribution('hermes-agent'); print(next(str(d.locate_file(f)) for f in d.files if str(f).endswith('tools/mcp_tool.py')))" 2>/dev/null) || _hmt=""
  if [ -z "$_hmt" ] || [ ! -f "$_hmt" ]; then
    HERMES_BREAKER_NOTE="Hermes's MCP module was not found; a tool's own errors may be counted as its server failing"
    return 0
  fi
  _out=$("$TOOLS/venv/bin/python" "$HERMES_BREAKER" "$_hmt" 2>&1) || true
  case "$_out" in
    *"already applied"*|*": applied"*) : ;;
    *) HERMES_BREAKER_NOTE="$_out" ;;
  esac
  return 0
}

# Run an install and, if it fails, SAY WHY.
#
# This was `>/dev/null 2>&1 || true`, and the silence cost a day of someone's life: a root-owned
# npm cache baked into the image made every `npm install` fail with EACCES, and the only trace was
# the "requested but not installed" line further down — which reads like a configuration choice,
# not a broken install. An optional step may fail without stopping start-up; it may not fail
# without leaving the reason where the person looking will find it.
# What an installer's processes may read of this environment: an allow-list (#623 step 3, its
# environment half). An install runs packages' own code (npm lifecycle scripts, setup.py, build
# backends), and their dependencies still resolve within upstream's ranges until the locks land. Each
# of those used to see the whole environment: HARNESS_INTERNAL_KEY, HR_AUTH_PASSWORD and every
# provider key an operator passed with -e. Now each sees what fetching and building need: the path and
# home, the locale, the proxy and CA settings, and the operator's registry settings (PIP_*, NPM_CONFIG_*,
# UV_*). A base that needs a token to install gets that one name here, never the whole environment.
# This stops code that reads or reports its environment. It does not stop code that sets out to read
# the secrets: installs still run as root, who can read /proc/1/environ and /data/secret-key. Running
# them as their own uid is what closes that.
install_env_ok() {
  case "$1" in
    PATH|HOME|LANG|LANGUAGE|LC_*|TZ|TERM|TMPDIR|PWD|SHLVL|OLDPWD) return 0 ;;
    HTTP_PROXY|HTTPS_PROXY|NO_PROXY|ALL_PROXY|http_proxy|https_proxy|no_proxy|all_proxy) return 0 ;;
    SSL_CERT_FILE|SSL_CERT_DIR|REQUESTS_CA_BUNDLE|CURL_CA_BUNDLE|NODE_EXTRA_CA_CERTS) return 0 ;;
    PIP_*|NPM_CONFIG_*|npm_config_*|UV_*) return 0 ;;
    DEBIAN_FRONTEND|PYTHONUNBUFFERED|NODE_PATH|PLAYWRIGHT_BROWSERS_PATH) return 0 ;;
  esac
  return 1
}
# install_env_only: in an install's own subshell, every other variable stays readable by this script
# and is no longer exported to the processes the install starts.
install_env_only() {
  local v
  for v in $(compgen -e); do install_env_ok "$v" || export -n "$v"; done
}
try_install() {
  label="$1"; shift
  log="$(mktemp)"
  if ( install_env_only; "$@" ) >"$log" 2>&1; then rm -f "$log"; return 0; fi
  echo "[harnessrouter] WARN: could not install $label — it will not be available:"
  tail -n 12 "$log" | sed 's/^/[harnessrouter]   /'
  rm -f "$log"
  return 1
}

# lock_ident <version> <locked version> <lock file>: a locked base's identity is the lock it was
# installed from, so a regenerated lock in a new image reaches a volume that holds the base.
lock_ident() {
  if [ "$1" = "$2" ]; then echo "$1 lock:$(file_sha "$HR_LOCKS_DIR/$3")"; else echo "$1 unverified"; fi
}

# Every base, in one form: `current` reads the stamp, and anything other than this script's pin is
# replaced in place. Nothing here runs an installed base to ask its version. A volume created before
# stamps existed reinstalls each base once, which is how what `latest` gave it is replaced.
install_backends() {
  mkdir -p "$TOOLS"
  # The npm bases' $TOOLS/bin/<cmd> is a link npm_link_bins makes (or, for an override, the one npm -g
  # makes); install_base checks the executable either way.
  # Claude Code: a model can require a minimum CLI (Claude Opus 5.5 needs 2.1.280; the API refuses
  # older ones), and a volume that installed the CLI once, months ago, would otherwise never learn it.
  if wanted claude && ! current claude "$(npm_ident claude "$CLAUDE_SPEC")"; then
    echo "[harnessrouter] installing Claude Code $CLAUDE_CODE_VERSION (Anthropic's terms apply)…"
    install_base claude "Claude Code" install_claude || true
  fi
  # opencode is MIT, so unlike Claude Code and hermes it COULD be baked into the image. It is
  # installed here anyway so that every backend has ONE install path.
  if wanted opencode && ! current opencode "$(ident "$OPENCODE_PIN" "$OPENCODE_SHA")"; then
    echo "[harnessrouter] installing opencode $OPENCODE_PIN (MIT)…"
    install_base opencode "opencode" install_opencode || true
  fi
  if wanted kilo && ! current kilo "$(ident "$KILO_PIN" "$KILO_SHA")"; then
    echo "[harnessrouter] installing Kilo CLI $KILO_PIN (MIT)…"
    install_base kilo "Kilo CLI" install_kilo || true
  fi
  if wanted qwen && ! current qwen "$(npm_ident qwen "$QWEN_SPEC")"; then
    echo "[harnessrouter] installing Qwen Code $QWEN_PIN (Apache-2.0)…"
    install_base qwen "Qwen Code" install_npm qwen "$QWEN_SPEC" || true
  fi
  if wanted gemini && ! current gemini "$(npm_ident gemini "$GEMINI_SPEC")"; then
    echo "[harnessrouter] installing Gemini CLI $GEMINI_PIN (Apache-2.0)…"
    install_base gemini "Gemini CLI" install_npm gemini "$GEMINI_SPEC" || true
  fi
  if wanted cline && ! current cline "$(npm_ident cline "$CLINE_SPEC")"; then
    echo "[harnessrouter] installing Cline $CLINE_PIN (Apache-2.0)…"
    install_base cline "Cline" install_npm cline "$CLINE_SPEC" || true
  fi
  if wanted codex && ! current codex "$(npm_ident codex "$CODEX_SPEC")"; then
    echo "[harnessrouter] installing Codex $CODEX_PIN (Apache-2.0)…"
    install_base codex "Codex" install_npm codex "$CODEX_SPEC" || true
  fi
  if wanted pi && ! current pi "$(npm_ident pi "$PI_SPEC") $(npm_ident pi-mcp-adapter "$PI_MCP_SPEC")"; then
    echo "[harnessrouter] installing Pi $PI_PIN and pi-mcp-adapter $PI_MCP_PIN (MIT)…"
    install_base pi "Pi" install_pi || true
  fi
  if wanted omp && ! current omp "$(ident "$OMP_PIN" "$OMP_SHA")"; then
    echo "[harnessrouter] installing Oh My Pi $OMP_PIN (MIT)…"
    install_base omp "Oh My Pi" install_omp || true
  fi
  if wanted goose && ! current goose "$(ident "$GOOSE_PIN" "$GOOSE_SHA")"; then
    echo "[harnessrouter] installing goose $GOOSE_PIN (Apache-2.0)…"
    install_base goose "goose" install_goose || true
  fi
  if wanted openhands && ! current openhands "$(pinned_ident openhands "${OPENHANDS_REQS[@]}")"; then
    echo "[harnessrouter] installing OpenHands agent-server $OPENHANDS_PIN (MIT) — ~666 MB, this takes a minute…"
    install_base openhands "OpenHands" install_openhands || true
  fi
  if wanted systemone && ! current systemone "$(pinned_ident systemone "${SYSTEMONE_REQS[@]}")"; then
    echo "[harnessrouter] installing System One Harness $SYSTEMONE_PIN (Apache-2.0)…"
    install_base systemone "System One Harness" install_systemone || true
  fi
  if wanted systemone && [ -x "$TOOLS/systemone-venv/bin/playwright" ]; then
    chromium_libs || echo "[harnessrouter]   WARNING: Chromium's system libraries could not be installed; the System One base's browser environments will not start until they are (retried on the next start)"
  fi
  if wanted cheetahclaws && ! current cheetahclaws "$(pinned_ident cheetahclaws "${CHEETAHCLAWS_REQS[@]}")"; then
    echo "[harnessrouter] installing CheetahClaws $CHEETAHCLAWS_PIN (Apache-2.0)…"
    install_base cheetahclaws "CheetahClaws" install_cheetahclaws || true
  fi
  [ -x "$TOOLS/cheetahclaws-venv/bin/python" ] && export HR_CHEETAHCLAWS_PYTHON="$TOOLS/cheetahclaws-venv/bin/python"
  if wanted qoder && ! current qoder "$(pinned_ident qoder "${QODER_REQS[@]}")"; then
    echo "[harnessrouter] installing the Qoder Cloud Agents SDK qca-sdk $QODER_PIN (MIT)…"
    install_base qoder "Qoder SDK" install_qoder || true
  fi
  [ -x "$TOOLS/qoder-venv/bin/python" ] && export HR_QODER_PYTHON="$TOOLS/qoder-venv/bin/python"
  # The archive's digest and the lock its dependencies come from. The lock is used only when the
  # archive yields the requirements it was compiled from, which the pinned archive does (its digest
  # is checked first), so the pin and the default ipython are what decide it here.
  if [ "$AGENTZERO_PIN" = "2.13" ] && [ "${HR_AGENTZERO_IPYTHON_VERSION:-9.17.1}" = "9.17.1" ]; then
    AGENTZERO_DEPS="lock:$(file_sha "$HR_LOCKS_DIR/agentzero.lock.txt")"
  else
    AGENTZERO_DEPS="deps unverified"
  fi
  if wanted agentzero && ! current agentzero "$(ident "$AGENTZERO_PIN" "$AGENTZERO_SHA") $AGENTZERO_DEPS"; then
    echo "[harnessrouter] installing Agent Zero $AGENTZERO_PIN (MIT) — ~640 MB, this takes a minute or two…"
    install_base agentzero "Agent Zero" install_agentzero || true
  fi
  # A volume first started by 0.18.0 holds Kimi CLI 1.50.0, the predecessor, under the same name;
  # its stamp is missing, so it is replaced with Kimi Code CLI here.
  if wanted kimi && ! current kimi "$(ident "$KIMI_PIN" "$KIMI_SHA")"; then
    echo "[harnessrouter] installing Kimi Code CLI $KIMI_PIN (MIT)…"
    install_base kimi "Kimi Code CLI" install_kimi || true
  fi
  if wanted minimax && ! current minimax "$(npm_ident minimax "$MINIMAX_SPEC")"; then
    echo "[harnessrouter] installing MiniMax Code $MINIMAX_PIN (MIT)…"
    install_base minimax "MiniMax Code" install_minimax || true
  fi
  if wanted grok && ! current grok "$(ident "$GROK_PIN" "$GROK_SHA")"; then
    echo "[harnessrouter] installing Grok Build $GROK_PIN (Apache-2.0)…"
    install_base grok "Grok Build" install_grok || true
  fi
  if wanted mimo && ! current mimo "$(npm_ident mimo "$MIMO_SPEC")"; then
    echo "[harnessrouter] installing MiMo Code $MIMO_PIN (MIT)…"
    install_base mimo "MiMo Code" install_mimo || true
  fi

  if wanted roder && ! current roder "$(ident "$RODER_PIN" "$RODER_SHA")"; then
    echo "[harnessrouter] installing Roder $RODER_PIN (MIT, version-pinned)…"
    install_base roder "Roder" install_roder || true
  fi

  if wanted jcode && ! current jcode "$(ident "$JCODE_PIN" "$JCODE_SHA")"; then
    echo "[harnessrouter] installing jcode $JCODE_PIN (MIT) — ~127 MB…"
    install_base jcode "jcode" install_jcode || true
  fi
  if wanted opensquilla && ! current opensquilla "$(pinned_ident opensquilla "${OPENSQUILLA_REQS[@]}")"; then
    echo "[harnessrouter] installing OpenSquilla $OPENSQUILLA_PIN (Apache-2.0)…"
    install_base opensquilla "OpenSquilla" install_opensquilla || true
  fi
  if wanted nanobot && ! current nanobot "$(pinned_ident nanobot "${NANOBOT_REQS[@]}")"; then
    echo "[harnessrouter] installing nanobot $NANOBOT_PIN (MIT)…"
    install_base nanobot "nanobot" install_nanobot || true
  fi
  [ -x "$TOOLS/nanobot-venv/bin/python" ] && export HR_NANOBOT_PYTHON="$TOOLS/nanobot-venv/bin/python"
  VIBE_PIN="${HR_VIBE_VERSION:-$VIBE_LOCKED}"; VIBE_PIN="${VIBE_PIN#v}"
  if wanted vibe && ! current vibe "$(lock_ident "$VIBE_PIN" "$VIBE_LOCKED" vibe.lock.txt)"; then
    echo "[harnessrouter] installing Mistral Vibe $VIBE_PIN (Apache-2.0)…"
    install_base vibe "Mistral Vibe" install_vibe || true
  fi
  [ -x "$TOOLS/vibe-venv/bin/vibe" ] && export HR_VIBE_BIN="$TOOLS/vibe-venv/bin/vibe"
  FAST_AGENT_PIN="${HR_FAST_AGENT_VERSION:-$FAST_AGENT_LOCKED}"; FAST_AGENT_PIN="${FAST_AGENT_PIN#v}"
  if wanted fast-agent && ! current fast-agent "$(lock_ident "$FAST_AGENT_PIN" "$FAST_AGENT_LOCKED" fast-agent.lock.txt)"; then
    echo "[harnessrouter] installing fast-agent $FAST_AGENT_PIN (Apache-2.0)…"
    install_base fast-agent "fast-agent" install_fast_agent || true
  fi
  if [ -x "$TOOLS/fast-agent-venv/bin/fast-agent-acp" ]; then
    export HR_FAST_AGENT_ACP_BIN="$TOOLS/fast-agent-venv/bin/fast-agent-acp"
    # The driver is stdlib-only, so the agent's own interpreter runs it (dcode's arrangement).
    export HR_FAST_AGENT_PYTHON="$TOOLS/fast-agent-venv/bin/python"
  fi
  # dcode's identity carries the interpreter it was built on: the pinned CPython, or the operator's.
  DCODE_PIN="${HR_DCODE_VERSION:-$DCODE_LOCKED}"; DCODE_PIN="${DCODE_PIN#v}"
  if wanted dcode && ! current dcode "$(lock_ident "$DCODE_PIN" "$DCODE_LOCKED" dcode.lock.txt) python:${HR_DCODE_BASE_PYTHON:-$DCODE_PY_VERSION+$DCODE_PY_RELEASE}"; then
    echo "[harnessrouter] installing Deep Agents Code $DCODE_PIN (MIT)…"
    install_base dcode "Deep Agents Code" install_dcode || true
  fi
  if [ -x "$TOOLS/dcode-venv/bin/dcode" ]; then
    export HR_DCODE_BIN="$TOOLS/dcode-venv/bin/dcode"
    # The driver is stdlib-only, so the CLI's own interpreter runs it and no second venv exists
    # for a backend to drift out of (nanobot's arrangement).
    export HR_DCODE_PYTHON="$TOOLS/dcode-venv/bin/python"
  fi
  if wanted docker-agent && ! current docker-agent "$(ident "$DOCKER_AGENT_PIN" "$DOCKER_AGENT_SHA")"; then
    echo "[harnessrouter] installing Docker Agent $DOCKER_AGENT_PIN (Apache-2.0) — ~150 MB…"
    install_base docker-agent "Docker Agent" install_docker_agent || true
  fi
  if wanted zeroclaw && ! current zeroclaw "$(ident "$ZEROCLAW_PIN" "$ZEROCLAW_SHA")"; then
    echo "[harnessrouter] installing zeroclaw $ZEROCLAW_PIN (Apache-2.0)…"
    install_base zeroclaw "zeroclaw" install_zeroclaw || true
  fi
  [ -x "$(backend_bin zeroclaw)" ] && export HR_ZEROCLAW_BIN="$(backend_bin zeroclaw)"
  # Both venv bases are reached by PATH from the runner, so the interpreter and the console script
  # are named explicitly — $TOOLS/bin is what PATH carries, and neither of these lives there.
  [ -x "$TOOLS/opensquilla-venv/bin/opensquilla" ] && export HR_OPENSQUILLA_BIN="$TOOLS/opensquilla-venv/bin/opensquilla"
  # The largest install of the set: ~735 MB and about ninety seconds on a fresh volume
  # (tree-sitter-language-pack 351 MB, scipy 100, numpy 57). In the default list all the same,
  # because the console offers every base the gateway's catalogue lists and a base that is listed
  # but not installed fails on its first task; an operator who does not want it leaves it out of
  # HR_BACKENDS, the same switch every backend has.
  if wanted aider && ! current aider "$(pinned_ident aider "${AIDER_REQS[@]}")"; then
    echo "[harnessrouter] installing Aider $AIDER_PIN (Apache-2.0) — ~735 MB, this takes a minute…"
    install_base aider "Aider" install_aider || true
  fi
  if wanted dsh && ! current dsh "$(pinned_ident dsh "${DSH_REQS[@]}")"; then
    echo "[harnessrouter] installing DeepSeek Harness $DSH_PIN (MIT, developer preview)…"
    install_base dsh "DeepSeek Harness" install_dsh || true
  fi
  if wanted hermes && ! current hermes "$(pinned_ident hermes "${HERMES_REQS[@]}") breaker:$(file_sha "$HERMES_BREAKER")"; then
    echo "[harnessrouter] installing Hermes $HERMES_PIN (check its upstream license before use)…"
    install_base hermes "Hermes" install_hermes || true
    [ -z "$HERMES_BREAKER_NOTE" ] || echo "[harnessrouter] WARNING: $HERMES_BREAKER_NOTE"
  fi

  [ -d "$TOOLS/venv/bin" ] && export PATH="$TOOLS/venv/bin:$PATH"
  # Hermes otherwise tries to install its own dependencies mid-turn.
  export HERMES_DISABLE_LAZY_INSTALLS=1
  # Where the runner finds the MCP extension to mount (-e) on pi turns with MCP servers.
  if [ -d "$TOOLS/npm/pi-mcp-adapter/node_modules/pi-mcp-adapter" ]; then
    export HR_PI_MCP_EXT="$TOOLS/npm/pi-mcp-adapter/node_modules/pi-mcp-adapter"
  elif [ -d "$TOOLS/lib/node_modules/pi-mcp-adapter" ]; then
    export HR_PI_MCP_EXT="$TOOLS/lib/node_modules/pi-mcp-adapter"
  fi
  [ -x "$TOOLS/dsh-venv/bin/python" ] && export HR_DSH_PYTHON="$TOOLS/dsh-venv/bin/python"
  # The last command is a test, and under `set -e` a false one as a function's last status aborts
  # the entrypoint (an instance without hermes once died here with no message), so it ends on true.
  return 0
}

install_backends
seal_tools    # nothing else is running yet: the runner and the gateway start below

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
( cd /app/gateway && export HR_SECRET_KEY="$GATEWAY_SECRET_KEY" && exec $AS_PRODUCT sh -c 'umask 077; exec "$0" -m uvicorn app:app --host 127.0.0.1 --port 8080 --log-level warning' "$PY" ) &
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
