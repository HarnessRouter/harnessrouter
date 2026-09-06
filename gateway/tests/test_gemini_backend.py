"""The gemini backend (Gemini CLI, Google's native API) on the gateway side: wired into the ONE google
provider, refused in broker mode with the reason, the served model kept on the record."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_the_gemini_backend_is_wired_into_the_one_google_provider():
    assert gw._INTEGRATION_WIRING[("google", "gemini")] == "google"
    assert gw._PROVIDER_CATALOG["google"]["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert set(gw._MODEL_CATALOG["gemini"]["models"]) <= set(gw._VENDOR_MODELS["google"])
    assert gw._MODEL_CATALOG["gemini"]["default"] in gw._MODEL_CATALOG["gemini"]["models"]
    assert gw._BASE_CATALOG["gemini"]["backend"] == "gemini"


def test_a_native_api_backend_is_refused_in_broker_mode_and_served_raw_in_owner_trust(monkeypatch):
    conn = {"name": "integration:Google AI Studio", "backend": "gemini", "provider": "google", "api_key": "AIza-t"}
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "broker")
    monkeypatch.setattr(gw, "PUBLIC_BASE_URL", "https://hr.example")
    assert gw._auth_from_conn(conn, "sid1") is None
    # the same connection brokers fine for an OpenAI-shape backend
    assert gw._auth_from_conn({**conn, "backend": "pi", "provider": "openai-api"}, "sid1") is not None
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    out = gw._auth_from_conn(conn, "sid1")
    assert out and out.get("api_key") == "AIza-t"


def test_the_served_model_rides_the_result_onto_the_record():
    ev = {"type": "result", "result": "PONG", "usage": {"input_tokens": 1, "output_tokens": 1}, "model": "gemini-3.5-flash"}
    assert ("result", {"text": "PONG", "usage": ev["usage"], "is_error": False, "model": "gemini-3.5-flash"}) in gw._blocks_from_canonical(ev)
    plain = {"type": "result", "result": "ok", "usage": None}
    assert ("result", {"text": "ok", "usage": None, "is_error": False, "model": ""}) in gw._blocks_from_canonical(plain)
    tr = gw._RespTranslator("resp_1", "gemini-3.6-flash", None, True, 0.0)
    tr._handle("result", {"text": "PONG", "usage": {"input_tokens": 1, "output_tokens": 1}, "is_error": False, "model": "gemini-3.5-flash"})
    assert tr.served_model == "gemini-3.5-flash"
    assert tr.record()["served_model"] == "gemini-3.5-flash" if hasattr(tr, "record") else True
