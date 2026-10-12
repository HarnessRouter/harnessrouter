"""gajae is implemented and deliberately NOT offered — this pins that state at every surface.

Gajae-Code works: it was measured end to end through the product on 2026-10-03, and the runner
still carries `_build_gajae`, `_gajae_to_claude`, their tests and their captured fixtures. What
stops it is this product's own write-wall, not a defect in either side:

  gjc's native lock helper walks from / down to the path it is locking and opens EVERY ancestor
  with O_RDONLY|O_DIRECTORY|O_NOFOLLOW, which needs READ on each ancestor rather than traverse.
  docker/entrypoint.sh sets /data and /data/workspaces to 751 — "traversable by sessions, neither
  listable nor writable" — so a session uid gets EACCES, the addon reports io_error, and the turn
  dies before its first model call. Both sides defend the same thing from opposite ends: gjc
  refuses to trust path resolution for a lock; the product makes the ancestors unreadable.

  Measured BOTH WAYS on a live instance: at 751 a real turn failed with that error; at 755 the same
  turn completed in 4.6 s answering correctly; back at 751 it failed again.

A half-restore is the risk this file exists for — a base that is listed but not routable, or
routable but not installed, fails on a user's first turn with nothing to read. So the rule is all
or nothing: either every surface offers it or none does, and today it is none.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_gateway_neither_lists_nor_routes_it():
    assert "gajae" not in A._BASE_CATALOG
    assert "gajae" not in A._MODEL_CATALOG
    # _SUPPORTED_BASES and the per-harness URL matcher are DERIVED from _BASE_CATALOG, so this
    # follows — asserted anyway, because routing a base nothing can serve is the worst shape.
    assert "gajae" not in A._SUPPORTED_BASES
    assert not A._HID_PREFIX_RE.match("/gajae/v1/responses")
    assert not any(b == "gajae" for _p, b in A._INTEGRATION_WIRING)
    assert not any("gajae" in bs for bs in A._CUSTOM_FORMAT_BACKENDS.values())


def test_the_console_does_not_offer_it():
    ts = (ROOT / "ui" / "src" / "lib" / "harness.ts").read_text()
    assert "id: 'gajae'" not in ts
    assert "'gajae'" not in ts          # also out of the backend union and the label map
    logo = (ROOT / "ui" / "src" / "components" / "HarnessLogo.tsx").read_text()
    assert "gajae" not in logo
    # and the mark it would have used is gone rather than left to rot in the tree
    assert not (ROOT / "ui" / "public" / "logos" / "gajae.png").exists()


def test_nothing_installs_it_by_default():
    sh = (ROOT / "docker" / "entrypoint.sh").read_text()
    default = re.search(r'HR_BACKENDS="\$\{HR_BACKENDS:-([^}]+)\}"', sh).group(1)
    assert "gajae" not in default.split(",")


def test_no_measurement_dimension_claims_to_cover_it():
    # A base in a dimension's list that the server cannot serve produces a column of failures that
    # say nothing about the base.
    mjs = (ROOT / "scripts" / "support-matrix" / "custom-harness.mjs").read_text()
    assert "gajae" not in mjs
    plugins = (ROOT / "scripts" / "support-matrix" / "plugins" / "run-matrix.py").read_text()
    assert "gajae" not in plugins


def test_the_runner_implementation_is_still_there_and_still_works():
    # Kept on purpose: the base works, and the thing that blocks it is a decision about file modes.
    # If someone deletes this code, this test is where they are asked to mean it.
    from server import ALL_GAJAE_TOOLS, _build_gajae, _gajae_to_claude   # noqa: F401
    assert len(ALL_GAJAE_TOOLS) > 30
    assert (ROOT / "runner" / "tests" / "fixtures" / "batch3" / "gajae-write-file.ndjson").is_file()


def test_the_reason_is_written_down_where_someone_would_look():
    # Not folklore: the measurement lives in the code that would have to change and in the notes.
    gw = (ROOT / "gateway" / "app.py").read_text()
    assert "gajae (Gajae-Code) is implemented and NOT offered" in gw
    assert "O_RDONLY|O_DIRECTORY|O_NOFOLLOW" in gw
    notes = (ROOT / "docs" / "support-matrix-notes.md").read_text()
    assert "write-wall" in notes and "open_parent_no_follow" in notes
