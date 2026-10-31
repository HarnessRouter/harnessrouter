#!/usr/bin/env bash
# Run in the audit image with --network none and no mounted host directories.
set -euo pipefail
cd /src
python -m pytest gateway/tests/test_pinned_address.py -q
python -m pytest runner/tests/test_workspace_delete.py -q
python -m pytest protocol/conformance/tests -q
