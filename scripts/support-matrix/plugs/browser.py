#!/usr/bin/env python3
"""Prove the browser plugin on a HarnessRouter instance, end to end, directly. No workflow.

Turns the browser plugin on for the key's workspace, creates a harness that includes it, runs one
real task that must navigate, snapshot, click, extract text and take a screenshot, reads the
task's trace for the plug rows (each with unit and usd) and the session's stop row, then deletes
the harness. The instance needs BROWSER_USE_API_KEY in its environment; without it the probe
reports the refusal it got and fails.

    python3 plugs/browser.py --base-url https://20-98-237-6.sslip.io/api/harness --api-key "$KEY" \\
        [--base pi] [--model claude-sonnet-5] [--workspace default] [--keep] [--out result.json]
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request

PROMPT = ("Use your browser tools for this, in order: 1) browser.navigate to https://example.com/ ; "
          "2) browser.snapshot ; 3) browser.click the 'More information...' link by its ref ; 4) browser.extract_text ; "
          "5) browser.screenshot . Then answer with: the final URL, the page title, and the first 200 characters of "
          "the extracted text. Do nothing else and do not visit any other site.")
NEEDED = ["navigate", "snapshot", "click", "extract_text", "screenshot"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--base", default="pi")
    ap.add_argument("--model", default="")
    ap.add_argument("--workspace", default="default")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    H = {"Authorization": f"Bearer {a.api_key}", "Content-Type": "application/json", "x-harness-workspace": a.workspace}

    def call(method: str, path: str, body=None, timeout=120):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={**H, **({"Idempotency-Key": secrets.token_hex(8)} if path.endswith("/responses") else {})}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw.strip().startswith(b"{") or raw.strip().startswith(b"[") else raw.decode())
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode()[:300]

    result: dict = {"ok": False}
    code, d = call("PUT", "/v1/plugs/browser", {"enabled": True, "config": {"allow_domains": [], "deny_domains": []}})
    print("plugin on:", code, json.dumps(d)[:200])
    if code != 200 or d.get("status") != "connected":
        print("FAIL the browser plugin did not connect"); return 2
    body = {"name": f"Browser probe {int(time.time())}", "base": a.base}
    if a.model:
        body["default_model"] = a.model
    code, h = call("POST", "/v1/harnesses", body)
    if code != 200:
        print("FAIL harness:", code, h); return 2
    hid = h["id"]
    try:
        code, inc = call("POST", f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["browser"]})
        print("include:", code, json.dumps(inc)[:200])
        if code != 200 or inc.get("status", {}).get("browser") != "connected":
            print("FAIL the harness did not include a connected browser plugin"); return 2
        code, resp = call("POST", "/v1/responses", {"input": PROMPT, "stream": False, "background": True, "model": a.model or None,
                                                                           "metadata": {"harness_id": hid}}, timeout=180)
        if code != 200:
            print("FAIL turn:", code, resp); return 2
        rid, sid = resp.get("id"), (resp.get("metadata") or {}).get("session_id") or ""
        print("turn:", resp.get("status"), "sid", sid)
        t0 = time.time(); status = ""; d = {}
        while time.time() - t0 < 900:
            code, d = call("GET", f"/v1/responses/{rid}", timeout=60)
            status = d.get("status") or "" if isinstance(d, dict) else ""
            if status in ("completed", "failed", "incomplete", "cancelled"):
                break
            time.sleep(8)
        text = "".join(p.get("text") or "" for it in (d.get("output") or []) for p in (it.get("content") or []) if p.get("type") in ("output_text", "text"))
        print("settled:", status, "after", int(time.time() - t0), "s")
        print("--- agent report ---"); print(text[:800]); print("--- end ---")
        time.sleep(8)
        code, trace = call("GET", f"/v1/traces/{sid}/all?compact=0", timeout=120)
        rows = []
        for line in (trace if isinstance(trace, str) else "").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "plug" and ev.get("plug") == "browser":
                rows.append({k: ev.get(k) for k in ("tool", "risk", "outcome", "ms", "unit", "usd", "error", "detail")})
        print(f"plug rows: {len(rows)}")
        for r in rows:
            print(f"  {str(r['tool']):14} {str(r['outcome']):8} {str(r['ms']):>6} ms  {str(r['unit']):12} {str(r['usd']):>9}  {json.dumps(r['detail']) if r.get('detail') else (r.get('error') or '')}"[:200])
        ok_tools = {r["tool"] for r in rows if r["outcome"] == "ok"}
        stop = next((r for r in rows if r["tool"] == "session"), None)
        missing = [t for t in NEEDED if t not in ok_tools]
        result = {"harness": hid, "session": sid, "status": status, "rows": rows, "stop": stop, "report": text,
                  "ok": status == "completed" and not missing and stop is not None and stop["unit"] == "browser.usd"}
        print("stop row:", json.dumps(stop) if stop else "NONE")
        print("RESULT", "PASS" if result["ok"] else f"FAIL missing={missing} stop={'yes' if stop else 'no'} status={status}")
    finally:
        if not a.keep:
            call("DELETE", f"/v1/harnesses/{hid}")
    if a.out:
        with open(a.out, "w") as f:
            json.dump(result, f, indent=1)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
