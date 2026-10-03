"""Independent Pi Lab backend; only the Pi transport is shared with ordinary Pi."""
import json
import os
from pathlib import Path

from fastapi import HTTPException

REVISION = "1559b5cb12c72da4a485bc50fe326586b216fb19"
FEATURES = ("actionFusion", "observationPack", "evidencePreservingReducer", "onlineContextCompact")


def with_defaults(config=None):
    """The harness's switches over the defaults: all four on, SoL-Pi's cache ratio. The gateway
    validated them when the harness was saved; a built-in harness sends none."""
    return {**{key: True for key in FEATURES}, "cacheWriteReadRatio": 12.5, **(config or {})}


def build(build_pi, provider, auth, model, prompt, cwd, env, *, config=None,
          resume_session_id=None, mcp_servers=None, tools_disabled=None, vision=True):
    config = with_defaults(config)
    disabled = {x.split(" (")[0].strip() for x in tools_disabled or []}
    if config["actionFusion"] and disabled.intersection({"bash", "edit", "write"}):
        raise HTTPException(400, "Disable Action Fusion before disabling bash, edit, or write")
    if config["observationPack"] and "obs_recall" in disabled:
        raise HTTPException(400, "ObservationPack requires obs_recall")
    if config["onlineContextCompact"] and "update_plan" in disabled:
        raise HTTPException(400, "Online Context Compact requires update_plan")
    entry = Path(os.environ["HR_PI_LAB_SOL_PI_ENTRY"])
    agent_dir = Path(env.get("HOME") or cwd) / ".pi-lab" / "agent"
    cmd = build_pi(provider, auth, model, prompt, cwd, env,
                   resume_session_id=resume_session_id, mcp_servers=mcp_servers,
                   tools_disabled=tools_disabled, vision=vision, agent_dir=agent_dir,
                   mcp_extension=os.environ.get("HR_PI_LAB_MCP_EXT", ""), mcp_filename="mcp.json")
    # Pi Lab's own pinned pi, never the ordinary one on PATH.
    cmd[0] = os.environ["HR_PI_LAB_BIN"]
    route = cmd[cmd.index("--provider") + 1]
    reducer_model = config.pop("reducerModel", model)
    effective = {"version": 1, **config, "evidencePreservingReducerProvider": route,
                 "evidencePreservingReducerModel": reducer_model}
    if route == "hr" and config["evidencePreservingReducer"] and reducer_model != model:
        path = agent_dir / "models.json"
        models = json.loads(path.read_text(encoding="utf-8"))
        main = models["providers"]["hr"]["models"][0]
        models["providers"]["hr"]["models"].append({**main, "id": reducer_model, "name": reducer_model})
        path.write_text(json.dumps(models), encoding="utf-8")
    managed = Path(cwd) / ".harness" / "pi-lab"
    managed.mkdir(parents=True, exist_ok=True)
    # Inject configuration via the upstream registration API: a task-created project config
    # cannot override the harness switches. The wrapper is rewritten before every invocation.
    wrapper = managed / "extension.ts"
    wrapper.write_text(
        "import { registerConfiguredFeatures } from " + json.dumps(entry.resolve().as_posix()) + ";\n"
        "const config = " + json.dumps(effective) + ";\n"
        "export default function(pi) {\n"
        "  const observed = Object.create(pi);\n"
        "  observed.appendEntry = (type, data) => {\n"
        "    pi.appendEntry(type, data);\n"
        "    if (type === 'sol-pi-evidence-preserving-reducer-v1') {\n"
        "      const event = { type: 'pi_lab_event', kind: data.kind, reason: data.reason };\n"
        "      if (data.kind === 'provider_response') Object.assign(event, {usage: data.usage, model: data.model, provider: data.provider});\n"
        "      process.stdout.write(JSON.stringify(event) + '\\n');\n"
        "    }\n"
        "  };\n"
        "  let initialized = false;\n"
        "  pi.on('session_start', () => {\n"
        "    if (initialized) return; initialized = true;\n"
        "    registerConfiguredFeatures(observed, config);\n"
        "    process.stdout.write(JSON.stringify({type: 'pi_lab_ready', config, revision: " + json.dumps(REVISION) + "}) + '\\n');\n"
        "  });\n"
        "}\n",
        encoding="utf-8")
    (managed / "effective-config.json").write_text(json.dumps(effective, indent=2), encoding="utf-8")
    cmd[-1:-1] = ["--extension", str(wrapper)]
    return cmd
