#!/usr/bin/env python3
"""Prove the plugin path on every harness base, directly. No workflow, no fan out.

For each base it creates a harness carrying the fixture package, runs one real task, checks the
answer for the probe token, and deletes the harness. Two modes:

  skills   the package carries only its Skill; every base must load it
  mcp      the package also declares a stdio MCP server; every base must call its tool (since
           #180/#182 every base takes a stdio server; pi's adapter and dsh's client spawn it)
  sse      the package declares an SSE server (a public probe); codex, dsh and goose reach it
           through the runner's bridge (#185), every other base natively
  http     the package declares a streamable-HTTP server (the same probe's /mcp end)

An Agent Plugins 1.0.0 package is the unit in every column: the harness is created with ONE
plugin and nothing on its direct mcpServers/skills lists, so what is proved is the plugin path.

    python3 plugins/run-matrix.py --base-url https://20-98-237-6.sslip.io/api/harness --api-key "$KEY" \
        --mode all --out matrix-results.json

Add --bases codex,hermes to narrow it, --model to pin one, --keep to leave the harnesses behind.
Runs one base at a time on purpose: hr-test is a single box and a hosted matrix is capped at 8.
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).parent
FIXTURE = HERE / "fixture"
# Every base the catalog serves. Since #180/#182 every one of them takes a stdio server (pi's
# adapter and dsh's client spawn it themselves), so no base is expected to refuse any column.
BASES = ["claude-code", "codex", "hermes", "goose", "gemini", "qwen", "opencode", "cline", "omp", "pi", "dsh", "kimi", "aider"]
NO_STDIO: set[str] = set()
# The public probe the remote columns call: its SSE end answers PROBE-SSE-<id>, its streamable-HTTP
# end PROBE-HTTP-<id>. Both are the same fixed server, so a wrong answer is the base, not the probe.
PROBE_URL = "https://mcp-probe.calmrock-23b12d3f.eastus2.azurecontainerapps.io"
PROBE_ID = "ef8e44614954"
SKILL_PROMPT = ("Use your plugin-probe skill and follow it exactly. Reply with the single line it "
                "tells you to reply with, and nothing else.")
# A client may expose an MCP tool under the bare name or as <server>_<tool> (pi does the latter),
# so the prompt names the server too and both spellings; the answer is judged on the token alone.
MCP_PROMPT = ("Call the MCP tool plugin_probe from the server named probe (it may appear to you as "
              "plugin_probe or probe_plugin_probe) with note=matrix, then reply with the tool's output "
              "text verbatim and nothing else. Do not answer from memory or from a skill; the tool "
              "must actually be called.")
REMOTE_PROMPT = ("Call the MCP tool {tool} from the server named probe (it may appear to you as {tool} "
                 "or probe_{tool}) with no arguments, then reply with the tool's output text verbatim and "
                 "nothing else. The tool must actually be called.")
MODES = ["skills", "mcp", "sse", "http"]
# Per column: the server entry the package's mcp.json carries (None = no server), the tool the task
# calls, and the token that proves the whole chain answered.
COLUMN = {
    "skills": (None, None, "PLUGIN_SKILL_OK"),
    "mcp":    ("stdio", "plugin_probe", "PLUGIN_MCP_OK"),
    "sse":    ({"type": "sse", "url": f"{PROBE_URL}/sse"}, "probe_sse", f"PROBE-SSE-{PROBE_ID}"),
    "http":   ({"type": "streamable-http", "url": f"{PROBE_URL}/mcp"}, "probe_http", f"PROBE-HTTP-{PROBE_ID}"),
}


def package(mode: str) -> list[dict]:
    server = COLUMN[mode][0]
    files = []
    for f in sorted(FIXTURE.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(FIXTURE).as_posix()
        if rel == "mcp.json" and server is None:
            continue
        if rel.startswith("bin/") and server != "stdio":
            continue
        if rel == "mcp.json" and isinstance(server, dict):
            # the remote columns: the fixture's stdio entry is replaced by a url server, the shape
            # agent-plugins.org's mcp.schema 1.0.0 allows (type + url, optional headers)
            files.append({"path": rel, "content": json.dumps({
                "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
                "mcpServers": {"probe": server}}, indent=2)})
            continue
        raw = f.read_bytes()
        try:
            entry = {"path": rel, "content": raw.decode()}
        except UnicodeDecodeError:
            entry = {"path": rel, "content_b64": base64.b64encode(raw).decode()}
        if rel.startswith("bin/"):
            entry["executable"] = True
        files.append(entry)
    return files


class Api:
    def __init__(self, base_url: str, key: str, timeout: float):
        self.base, self.key, self.timeout = base_url.rstrip("/"), key, timeout

    def call(self, method: str, path: str, body=None, timeout=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "authorization": f"Bearer {self.key}", "accept": "application/json",
            **({"content-type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"{}")
            except Exception:
                return e.code, {"raw": raw[:400].decode(errors="replace")}


def text_of(resp: dict) -> str:
    out = []
    for item in resp.get("output") or []:
        for c in item.get("content") or []:
            if c.get("type") == "output_text":
                out.append(c.get("text") or "")
    return "\n".join(out)


def run_one(api: Api, base: str, mode: str, model: str, keep: bool, task_timeout: float) -> dict:
    row = {"base": base, "mode": mode, "harness": "", "outcome": "", "detail": ""}
    body = {"name": f"plugin-matrix-{base}-{mode}", "base": base,
            "plugins": [{"files": package(mode)}]}
    if model:
        body["default_model"] = model
    status, created = api.call("POST", "/v1/harnesses", body)
    if status != 200:
        err = (created.get("error") or {})
        if mode == "mcp" and base in NO_STDIO and err.get("code") == "unsupported_transport":
            row["outcome"] = "refused as designed"
            row["detail"] = f"422 {err.get('code')} detail={err.get('detail')}"
        else:
            row["outcome"] = "create failed"
            row["detail"] = f"HTTP {status} {err.get('code') or created}"
        return row
    if mode == "mcp" and base in NO_STDIO:
        row["outcome"] = "should have been refused"
        row["detail"] = "the package declares a stdio server and this base cannot run one"
        api.call("DELETE", f"/v1/harnesses/{created['id']}")
        return row
    row["harness"] = created["id"]
    plug = (created.get("plugins") or [{}])[0]
    row["detail"] = (f"derived skills={[s['name'] for s in plug.get('skills') or []]} "
                     f"servers={[s['name'] for s in plug.get('mcpServers') or []]} "
                     f"skipped={plug.get('skipped')}")
    try:
        _, tool, token = COLUMN[mode]
        prompt = (SKILL_PROMPT if mode == "skills" else MCP_PROMPT if mode == "mcp"
                  else REMOTE_PROMPT.format(tool=tool))
        status, resp = api.call("POST", "/v1/responses", {
            "input": prompt, "metadata": {"harness_id": created["id"]}, "stream": False,
            "max_step": 12}, timeout=task_timeout)
        answer = text_of(resp) if status == 200 else ""
        if status != 200:
            row["outcome"], row["detail"] = "task failed", f"HTTP {status} {str(resp)[:200]}"
        elif token in answer:
            row["outcome"] = "pass"
            row["detail"] = answer.strip().splitlines()[-1][:200]
        else:
            row["outcome"] = "no token"
            row["detail"] = f"status={resp.get('status')} answer={answer.strip()[:200]!r}"
    finally:
        if not keep:
            api.call("DELETE", f"/v1/harnesses/{created['id']}")
    return row


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", required=True)
    p.add_argument("--api-key", required=True)
    p.add_argument("--bases", default="all")
    p.add_argument("--mode", default="all", choices=MODES + ["all"])
    p.add_argument("--model", default="")
    p.add_argument("--task-timeout", type=float, default=420.0)
    p.add_argument("--keep", action="store_true")
    p.add_argument("--out", default="")
    a = p.parse_args()

    api = Api(a.base_url, a.api_key, 60.0)
    status, disc = api.call("GET", "/v1/uhp")
    if status != 200 or not (disc.get("capabilities") or {}).get("plugins"):
        print(f"this server does not report the plugins capability (HTTP {status}): {disc}", file=sys.stderr)
        return 2
    print(f"server serves {disc.get('default_version')} · plugins {disc['capabilities']['plugins']} · "
          f"schemas {disc.get('plugin_schemas')}\n")

    bases = BASES if a.bases == "all" else [b.strip() for b in a.bases.split(",") if b.strip()]
    modes = MODES if a.mode == "all" else [a.mode]
    rows = []
    for mode in modes:
        for base in bases:
            t0 = time.time()
            row = run_one(api, base, mode, a.model, a.keep, a.task_timeout)
            row["seconds"] = round(time.time() - t0, 1)
            rows.append(row)
            print(f"{mode:<7} {base:<12} {row['outcome']:<24} {row['seconds']:>6}s  {row['detail'][:120]}")
    print("\nsummary")
    for mode in modes:
        good = [r for r in rows if r["mode"] == mode and r["outcome"] in ("pass", "refused as designed")]
        print(f"  {mode}: {len(good)}/{len([r for r in rows if r['mode'] == mode])} as expected")
    bad = [f"{r['mode']}/{r['base']}: {r['outcome']}" for r in rows
           if r["outcome"] not in ("pass", "refused as designed")]
    if bad:
        print("  not as expected: " + "; ".join(bad))
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps({"target": a.base_url, "rows": rows}, indent=2))
        print(f"\nwrote {a.out}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
