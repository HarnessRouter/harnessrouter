#!/usr/bin/env python3
"""The browser column of the support matrix: every base (but System One) drives the browser
plugin on a real task, through the API, the way a customer's product would.

For each base: the browser plugin is on for the key's workspace, a harness that includes it is
created, one task in plain words asks for a page to be opened and a link followed, the task's
trace is read for the plugin's rows (navigate, click, ... each with unit and usd) and the
session's stop row, and the harness is deleted. A base passes when the task completed, the trace
shows the browser navigating and clicking, the answer names the page it reached, and the browser
session was stopped and billed. A failed base is retested once, as every matrix column is.

The prompt names no tool: the agent's own instructions file carries a Browser section when the
harness includes the plugin (the gateway writes it), and that is what a person's prompt relies on.

    python3 plugs/browser.py --base-url https://20-98-237-6.sslip.io/api/harness --api-key "$KEY" \\
        [--bases all|pi,codex,...] [--model ID] [--workers 2] [--keep] [--out result.json] [--md table.md]

`--bases` defaults to every ready base the instance lists except systemone (a System One model
chooses among offered actions and has no tools to call). `--model` runs every base on one model
instead of each base's default. The instance needs BROWSER_USE_API_KEY in its environment;
without it every base reports the refusal it got.
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

# In plain words, as a person would put it. Not "do not visit any other site": the link leads to
# another site, and two bases obeyed the ban instead of the click (rc.14 baseline).
PROMPT = ("Open https://example.com/ in the browser, click the only link on that page, and reply with "
          "the URL and the title of the page you land on.")
NEEDED = ["navigate", "click"]      # the rows the trace must show, each with outcome ok
REACHED = "iana.org"                # where the link goes: the answer must name it
EXCLUDED = {"systemone"}


def _client(base_url: str, api_key: str, workspace: str):
    base = base_url.rstrip("/")
    # Named, not Python's default: the hosted console's edge answers that with 403 (error 1010).
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "x-harness-workspace": workspace,
         "User-Agent": "harnessrouter-browser-column/1"}

    def call(method: str, path: str, body=None, timeout=120):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={**H, **({"Idempotency-Key": secrets.token_hex(8)} if path.endswith("/responses") else {})}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                try:
                    return r.status, json.loads(raw)
                except ValueError:
                    return r.status, raw.decode()      # the trace stream: one JSON object per line
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode()[:300]
    return call


def run_base(call, base: str, model: str, keep: bool, log) -> dict:
    """One base, one task: the record the table is rendered from."""
    t0 = time.time()
    out: dict = {"base": base, "model": model or "", "ok": False, "tools": [], "missing": list(NEEDED), "status": "", "answer": "", "why": ""}
    body = {"name": f"Browser matrix {base} {int(time.time())}", "base": base}
    if model:
        body["default_model"] = model
    code, h = call("POST", "/v1/harnesses", body)
    if code != 200:
        out["why"] = f"harness: HTTP {code} {json.dumps(h)[:160]}"
        return out
    hid = h["id"]
    try:
        code, inc = call("POST", f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["browser"]})
        if code != 200 or (inc.get("status") or {}).get("browser") != "connected":
            out["why"] = f"include: HTTP {code} {json.dumps(inc)[:160]}"
            return out
        code, resp = call("POST", "/v1/responses", {"input": PROMPT, "stream": False, "background": True,
                                                    "model": model or None, "metadata": {"harness_id": hid}}, timeout=180)
        if code != 200:
            out["why"] = f"turn: HTTP {code} {json.dumps(resp)[:160]}"
            return out
        rid, sid = resp.get("id"), (resp.get("metadata") or {}).get("session_id") or ""
        out["session"] = sid
        status, d = "", {}
        while time.time() - t0 < 900:
            code, d = call("GET", f"/v1/responses/{rid}", timeout=60)
            status = (d.get("status") or "") if isinstance(d, dict) else ""
            if status in ("completed", "failed", "incomplete", "cancelled"):
                break
            time.sleep(6)
        out["status"] = status
        out["model"] = model or (str(d.get("model") or "") if isinstance(d, dict) else "")   # the turn's own model: the base's default
        text = "".join(p.get("text") or "" for it in (d.get("output") or []) for p in (it.get("content") or [])
                       if p.get("type") in ("output_text", "text")) if isinstance(d, dict) else ""
        out["answer"] = text[-400:]
        # The stop row is in the trace once the browser has been stopped, which the gateway does
        # before it finalizes the trace; read until it is there, up to a bound.
        rows = []
        for _ in range(18):
            code, trace = call("GET", f"/v1/traces/{sid}/all?compact=0", timeout=120)
            rows = []
            for line in (trace if isinstance(trace, str) else "").splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "plug" and ev.get("plug") == "browser":
                    rows.append({k: ev.get(k) for k in ("tool", "outcome", "ms", "unit", "usd", "error")})
            if any(r["tool"] == "session" for r in rows):
                break
            time.sleep(5)
        ok_tools = [r["tool"] for r in rows if r.get("outcome") == "ok"]
        stop = next((r for r in rows if r["tool"] == "session"), None)
        out["tools"] = sorted(set(t for t in ok_tools if t != "session"))
        out["missing"] = [t for t in NEEDED if t not in ok_tools]
        out["stopped"] = bool(stop and stop.get("unit") == "browser.usd")
        out["usd"] = float(stop.get("usd") or 0) if stop else 0.0
        reached = REACHED in text.lower()
        out["ok"] = status == "completed" and not out["missing"] and reached and out["stopped"]
        if not out["ok"]:
            why = []
            if status != "completed":
                why.append(f"status {status or 'unknown'}" + (f": {str((d.get('error') or {}).get('message') or '')[:120]}" if isinstance(d, dict) and d.get("error") else ""))
            if out["missing"]:
                why.append("no browser " + "/".join(out["missing"]) + " in the trace" + (" (used " + ", ".join(out["tools"]) + ")" if out["tools"] else " (no browser tool at all)"))
            if not reached:
                why.append(f"answered without {REACHED}: {text[-160:].strip()!r}")
            if not out["stopped"]:
                why.append("no stop row")
            out["why"] = "; ".join(why)
    finally:
        if not keep:
            call("DELETE", f"/v1/harnesses/{hid}")
    out["s"] = int(time.time() - t0)
    log(f"{'PASS' if out['ok'] else 'FAIL'} {base} {out['model']} {out['s']}s tools={','.join(out['tools']) or '-'} {out['why']}")
    return out


def render(rows: list[dict]) -> str:
    """The column as a markdown table, one row per base."""
    lines = ["| base | model | browser | tools seen | seconds | notes |", "|---|---|---|---|---:|---|"]
    for r in rows:
        mark = "pass" if r.get("ok") else "FAIL"
        note = r.get("why", "")
        if r.get("retested"):
            note = ("retested once; first try: " + r["retested"].get("why", "")[:120] + (" ; " + note if note else ""))
        lines.append(f"| {r['base']} | {r.get('model', '')} | {mark} | {', '.join(r.get('tools') or []) or '-'} | {r.get('s', '')} | {note.replace('|', '/')} |")
    ok = sum(1 for r in rows if r.get("ok"))
    lines.append(f"\n{ok} of {len(rows)} bases drive the browser.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--bases", default="all")
    ap.add_argument("--model", default="")
    ap.add_argument("--workspace", default="default")
    ap.add_argument("--workers", type=int, default=2)   # the plane allows a few browsers per account at once
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--md", default="")
    a = ap.parse_args()
    call = _client(a.base_url, a.api_key, a.workspace)
    lock = threading.Lock()

    def log(s: str):
        with lock:
            print(time.strftime("%H:%M:%S"), s, flush=True)

    code, d = call("PUT", "/v1/plugs/browser", {"enabled": True, "config": {"allow_domains": [], "deny_domains": []}})
    if code in (404, 405):
        print("the instance manages plugins in its console; the include's status is the gate")   # hosted
    elif code != 200 or d.get("status") != "connected":
        print("FAIL the browser plugin did not connect:", code, json.dumps(d)[:200]); return 2
    if a.bases == "all":
        code, bases = call("GET", "/v1/bases")
        if code != 200:
            print("FAIL bases:", code, bases); return 2
        items = bases.get("bases") if isinstance(bases, dict) else bases
        items = items if isinstance(items, list) else list(items.values())
        names = [str(b.get("id") or b.get("base")) for b in items if str(b.get("status") or "ready") == "ready"]
        names = [n for n in names if n not in EXCLUDED]
    else:
        names = [x.strip() for x in a.bases.split(",") if x.strip()]
    log(f"bases: {', '.join(names)}")

    def one(base: str) -> dict:
        r = run_base(call, base, a.model, a.keep, log)
        if not r["ok"]:
            first = r
            r = run_base(call, base, a.model, a.keep, log)
            r["retested"] = {"why": first.get("why", ""), "tools": first.get("tools", [])}
        return r

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        rows = list(ex.map(one, names))
    table = render(rows)
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
