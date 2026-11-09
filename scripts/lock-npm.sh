#!/usr/bin/env bash
# lock-npm.sh <name> [--before <date>]: regenerate docker/locks/npm/<name>/package-lock.json from the
# package.json beside it (#623, step 2, the npm half). docker/entrypoint.sh installs each npm base with
# `npm ci --ignore-scripts` from that pair, so the lock is the whole tree: every package by version,
# by the URL it is fetched from and by the sha512 npm checks it against.
#
# Run it with the npm the image runs (`docker run --rm --entrypoint npm <image> -v`; 10.x today), for
# example inside the image with the checkout mounted. --before passes npm's own release cutoff, so a
# lock can be regenerated as of the day its pin was measured.
#
# npm 10 reads a `libc` field in a lockfile entry and skips a package built for another C library,
# but it does not write that field. Without it, `npm ci` on the image's glibc installs every musl
# build beside the glibc one (217 MB more for Claude Code alone), which `npm install -g` never did.
# So this script copies `libc` from each platform package's own manifest in the registry into the lock.
set -euo pipefail

name="${1:?usage: lock-npm.sh <name> [--before <date>]}"; shift
before=()
while [ $# -gt 0 ]; do
  case "$1" in
    --before) before=(--before "$2"); shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

export npm_config_update_notifier=false
root="$(cd "$(dirname "$0")/.." && pwd)"
dir="$root/docker/locks/npm/$name"
[ -f "$dir/package.json" ] || { echo "no $dir/package.json" >&2; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cp "$dir/package.json" "$tmp/"
( cd "$tmp" && npm install --package-lock-only --ignore-scripts --no-audit --no-fund ${before[@]+"${before[@]}"} >/dev/null )

# name@version of every platform package (one that declares os or cpu), for the libc lookup.
node -e '
const l = require(process.argv[1]).packages;
for (const [k, v] of Object.entries(l)) {
  if (k && (v.os || v.cpu)) console.log(k + "\t" + (v.name || k.replace(/.*node_modules\//, "")) + "@" + v.version);
}' "$tmp/package-lock.json" > "$tmp/platform.tsv"

: > "$tmp/libc.tsv"
while IFS=$'\t' read -r key spec; do
  # A failed lookup stops the script: a missing libc is a lock that installs every musl build.
  out="$(npm view "$spec" libc --json)" || { echo "npm view $spec failed" >&2; exit 1; }
  libc="$(printf '%s' "$out" | tr -d ' \n')"
  [ -n "$libc" ] && printf '%s\t%s\n' "$key" "$libc" >> "$tmp/libc.tsv"
done < "$tmp/platform.tsv"

node -e '
const fs = require("fs");
const [lockPath, libcPath] = process.argv.slice(1);
const lock = JSON.parse(fs.readFileSync(lockPath, "utf8"));
for (const line of fs.readFileSync(libcPath, "utf8").split("\n").filter(Boolean)) {
  const [key, json] = line.split("\t");
  let v = JSON.parse(json);
  if (typeof v === "string") v = [v];
  lock.packages[key].libc = v;
}
// Every package is fetched from a URL and checked against a digest: nothing in the tree is a
// link, a git checkout or a path, which `npm ci` would install without one.
const bad = Object.entries(lock.packages).filter(([k, v]) => k && !(v.resolved && v.integrity));
if (bad.length) { console.error("entries without resolved+integrity: " + bad.map(([k]) => k).join(" ")); process.exit(1); }
fs.writeFileSync(lockPath, JSON.stringify(lock, null, 2) + "\n");' "$tmp/package-lock.json" "$tmp/libc.tsv"

cp "$tmp/package-lock.json" "$dir/package-lock.json"
echo "$name: $(grep -c '"integrity"' "$dir/package-lock.json") packages, $(wc -l < "$tmp/libc.tsv") with libc"
