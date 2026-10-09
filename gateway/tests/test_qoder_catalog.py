"""The qoder base: a remote runtime, and what the catalog says about it is what the runner does.

Qoder Cloud Agent runs the agent loop in Qoder's cloud; the runner's turn process is an HTTP client
to it (runner/qoder_driver.py). What these pin:

  the tool list is Qoder's own names and EQUALS the runner's whitelist, so a toggle the console
      shows always withholds a tool the Agent was actually offered; enforcement is `hard`
  the base takes skills (published to Qoder) and NOT environments (mounted on this box only)
  one provider drives it, `qoder`, its own; no aggregator, no custom endpoint, no harnessrouter row
  the model ids are Qoder's, in its vendor table and in no other base's picker
  the connection is not brokered: owner trust runs it, broker trust refuses it with the reason
  a turn's `charge` (a remote runtime's bill in its own unit) rides the result into the response's
      metadata and the turn record, beside — never inside — the token usage
  a session delete hands the runner the qoder connection so the remote objects go too
"""
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
import server as rs  # noqa: E402

BASE = gw._BASE_CATALOG["qoder"]


def test_the_tool_list_is_the_runners_whitelist_and_the_enforcement_is_hard():
    assert BASE["backend"] == "qoder" and BASE["status"] == "ready"
    assert tuple(sorted(n for n, _ in BASE["tools"])) == tuple(sorted(rs.QODER_TOOLS))
    assert BASE["tool_enforcement"] == "hard"
    assert "DeliverArtifacts" in BASE["system_prompt"]


def test_the_base_takes_skills_and_not_environments():
    assert gw._base_takes_skills("qoder") is True
    assert BASE["environments"] is False and BASE["remote"] is True
    assert gw._backend_takes_environments("qoder") is False
    for b in ("claude", "codex", "systemone", "goose"):
        assert gw._backend_takes_environments(b) is True
    assert gw._backend_takes_environments("") is True


def test_one_provider_its_own_and_nothing_else_drives_it():
    wired = {p for (p, b) in gw._INTEGRATION_WIRING if b == "qoder"}
    assert wired == {"qoder"} and gw._INTEGRATION_WIRING[("qoder", "qoder")] == "qoder"
    assert {b for (p, b) in gw._INTEGRATION_WIRING if p == "qoder"} == {"qoder"}
    assert not any("qoder" in s for s in gw._CUSTOM_FORMAT_BACKENDS.values())
    prov = gw._PROVIDER_CATALOG["qoder"]
    assert prov["base_url"] == "https://api.qoder.com/api/v1/cloud" and prov["fields"] == [] and prov["secret"] == "api_key"
    assert gw._PROVIDER_BASE["qoder"] == prov["base_url"] == rs.QODER_DEFAULT_BASE
    assert gw._provider_base_url("qoder", prov["base_url"]) == prov["base_url"]     # no /v1 of its own


def test_the_model_ids_are_qoders_and_in_no_other_picker():
    cat = gw._MODEL_CATALOG["qoder"]
    assert cat["default"] in cat["models"] and set(cat["models"]) <= set(gw._VENDOR_MODELS["qoder"])
    for backend, entry in gw._MODEL_CATALOG.items():
        if backend != "qoder":
            assert not set(entry["models"]) & set(gw._VENDOR_MODELS["qoder"]), backend
    for vendor, table in gw._VENDOR_MODELS.items():
        if vendor != "qoder":
            assert not set(table) & set(gw._VENDOR_MODELS["qoder"]), vendor
    assert gw._route_backend(None, "qoder") == "qoder"
    assert gw._backend_of_harness({"base": "qoder"}) == "qoder"


def test_the_connection_is_owner_trust_only(monkeypatch):
    conn = {"name": "integration:q", "backend": "qoder", "provider": "qoder", "api_key": "pat", "base_url": gw._PROVIDER_BASE["qoder"]}
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    auth = gw._auth_from_conn(conn, "sess")
    assert auth["api_key"] == "pat" and auth["base_url"] == gw._PROVIDER_BASE["qoder"]
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "broker")
    assert "qoder" in gw._NATIVE_ONLY_BACKENDS and "qoder" not in gw._BROKERABLE_PROVIDERS
    assert gw._auth_from_conn(conn, "sess") is None


def test_the_charge_rides_the_result_into_the_response_and_the_record():
    charge = {"amount": 2.0, "unit": "qoder_credits", "basis": "snapshot"}
    kinds = gw._blocks_from_canonical({"type": "result", "subtype": "success", "result": "done",
                                       "usage": {}, "charge": charge, "_ts": 1.0})
    res = [p for k, p in kinds if k == "result"][0]
    assert res["charge"] == charge and res["usage"] == {}
    tr = gw._RespTranslator("resp_x", "ultimate", None, True, 1.0, sid="sess_x")
    tr._handle("result", res)
    assert tr.charge == charge and tr.usage is None            # never folded into the tokens
    obj = tr._response_obj("completed")
    assert obj["metadata"]["charge"] == charge and obj["usage"] is None
    # a backend with tokens and no charge is as before
    tr2 = gw._RespTranslator("resp_y", "m", None, True, 1.0, sid="sess_y")
    tr2._handle("result", {"text": "x", "usage": {"input_tokens": 3, "output_tokens": 4}, "is_error": False, "model": ""})
    assert tr2.charge is None and "charge" not in tr2._response_obj("completed")["metadata"]


def test_a_session_delete_carries_the_qoder_connection_to_the_runner(monkeypatch):
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")

    async def integs():
        return [{"name": "qoder-main", "provider": "qoder", "config": {"api_key": "pat", "base_url": ""}},
                {"name": "openai", "provider": "openai", "config": {"api_key": "sk"}}]

    monkeypatch.setattr(gw, "_integrations_doc", integs)
    body = asyncio.run(gw._remote_delete_body("sess_1", {"backend": "qoder"}))
    assert body["backend"] == "qoder" and body["auth"]["api_key"] == "pat"
    assert body["auth"]["base_url"] == gw._PROVIDER_BASE["qoder"]
    assert asyncio.run(gw._remote_delete_body("sess_1", {"backend": "claude"})) is None
    assert asyncio.run(gw._remote_delete_body("sess_1", None)) is None
    # broker trust: the connection is not brokered, so nothing goes, and the runner will say what was left
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "broker")
    assert asyncio.run(gw._remote_delete_body("sess_1", {"backend": "qoder"})) == {"backend": "qoder", "auth": None}

    async def none():
        return []

    monkeypatch.setattr(gw, "_integrations_doc", none)
    assert asyncio.run(gw._remote_delete_body("sess_1", {"backend": "qoder"})) == {"backend": "qoder"}


def test_a_session_delete_uses_the_qoder_account_its_turns_ran_on(monkeypatch):
    """With two Qoder connections, the session's objects live in the account its turns used
    (last_connection); the other account's key would be refused there and leave them billing."""
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")

    async def integs():
        return [{"name": "qoder-a", "provider": "qoder", "config": {"api_key": "pat-a"}},
                {"name": "qoder-b", "provider": "qoder", "config": {"api_key": "pat-b"}}]

    monkeypatch.setattr(gw, "_integrations_doc", integs)
    v = {"backend": "qoder", "last_connection": "integration:qoder-b"}
    assert asyncio.run(gw._remote_delete_body("sess_1", v))["auth"]["api_key"] == "pat-b"
    # the session's own connection is gone and two others remain: nothing is guessed
    v = {"backend": "qoder", "last_connection": "integration:qoder-old"}
    assert asyncio.run(gw._remote_delete_body("sess_1", v)) == {"backend": "qoder"}
    # no record of which ran, two candidates: nothing is guessed either
    assert asyncio.run(gw._remote_delete_body("sess_1", {"backend": "qoder"})) == {"backend": "qoder"}
