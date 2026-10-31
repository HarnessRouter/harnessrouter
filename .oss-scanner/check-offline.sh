#!/usr/bin/env bash
# Run in the audit image with --network none and no mounted host directories.
# The same suites .github/workflows/tests.yml runs, so a green run here means the scanner can test
# a patch the way a contributor does. Every suite runs even after one fails, so one run names them all.
set -uo pipefail
# The suites assume an unprivileged user, as in CI, so root runs them as `audit`.
if [ "$(id -u)" = 0 ]; then
  exec runuser -u audit -- env HOME=/home/audit bash "$0" "$@"
fi
cd /src
failed=()
for f in SECURITY.md CONTRIBUTING.md .oss-scanner/threat_model.md docs; do
  [ -e "$f" ] || failed+=("missing from the image: $f")
done
suite() {
  echo "== $1"
  shift
  "$@" || failed+=("$*")
}
suite gateway python -m pytest gateway/tests -q
suite benchmark python -m pytest scripts/benchmark -q
suite runner python -m pytest runner/tests -q
suite conformance python -m pytest protocol/conformance/tests -q
suite console bash -c 'cd ui && npm test -- --passWithNoTests'
if [ ${#failed[@]} -gt 0 ]; then
  printf 'FAILED: %s\n' "${failed[@]}" >&2
  exit 1
fi
echo "every suite passed offline"
