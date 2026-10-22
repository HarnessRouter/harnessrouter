"""A package spec is read by one rule on both sides. The gateway checks a declared package before the
runner ever sees it (GET /v1/environments/packages/check, and an environment's create and update); a
copy of the runner's pattern that drifted refused, at the gateway, the apt spec with an epoch the
runner accepts ("ffmpeg=7:4.4.2-0ubuntu0.22.04.1"), so the console was told no for a package it can
build.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

RUNNER = pathlib.Path(__file__).resolve().parents[2] / "runner" / "environments.py"


def test_the_gateway_reads_a_spec_by_the_runners_own_pattern():
    src = RUNNER.read_text()
    runner_pattern = re.search(r'^_SPEC_RE = re\.compile\(r"(.*)"\)', src, re.M).group(1)
    assert gw._ENV_SPEC_RE.pattern == runner_pattern


def test_an_apt_version_with_its_epoch_is_a_spec_at_the_gateway():
    for spec in ("ffmpeg=7:4.4.2-0ubuntu0.22.04.1", "libssl3=3.0.2-0ubuntu1.18", "numpy==2.3.1", "left-pad@1.3.0", "jq"):
        assert gw._ENV_SPEC_RE.match(spec), spec
    for bad in ("rm -rf /", "a;b", "x=12345:1.0", "x=1:2:3"):
        assert not gw._ENV_SPEC_RE.match(bad), bad
