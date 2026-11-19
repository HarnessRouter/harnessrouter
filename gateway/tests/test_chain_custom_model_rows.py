"""A scripted custom connection's model rows are its list, and its wire ids.

The integrations form has said so from the start (`_integration_models`: "The custom provider is
the exception: it has no vendor table, so its stored rows ARE the list"), and the console path acts
on it — `_mapped_integration_conn` pre-resolves the row's `provider_id` and sets `_model_resolved`.
A connection written into the ENVIRONMENT (HR_SECRET_GLOBAL_HARNESS_CONN_*, the scripted deploy the
self-hosting guide documents) took neither door, and both halves were measured on 2026-11-19 with a
recording proxy inside the instance, in front of the gateway:

  * a connection whose rows mapped `claude-sonnet-5` -> `anthropic/claude-sonnet-5` sent
    `claude-sonnet-5` on the wire. An endpoint whose ids are its own — a proxy with its own SKUs, a
    deployment alias — was unreachable from that path, and the only reason the turn passed at all is
    that the aggregator behind it happens to resolve a bare id;
  * the picker reported all 60 ids of the base's catalog as available on a connection that had
    declared thirteen, because "no vendor table" fell through to "unknown vendor, no restriction".

Each test here is one of those two halves, plus the sensitivity case: a custom connection with NO
rows must keep the old behaviour (nothing is restricted, nothing is pre-resolved), since that is
ignorance rather than a statement.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

ROWS = [{"canonical": "gpt-5.4-mini", "provider_id": "openai/gpt-5.4-mini"},
        {"canonical": "claude-sonnet-5", "provider_id": "anthropic/claude-sonnet-5"},
        {"canonical": "house-model"}]          # no wire id: the canonical goes verbatim
CONN = {"name": "byok", "provider": "custom", "api_format": "openai",
        "base_url": "http://endpoint.example/v1", "api_key": "k", "models": ROWS}


def test_the_rows_are_read_as_the_connections_model_table():
    rows = gw._chain_custom_models(CONN)
    assert rows == {"gpt-5.4-mini": "openai/gpt-5.4-mini",
                    "claude-sonnet-5": "anthropic/claude-sonnet-5",
                    "house-model": "house-model"}


def test_the_rows_are_still_read_after_the_provider_is_renamed_for_the_runner():
    # _chain_wired renames custom -> the runner's openai-api and keeps the vendor beside it; a conn
    # that has been through it must still answer, because the turn path resolves the id afterwards.
    wired = gw._chain_wired(CONN, "jiuwenswarm")
    assert wired["provider"] == "openai-api" and wired["_vendor"] == "custom"
    assert gw._chain_custom_models(wired)["claude-sonnet-5"] == "anthropic/claude-sonnet-5"


def test_a_model_the_endpoint_never_declared_is_not_claimed():
    assert gw._conn_serves(CONN, "gpt-5.4-mini") is True
    assert gw._conn_serves(CONN, "openai/gpt-5.4-mini") is True      # its own wire id, too
    assert gw._conn_serves(CONN, "gemini-4-argon") is False


def test_a_custom_endpoint_with_no_rows_restricts_nothing():
    # The sensitivity half: no rows is ignorance, not a statement, and the old behaviour stands.
    bare = {k: v for k, v in CONN.items() if k != "models"}
    assert gw._chain_custom_models(bare) == {}
    assert gw._conn_serves(bare, "gemini-4-argon") is True


def test_one_model_id_from_an_older_connection_still_reads_as_one_row():
    old = {k: v for k, v in CONN.items() if k != "models"} | {"model_id": "house-sku-7"}
    assert gw._chain_custom_models(old) == {"house-sku-7": "house-sku-7"}
    assert gw._conn_serves(old, "house-sku-7") is True
    assert gw._conn_serves(old, "gpt-5.4-mini") is False
