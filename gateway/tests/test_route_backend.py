"""`backend` on POST /v1/responses takes a base's id as GET /v1/bases lists it, or its backend.

The id was returned as the backend ("claude-code"), matched no model, and every model was refused as
"no connected provider serves it there" while "claude" worked (found on the hosted service, 2026-10-05).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_a_bases_id_names_its_backend():
    assert gw._route_backend("claude-sonnet-5.5", "claude-code") == "claude"
    assert gw._route_backend(None, " Claude-Code ") == "claude"
    for base_id, base in gw._BASE_CATALOG.items():
        assert gw._route_backend(None, base_id) == base["backend"], base_id


def test_a_backend_named_directly_and_a_name_that_is_neither_are_as_before():
    assert gw._route_backend(None, "claude") == "claude" and gw._route_backend(None, "CODEX") == "codex"
    assert gw._route_backend(None, "nosuchbase") == "nosuchbase"      # refused later, with its name
    assert gw._route_backend("gpt-5.4", None) == "codex" and gw._route_backend("claude-opus-5", "") == "claude"
