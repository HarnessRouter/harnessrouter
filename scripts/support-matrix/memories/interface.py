#!/usr/bin/env python3
"""The interface column of the memories matrix: every route of the Memories chapter, called once
on each memory engine, with the answer checked against what that engine says it does.

The conformance suite proves the rules (who may read what, what a version is). This is the
coverage beside it: no route is left uncalled, and a route an engine does not serve must answer
`memory_unsupported` (and its capability document must say the same), never a 500 and never a
silent success.

    python3 memories/interface.py --base-url https://host/api/harness --api-key "$KEY" \\
        [--engines mem0] [--out interface.json] [--md interface.md] [--keep]

Each probe is (name, what it calls, what a serving engine answers). A probe returns:
    pass   the route answered as the chapter says
    n/a    the engine declares it does not serve this, and the route said so in the chapter's words
    FAIL   anything else, with what came back
Adding a route: one line in PROBES.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request


def _client(base_url: str, api_key: str, workspace: str):
    base = base_url.rstrip("/")
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "x-harness-workspace": workspace,
         "User-Agent": "harnessrouter-memories-interface/1"}

    def call(method: str, path: str, body=None, timeout=120):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=H, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                try:
                    return r.status, json.loads(raw)
                except ValueError:
                    return r.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode()[:300]
    return call


def _code(d) -> str:
    return str(((d or {}).get("error") or {}).get("code") or "") if isinstance(d, dict) else ""


class World:
    """One engine's small tree, and what the probes made in it."""

    def __init__(self, call, engine: dict):
        self.call, self.engine, self.tag, self.ids = call, engine, secrets.token_hex(3), {}

    def until(self, fn, seconds: int = 60):
        end = time.time() + seconds
        while True:
            got = fn()
            if got or time.time() > end:
                return got
            time.sleep(3)


def _ok(cond, said: str = ""):
    return ("pass", "") if cond else ("FAIL", said)


def _unsupported(code: int, d, declared_off: bool, said: str = ""):
    """A route an engine may leave out: served, or refused in the chapter's words AND declared."""
    if code == 200:
        return ("pass", "") if not declared_off else ("FAIL", "the capability document says this is not served, and the route served it")
    if code == 422 and _code(d) == "memory_unsupported":
        return ("n/a", "declared") if declared_off else ("FAIL", "refused as unsupported, and the capability document does not say so")
    return "FAIL", f"HTTP {code} {_code(d) or str(d)[:120]} {said}"


def probes(w: World):
    """Every route once, in an order where each has what it needs. Yields (name, verdict, why)."""
    c, eng, i = w.call, w.engine, w.ids
    caps = eng
    hist = (caps.get("history") or {}).get("content", "none")
    signals = (caps.get("recall") or {}).get("signals") or []

    code, d = c("GET", "/v1/memories/providers")
    yield ("GET providers",) + _ok(code == 200 and any(p.get("id") == eng["id"] for p in d.get("data") or []), f"HTTP {code}")
    code, d = c("GET", "/v1/memories/types")
    yield ("GET types",) + _ok(code == 200 and {"fact", "entity"} <= {t.get("type") for t in d.get("data") or []}, f"HTTP {code} {str(d)[:100]}")

    code, d = c("POST", "/v1/memories", {"name": f"Interface {w.tag}", "description": "the interface column's tree", "provider": eng["id"]})
    yield ("POST memories",) + _ok(code == 200 and d.get("provider") == eng["id"], f"HTTP {code} {str(d)[:160]}")
    if code != 200:
        return
    i["root"] = d["id"]
    code, d = c("POST", "/v1/memories", {"name": f"Below {w.tag}", "description": "one level down", "parent_id": i["root"]})
    yield ("POST memories (child)",) + _ok(code == 200 and d.get("parent_id") == i["root"] and d.get("provider") == eng["id"], f"HTTP {code}")
    i["kid"] = d.get("id", "")
    code, d = c("GET", "/v1/memories")
    yield ("GET memories",) + _ok(code == 200 and i["root"] in [m["id"] for m in d.get("data") or []], f"HTTP {code}")
    code, d = c("GET", f"/v1/memories?parent={i['root']}")
    yield ("GET memories?parent",) + _ok(code == 200 and [m["id"] for m in d.get("data") or []] == [i["kid"]], f"HTTP {code}")
    code, d = c("GET", f"/v1/memories/{i['kid']}")
    yield ("GET memory",) + _ok(code == 200 and d.get("ancestors") == [i["root"]] and "delete" in (d.get("privileges") or []), f"HTTP {code} {str(d)[:120]}")
    code, d = c("PUT", f"/v1/memories/{i['kid']}", {"description": "one level down, described again"})
    yield ("PUT memory",) + _ok(code == 200 and d.get("description", "").endswith("again"), f"HTTP {code} {str(d)[:120]}")

    code, d = c("POST", "/v1/harnesses", {"name": f"Interface agent {w.tag}", "base": "claude-code"})
    i["hid"] = d.get("id", "") if code == 200 else ""
    who = f"member:{i['hid']}"
    code, d = c("POST", f"/v1/memories/{i['root']}/grants", {"principal": who, "privileges": ["read", "write"]})
    yield ("POST grants",) + _ok(code == 200 and d.get("principal") == who, f"HTTP {code} {str(d)[:120]}")
    i["grant"] = d.get("id", "") if code == 200 else ""
    code, d = c("GET", f"/v1/memories/{i['kid']}/grants")
    yield ("GET grants",) + _ok(code == 200 and any(g["principal"] == who and g["inherited"] for g in d.get("data") or []), f"HTTP {code} {str(d)[:160]}")
    code, d = c("GET", f"/v1/harnesses/{i['hid']}/memories")
    yield ("GET harness memories",) + _ok(code == 200 and d.get("principal") == who and [m["id"] for m in d.get("data") or []] == [i["root"]], f"HTTP {code} {str(d)[:160]}")
    code, d = c("PUT", f"/v1/harnesses/{i['hid']}/memories", {"default_memory_id": i["kid"], "observe": False})
    yield ("PUT harness memories",) + _ok(code == 200 and d.get("default_memory_id") == i["kid"] and d.get("observe") is False, f"HTTP {code} {str(d)[:160]}")

    body = "Either side can end the order form with 90 days written notice.\n\nPrice increases are capped at 5% a year."
    code, d = c("POST", f"/v1/memories/{i['kid']}/records", {"type": "note", "title": f"Master agreement {w.tag}", "content": body})
    yield ("POST records",) + _ok(code == 200 and d.get("title", "").startswith("Master agreement") and (d.get("content") or [{}])[0].get("text") == body, f"HTTP {code} {str(d)[:160]}")
    i["note"] = d.get("id", "") if code == 200 else ""
    code, a = c("POST", f"/v1/memories/{i['kid']}/records", {"type": "entity", "title": f"Ines Varga {w.tag}", "attributes": {"kind": "person"}})
    code2, b = c("POST", f"/v1/memories/{i['kid']}/records", {"type": "entity", "title": f"Harlow Mills {w.tag}", "attributes": {"kind": "company"}})
    code3, f = c("POST", f"/v1/memories/{i['kid']}/records", {"type": "fact", "title": f"Ines Varga {w.tag} runs purchasing at Harlow Mills {w.tag}",
                                                               "attributes": {"predicate": "runs purchasing at"},
                                                               "references": [{"rel": "subject", "record_id": a.get("id")}, {"rel": "object", "record_id": b.get("id")}]})
    yield ("POST records (entity, fact)",) + _ok((code, code2, code3) == (200, 200, 200) and f.get("content") == [], f"HTTP {code}/{code2}/{code3}")
    i.update(a=a.get("id", ""), b=b.get("id", ""), fact=f.get("id", ""))

    code, d = c("GET", f"/v1/memories/{i['kid']}/records/{i['note']}")
    yield ("GET record",) + _ok(code == 200 and d.get("trust") == "untrusted" and (d.get("written_by") or {}).get("kind") == "member", f"HTTP {code} {str(d)[:120]}")
    got = w.until(lambda: (lambda r: r[1] if r[0] == 200 and len(r[1].get("data") or []) >= 4 else None)(c("GET", f"/v1/memories/{i['kid']}/records?limit=50")))
    yield ("GET records",) + _ok(bool(got), "the four records written are not all listed")
    code, d = c("GET", f"/v1/memories/{i['kid']}/records?type=entity")
    yield ("GET records?type",) + _ok(code == 200 and {r["type"] for r in d.get("data") or []} <= {"entity"}, f"HTTP {code}")

    code, d = c("PATCH", f"/v1/memories/{i['kid']}/records/{i['note']}", {"title": f"Master agreement {w.tag} (2024)", "attributes": {"revision_reason": "dated"}})
    yield ("PATCH record",) + _ok(code == 200 and d.get("version") == 2 and d.get("title", "").endswith("(2024)"), f"HTTP {code} {str(d)[:160]}")
    code, d = c("GET", f"/v1/memories/{i['kid']}/records/{i['note']}/history")
    if hist == "none":
        yield ("GET history",) + (("n/a", "declared") if code in (200, 422) else ("FAIL", f"HTTP {code}"))
    else:
        yield ("GET history",) + _ok(code == 200 and [h.get("version") for h in d.get("data") or []] == [1, 2], f"HTTP {code} {[h.get('version') for h in (d.get('data') or [])] if isinstance(d, dict) else d}")

    q = {"query": "notice period of the master agreement"} if "query" in signals else {"text": "notice"}
    got = w.until(lambda: (lambda r: r[1] if r[0] == 200 and any(x["record"]["id"] == i["note"] for x in r[1].get("results") or []) else None)(c("POST", f"/v1/memories/{i['root']}/recall", q)))
    yield ("POST recall (subtree)",) + _ok(bool(got) and next(x for x in got["results"] if x["record"]["id"] == i["note"])["memory"]["id"] == i["kid"],
                                           "asked at the root, the child's record was not found with its memory named")
    code, d = c("POST", f"/v1/memories/{i['root']}/recall", {**q, "depth": 0})
    yield ("POST recall (depth 0)",) + _ok(code == 200 and not any(x["record"]["id"] == i["note"] for x in d.get("results") or []), f"HTTP {code}")
    code, d = c("POST", f"/v1/memories/{i['kid']}/recall", {"text": "notice"})
    yield ("POST recall (text)",) + _ok(code == 200 and (("text:not_supported" in (d.get("degraded") or [])) == ("text" not in signals)), f"HTTP {code} degraded={d.get('degraded') if isinstance(d, dict) else d}")

    got = w.until(lambda: (lambda r: r[1] if r[0] == 200 and {i["a"], i["b"], i["fact"]} <= {n["record"]["id"] for n in r[1].get("nodes") or []} else None)(
        c("POST", f"/v1/memories/{i['kid']}/graph", {"around": i["a"], "hops": 2})))
    yield ("POST graph",) + _ok(bool(got) and {"subject", "object"} <= {e.get("rel") for e in got["edges"]}, "two hops from the subject did not return the fact and its object")

    code, d = c("POST", f"/v1/memories/{i['kid']}/observe", {"episodes": [{"content": [
        {"type": "text", "role": "user", "text": f"Our warehouse {w.tag} in Porto closes at six."},
        {"type": "text", "role": "assistant", "text": "Noted: Porto closes at six."}]}]})
    yield ("POST observe",) + _ok(code in (200, 202) and isinstance(d.get("data"), list), f"HTTP {code} {str(d)[:160]}")
    if code == 202:
        job = (d.get("job") or {}).get("id", "")
        got = w.until(lambda: (lambda r: r[1] if r[0] == 200 and r[1].get("status") != "pending" else None)(c("GET", f"/v1/memories/{i['kid']}/jobs/{job}")), 120)
        yield ("GET job",) + _ok(bool(got) and got.get("status") == "completed", f"the job did not complete: {str(got)[:160]}")
    else:
        yield ("GET job", "n/a", "observe answered at once")

    langs = (((caps.get("queries") or {}).get("free") or {}).get("languages")) or []
    named_off = not (caps.get("queries") or {}).get("named")
    code, d = c("PUT", f"/v1/memories/{i['kid']}/queries/notes", {"description": "every note", "requires": "read", "language": (langs or ["none"])[0],
                                                                 "body": '{"field": "type", "op": "eq", "value": "note"}'})
    yield ("PUT query",) + _unsupported(code, d, named_off)
    code, d = c("GET", f"/v1/memories/{i['kid']}/queries")
    yield ("GET queries",) + _ok(code == 200 and isinstance(d.get("data"), list), f"HTTP {code} {str(d)[:120]}")
    code, d = c("POST", f"/v1/memories/{i['kid']}/queries/notes", {"params": {}})
    yield ("POST query (named)",) + (("n/a", "declared") if named_off and code in (404, 422) else _ok(code == 200, f"HTTP {code} {_code(d)}"))
    code, d = c("POST", f"/v1/memories/{i['kid']}/query", {"language": (langs or ["none"])[0], "statement": '{"field": "type", "op": "eq", "value": "note"}'})
    yield ("POST query (free)",) + _unsupported(code, d, not langs)
    code, d = c("POST", f"/v1/memories/{i['kid']}/records/{i['note']}/operations/none", {})
    yield ("POST operation",) + (("n/a", "no extension type on this engine") if code in (404, 422) else ("FAIL", f"an operation nobody defined answered HTTP {code}"))

    code, d = c("POST", f"/v1/memories/{i['kid']}/snapshots", {"name": "before"})
    yield ("POST snapshots",) + _ok(code == 200 and d.get("name") == "before", f"HTTP {code} {str(d)[:120]}")
    code, d = c("GET", f"/v1/memories/{i['kid']}/snapshots")
    yield ("GET snapshots",) + _ok(code == 200 and [s["name"] for s in d.get("data") or []] == ["before"], f"HTTP {code}")

    runs_off = str(caps.get("consolidate") or "none") not in ("runs", "trigger")
    code, d = c("POST", f"/v1/memories/{i['kid']}/consolidations", {})
    yield ("POST consolidations",) + _unsupported(code, d, runs_off)
    run = d.get("id", "") if code == 200 else ""
    code, d = c("GET", f"/v1/memories/{i['kid']}/consolidations")
    yield ("GET consolidations",) + (("n/a", "declared") if runs_off and code in (200, 422) else _ok(code == 200, f"HTTP {code}"))
    for name, method, path in (("GET consolidation", "GET", ""), ("GET consolidation changes", "GET", "/changes"), ("POST consolidation revert", "POST", "/revert")):
        if not run:
            yield (name, "n/a", "declared")
            continue
        code, d = c(method, f"/v1/memories/{i['kid']}/consolidations/{run}{path}", {} if method == "POST" else None)
        yield (name,) + _ok(code == 200, f"HTTP {code} {_code(d)}")

    code, d = c("DELETE", f"/v1/memories/{i['kid']}/records/{i['fact']}")
    yield ("DELETE record (forget)",) + _ok(code == 200 and d.get("status") == "forgotten", f"HTTP {code} {str(d)[:120]}")
    code, d = c("POST", f"/v1/memories/{i['kid']}/erase", {"record_ids": [i["b"]]})
    yield ("POST erase",) + _ok(code == 200 and d.get("erased") == [i["b"]] and isinstance(d.get("unreachable"), list), f"HTTP {code} {str(d)[:160]}")
    code, d = c("GET", f"/v1/memories/{i['kid']}/records/{i['b']}")
    yield ("GET record (erased)",) + _ok(code == 404 and _code(d) == "memory_record_not_found", f"HTTP {code} {_code(d)}")

    code, d = c("DELETE", f"/v1/memories/{i['root']}/grants/{i['grant']}")
    yield ("DELETE grant",) + _ok(code == 200, f"HTTP {code}")
    code, d = c("GET", f"/v1/harnesses/{i['hid']}/memories")
    yield ("GET harness memories (revoked)",) + _ok(code == 200 and d.get("data") == [], f"HTTP {code} {str(d)[:120]}")
    code, d = c("GET", "/v1/memories/" + "no-such-memory-" + w.tag)
    yield ("GET memory (unknown)",) + _ok(code == 404 and _code(d) == "memory_not_found", f"HTTP {code} {_code(d)}")
    code, d = c("DELETE", f"/v1/memories/{i['root']}")
    yield ("DELETE memory",) + _ok(code == 200 and set(d.get("memories") or []) == {i["root"], i["kid"]}, f"HTTP {code} {str(d)[:160]}")
    i["root"] = ""


def run_engine(call, engine: dict, keep: bool, log) -> list[dict]:
    w, rows = World(call, engine), []
    try:
        for name, verdict, why in probes(w):
            rows.append({"route": name, "verdict": verdict, "why": why})
            log(f"{verdict:4} {engine['id']} {name} {why}")
    except Exception as e:  # noqa: BLE001
        rows.append({"route": "(the run)", "verdict": "FAIL", "why": f"{type(e).__name__}: {e}"[:240]})
        log(f"FAIL {engine['id']} the run stopped: {rows[-1]['why']}")
    finally:
        if not keep:
            if w.ids.get("hid"):
                call("DELETE", f"/v1/harnesses/{w.ids['hid']}")
            if w.ids.get("root"):
                call("DELETE", f"/v1/memories/{w.ids['root']}")
    return rows


def render(result: dict) -> str:
    engines = list(result["engines"])
    routes = []
    for e in engines:
        routes += [r["route"] for r in result["engines"][e] if r["route"] not in routes]
    out = [f"Instance {result['meta'].get('instance', '')}, protocol {result['meta'].get('protocol', '')}, {result['meta'].get('at', '')}.", "",
           "| route | " + " | ".join(engines) + " |", "|---|" + "---|" * len(engines)]
    notes = []
    for route in routes:
        cells = []
        for e in engines:
            r = next((x for x in result["engines"][e] if x["route"] == route), None)
            cells.append(r["verdict"] if r else "-")
            if r and r["verdict"] == "FAIL":
                notes.append(f"- {e}, {route}: {r['why']}")
        out.append(f"| {route} | " + " | ".join(cells) + " |")
    for e in engines:
        rows = result["engines"][e]
        out.append(f"\n{e}: {sum(1 for r in rows if r['verdict'] == 'pass')} pass, {sum(1 for r in rows if r['verdict'] == 'n/a')} not served and declared, "
                   f"{sum(1 for r in rows if r['verdict'] == 'FAIL')} fail, of {len(rows)} calls.")
    return "\n".join(out + ([""] + ["Notes:"] + notes if notes else []))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--engines", default="mem0")
    ap.add_argument("--workspace", default="default")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--md", default="")
    a = ap.parse_args()
    call = _client(a.base_url, a.api_key, a.workspace)

    def log(s: str):
        print(time.strftime("%H:%M:%S"), s, flush=True)

    code, disc = call("GET", "/v1/uhp")
    if code != 200 or not (disc.get("capabilities") or {}).get("memories"):
        print("FAIL the instance does not report the memories capability:", code); return 2
    code, provs = call("GET", "/v1/memories/providers")
    have = {p["id"]: p for p in (provs.get("data") or [])} if code == 200 else {}
    result: dict = {"meta": {"instance": str(disc.get("server") or ""), "protocol": str(disc.get("default_version") or ""),
                             "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}, "engines": {}}
    for e in [x.strip() for x in a.engines.split(",") if x.strip()]:
        if e not in have:
            print(f"FAIL engine {e} is not connected on this instance (connected: {', '.join(have) or 'none'})"); return 2
        result["engines"][e] = run_engine(call, have[e], a.keep, log)
    table = render(result)
    print(table)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(result, f, indent=1)
    if a.md:
        with open(a.md, "w") as f:
            f.write(table + "\n")
    return 0 if all(r["verdict"] != "FAIL" for rows in result["engines"].values() for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
