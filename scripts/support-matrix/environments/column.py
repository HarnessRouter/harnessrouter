#!/usr/bin/env python3
"""The environments column of the support matrix: every base (but System One) runs three tasks on
one environment that carries a pip, an npm and an apt package, and each task must use its manager's
package from the environment without installing anything.

The environment is one the operator built beforehand (its id is an argument): its layer holds
tabulate (pip), qrcode (npm) and jq (apt). For each base a harness naming the environment is
created, three tasks run in turn (pip, npm, apt), and each is judged by the server's own record:
the turn completed, the trace holds no install command, the answer shows the package used from
the environment (the module's path under the mount or the store, jq's version), and the session
names the environment. A failed row is retested once, as every matrix column is; the harness is
deleted at the end unless --keep.

    python3 environments/column.py --base-url https://20-98-237-6.sslip.io/api/harness --api-key "$KEY" \\
        --environment henv_... [--bases all|pi,codex,...] [--workers 2] [--keep] [--out result.json] [--md table.md]
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

EXCLUDED = {"systemone"}     # a System One model chooses among offered actions and runs no shell
INSTALL = ("pip install", "pip3 install", "python -m pip", "uv pip", "npm install", "npm i ", "npx ", "pnpm", "yarn add", "apt-get install", "apt install", "conda install")
TASKS = {
    # Each judge reads the evidence, not the labels: a base that paraphrases (aider) or whose shell
    # names its tools differently (omp's jq answers as jaq) still shows the package's path under the
    # environment and the command's output.
    "pip": ("Run exactly: python3 -c 'import tabulate, sys; print(\"TABULATE_FROM\", tabulate.__file__); print(\"PY\", sys.executable)'\n"
            "Reply with the printed output only. Do not install anything.",
            lambda t, m, st: "/.venv/" in t and "tabulate" in t and (m in t or st in t)),
    "npm": ("Run exactly: node -e 'console.log(\"QRCODE_FROM\", require.resolve(\"qrcode\"))'\n"
            "Reply with the printed output only. Do not install anything.",
            lambda t, m, st: "node_modules/qrcode" in t and (m in t or st in t)),
    "apt": ("Run exactly: which jq; jq --version; printf '[3,1,2]' | jq -c 'sort'\n"
            "Reply with the combined output only. Do not install anything.",
            lambda t, m, st: "/apt/usr/bin/jq" in t and "[1,2,3]" in t),
}


def _client(base_url: str, api_key: str, workspace: str):
    base = base_url.rstrip("/")
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "x-harness-workspace": workspace,
         "User-Agent": "harnessrouter-environments-column/1"}

    def call(method: str, path: str, body=None, timeout=120):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={**H, **({"Idempotency-Key": secrets.token_hex(8)} if path.endswith("/responses") else {})}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                try:
                    return r.status, json.loads(raw)
                except ValueError:
                    return r.status, raw.decode(errors="replace")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:300]
    return call


def _trace_commands(call, sid: str) -> list[str]:
    code, trace = call("GET", f"/v1/traces/{sid}/all?compact=0", timeout=120)
    out = []
    for line in (trace if isinstance(trace, str) else "").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        for blk in ((ev.get("message") or {}).get("content") or []):
            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                inp = blk.get("input") or {}
                out.append(str(inp.get("command") or inp.get("cmd") or json.dumps(inp)))
    return out


def run_task(call, hid: str, manager: str, env: dict, model: str, log) -> dict:
    prompt, judge = TASKS[manager]
    t0 = time.time()
    out = {"manager": manager, "ok": False, "status": "", "why": "", "answer": "", "commands": 0, "installs": 0}
    body = {"input": prompt, "stream": False, "background": True, "metadata": {"harness_id": hid}}
    if model:
        body["model"] = model
    code, resp = call("POST", "/v1/responses", body, timeout=180)
    if code != 200:
        out["why"] = f"turn: HTTP {code} {json.dumps(resp)[:160]}"
        return out
    rid, sid = resp.get("id"), (resp.get("metadata") or {}).get("session_id") or ""
    out["session"] = sid
    status, d = "", {}
    while time.time() - t0 < 600:
        code, d = call("GET", f"/v1/responses/{rid}", timeout=60)
        status = (d.get("status") or "") if isinstance(d, dict) else ""
        if status in ("completed", "failed", "incomplete", "cancelled"):
            break
        time.sleep(5)
    out["status"] = status
    text = "".join(p.get("text") or "" for it in (d.get("output") or []) for p in (it.get("content") or [])
                   if p.get("type") in ("output_text", "text")) if isinstance(d, dict) else ""
    out["answer"] = text[-300:]
    cmds = _trace_commands(call, sid) if sid else []
    installs = [c for c in cmds if any(k in c for k in INSTALL)]
    out["commands"], out["installs"] = len(cmds), len(installs)
    mount, store = env["mount"], f"/data/environments/{env['id']}/versions/"
    used = judge(text, mount, store)
    named = (call("GET", f"/v1/sessions/{sid}")[1] or {}).get("environment") == env["id"] if sid else False
    out["ok"] = status == "completed" and not installs and used and named
    if not out["ok"]:
        why = []
        if status != "completed":
            why.append(f"status {status or 'unknown'}" + (f": {str((d.get('error') or {}).get('message') or '')[:100]}" if isinstance(d, dict) and d.get("error") else ""))
        if installs:
            why.append(f"{len(installs)} install command(s) in the trace")
        if not used:
            why.append(f"the answer does not show the {manager} package used from the environment: {text[-120:].strip()!r}")
        if not named:
            why.append("the session does not name the environment")
        out["why"] = "; ".join(why)
    out["s"] = int(time.time() - t0)
    return out


def run_base(call, base: str, env: dict, model: str, keep: bool, log) -> dict:
    t0 = time.time()
    row = {"base": base, "model": model or "", "tasks": {}, "ok": False, "why": ""}
    code, h = call("POST", "/v1/harnesses", {"name": f"Environments matrix {base} {int(time.time())}", "base": base, "environment": env["id"],
                                             **({"default_model": model} if model else {})})
    if code != 200:
        row["why"] = f"harness: HTTP {code} {json.dumps(h)[:160]}"
        return row
    hid = h["id"]
    try:
        for m in ("pip", "npm", "apt"):
            r = run_task(call, hid, m, env, model, log)
            if not r["ok"]:
                first = r
                r = run_task(call, hid, m, env, model, log)
                r["retested"] = first.get("why", "")
            row["tasks"][m] = r
            log(f"{'PASS' if r['ok'] else 'FAIL'} {base} {m} {r['s']}s cmds={r['commands']} installs={r['installs']} {r['why']}")
        row["model"] = model or next((str(t.get("model") or "") for t in row["tasks"].values() if t.get("model")), row["model"])
    finally:
        if not keep:
            call("DELETE", f"/v1/harnesses/{hid}")
    row["ok"] = all(t["ok"] for t in row["tasks"].values()) and len(row["tasks"]) == 3
    row["why"] = "; ".join(f"{m}: {t['why']}" for m, t in row["tasks"].items() if not t["ok"])
    row["s"] = int(time.time() - t0)
    return row


def render(rows: list[dict], env: dict) -> str:
    lines = ["| base | model | pip (tabulate) | npm (qrcode) | apt (jq) | installs | seconds | notes |", "|---|---|---|---|---|---:|---:|---|"]
    for r in rows:
        cells = []
        for m in ("pip", "npm", "apt"):
            t = r["tasks"].get(m)
            cells.append("pass" + (" (retested)" if t and t.get("retested") else "") if t and t.get("ok") else "FAIL")
        installs = sum(int(t.get("installs") or 0) for t in r["tasks"].values())
        lines.append(f"| {r['base']} | {r.get('model', '')} | {' | '.join(cells)} | {installs} | {r.get('s', '')} | {r.get('why', '').replace('|', '/')[:160]} |")
    ok = sum(1 for r in rows if r.get("ok"))
    tasks_ok = sum(1 for r in rows for t in r["tasks"].values() if t.get("ok"))
    tasks = sum(len(r["tasks"]) for r in rows)
    lines.append(f"\n{ok} of {len(rows)} bases use the environment's pip, npm and apt packages without installing; {tasks_ok} of {tasks} tasks. Environment {env['id']} at {env['mount']}.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--environment", required=True, help="An environment whose active build holds tabulate (pip), qrcode (npm) and jq (apt)")
    ap.add_argument("--bases", default="all")
    ap.add_argument("--model", default="")
    ap.add_argument("--workspace", default="default")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--md", default="")
    a = ap.parse_args()
    call = _client(a.base_url, a.api_key, a.workspace)
    lock = threading.Lock()

    def log(s: str):
        with lock:
            print(time.strftime("%H:%M:%S"), s, flush=True)

    code, env = call("GET", f"/v1/environments/{a.environment}")
    if code != 200 or env.get("status") != "ready":
        print("FAIL the environment is not ready:", code, json.dumps(env)[:200]); return 2
    have = {(p["manager"], p["name"].lower()) for p in env.get("packages", [])}
    for need in (("pip", "tabulate"), ("npm", "qrcode"), ("apt", "jq")):
        if need not in have:
            print(f"FAIL the environment's active build lacks {need[1]} ({need[0]}); declare it and build first"); return 2
    if a.bases == "all":
        code, bases = call("GET", "/v1/bases")
        items = bases.get("bases") if isinstance(bases, dict) else bases
        items = items if isinstance(items, list) else list(items.values())
        names = [str(b.get("id") or b.get("base")) for b in items if str(b.get("status") or "ready") == "ready" and str(b.get("id") or b.get("base")) not in EXCLUDED]
    else:
        names = [x.strip() for x in a.bases.split(",") if x.strip()]
    log(f"environment {env['id']} at {env['mount']} (version {env.get('version')}); bases: {', '.join(names)}")
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        rows = list(ex.map(lambda b: run_base(call, b, env, a.model, a.keep, log), names))
    table = render(rows, env)
    print(table)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(rows, f, indent=1)
    if a.md:
        with open(a.md, "w") as f:
            f.write(table + "\n")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
