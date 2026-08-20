#!/usr/bin/env sh
# Build HarnessRouter from source and run it — the contributor path, not the pull path.
#
# WHY THIS EXISTS, beyond "developers like building things":
#
#   The published image is linux/amd64 only. On an Apple Silicon Mac, `docker pull` gets you an
#   emulated image: a platform-mismatch warning, and a first boot that is already slow (it installs
#   three agent CLIs) made several times slower. Building here produces a NATIVE image for whatever
#   machine you are on, so on an M-series Mac this is the fast path today, not the slow one.
#
# It is deliberately one file with no dependencies beyond docker and git, because a build script
# that needs its own build step is not a starting point.
#
# Usage:
#   ./scripts/build-local.sh                 build and run
#   ./scripts/build-local.sh --build-only    build, do not start anything
#   ./scripts/build-local.sh --name my-hr --port 8080
#
set -eu

IMAGE_TAG="harnessrouter:local"
NAME="hr-local"
PORT="3000"
VOLUME=""
BUILD_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --build-only) BUILD_ONLY=1 ;;
    --name)  NAME="${2:?--name needs a value}"; shift ;;
    --port)  PORT="${2:?--port needs a value}"; shift ;;
    --tag)   IMAGE_TAG="${2:?--tag needs a value}"; shift ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done
[ -n "$VOLUME" ] || VOLUME="${NAME}-data"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# ── preflight ────────────────────────────────────────────────────────────────
# Every check here exists because its absence produces a confusing failure several minutes in,
# rather than a clear one now.
say "Checking what this machine can do"

command -v docker >/dev/null 2>&1 || die \
"docker is not installed.
   macOS: Docker Desktop, OrbStack, or  brew install colima docker && colima start
   Linux: your distribution's docker.io / docker-ce package"

docker info >/dev/null 2>&1 || die \
"docker is installed but the daemon is not running. Start Docker Desktop (or: colima start)."

command -v git >/dev/null 2>&1 || die "git is not installed."

ARCH="$(uname -m)"
case "$ARCH" in
  arm64|aarch64) info "architecture: $ARCH — this build will be native (the published image is not)" ;;
  x86_64|amd64)  info "architecture: $ARCH — same as the published image" ;;
  *)             info "architecture: $ARCH — untested; the build may not work" ;;
esac

# Disk. The finished image is ~2.7GB; BuildKit's intermediate layers and cache run well past that,
# and a build that dies at 90% full leaves a wedged daemon rather than an error you can read.
FREE_GB=""
if df -g . >/dev/null 2>&1; then FREE_GB="$(df -g . | awk 'NR==2 {print $4}')"   # macOS
elif df -BG . >/dev/null 2>&1; then FREE_GB="$(df -BG . | awk 'NR==2 {gsub(/G/,"",$4); print $4}')"  # GNU
fi
if [ -n "$FREE_GB" ]; then
  info "free disk: ${FREE_GB}G"
  [ "$FREE_GB" -lt 15 ] 2>/dev/null && printf '  \033[33m%s\033[0m\n' \
    "warning: under 15G free. A clean build wants roughly that much. 'docker system prune -a' frees the most."
else
  info "free disk: could not determine — make sure you have ~15G"
fi

cd "$(dirname "$0")/.."
[ -f Dockerfile ] || die "Run this from a checkout of the repository (Dockerfile not found)."

# ── what we are about to build ───────────────────────────────────────────────
# The skills and the starter kits are pulled from their own repositories during the build, and the
# layer is keyed on these values. Left at "main" they are NOT re-fetched when those repositories
# move, so a rebuild silently keeps whatever catalogue it fetched the first time. Resolving them to
# a commit here means the layer rebuilds exactly when the content changes, and the build log records
# what actually went in.
say "Resolving what will be baked in"
resolve() {
  sha="$(git ls-remote "https://github.com/HarnessRouter/$1.git" refs/heads/main 2>/dev/null | cut -f1)"
  if [ -z "$sha" ]; then
    printf '  \033[33m%s\033[0m\n' "could not reach HarnessRouter/$1 — falling back to 'main' (this layer may be cached)" >&2
    echo main
  else
    printf '  %-12s %s\n' "$1" "$sha" >&2
    echo "$sha"
  fi
}
SKILLS_REF="$(resolve skills)"
KITS_REF="$(resolve starter-kit)"

# ── build ────────────────────────────────────────────────────────────────────
say "Building $IMAGE_TAG (first build takes a while — it compiles the console and installs Python deps)"
docker build \
  --build-arg "HR_SKILLS_REF=$SKILLS_REF" \
  --build-arg "HR_KITS_REF=$KITS_REF" \
  -t "$IMAGE_TAG" .

BUILT_ARCH="$(docker image inspect "$IMAGE_TAG" --format '{{.Os}}/{{.Architecture}}' 2>/dev/null || echo '?')"
SIZE="$(docker image inspect "$IMAGE_TAG" --format '{{.Size}}' 2>/dev/null || echo 0)"
say "Built"
info "image: $IMAGE_TAG"
info "platform: $BUILT_ARCH"
[ "$SIZE" -gt 0 ] 2>/dev/null && info "size: $(( SIZE / 1024 / 1024 ))MB"

[ "$BUILD_ONLY" -eq 1 ] && { info "--build-only: not starting anything."; exit 0; }

# ── run ──────────────────────────────────────────────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  die "A container named '$NAME' already exists.
   Remove it:  docker rm -f $NAME
   Or use:     $0 --name something-else"
fi

# A password you did not choose is a password you did not reuse. Printed once, here, and stored
# nowhere else — the container keeps only what you pass it.
PASSWORD="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24)"

say "Starting"
docker run -d --name "$NAME" \
  -p "127.0.0.1:${PORT}:3000" \
  -v "${VOLUME}:/data" \
  -e HR_AUTH_USER=admin \
  -e HR_AUTH_PASSWORD="$PASSWORD" \
  "$IMAGE_TAG" >/dev/null

info "container: $NAME"
info "volume:    $VOLUME  (state lives here; delete it to start over)"
info "bound to 127.0.0.1 only — nothing is exposed to your network"

# The first boot installs the agent CLIs, which is why it is slow. Saying so beats a silent wait
# that reads as a hang.
say "Waiting for first boot (it installs the agent CLIs now — this is the slow part)"
i=0
while [ "$i" -lt 180 ]; do
  if docker logs "$NAME" 2>&1 | grep -q "backends available"; then break; fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" != "true" ]; then
    printf '\n'; docker logs --tail 30 "$NAME" 2>&1
    die "The container stopped. Its last output is above."
  fi
  printf '.'; sleep 5; i=$((i + 1))
done
printf '\n'

LINE="$(docker logs "$NAME" 2>&1 | grep 'backends available' | tail -1)"
if [ -n "$LINE" ]; then info "$LINE"; else
  printf '  \033[33m%s\033[0m\n' "still starting after 15 minutes. Watch it with: docker logs -f $NAME"
fi

say "Ready"
info "open      http://localhost:${PORT}"
info "username  admin"
info "password  $PASSWORD"
printf '\n'
info "It cannot run a task until you connect a model provider — do that under Integrations."
info "logs:   docker logs -f $NAME"
info "stop:   docker rm -f $NAME"
info "reset:  docker rm -f $NAME && docker volume rm $VOLUME"
