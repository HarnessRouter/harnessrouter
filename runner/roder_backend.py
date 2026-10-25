"""Roder's native app-server backend. Provider traffic stays on the runner relay."""
import json
import pathlib
import sys

PROVIDERS = {"openai", "azure", "tokenrouter"}
DEFAULT_MODEL = "gpt-5.4"


def build(provider, auth, model, prompt, cwd, env, *, relay, resume_session_id=None,
          mcp_servers=None, tools_disabled=None, thinking=None):
    from fastapi import HTTPException
    if provider not in PROVIDERS:
        raise HTTPException(400, f"unknown roder provider '{provider}'")
    if auth.api_format and auth.api_format != "responses":
        raise HTTPException(400, "roder requires a Responses-format endpoint")
    base = auth.base_url or {"openai": "https://api.openai.com/v1"}.get(provider)
    if not base or not auth.api_key:
        raise HTTPException(400, "roder needs a base_url and API key")
    base, token = relay(base, auth.api_key)
    root = pathlib.Path(cwd) / ".harness" / "roder"
    root.mkdir(parents=True, exist_ok=True)
    env.update(RODER_CONFIG_DIR=str(root), RODER_DATA_DIR=str(root), HR_RODER_KEY=token)
    # Roder custom providers speak Responses. The id is ours, never the built-in Codex provider
    # (which would use OAuth); the wire model id is preserved exactly, including vendor slashes.
    config = (f'provider = "hr"\nmodel = {json.dumps(model)}\nruntime_profile = "non_interactive"\n'
              '[providers.hr]\napi_key_env = "HR_RODER_KEY"\n'
              f'base_url = {json.dumps(base)}\n'
              '[policy_modes]\ndefault = "bypass"\nwarn_on_bypass = false\n')
    (root / "config.toml").write_text(config)
    env["HR_RODER_JOB"] = json.dumps({"model": model, "prompt": prompt,
        "resume": resume_session_id, "tools_disabled": tools_disabled or [],
        "mcp_servers": mcp_servers or [], "reasoning": (thinking or {}).get("asked")})
    return [sys.executable, str(pathlib.Path(__file__).with_name("roder_driver.py"))]


def normalize(obj, state):
    """The driver already emits the same canonical events as Codex's app-server path."""
    if obj.get("type") == "result" and not obj.get("is_error"):
        state["final"] = obj.get("result") or ""
    if obj.get("type") == "assistant":
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "text":
                state["final"] = state.get("final", "") + block["text"]
    return [obj]


def eof(state, rc):
    # Unlike the generic runner's exit-zero fallback, a truncated app-server stream never passes.
    return [{"type": "result", "subtype": "error", "is_error": True,
             "result": f"Roder exited without turn/completed (exit {rc})"}]


normalize.eof = eof
