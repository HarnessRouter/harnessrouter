"""Which relay route is the turn's, and the two bases that did not ride one on Azure.

The relay is where a turn's served model is read (hermes and Codex report none of their own), so a
turn whose CLI called the provider directly finished unlabelled: hermes and Codex on Azure, where the
matrix could not tell which model answered gpt-5.5 (four of four hermes switches on 0.33.0-rc.15).
And a hermes turn whose image questions ride the relay registers that route FIRST, so the lookup
that takes the first placeholder in the environment read the image model's route instead.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


def _drop(env):
    for v in env.values():
        if isinstance(v, str) and v.startswith("hr-relay-"):
            rs._HERMES_RELAY["routes"].pop(v, None)


def test_the_image_route_is_not_the_turns_even_when_it_comes_first(tmp_path):
    env = {"HOME": str(tmp_path)}
    rs._hermes_prepare_env("openrouter", rs.Auth(api_key="k-chat", base_url="https://openrouter.ai/api/v1"),
                           str(tmp_path), env, model="openai/gpt-5.5",
                           vision_auth={"provider": "openai-api", "model": "gpt-5.4-mini",
                                        "base_url": "https://vision.example/v1", "api_key": "k-vision"})
    try:
        tokens = [v for v in env.values() if isinstance(v, str) and v.startswith("hr-relay-")]
        assert tokens[0] == env["HR_VISION_API_KEY"], "the case this guards: the image route is first"
        vision = rs._HERMES_RELAY["routes"][env["HR_VISION_API_KEY"]][2]
        chat = rs._HERMES_RELAY["routes"][env["OPENROUTER_API_KEY"]][2]
        # before either answered
        assert rs._relay_served_model(env) == "" and rs._relay_usage(env) == {}
        vision.update(served_model="gpt-5.4-mini-2026-03-17", usage={"input_tokens": 900, "output_tokens": 40},
                      last_finish="stop")
        assert rs._relay_served_model(env) == "", "the image model is not what served the turn"
        assert rs._relay_usage(env) == {} and rs._relay_last_finish(env) == ""
        chat.update(served_model="openai/gpt-5.5", usage={"input_tokens": 12, "output_tokens": 3},
                    last_finish="content-filter")
        assert rs._relay_served_model(env) == "openai/gpt-5.5"
        assert rs._relay_usage(env) == {"input_tokens": 12, "output_tokens": 3}
        assert rs._relay_last_finish(env) == "content_filter"
    finally:
        _drop(env)


def test_hermes_on_azure_rides_the_relay_at_the_connections_own_base(tmp_path):
    base = "https://res.openai.azure.com/openai/v1"
    env = {"HOME": str(tmp_path)}
    rs._hermes_prepare_env("azure-foundry", rs.Auth(api_key="sk-azure", base_url=base),
                           str(tmp_path), env, model="gpt-5.5")
    try:
        tok = env["AZURE_FOUNDRY_API_KEY"]
        assert tok.startswith("hr-relay-")
        assert env["AZURE_FOUNDRY_BASE_URL"].startswith("http://127.0.0.1:")
        assert "sk-azure" not in json.dumps(env)
        assert "sk-azure" not in (tmp_path / ".hermes" / "config.yaml").read_text()
        upstream, key, flags = rs._HERMES_RELAY["routes"][tok]
        assert (upstream, key) == (base, "sk-azure") and not flags.get("aux")
        flags["served_model"] = "gpt-5.5-2026-04-23"
        assert rs._relay_served_model(env) == "gpt-5.5-2026-04-23"
    finally:
        _drop(env)


def test_the_codex_app_server_result_carries_the_served_model_and_the_relays_usage():
    """The exec path stamped both; the app-server path stamped neither."""
    import inspect
    src = inspect.getsource(rs._run_codex_appserver_bg)
    tail = src[src.index('ev = {"type": "result"'):]
    assert tail.index("_relay_served_model(env)") < tail.index("append(ev)")
    assert tail.index("_fill_relay_usage(ev, env)") < tail.index("append(ev)")
