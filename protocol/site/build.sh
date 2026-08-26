#!/usr/bin/env bash
# The one place the site's build steps live. Vercel (protocol/vercel.json) and CI
# (.github/workflows/tests.yml) both invoke this script rather than repeating the commands, so the
# deployed build and the gated build can never diverge. It resolves paths against its own location,
# so it runs identically from any working directory.
set -euo pipefail
cd "$(dirname "$0")"
# Install into a throwaway virtualenv rather than the system Python. Vercel's build image ships a
# uv-managed, PEP 668 "externally managed" Python that refuses `pip install` into it; a venv sidesteps
# that and behaves identically on GitHub CI, so one script works in both places.
python3 -m venv .venv
.venv/bin/python -m pip install --quiet --requirement requirements.txt
.venv/bin/python build.py
