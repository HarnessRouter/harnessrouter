"""Installing the suite outside a checkout must still run its schema checks (#203)."""
from __future__ import annotations

from importlib import resources
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from uhp_conformance import UHP_VERSION


PROJECT = Path(__file__).resolve().parents[1]
SCHEMA_NAME = f"uhp-{UHP_VERSION}.schema.json"


def test_bundled_schema_matches_the_specification():
    """The protocol owns the schema; the package carries an exact release snapshot of it."""
    canonical = PROJECT.parent / "schema" / SCHEMA_NAME
    bundled = resources.files("uhp_conformance").joinpath(SCHEMA_NAME)
    assert bundled.read_bytes() == canonical.read_bytes(), (
        f"refresh uhp_conformance/{SCHEMA_NAME} from protocol/schema/{SCHEMA_NAME}"
    )


def _run(*args, cwd):
    result = subprocess.run(
        [sys.executable, "-I", *args], cwd=cwd, text=True, capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def distributions(tmp_path_factory):
    root = tmp_path_factory.mktemp("conformance-dist")
    source = root / "source"
    shutil.copytree(
        PROJECT, source,
        ignore=shutil.ignore_patterns("*.egg-info", "__pycache__", "build", "dist", ".pytest_cache"),
    )
    # Only the conformance project is copied: no sibling protocol/schema directory can rescue
    # an incomplete distribution, and a stale local build/ or egg-info cannot supply its files.
    output = root / "dist"
    _run("-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(output),
         cwd=source)
    return {"wheel": next(output.glob("*.whl")), "sdist": next(output.glob("*.tar.gz"))}


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_installed_distribution_validates_instead_of_skipping(distributions, tmp_path, kind):
    target = tmp_path / "installed"
    # jsonschema and build requirements are already test dependencies. Installing the sdist
    # builds another wheel from its contents, without fetching anything or using the checkout.
    _run("-m", "pip", "install", "--no-deps", "--no-build-isolation", "--no-index",
         "--target", str(target), str(distributions[kind]), cwd=tmp_path)
    _run("-c", """
import pathlib
import sys

target = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(target))
from uhp_conformance import context
from uhp_conformance.client import Client

assert pathlib.Path(context.__file__).resolve().is_relative_to(target)
ctx = context.Context(client=Client("http://unused.invalid", ""))
ctx.validate({"id": "file_1", "filename": "report.csv"}, "File")
try:
    ctx.validate({"id": "file_1", "filename": 42}, "File")
except AssertionError as error:
    assert "does not match schema File" in str(error)
else:
    raise AssertionError("the installed schema accepted an invalid filename")
""", str(target), cwd=tmp_path)
