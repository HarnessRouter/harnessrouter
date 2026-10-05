#!/usr/bin/env python3
"""The memories matrix: every harness base, on every memory engine, doing with memory what an
agent is given memory for, through the API, the way a customer's product would.

Three dimensions, each a list this file grows by one entry at a time:

    engine    a memory provider the instance has connected (mem0 today)
    base      a harness base (claude-code, codex, ...), on its default model or on --model
    scenario  one thing memory must do end to end (SCENARIOS below)

For each (engine, base) the runner builds its own small world and tears it down afterwards:

    root                 the agent is granted read here
     ├─ notes            read and write, and the harness's default memory
     ├─ archive          reached only through the grant on root; holds a seeded passphrase
     ├─ client           read and write; named by one task as that task's memory
     └─ vault            restricted, and the agent holds nothing on it; holds a seeded code

A scenario is one task in plain words, in a session of its own, so the memory is the only thing
that carries anything from one to the next. It passes on what the SERVICE holds afterwards (the
records, their writer, their versions, the graph), and on the answer only where the answer is the
point. The prompts name no tool: the agent's instructions carry a Memory section when it holds a
memory (the gateway writes it), and that is what a person's prompt relies on.

    python3 memories/matrix.py --base-url https://host/api/harness --api-key "$KEY" \\
        [--engines mem0] [--bases all|claude-code,codex] [--model ID] [--scenarios all|remember,recall]
        [--workers 2] [--out results.json] [--md table.md] [--rerun] [--keep]

`--out` is also the resume point: a cell whose scenarios all passed there is not run again unless
`--rerun`. A failed scenario is retried once, as every matrix column is. The interface itself
(every route, on each engine) is the conformance suite's part: `uhp-conformance --class full
--only ME-01,...`; this matrix is what agents do through it.

Adding an engine: connect it on the instance and name it in --engines; a scenario an engine cannot
serve is skipped from its capability document, never failed. Adding a scenario: one function that
returns (ok, why) and one line in SCENARIOS.
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

EXCLUDED = {"systemone"}        # chooses among offered actions and has no tools to call
TURN_CAP_S = 900
SETTLE_S = 90                   # an engine may index, or derive, a little after it stores


def _client(base_url: str, api_key: str, workspace: str):
    base = base_url.rstrip("/")
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "x-harness-workspace": workspace,
         "User-Agent": "harnessrouter-memories-matrix/1"}

    def call(method: str, path: str, body=None, timeout=120):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={**H, **({"Idempotency-Key": secrets.token_hex(8)} if path.endswith("/responses") else {})}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                try:
                    return r.status, json.loads(raw)
                except ValueError:
                    return r.status, raw.decode()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode()[:300]
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return 0, f"{type(e).__name__}: {e}"[:200]
    return call


class Cell:
    """One (engine, base): its world, and the helpers every scenario reads the service through."""

    def __init__(self, call, engine: dict, base: str, model: str, log):
        self.call, self.engine, self.base, self.model, self.log = call, engine, base, model, log
        self.tag = secrets.token_hex(3)
        self.mem: dict[str, str] = {}
        self.hid = self.reader = ""
        self.word = {k: f"{k.upper()}-{secrets.token_hex(3).upper()}" for k in
                     ("launch", "launch2", "archive", "vault", "client", "viewer")}
        self.turns: list[dict] = []

    # ── the world ──────────────────────────────────────────────────────────────────────────
    def _must(self, res, what: str):
        code, d = res
        if code != 200:
            raise RuntimeError(f"{what}: HTTP {code} {json.dumps(d)[:200]}")
        return d

    def build(self) -> None:
        c, eng = self.call, self.engine["id"]
        mk = lambda **b: self._must(c("POST", "/v1/memories", b), f"create memory {b.get('name')}")["id"]   # noqa: E731
        root = mk(name=f"Matrix {self.base} {self.tag}", description="What this team keeps.", provider=eng)
        self.mem = {"root": root,
                    "notes": mk(name=f"Notes {self.tag}", description="What the agent learns while working.", parent_id=root),
                    "archive": mk(name=f"Archive {self.tag}", description="Older decisions and passphrases.", parent_id=root),
                    "client": mk(name=f"Client {self.tag}", description="What is known about one client.", parent_id=root),
                    "vault": mk(name=f"Vault {self.tag}", description="Kept to the owners.", parent_id=root, restricted=True)}
        self.remember("archive", type="fact", title=f"The archive passphrase is {self.word['archive']}")
        self.remember("vault", type="fact", title=f"The vault code is {self.word['vault']}")
        self.hid = self.harness("Agent")
        self.grant(self.hid, "root", ["read"])
        for m in ("notes", "client"):
            self.grant(self.hid, m, ["read", "write"])
        self._must(c("PUT", f"/v1/harnesses/{self.hid}/memories", {"default_memory_id": self.mem["notes"]}), "set the default memory")

    def harness(self, role: str) -> str:
        body = {"name": f"Memories matrix {self.base} {role} {self.tag}", "base": self.base}
        if self.model:
            body["default_model"] = self.model
        return self._must(self.call("POST", "/v1/harnesses", body), "create harness")["id"]

    def grant(self, hid: str, mem: str, privs: list[str]) -> None:
        self._must(self.call("POST", f"/v1/memories/{self.mem[mem]}/grants", {"principal": f"member:{hid}", "privileges": privs}),
                   f"grant {mem}")

    def remember(self, mem: str, **record) -> dict:
        return self._must(self.call("POST", f"/v1/memories/{self.mem[mem]}/records", record), f"seed {mem}")

    def teardown(self) -> None:
        for hid in (self.hid, self.reader):
            if hid:
                self.call("DELETE", f"/v1/harnesses/{hid}")
        if self.mem.get("root"):
            self.call("DELETE", f"/v1/memories/{self.mem['root']}")

    # ── reading the service ────────────────────────────────────────────────────────────────
    def records(self, mem: str, include: str = "active") -> list[dict]:
        out, cursor = [], ""
        for _ in range(10):
            code, d = self.call("GET", f"/v1/memories/{self.mem[mem]}/records?limit=200&include={include}" + (f"&cursor={cursor}" if cursor else ""))
            if code != 200:
                break
            out += d.get("data") or []
            cursor = d.get("next") or ""
            if not cursor:
                break
        return out

    @staticmethod
    def said(r: dict) -> str:
        return " ".join([str(r.get("title") or "")] + [str(p.get("text") or "") for p in r.get("content") or []])

    def holding(self, mem: str, word: str, include: str = "active") -> list[dict]:
        return [r for r in self.records(mem, include) if word.lower() in self.said(r).lower()]

    def wait(self, check, seconds: int = SETTLE_S):
        """`check()` until it returns something truthy, or the engine's settling time is up."""
        end, got = time.time() + seconds, None
        while True:
            got = check()
            if got or time.time() > end:
                return got
            time.sleep(4)

    # ── one task ───────────────────────────────────────────────────────────────────────────
    def ask(self, text: str, hid: str = "", memory: str = "") -> dict:
        """One task in a session of its own. Returns {status, answer, tools, s, error}."""
        t0 = time.time()
        meta = {"harness_id": hid or self.hid}
        if memory:
            meta["memory"] = self.mem[memory]
        code, resp = self.call("POST", "/v1/responses", {"input": text, "stream": False, "background": True,
                                                         "model": self.model or None, "metadata": meta}, timeout=180)
        out = {"status": "", "answer": "", "tools": [], "error": "", "s": 0}
        if code != 200:
            out["error"] = f"HTTP {code} {json.dumps(resp)[:160]}"
            return out
        rid, d = resp.get("id"), {}
        while time.time() - t0 < TURN_CAP_S:
            code, d = self.call("GET", f"/v1/responses/{rid}", timeout=60)
            if isinstance(d, dict) and d.get("status") in ("completed", "failed", "incomplete", "cancelled"):
                break
            time.sleep(5)
        d = d if isinstance(d, dict) else {}
        out["status"] = d.get("status") or "timeout"
        out["answer"] = "".join(p.get("text") or "" for it in (d.get("output") or []) for p in (it.get("content") or [])
                                if p.get("type") in ("output_text", "text"))
        out["tools"] = sorted({str(it.get("name") or "").split("__")[-1] for it in (d.get("output") or [])
                               if "memory_" in str(it.get("name") or "")})
        out["error"] = str((d.get("error") or {}).get("message") or "")[:200]
        out["model"] = str(d.get("model") or "")
        out["s"] = int(time.time() - t0)
        self.turns.append({"asked": text[:60], **{k: out[k] for k in ("status", "tools", "s", "model")}})
        return out


def _done(t: dict) -> str:
    """'' when the task completed, else why it did not."""
    return "" if t["status"] == "completed" else f"the task ended {t['status'] or 'unknown'}" + (f": {t['error']}" if t["error"] else "")


# ── scenarios: each returns (ok, why); `why` is said on a pass too when it is worth reading ────
def s_remember(c: Cell):
    """The agent keeps something it was told, in the memory it writes by default, as itself."""
    t = c.ask(f"Please remember this for later conversations: the launch codeword is {c.word['launch']}.")
    if _done(t):
        return False, _done(t)
    got = c.wait(lambda: [r for r in c.holding("notes", c.word["launch"]) if (r.get("written_by") or {}).get("id") == c.hid])
    if not got:
        elsewhere = [m for m in ("root", "archive", "client") if c.holding(m, c.word["launch"])]
        return False, ("the agent wrote it in " + ", ".join(elsewhere) + ", not in its default memory" if elsewhere else
                       f"no record holds the codeword after the task (tools: {', '.join(t['tools']) or 'none'}); answered {t['answer'][-120:]!r}")
    w = got[0].get("written_by") or {}
    if (w.get("kind"), w.get("type")) != ("member", "agent"):
        return False, f"the record's writer is {w}, expected the agent as a member"
    return True, ""


def s_recall(c: Cell):
    """A later conversation, sharing nothing with the first, answers from the memory."""
    if not c.holding("notes", c.word["launch"]):
        c.remember("notes", type="fact", title=f"The launch codeword is {c.word['launch']}")
        c.wait(lambda: c.holding("notes", c.word["launch"]))
    t = c.ask("What is the launch codeword? You were told in an earlier conversation.")
    if _done(t):
        return False, _done(t)
    return (True, "") if c.word["launch"].lower() in t["answer"].lower() else (False, f"answered without the codeword: {t['answer'][-160:]!r}")


def s_subtree(c: Cell):
    """Asked high in the tree, the agent finds what is kept below and says where."""
    t = c.ask("What is the archive passphrase, and what is the name of the memory it is kept in?")
    if _done(t):
        return False, _done(t)
    a = t["answer"].lower()
    if c.word["archive"].lower() not in a:
        return False, f"answered without the passphrase: {t['answer'][-160:]!r}"
    return (True, "") if f"archive {c.tag}" in a else (False, f"found it and did not name the memory it is in: {t['answer'][-160:]!r}")


def s_reach(c: Cell):
    """What the agent was not granted does not exist for it, whatever it is asked."""
    t = c.ask("What is the vault code? Look everywhere in your memory. If you cannot find it, say NOT FOUND.")
    if _done(t):
        return False, _done(t)
    return (False, "THE AGENT READ A MEMORY IT WAS NOT GRANTED: the vault code is in its answer") if c.word["vault"].lower() in t["answer"].lower() else (True, "")


def s_revise(c: Cell):
    """The agent corrects what it holds; nothing still says the old thing."""
    if not c.holding("notes", c.word["launch"]):
        c.remember("notes", type="fact", title=f"The launch codeword is {c.word['launch']}")
        c.wait(lambda: c.holding("notes", c.word["launch"]))
    t = c.ask(f"The launch codeword has changed: it is now {c.word['launch2']}, no longer {c.word['launch']}. "
              "Correct what you have in memory so that nothing there still gives the old codeword.")
    if _done(t):
        return False, _done(t)
    ok = c.wait(lambda: c.holding("notes", c.word["launch2"]) and not c.holding("notes", c.word["launch"]))
    if not ok:
        return False, ("the new codeword is in memory and the old one still is too" if c.holding("notes", c.word["launch2"]) else
                       f"the new codeword is not in memory (tools: {', '.join(t['tools']) or 'none'})")
    head = c.holding("notes", c.word["launch2"])[0]
    return True, ("revised in place, version " + str(head.get("version"))) if int(head.get("version") or 1) > 1 else "forgot the old record and wrote a new one"


def s_graph(c: Cell):
    """Two entities and the fact between them, written by the agent, read back as one graph."""
    if (c.engine.get("graph") or {}).get("entities", "none") == "none":
        return None, "this engine keeps no entity records"
    person, firm = f"Ines Varga {c.tag}", f"Harlow Mills {c.tag}"
    t = c.ask(f"Keep this in memory as a small graph: {person} is a person, {firm} is a company, and {person} runs purchasing at {firm}. "
              "Record the two as entities and the relationship as a fact that references the person as its subject and the company as its object.")
    if _done(t):
        return False, _done(t)

    def edges():
        # read each memory the agent may write or read: where it keeps the graph is its choice
        ents, rels = {}, {}
        for m in ("root", "notes", "client", "archive"):
            code, g = c.call("POST", f"/v1/memories/{c.mem[m]}/graph", {"limit": 300})
            if code != 200:
                continue
            ents.update({n["record"]["id"]: c.said(n["record"]) for n in g.get("nodes") or [] if n["record"].get("type") == "entity"})
            for e in g.get("edges") or []:
                if e.get("rel") in ("subject", "object"):
                    rels.setdefault(e["from"]["record_id"], {})[e["rel"]] = e["to"]["record_id"]
        named = [{k: ents.get(v, "") for k, v in r.items()} for r in rels.values()]
        return [r for r in named if person.lower() in r.get("subject", "").lower() and firm.lower() in r.get("object", "").lower()]
    if c.wait(edges):
        return True, ""
    ents = [c.said(r)[:40] for m in ("notes", "root", "client") for r in c.records(m) if r.get("type") == "entity"]
    return False, (f"entities written ({'; '.join(ents)}) and no fact joins them as subject and object" if ents else
                   f"no entity record was written (tools: {', '.join(t['tools']) or 'none'})")


def s_forget(c: Cell):
    """The agent forgets on request; the record is closed, and no longer found."""
    word = c.word["launch2"] if c.holding("notes", c.word["launch2"]) else c.word["launch"]
    if not c.holding("notes", word):
        c.remember("notes", type="fact", title=f"The launch codeword is {word}")
        c.wait(lambda: c.holding("notes", word))
    t = c.ask("Forget the launch codeword: it must not be in your memory any more.")
    if _done(t):
        return False, _done(t)
    return (True, "") if c.wait(lambda: not c.holding("notes", word)) else (False, f"the codeword is still an active record (tools: {', '.join(t['tools']) or 'none'})")


def s_task_memory(c: Cell):
    """A task names the memory it is for, and that conversation writes there."""
    t = c.ask(f"Remember that this client's preferred contact word is {c.word['client']}.", memory="client")
    if _done(t):
        return False, _done(t)
    if c.wait(lambda: c.holding("client", c.word["client"])):
        return True, ""
    return False, ("it was written in the harness's default memory, not in the one the task named" if c.holding("notes", c.word["client"]) else
                   f"no record holds it (tools: {', '.join(t['tools']) or 'none'})")


def s_viewer(c: Cell):
    """An agent granted only read cannot write, however it is asked."""
    c.reader = c.harness("Viewer")
    c.grant(c.reader, "root", ["read"])
    c.call("PUT", f"/v1/harnesses/{c.reader}/memories", {"observe": False})
    t = c.ask(f"Please remember this for later: the viewer token is {c.word['viewer']}.", hid=c.reader)
    if _done(t):
        return False, _done(t)
    time.sleep(8)
    wrote = [m for m in c.mem if c.holding(m, c.word["viewer"])]
    return (False, "A READ-ONLY AGENT WROTE: the token is in " + ", ".join(wrote)) if wrote else (True, "")


def s_observe(c: Cell):
    """A finished conversation is recorded in the default memory without the agent being asked."""
    eng = c.engine
    if not (eng.get("observe") or {}).get("keeps_episodes") and str(eng.get("derivation") or "none") == "none":
        return None, "this engine neither keeps episodes nor derives from them"

    def recorded():
        return [r for r in c.records("notes") if r.get("type") == "episode" or (r.get("written_by") or {}).get("kind") == "provider"]
    if recorded():
        return True, ""
    t = c.ask("For the record: our support line opens at 8 in the morning on weekdays and is closed on Sundays.")
    if _done(t):
        return False, _done(t)
    got = c.wait(recorded, 120)
    if not got:
        return False, "nothing was recorded in the default memory after a finished conversation"
    w = got[0].get("written_by") or {}
    return True, ("an episode" if got[0].get("type") == "episode" else f"derived by {w.get('id')} on behalf of {w.get('on_behalf_of') or 'nobody named'}")


SCENARIOS = [("remember", s_remember), ("recall", s_recall), ("subtree", s_subtree), ("reach", s_reach),
             ("revise", s_revise), ("graph", s_graph), ("forget", s_forget), ("task_memory", s_task_memory),
             ("viewer", s_viewer), ("observe", s_observe)]


def run_cell(call, engine: dict, base: str, model: str, wanted: list[str], keep: bool, log) -> dict:
    t0 = time.time()
    row: dict = {"engine": engine["id"], "base": base, "model": model, "scenarios": {}, "why": ""}
    cell = Cell(call, engine, base, model, log)
    try:
        cell.build()
        for name, fn in SCENARIOS:
            if name not in wanted:
                continue
            s0 = time.time()
            try:
                ok, why = fn(cell)
                if ok is False:                    # once more, as every matrix column is retested
                    first = why
                    ok, why = fn(cell)
                    why = (f"passed on the second try; first: {first}" if ok else why)
            except Exception as e:  # noqa: BLE001
                ok, why = False, f"{type(e).__name__}: {e}"[:240]
            row["scenarios"][name] = {"ok": ok, "why": why, "s": int(time.time() - s0)}
            log(f"{'PASS' if ok else 'skip' if ok is None else 'FAIL'} {engine['id']} {base} {name} {int(time.time() - s0)}s {why}")
        row["model"] = model or next((t["model"] for t in cell.turns if t.get("model")), "")
    except Exception as e:  # noqa: BLE001
        row["why"] = f"{type(e).__name__}: {e}"[:300]
        log(f"FAIL {engine['id']} {base} could not build its world: {row['why']}")
    finally:
        row["turns"] = cell.turns
        if not keep:
            cell.teardown()
    row["s"] = int(time.time() - t0)
    return row


def cell_ok(row: dict, wanted: list[str]) -> bool:
    return not row.get("why") and all((row.get("scenarios") or {}).get(n, {}).get("ok") in (True, None) for n in wanted) and \
        all(n in (row.get("scenarios") or {}) for n in wanted)


def render(rows: list[dict], wanted: list[str], meta: dict) -> str:
    """One table per engine: a row per base, a column per scenario."""
    out = [f"Instance {meta.get('instance', '')}, protocol {meta.get('protocol', '')}, {meta.get('at', '')}.", ""]
    for eng in sorted({r["engine"] for r in rows}):
        mine = [r for r in rows if r["engine"] == eng]
        out += [f"### {eng}", "", "| base | model | " + " | ".join(wanted) + " | seconds |", "|---|---|" + "---|" * len(wanted) + "---:|"]
        notes = []
        for r in mine:
            cells = []
            for n in wanted:
                s = (r.get("scenarios") or {}).get(n)
                cells.append("-" if s is None else "pass" if s["ok"] else "n/a" if s["ok"] is None else "FAIL")
                if s and (s["ok"] is False or (s["why"] and s["ok"])):
                    notes.append(f"- {r['base']}, {n}: {s['why']}")
            out.append(f"| {r['base']} | {r.get('model') or 'default'} | " + " | ".join(cells) + f" | {r.get('s', '')} |")
            if r.get("why"):
                notes.append(f"- {r['base']}: {r['why']}")
        done = sum(1 for r in mine if cell_ok(r, wanted))
        out += ["", f"{done} of {len(mine)} bases pass every scenario on {eng}.", ""] + (["Notes:"] + notes + [""] if notes else [])
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--engines", default="mem0")
    ap.add_argument("--bases", default="all")
    ap.add_argument("--model", default="")
    ap.add_argument("--scenarios", default="all")
    ap.add_argument("--workspace", default="default")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--rerun", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--md", default="")
    a = ap.parse_args()
    call = _client(a.base_url, a.api_key, a.workspace)
    lock = threading.Lock()

    def log(s: str):
        with lock:
            print(time.strftime("%H:%M:%S"), s, flush=True)

    wanted = [n for n, _ in SCENARIOS] if a.scenarios == "all" else [x.strip() for x in a.scenarios.split(",") if x.strip()]
    unknown = [n for n in wanted if n not in dict(SCENARIOS)]
    if unknown:
        print("FAIL no such scenario:", ", ".join(unknown)); return 2
    code, disc = call("GET", "/v1/uhp")
    if code != 200 or not (disc.get("capabilities") or {}).get("memories"):
        print("FAIL the instance does not report the memories capability:", code); return 2
    code, provs = call("GET", "/v1/memories/providers")
    have = {p["id"]: p for p in (provs.get("data") or [])} if code == 200 else {}
    engines = []
    for e in [x.strip() for x in a.engines.split(",") if x.strip()]:
        if e not in have:
            print(f"FAIL engine {e} is not connected on this instance (connected: {', '.join(have) or 'none'})"); return 2
        engines.append(have[e])
    if a.bases == "all":
        code, bases = call("GET", "/v1/bases")
        items = bases.get("data") or bases.get("bases") if isinstance(bases, dict) else bases
        names = [str(b.get("id")) for b in items or [] if str(b.get("status") or "ready") == "ready" and str(b.get("id")) not in EXCLUDED]
    else:
        names = [x.strip() for x in a.bases.split(",") if x.strip()]
    prior: dict[tuple, dict] = {}
    if a.out and not a.rerun:
        try:
            prior = {(r["engine"], r["base"]): r for r in json.load(open(a.out)).get("rows", [])}
        except (OSError, ValueError):
            prior = {}
    cells = [(e, b) for e in engines for b in names]
    todo = [(e, b) for e, b in cells if not (prior.get((e["id"], b)) and cell_ok(prior[(e["id"], b)], wanted))]
    log(f"engines: {', '.join(e['id'] for e in engines)} | bases: {', '.join(names)} | scenarios: {', '.join(wanted)} | "
        f"{len(todo)} of {len(cells)} cells to run")
    meta = {"instance": str(disc.get("server") or disc.get("version") or ""), "protocol": str(disc.get("default_version") or ""),
            "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
    done = dict(prior)

    def save():
        rows = [done[k] for k in ((e["id"], b) for e, b in cells) if k in done]
        if a.out:
            with open(a.out, "w") as f:
                json.dump({"meta": meta, "scenarios": wanted, "rows": rows}, f, indent=1)
        return rows

    def one(cell) -> None:
        e, b = cell
        row = run_cell(call, e, b, a.model, wanted, a.keep, log)
        with lock:
            done[(e["id"], b)] = row
            save()

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        list(ex.map(one, todo))
    rows = save()
    table = render(rows, wanted, meta)
    print(table)
    if a.md:
        with open(a.md, "w") as f:
            f.write(table + "\n")
    return 0 if all(cell_ok(r, wanted) for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
