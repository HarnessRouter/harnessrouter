"""A self-hosted sandbox reaches the broker on loopback; a hosted one on the public base URL."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


def test_self_hosted_hands_the_sandbox_the_loopback_gateway(monkeypatch):
    monkeypatch.setenv("HARNESS_GATEWAY_URL", "http://127.0.0.1:8080/")
    monkeypatch.setattr(gw, "PUBLIC_BASE_URL", "https://console.example")
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)
    assert gw._sandbox_broker_origin() == "http://127.0.0.1:8080"


def test_hosted_hands_the_sandbox_the_public_base(monkeypatch):
    monkeypatch.setenv("HARNESS_GATEWAY_URL", "http://gateway.internal")
    monkeypatch.setattr(gw, "PUBLIC_BASE_URL", "https://app.example")
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)
    assert gw._sandbox_broker_origin() == "https://app.example"


def test_the_sandbox_auth_carries_that_origin(monkeypatch):
    monkeypatch.setenv("HARNESS_GATEWAY_URL", "http://127.0.0.1:8080")
    monkeypatch.setattr(gw, "PUBLIC_BASE_URL", "https://console.example")
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "")
    monkeypatch.setattr(gw, "_mint_turn_cred", lambda sid, name: "hrt_x")
    out = gw._auth_from_conn({"provider": "anthropic", "api_key": "sk-ant-real", "name": "Anthropic"}, "sid1")
    assert out["base_url"] == "http://127.0.0.1:8080/v1/llm" and out["api_key"] == "hrt_x" and "sk-ant-real" not in str(out)
