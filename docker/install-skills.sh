#!/usr/bin/env bash
# Bake the built-in skills into the image.
#
# The catalogue lives in its own repository (HarnessRouter/skills) rather than here, because a
# skill is content that changes on its own schedule: adding one should not mean a change to the
# gateway, and the set an image ships should be inspectable without reading a Dockerfile.
#
# skills.json in that repo decides what ships (`include`) and what a new Harness starts with
# (`default_enabled`). This script honours `include` and copies `default_enabled` through to the
# manifest the gateway reads at run time. It never asks the network for anything afterwards:
# everything a skill needs is installed here, at build time, because a task has no internet.
set -euo pipefail

REPO="${HR_SKILLS_REPO:-https://github.com/HarnessRouter/skills.git}"
REF="${HR_SKILLS_REF:-main}"
DEST="${HR_SKILLS_DIR:-/opt/harnessrouter/skills}"

if [ "${WITH_BUILTIN_SKILLS:-1}" != "1" ]; then
    echo "skills: WITH_BUILTIN_SKILLS=0 — none bundled"
    mkdir -p "$DEST"
    echo '{"skills":[]}' > "$DEST/manifest.json"
    exit 0
fi

SRC="$(mktemp -d)"
trap 'rm -rf "$SRC"' EXIT

echo "skills: cloning $REPO @ $REF"
git clone -q --depth 1 --branch "$REF" "$REPO" "$SRC" 2>/dev/null \
    || { git clone -q "$REPO" "$SRC" && git -C "$SRC" checkout -q "$REF"; }
echo "skills: source commit $(git -C "$SRC" rev-parse --short HEAD)"

mkdir -p "$DEST"

# One pass over skills.json: copy every included folder, and emit the manifest the gateway serves.
# jq is not assumed to be present, so Python (which the image has, and which already parses this
# file's format) does the reading.
python3 - "$SRC" "$DEST" <<'PY'
import json, pathlib, shutil, sys

src, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
manifest = json.loads((src / "skills.json").read_text())

out = []
for entry in manifest.get("skills", []):
    name = entry.get("name") or ""
    if not name or not entry.get("include"):
        print(f"skills: skipping {name or '(unnamed)'} — include is false")
        continue
    folder = src / name
    if not (folder / "SKILL.md").is_file():
        raise SystemExit(f"skills: {name} is in skills.json but has no {name}/SKILL.md")
    shutil.copytree(folder, dest / name, dirs_exist_ok=True)
    out.append({
        "name": name,
        "title": entry.get("title") or name,
        "description": entry.get("description") or "",
        "default_enabled": bool(entry.get("default_enabled")),
        "origin": entry.get("origin") or "",
    })
    print(f"skills: bundled {name} (default_enabled={bool(entry.get('default_enabled'))})")

(dest / "manifest.json").write_text(json.dumps({"skills": out}, indent=2))
print(f"skills: {len(out)} bundled")
PY

# Dependencies, declared by the skills themselves. Union across every bundled skill so a shared
# package is installed once.
APT=$(cat "$DEST"/*/apt-packages.txt 2>/dev/null | sed 's/#.*//' | tr -d '\r' | awk 'NF' | sort -u || true)
if [ -n "$APT" ]; then
    echo "skills: apt install $(echo "$APT" | tr '\n' ' ')"
    apt-get update -y
    # shellcheck disable=SC2086
    apt-get install -y --no-install-recommends $APT
    rm -rf /var/lib/apt/lists/*
fi

PIPREQ=$(cat "$DEST"/*/requirements.txt 2>/dev/null | sed 's/#.*//' | tr -d '\r' | awk 'NF' | sort -u || true)
if [ -n "$PIPREQ" ]; then
    echo "skills: pip install $(echo "$PIPREQ" | tr '\n' ' ')"
    echo "$PIPREQ" | pip install --no-cache-dir -r /dev/stdin
fi

for s in "$DEST"/*/install.sh; do
    [ -f "$s" ] || continue
    echo "skills: running $(basename "$(dirname "$s")")/install.sh"
    bash "$s"
done

echo "skills: done — $DEST"
