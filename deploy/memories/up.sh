#!/usr/bin/env bash
# Start memory engines beside HarnessRouter, connected to it, with no model key of their own.
#
#   ./up.sh                    every engine: mem0, graphiti, hindsight and reme
#   ./up.sh mem0 hindsight     only these (engines already running keep running)
#   ./up.sh --down             stop every engine; what they remember is kept
#
# Every run does the same five things, and keeps whatever already works, so run it again at any time:
#   1. finds your HarnessRouter container: the one named in HR_CONTAINER, else the one running;
#   2. asks that HarnessRouter, from inside its container, for a model credential for each engine, so the
#      engines read and search with HarnessRouter's own model keys and need none of their own;
#   3. writes .env beside this file (mode 600) with that credential and every secret the engines need;
#   4. starts the engines, puts HarnessRouter on their network and waits until each one answers it;
#   5. connects each engine to HarnessRouter, so every new agent can remember.
#
# Optional settings: HR_CONTAINER (the HarnessRouter container), HR_MEMORIES_NAME (the name of this stack
# and of its network, harnessrouter-memories unless set), HR_MEMORIES_WAIT (seconds to wait for the
# engines to answer, 900 unless set). MEMORY_MODEL and EMBEDDING_MODEL in .env choose the models.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="${HR_MEMORIES_NAME:-harnessrouter-memories}"
WAIT="${HR_MEMORIES_WAIT:-900}"
ENV_FILE="$HERE/.env"
ME="$0"
ALL="mem0 graphiti hindsight reme"

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf '\nup.sh: %s\n' "$*" >&2; exit 1; }

label_of() { case "$1" in mem0) echo Mem0 ;; graphiti) echo Graphiti ;; hindsight) echo Hindsight ;; reme) echo ReMe ;; esac; }
addr_of()  { case "$1" in mem0) echo http://mem0:8000 ;; graphiti) echo http://graphiti:8000 ;; hindsight) echo http://hindsight:8888 ;; reme) echo http://reme:2333 ;; esac; }
# the key HarnessRouter connects to the engine with, where the engine takes one
secret_of() { case "$1" in mem0) echo MEM0_ADMIN_API_KEY ;; graphiti) echo GRAPHITI_API_KEY ;; *) echo "" ;; esac; }
# the engine's own model credential in .env
model_key_of() { printf '%s_MODEL_KEY' "$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"; }

# ── arguments ─────────────────────────────────────────────────────────────────────────────────
DOWN=0
ENGINES=""
for a in "$@"; do
  case "$a" in
    --down) DOWN=1 ;;
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    mem0|graphiti|hindsight|reme) case " $ENGINES " in *" $a "*) ;; *) ENGINES="$ENGINES $a" ;; esac ;;
    *) die "there's no engine called '$a'. The engines are: $ALL." ;;
  esac
done
ENGINES="${ENGINES# }"
if [ "$DOWN" = 1 ] && [ -n "$ENGINES" ]; then die "--down stops every engine, so it takes no engine names."; fi
[ -n "$ENGINES" ] || ENGINES="$ALL"

# ── what this machine has ─────────────────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || die "Docker isn't installed here. Install Docker Desktop (macOS, Windows) or Docker Engine (Linux), then run this again."
docker info >/dev/null 2>&1 || die "Docker isn't answering. Start it (Docker Desktop, or: sudo systemctl start docker), or check that this user may use it, then run this again."
docker compose version >/dev/null 2>&1 || die "Docker Compose isn't installed. It comes with Docker Desktop; on Linux, install the docker-compose-plugin package."
[ -f "$HERE/docker-compose.yml" ] || die "docker-compose.yml isn't beside this script. Run it from the deploy/memories folder it came in."

# an override file beside it counts, as it would for a plain `docker compose`
FILES=(-f "$HERE/docker-compose.yml")
[ ! -f "$HERE/docker-compose.override.yml" ] || FILES+=(-f "$HERE/docker-compose.override.yml")
compose() { HR_MEMORIES_NAME="$NAME" docker compose --project-directory "$HERE" "${FILES[@]}" -p "$NAME" "$@"; }
PROFILES=""
for e in $ENGINES; do PROFILES="$PROFILES --profile $e"; done
ALL_PROFILES=""
for e in $ALL; do ALL_PROFILES="$ALL_PROFILES --profile $e"; done

if [ "$DOWN" = 1 ]; then
  step "Stopping the memory engines"
  # shellcheck disable=SC2086
  compose $ALL_PROFILES down
  say ""
  say "Stopped. What they remember is kept in their Docker volumes (${NAME}_*), and $ME starts them again."
  say "The $NAME network stays, so a HarnessRouter container started with it still starts."
  exit 0
fi

# ── the HarnessRouter container ───────────────────────────────────────────────────────────────
find_hr() {
  if [ -n "${HR_CONTAINER:-}" ]; then
    local running
    running="$(docker inspect -f '{{.State.Running}}' "$HR_CONTAINER" 2>/dev/null)" \
      || die "there's no container called '$HR_CONTAINER' (from HR_CONTAINER). See your containers with: docker ps"
    [ "$running" = true ] || die "the HarnessRouter container '$HR_CONTAINER' isn't running. Start it (docker start $HR_CONTAINER), then run this again."
    printf '%s\n' "$HR_CONTAINER"
    return
  fi
  local found n
  # Images from 0.40 on carry this label; an older one is known by its name (harnessrouter/harnessrouter,
  # harnessrouter:local). This stack's own containers are never it, whatever their image is called.
  found="$(docker ps --filter label=io.harnessrouter.role=instance --format '{{.Names}}')"
  if [ -z "$found" ]; then
    found="$(docker ps --format '{{.Names}} {{.Image}} {{.Label "com.docker.compose.project"}}' | awk -v me="$NAME" '
      $3 == me { next }
      { img = $2; sub(/@.*/, "", img); n = split(img, p, "/"); sub(/:.*/, "", p[n]); if (p[n] == "harnessrouter") print $1 }')"
  fi
  n="$(printf '%s\n' "$found" | grep -c . || true)"
  if [ "$n" = 0 ]; then
    die "no HarnessRouter container is running. Start HarnessRouter first (Install, in the self-hosting guide), or name its container: HR_CONTAINER=<name> $ME"
  fi
  if [ "$n" != 1 ]; then
    die "more than one HarnessRouter container is running ($(printf '%s' "$found" | tr '\n' ' ')). Name the one to use: HR_CONTAINER=<name> $ME"
  fi
  printf '%s\n' "$found"
}

# What runs inside the HarnessRouter container, as its own product user (agent), never as root. The internal
# key is read there, from the gateway's own environment, and is never printed or sent back out. Input is JSON
# on stdin; each output line is "<word> <engine> <value>".
HR_PY='
import json, os, sys, time, urllib.error, urllib.request
GW = "http://127.0.0.1:8080"
OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def internal_key():
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if b"app:app" not in f.read().split(b"\0"):
                    continue
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = f.read().split(b"\0")
        except OSError:
            continue
        for kv in env:
            k, _, v = kv.partition(b"=")
            if k == b"HARNESS_INTERNAL_KEY" and v:
                return v.decode()
    return ""

def call(method, path, body=None, bearer="", local=False, key=""):
    h = {"content-type": "application/json"}
    if key:
        h["x-harness-internal"] = key
    if local:
        h.update({"x-harness-org": "local", "x-harness-member": "local@localhost", "x-harness-workspace": "default"})
    if bearer:
        h["authorization"] = "Bearer " + bearer
    req = urllib.request.Request(GW + path, method=method, headers=h,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with OPEN.open(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        return 0, {"detail": str(getattr(e, "reason", e))}

def why(d):
    e = d.get("error") if isinstance(d, dict) else None
    if isinstance(e, dict) and e.get("message"):
        return str(e["message"])
    return str((d or {}).get("detail") or d or "no reason given").replace("\n", " ")

def out(*words):
    print(" ".join(str(w) for w in words), flush=True)

def ready():
    for _ in range(90):
        if call("GET", "/healthz")[0] == 200:
            return True
        time.sleep(2)
    return False

act, inp = sys.argv[1], json.load(sys.stdin)
if act == "wait":
    # each engine answers when its address gives any HTTP answer at all, from here, on the network
    left, end = dict(inp["engines"]), time.time() + inp["wait"]
    start = time.time()
    while left and time.time() < end:
        for eng, url in list(left.items()):
            try:
                OPEN.open(urllib.request.Request(url), timeout=5).close()
                ok = True
            except urllib.error.HTTPError:
                ok = True
            except (urllib.error.URLError, OSError):
                ok = False
            if ok:
                out("up", eng, int(time.time() - start))
                del left[eng]
        if left:
            time.sleep(3)
    for eng in left:
        out("down", eng, "-")
    sys.exit(0)

if not ready():
    out("error", "-", "HarnessRouter in this container is not answering yet. Wait until its log says it is ready, then run this again.")
    sys.exit(0)
KEY = internal_key()
if not KEY:
    out("error", "-", "HarnessRouter is running here but its gateway could not be read. Is this a HarnessRouter container?")
    sys.exit(0)

if act == "credentials":
    st, lst = call("GET", "/v1/memory-services", key=KEY)
    if st != 200:
        out("error", "-", f"HarnessRouter did not list its memory credentials (HTTP {st}): {why(lst)}")
        sys.exit(0)
    services = {s.get("id"): s for s in lst.get("data") or []}
    for eng, cur in inp["engines"].items():
        sid = cur[4:].rsplit(".", 1)[0] if cur.startswith("hrm_") and "." in cur else ""
        s = services.get(sid)
        if s and not s.get("revoked") and s.get("vendor") == eng \
                and s.get("llm_model") == inp["llm"] and s.get("embedding_model") == inp["embedding"]:
            # A path the relay never serves: it answers 403 to a credential it accepts and 401 to one it does not.
            if call("GET", "/v1/llm/v1/models", bearer=cur)[0] == 403:
                out("kept", eng, "-")
                continue
        if s and not s.get("revoked"):
            call("POST", f"/v1/memory-services/{sid}/revoke", key=KEY)
        st, d = call("POST", "/v1/memory-services", {"vendor": eng, "llm_model": inp["llm"], "embedding_model": inp["embedding"]}, key=KEY)
        if st != 200 or not str(d.get("credential") or "").startswith("hrm_"):
            out("refused", eng, why(d))
            continue
        out("renewed" if cur else "new", eng, d["credential"])
    sys.exit(0)

if act == "connect":
    for eng, c in inp["engines"].items():
        body = {"enabled": True, "config": {"base_url": c["base_url"]}}
        if c.get("api_key"):
            body["secrets"] = {"api_key": c["api_key"]}
        st, d = call("PUT", f"/v1/plugs/{eng}", body, key=KEY, local=True)
        if st == 200 and d.get("status") == "connected":
            out("connected", eng, "-")
        else:
            out("refused", eng, why(d) if st else f"HarnessRouter did not answer: {why(d)}")
    sys.exit(0)
'
hr_py() { docker exec -i -u agent "$HR" /usr/local/bin/python3 -I -c "$HR_PY" "$1"; }

# ── .env: secrets made here, kept here, mode 600 ─────────────────────────────────────────────
env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 || true; }
# The value goes through the environment, never a command line another user could read.
env_set() {
  local tmp
  tmp="$(mktemp "$HERE/.env.XXXXXX")"
  K="$1" V="$2" awk 'BEGIN { k = ENVIRON["K"]; v = ENVIRON["V"]; done = 0 }
    index($0, k "=") == 1 { if (!done) print k "=" v; done = 1; next }
    { print }
    END { if (!done) print k "=" v }' "$ENV_FILE" > "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$ENV_FILE"
}
secret() { od -An -tx1 -N32 /dev/urandom | tr -d ' \n'; }

HR="$(find_hr)" || exit 1
step "HarnessRouter: $HR"
docker exec "$HR" test -f /app/gateway/app.py 2>/dev/null || die "'$HR' isn't a HarnessRouter container (it has no /app/gateway). Name the right one: HR_CONTAINER=<name> $ME"
HR_PORT="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$HR" | sed -n 's/^PORT=//p' | tail -n 1)"
HR_PORT="${HR_PORT:-3000}"

if [ ! -f "$ENV_FILE" ]; then
  ( umask 077; if [ -f "$HERE/.env.example" ]; then cp "$HERE/.env.example" "$ENV_FILE"; else : > "$ENV_FILE"; fi )
  say "Made .env (mode 600)."
fi
chmod 600 "$ENV_FILE"

for k in POSTGRES_PASSWORD MEM0_ADMIN_API_KEY MEM0_JWT_SECRET GRAPHITI_API_KEY; do
  [ -n "$(env_get "$k")" ] || env_set "$k" "$(secret)"
done

LLM="$(env_get MEMORY_MODEL)"; LLM="${LLM:-gpt-4o-mini}"
EMB="$(env_get EMBEDDING_MODEL)"; EMB="${EMB:-text-embedding-3-small}"
for m in "$LLM" "$EMB"; do
  printf '%s' "$m" | grep -Eq '^[A-Za-z0-9._:/-]+$' || die "'$m' (MEMORY_MODEL or EMBEDDING_MODEL in .env) isn't a model name."
done
RELAY="http://$HR:$HR_PORT/api/harness/v1/llm/v1"

if [ -n "$(env_get OPENAI_API_KEY)" ]; then
  step "Model credentials"
  say "The engines use the key in .env (OPENAI_API_KEY), not HarnessRouter's. Empty it to use HarnessRouter's keys."
  case "$(env_get MEMORY_BASE_URL)" in */api/harness/v1/llm/*|"") env_set MEMORY_BASE_URL https://api.openai.com/v1 ;; esac
else
  step "Model credentials (the engines use HarnessRouter's own model keys, through $HR)"
  json="{\"llm\":\"$LLM\",\"embedding\":\"$EMB\",\"engines\":{"
  sep=""
  for e in $ENGINES; do
    json="$json$sep\"$e\":\"$(env_get "$(model_key_of "$e")")\""
    sep=","
  done
  json="$json}}"
  refused=""
  while read -r word eng value; do
    case "$word" in
      kept)    say "  $(label_of "$eng"): kept the one in .env" ;;
      new)     env_set "$(model_key_of "$eng")" "$value"; say "  $(label_of "$eng"): new credential, in .env" ;;
      renewed) env_set "$(model_key_of "$eng")" "$value"; say "  $(label_of "$eng"): replaced the one in .env, which HarnessRouter no longer takes for these models" ;;
      refused) refused="$value" ;;
      error)   die "$value" ;;
    esac
  done < <(printf '%s' "$json" | hr_py credentials)
  if [ -n "$refused" ]; then
    die "HarnessRouter can't give the engines a model yet: $refused.
The engines read with $LLM and search with $EMB. Connect a model provider that serves both in the console
(OpenAI, Azure OpenAI, Vercel AI Gateway and OpenRouter do), or set MEMORY_MODEL and EMBEDDING_MODEL in
$ENV_FILE to models your keys serve. Then run this again."
  fi
  for e in $ENGINES; do
    case "$(env_get "$(model_key_of "$e")")" in
      hrm_*) ;;
      *) die "HarnessRouter gave no model credential for $(label_of "$e"). What it said is above." ;;
    esac
  done
  env_set MEMORY_BASE_URL "$RELAY"
fi
unset json value

# ── start them ────────────────────────────────────────────────────────────────────────────────
step "Starting $(for e in $ENGINES; do printf '%s ' "$(label_of "$e")"; done)"
docker network inspect "$NAME" >/dev/null 2>&1 || docker network create "$NAME" >/dev/null
LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT
set +e
# shellcheck disable=SC2086
compose $PROFILES up -d 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
set -e
if [ "$rc" != 0 ]; then
  if grep -qiE 'port is already allocated|address already in use' "$LOG"; then
    port="$(grep -oiE 'bind for [^ ]+|listen tcp[46]? [^ ]+' "$LOG" | head -n 1 | sed -E 's/^([Bb]ind for|listen tcp[46]?) //; s/:$//')"
    die "${port:-a port} is already taken on this machine.
Nothing in this stack publishes a port of its own, so an override file or a change to docker-compose.yml asks
for it. Free that port, or change the left-hand number of that ports line, then run this again."
  fi
  if grep -qiE 'is already in use by container' "$LOG"; then
    die "a container with one of these names already exists outside this stack (above). Remove or rename it, or set HR_MEMORIES_NAME to run this stack under another name."
  fi
  die "the engines didn't start. What Docker said is above."
fi

nets="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$HR")"
case " $nets " in
  *" $NAME "*) ;;
  *) docker network connect "$NAME" "$HR" ;;
esac

step "Waiting for each engine to answer HarnessRouter (a first start can take minutes)"
json="{\"wait\":$WAIT,\"engines\":{"
sep=""
for e in $ENGINES; do json="$json$sep\"$e\":\"$(addr_of "$e")\""; sep=","; done
json="$json}}"
UP=""
DOWN_LIST=""
while read -r word eng secs; do
  case "$word" in
    up)   UP="$UP $eng"; say "  $(label_of "$eng") answers at $(addr_of "$eng") (${secs}s)" ;;
    down) DOWN_LIST="$DOWN_LIST $eng"; say "  $(label_of "$eng") didn't answer in ${WAIT}s. Its log: docker compose -p $NAME logs $eng" ;;
  esac
done < <(printf '%s' "$json" | hr_py wait)

# ── connect them ──────────────────────────────────────────────────────────────────────────────
CONNECTED=""
if [ -n "$UP" ]; then
  step "Connecting them to HarnessRouter"
  json="{\"engines\":{"
  sep=""
  for e in $UP; do
    k="$(secret_of "$e")"
    v=""
    [ -z "$k" ] || v="$(env_get "$k")"
    json="$json$sep\"$e\":{\"base_url\":\"$(addr_of "$e")\",\"api_key\":\"$v\"}"
    sep=","
  done
  json="$json}}"
  while read -r word eng reason; do
    case "$word" in
      connected) CONNECTED="$CONNECTED $eng"; say "  $(label_of "$eng"): connected" ;;
      refused)   say "  $(label_of "$eng"): HarnessRouter didn't connect it: $reason" ;;
      error)     say "  $reason" ;;
    esac
  done < <(printf '%s' "$json" | hr_py connect)
  unset json v
fi

# ── what now ──────────────────────────────────────────────────────────────────────────────────
step "Done"
if [ -n "$CONNECTED" ]; then
  say "Running and connected:$(for e in $CONNECTED; do printf ' %s' "$(label_of "$e")"; done)."
  say "Every agent you create from now on remembers, with the engine that suits it."
fi
if [ -n "$DOWN_LIST" ] || [ "$(printf '%s' "$CONNECTED" | wc -w)" != "$(printf '%s' "$ENGINES" | wc -w)" ]; then
  say "Not ready yet: $(for e in $ENGINES; do case " $CONNECTED " in *" $e "*) ;; *) printf '%s ' "$(label_of "$e")" ;; esac; done)(see above). Run $ME again once it's fixed."
fi
say ""
say "The engines' secrets and their model credentials are in $ENV_FILE (mode 600). A credential reaches"
say "only HarnessRouter's model relay, for the engine's own two models."
say ""
say "When you recreate the HarnessRouter container, keep it on this network: add this to your docker run"
say ""
say "    --network $NAME"
say ""
say "To check it at any time, run $ME again: it changes nothing that works and says what answers."
say "Each engine's log: docker compose -p $NAME logs <engine>. To stop them all: $ME --down"
if [ -n "$DOWN_LIST" ] || [ "$(printf '%s' "$CONNECTED" | wc -w)" != "$(printf '%s' "$ENGINES" | wc -w)" ]; then
  exit 1
fi
