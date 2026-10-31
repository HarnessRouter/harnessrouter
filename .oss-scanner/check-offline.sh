#!/usr/bin/env bash
# Run in the audit image with --network none and no mounted host directories.
# The same suites .github/workflows/tests.yml runs, so a green run here means the scanner can test
# a patch the way a contributor does.
set -euo pipefail
cd /src
for f in SECURITY.md CONTRIBUTING.md .oss-scanner/threat_model.md docs; do
  [ -e "$f" ] || { echo "missing from the image: $f" >&2; exit 1; }
done
python -m pytest gateway/tests -q
python -m pytest scripts/benchmark -q
python -m pytest runner/tests -q
python -m pytest protocol/conformance/tests -q
(cd ui && npm test -- --passWithNoTests)
