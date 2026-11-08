#!/bin/sh
# Regenerate the hashed lock of a Python base from the .in beside it (#623, step 2).
#
#   scripts/lock-pypi.sh <base> [--exclude-newer <date>]    e.g. scripts/lock-pypi.sh hermes
#
# docker/locks/<base>.in names the base's direct pins; docker/locks/<base>.lock.txt is every
# distribution of its tree, by version and by the sha256 of every file PyPI (or the URL) serves for
# that version. entrypoint.sh installs it with pip --require-hashes --no-deps, so the lock is the
# whole of what a volume gets. A bump is: edit the .in, run this, read the diff, run real turns on
# the base. Without --exclude-newer the resolution is today's.
#
# Resolved for the image's two platforms (Linux, CPython 3.12, amd64 and arm64), and the two must
# agree, so one file serves both. NOT --universal: that writes markers for macOS and Windows, and a
# `platform_release >= '19.0'` marker makes the image's pip parse the host kernel's release
# ("6.8.0-1070-gcp", "6.10.14-linuxkit") as a version and crash before it installs anything.
#
# <base>.overrides, when present, names a version the base's own pins refuse and its venv needs
# anyway (aider's idna); it is passed to the resolver as an override.
set -eu
base="${1:?usage: $0 <base> [--exclude-newer <date>]}"; shift
cd "$(dirname "$0")/.."
in="docker/locks/$base.in"; out="docker/locks/$base.lock.txt"
[ -f "$in" ] || { echo "no $in" >&2; exit 1; }
py=3.12
case "$base" in
  dcode) py=3.14 ;;                                                 # dcode runs on its own pinned CPython
  agentzero) set -- "$@" -c runner/agentzero-constraints.txt ;;   # the measured 2.13 tree
esac
[ -f "docker/locks/$base.overrides" ] && set -- "$@" --override "docker/locks/$base.overrides"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
for plat in x86_64-manylinux_2_40 aarch64-manylinux_2_40; do
  # --upgrade: resolve from the .in alone. Without it uv prefers whatever the old lock held.
  uv pip compile --quiet --refresh --upgrade --python-version "$py" --python-platform "$plat" \
    --generate-hashes --no-header "$@" "$in" -o "$tmp/$plat.txt"
done
if ! cmp -s "$tmp/x86_64-manylinux_2_40.txt" "$tmp/aarch64-manylinux_2_40.txt"; then
  echo "$base resolves differently on amd64 and arm64; one lock cannot serve both:" >&2
  diff "$tmp/x86_64-manylinux_2_40.txt" "$tmp/aarch64-manylinux_2_40.txt" | grep '^[<>] [A-Za-z]' >&2 || true
  exit 1
fi
cp "$tmp/x86_64-manylinux_2_40.txt" "$out"
echo "wrote $out ($(grep -c '^[A-Za-z0-9]' "$out") distributions)"
