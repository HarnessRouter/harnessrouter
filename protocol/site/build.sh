#!/usr/bin/env bash
# The one place the site's build steps live. Vercel (protocol/vercel.json) and CI
# (.github/workflows/tests.yml) both invoke this script rather than repeating the commands, so the
# deployed build and the gated build can never diverge. It resolves paths against its own location,
# so it runs identically from any working directory.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install --quiet --requirement requirements.txt
python3 build.py
