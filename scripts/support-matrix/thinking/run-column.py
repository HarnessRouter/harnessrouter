#!/usr/bin/env python3
"""The thinking column: does a level a turn asks for change how much the model thinks, on every base.

For each base it creates a harness on one model that has levels, runs the same task at each level
(and once with no level), and reads the turn's own record: what was applied, and the provider's count
of thinking tokens. The judge is the provider's figure, never what the agent says about itself:

  unset    no level asked: the record carries no `reasoning`, as before levels existed
  applied  each level asked is recorded with the level the model was given
  off      `none` spends no thinking tokens, where the model has `none`
  order    the low level spends fewer thinking tokens than the high one
  effect   where output tokens stand in for a missing count, low spends at least half again what
           none does: without it, a level that is recorded and never reaches the model passes by noise

Where a provider reports no thinking count for the model (Anthropic through some doors), output tokens
stand in, since thinking is billed as output, and the row says so.

    python3 thinking/run-column.py --base-url https://your-instance/api/harness --api-key "$KEY" \
        --bases codex,hermes --out thinking.json

--model pins one model for every base; without it each base gets the first model of PREFERRED it
lists as available with levels. --repeat N runs every level N times and compares the sums.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# A question worth thinking about, with a one-line answer, and no reason to reach for a tool.
PROMPT = ("Answer from your own reasoning; do not run any tool or command. A regular clock's hour and "
          "minute hands overlap 11 times in every 12 hours. At what time, to the nearest second, does the "
          "7th overlap after 12:00:00 happen? Then, how many integers between 1 and 5000 inclusive are "
          "divisible by none of 6, 10 and 15? Reply with exactly two lines: the time as HH:MM:SS, then the count.")
PREFERRED = ["gpt-5.4", "claude-haiku-4.5", "gemini-3.5-flash", "grok-4.6", "kimi-k3", "deepseek-v4-flash",
             "minimax-m3", "qwen3.7-max"]


class Api:
    def __init__(self, base_url: str, key: str):
        self.base, self.key = base_url.rstrip("/"), key

    def call(self, method: str, path: str, body=None, timeout: float = 60.0):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "authorization": f"Bearer {self.key}", "accept": "application/json",
            **({"content-type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"{}")
            except ValueError:
                return e.code, {"raw": raw[:300].decode(errors="replace")}
        except Exception as e:  # noqa: BLE001
            return 0, {"raw": repr(e)[:200]}


def one_turn(api: Api, harness: str, level: str, timeout: float) -> dict:
    body = {"input": PROMPT, "metadata": {"harness_id": harness}, "stream": False, "max_step": 6}
    if level:
        body["reasoning"] = {"effort": level}
    t0 = time.time()
    status, resp = api.call("POST", "/v1/responses", body, timeout=timeout)
    usage = resp.get("usage") or {}
    return {"level": level or "unset", "http": status, "status": resp.get("status"),
            "reasoning": resp.get("reasoning"), "connection": resp.get("connection"),
            "thinking_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
            "output_tokens": usage.get("output_tokens"), "seconds": round(time.time() - t0, 1),
            "error": ((resp.get("error") or {}).get("message") or resp.get("raw") or "")[:200] if status != 200 or resp.get("status") != "completed" else ""}


def judge(levels: list[str], turns: list[dict]) -> tuple[str, list[str]]:
    """→ (verdict, findings). A finding names the claim that did not hold, with its numbers."""
    by: dict[str, list[dict]] = {}
    for t in turns:
        by.setdefault(t["level"], []).append(t)
    findings = []
    bad = [f"{t['level']}: {t['status'] or t['http']} {t['error']}" for t in turns if t["status"] != "completed"]
    if bad:
        return "not run", bad
    if any(t["reasoning"] is not None for t in by.get("unset", [])):
        findings.append(f"unset: the record carries a level {by['unset'][0]['reasoning']}")
    for lv in levels:
        for t in by.get(lv, []):
            r = t["reasoning"] or {}
            if r.get("effort") != lv or r.get("applied") in (None, "", "default"):
                findings.append(f"{lv}: recorded {t['reasoning']}")
    # A provider may leave the count out of an answer that spent none, so a missing count on the
    # `none` turn is a zero; on a turn that was asked to think it means the provider gives no count.
    counted = all(t["thinking_tokens"] is not None for lv in levels if lv != "none" for t in by.get(lv, []))
    key = "thinking_tokens" if counted else "output_tokens"

    def total(lv):
        return sum(int(t[key] or 0) for t in by.get(lv, []))
    if "none" in levels and counted and total("none") != 0:
        findings.append(f"none: {total('none')} thinking tokens")
    # With no thinking count, output tokens stand in, and "low is below high" alone passes by noise
    # when a level was recorded and never reached the model (a broker that removed the thinking
    # controls: none 2,184, low 2,309, high 2,417 output tokens over three runs, 2026-10-06). A level
    # that reached the model spends well over what none does: the low level must be at least half
    # again the none level.
    if "none" in levels and "low" in levels and not counted and total("low") < 1.5 * total("none"):
        findings.append(f"effect: low {total('low')} is not half again none {total('none')} ({key}); "
                        f"the level may be recorded and not reaching the model")
    low, high = ("low" if "low" in levels else ""), ("high" if "high" in levels else "")
    if low and high and not total(low) < total(high):
        findings.append(f"order: {low} {total(low)} is not below {high} {total(high)} ({key})")
    if not low and "none" in levels and high and not total("none") < total(high):
        findings.append(f"order: none {total('none')} is not below {high} {total(high)} ({key})")
    return ("pass" if not findings else "fail"), ([] if not findings else findings) + ([] if counted else ["judged on output tokens: no thinking count from the provider"])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", required=True)
    p.add_argument("--api-key", required=True)
    p.add_argument("--bases", default="all")
    p.add_argument("--model", default="")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--task-timeout", type=float, default=420.0)
    p.add_argument("--keep", action="store_true")
    p.add_argument("--out", default="")
    a = p.parse_args()

    api = Api(a.base_url, a.api_key)
    status, doc = api.call("GET", "/v1/bases")
    if status != 200:
        print(f"GET /v1/bases answered {status}: {doc}", file=sys.stderr)
        return 2
    bases = {b["id"]: b for b in doc.get("bases") or []}
    if not any("reasoning" in m for b in bases.values() for m in b.get("models") or []):
        print("this server lists no thinking levels on /v1/bases", file=sys.stderr)
        return 2
    wanted = list(bases) if a.bases == "all" else [b.strip() for b in a.bases.split(",") if b.strip()]
    rows = []
    for base in wanted:
        info = bases.get(base)
        row = {"base": base, "model": "", "levels": [], "turns": [], "verdict": "", "findings": []}
        rows.append(row)
        if not info:
            row["verdict"], row["findings"] = "not run", ["no such base on this server"]
            continue
        have = {m["id"]: m.get("reasoning") or [] for m in info.get("models") or [] if m.get("available")}
        model = a.model if a.model else next((m for m in PREFERRED if have.get(m)), "") or \
            next((m for m, lv in have.items() if lv), "")
        if not model or not have.get(model):
            row["verdict"], row["findings"] = "no levels", [f"no available model with levels ({a.model or 'none listed'})"]
            print(f"{base:13s} no levels     {row['findings'][0]}", flush=True)
            continue
        row["model"] = model
        offered = have[model]
        levels = [lv for lv in ("none", "low", "high") if lv in offered]
        row["levels"] = levels
        status, created = api.call("POST", "/v1/harnesses", {"name": f"thinking-column-{base}", "base": base,
                                                             "default_model": model})
        if status != 200:
            row["verdict"], row["findings"] = "not run", [f"create harness: HTTP {status} {str(created)[:160]}"]
            print(f"{base:13s} not run       {row['findings'][0]}", flush=True)
            continue
        try:
            for _ in range(max(a.repeat, 1)):
                for lv in [""] + levels:
                    row["turns"].append(one_turn(api, created["id"], lv, a.task_timeout))
        finally:
            if not a.keep:
                api.call("DELETE", f"/v1/harnesses/{created['id']}")
        row["verdict"], row["findings"] = judge(levels, row["turns"])
        cells = "  ".join(f"{t['level']}={t['thinking_tokens']}/{t['output_tokens']}"
                          f"{'>' + str((t['reasoning'] or {}).get('applied')) if t['reasoning'] else ''}" for t in row["turns"])
        print(f"{base:13s} {row['verdict']:8s} {model:20s} {cells}", flush=True)
        for f in row["findings"]:
            print(f"{'':13s}   {f}", flush=True)
    if a.out:
        json.dump({"target": a.base_url, "prompt": PROMPT, "rows": rows}, open(a.out, "w"), indent=2)
    ran = [r for r in rows if r["verdict"] in ("pass", "fail")]
    print(f"\n  thinking: {sum(r['verdict'] == 'pass' for r in ran)}/{len(ran)} bases pass; "
          f"{sum(r['verdict'] == 'no levels' for r in rows)} with no levels; "
          f"{sum(r['verdict'] == 'not run' for r in rows)} not run")
    return 0 if all(r["verdict"] in ("pass", "no levels") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
