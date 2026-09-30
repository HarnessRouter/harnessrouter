#!/usr/bin/env bash
# Pi Lab runtime: pinned pi plus SoL-Pi at a fixed commit. Registry tarballs are held by the
# lockfile's integrity; SoL-Pi comes from git, which npm does not hash, so its sources are
# checked against source.sha256.
set -euo pipefail
target="${1:?usage: install.sh RUNTIME_DIRECTORY}"
manifest_dir="$(cd "$(dirname "$0")" && pwd)"
digest="$(cat "$manifest_dir/package-lock.json" "$manifest_dir/source.sha256" | sha256sum | cut -d ' ' -f1)"
if [ "$(cat "$target/lock.sha256" 2>/dev/null)" = "$digest" ]; then
  echo 'Pi Lab already installed'
  exit 0
fi
mkdir -p "$(dirname "$target")"
stage="$(mktemp -d "${target}.stage.XXXXXX")"
trap 'rm -rf -- "$stage"' EXIT
cp "$manifest_dir/package.json" "$manifest_dir/package-lock.json" "$stage/"
npm ci --prefix "$stage" --ignore-scripts --no-audit --no-fund
(cd "$stage/node_modules/sol-pi"; sha256sum --check --strict "$manifest_dir/source.sha256")
mkdir -p "$stage/bin" "$stage/lib"
ln -s ../node_modules/.bin/pi "$stage/bin/pi"
ln -s ../node_modules "$stage/lib/node_modules"
printf '%s' "$digest" > "$stage/lock.sha256"
# mktemp makes the stage 0700; session uids must read and run the runtime, not write it.
chmod -R a+rX "$stage"
rm -rf -- "$target"
mv -- "$stage" "$target"
echo "Pi Lab installed: lockfile SHA256 $digest"
