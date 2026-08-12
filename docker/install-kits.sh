#!/usr/bin/env bash
# Bake the Starter Kits into the image.
#
# A kit is a product in a folder: the Harness it needs, and a UI that talks to that Harness as its
# backend. Both come from HarnessRouter/starter-kit, pulled and BUILT here so a launch is instant
# and works on a box with no network — the same reasoning as the skills bundle, and the same
# shape, so there is one way to add content to this image rather than two.
#
# kits.json at the repo root says which folders ship. Each kit's own kit.json says everything
# else, next to the code it describes.
set -euo pipefail

REPO="${HR_KITS_REPO:-https://github.com/HarnessRouter/starter-kit.git}"
REF="${HR_KITS_REF:-main}"
DEST="${HR_KITS_DIR:-/opt/harnessrouter/kits}"

mkdir -p "$DEST"
if [ "${WITH_STARTER_KITS:-1}" != "1" ]; then
    echo "kits: WITH_STARTER_KITS=0 — none bundled"
    echo '{"kits":[]}' > "$DEST/manifest.json"
    exit 0
fi

SRC="$(mktemp -d)"
trap 'rm -rf "$SRC"' EXIT

echo "kits: cloning $REPO @ $REF"
git clone -q --depth 1 --branch "$REF" "$REPO" "$SRC" 2>/dev/null \
    || { git clone -q "$REPO" "$SRC" && git -C "$SRC" checkout -q "$REF"; }
echo "kits: source commit $(git -C "$SRC" rev-parse --short HEAD)"

if [ ! -f "$SRC/kits.json" ]; then
    echo "kits: no kits.json at the repo root — nothing to bundle"
    echo '{"kits":[]}' > "$DEST/manifest.json"
    exit 0
fi

# Copy every included kit, then build each one's app. Reading the manifest in Python keeps this
# script free of a jq dependency the image does not otherwise need.
INCLUDED=$(python3 - "$SRC" <<'PY'
import json, pathlib, sys
src = pathlib.Path(sys.argv[1])
for k in json.loads((src / "kits.json").read_text()).get("kits", []):
    if k.get("include") and (src / "kits" / str(k.get("name")) / "kit.json").is_file():
        print(k["name"])
PY
)

BUILT=""
for kid in $INCLUDED; do
    echo "kits: bundling $kid"
    rm -rf "${DEST:?}/$kid"
    cp -r "$SRC/kits/$kid" "$DEST/$kid"

    APP_DIR=$(python3 -c "import json,sys;print((json.load(open(sys.argv[1])).get('app') or {}).get('dir') or '')" "$DEST/$kid/kit.json")
    DIST=$(python3 -c "import json,sys;print((json.load(open(sys.argv[1])).get('app') or {}).get('dist') or 'dist')" "$DEST/$kid/kit.json")
    if [ -n "$APP_DIR" ] && [ -f "$DEST/$kid/$APP_DIR/package.json" ]; then
        echo "kits: building $kid app"
        ( cd "$DEST/$kid/$APP_DIR" && npm ci --no-audit --no-fund >/dev/null 2>&1 && npm run build >/dev/null )
        # Keep only what gets served. node_modules is ~200MB of build-time dependency per kit and
        # nothing reads it at run time.
        mv "$DEST/$kid/$APP_DIR/$DIST" "$DEST/$kid/.app-dist"
        rm -rf "$DEST/$kid/$APP_DIR"
        mv "$DEST/$kid/.app-dist" "$DEST/$kid/app"
    fi
    BUILT="$BUILT $kid"
done

python3 - "$DEST" $BUILT <<'PY'
import json, pathlib, sys
dest = pathlib.Path(sys.argv[1])
(dest / "manifest.json").write_text(json.dumps({"kits": sys.argv[2:]}, indent=2))
print(f"kits: {len(sys.argv) - 2} bundled")
PY
