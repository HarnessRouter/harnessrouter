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

`--out` is also the resume point: what passed there is not run again unless `--rerun`, scenario
by scenario. A failed scenario is retried once, as every matrix column is. The interface itself
(every route, on each engine) is the conformance suite's part: `uhp-conformance --class full
--only ME-01,...`; this matrix is what agents do through it.

With `--world world.json` the runner builds nothing: it takes memories and agents that exist. That
is for an instance whose memories another server keeps, so that its agents reach them with their
tools and the instance has no /v1/memories of its own to build a tree through. The file names the
five memories by role, the agents by base, and where the runner reads the service (README.md has
the shape). Those memories must be the matrix's own: it forgets what is in them before and after.

Adding an engine: connect it on the instance and name it in --engines; a scenario an engine cannot
serve is skipped from its capability document, never failed. Adding a scenario: one function that
returns (ok, why) and one line in SCENARIOS.
"""
from __future__ import annotations

import argparse
import json
import os
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
ROLES = ("root", "notes", "archive", "client", "vault")


def _client(base_url: str, api_key: str, workspace: str = ""):
    base = base_url.rstrip("/")
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "harnessrouter-memories-matrix/1",
         **({"x-harness-workspace": workspace} if workspace else {})}

    def call(method: str, path: str, body=None, timeout=120, raw=False):
        """(status, answer). `raw` asks for the bytes of a 200 as they came."""
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={**H, **({"Idempotency-Key": secrets.token_hex(8)} if path.endswith("/responses") else {})}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                if raw:
                    return r.status, data
                try:
                    return r.status, json.loads(data)
                except ValueError:
                    return r.status, data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            data = e.read()
            try:
                return e.code, json.loads(data)
            except ValueError:
                return e.code, data.decode("utf-8", "replace")[:300]
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return 0, f"{type(e).__name__}: {e}"[:200]
    return call


class Cell:
    """One (engine, base): its world, and the helpers every scenario reads the service through.

    `call` speaks to the instance (tasks, harnesses). `m` speaks to the server that keeps the
    memories: the same instance when the runner builds its world, another when it was given one."""

    def __init__(self, call, engine: dict, base: str, model: str, log, world: dict | None = None, m=None, outsider=None,
                 files: bool = False):
        self.call, self.engine, self.base, self.model, self.log = call, engine, base, model, log
        self.m, self.world, self.outsider, self.files = m or call, world, outsider, files
        self.tag = secrets.token_hex(3)
        self.mem: dict[str, str] = {}
        self.name: dict[str, str] = {}
        self.hid = self.reader = self.writer = ""     # writer: the id the agent's records are stamped with
        self.unserved: dict[str, str] = {}             # scenario -> why this world cannot be asked it
        self.word = {k: f"{k.upper()}-{secrets.token_hex(3).upper()}" for k in
                     ("launch", "launch2", "archive", "vault", "client", "viewer", "asset", "document", "body")}
        self.turns: list[dict] = []

    # ── the world ──────────────────────────────────────────────────────────────────────────
    def _must(self, res, what: str):
        code, d = res
        if code != 200:
            raise RuntimeError(f"{what}: HTTP {code} {json.dumps(d)[:200]}")
        return d

    def build(self) -> None:
        if self.world is not None:
            self._adopt()
        else:
            self._make()
        self.remember("archive", type="fact", title=f"The archive shelf label is {self.word['archive']}")
        self.remember("vault", type="fact", title=f"The vault folder number is {self.word['vault']}")

    def _make(self) -> None:
        c, eng = self.call, self.engine["id"]
        self.name = {"root": f"Matrix {self.base} {self.tag}", "notes": f"Notes {self.tag}", "archive": f"Archive {self.tag}",
                     "client": f"Client {self.tag}", "vault": f"Vault {self.tag}"}
        mk = lambda role, **b: self._must(c("POST", "/v1/memories", {"name": self.name[role], **b}), f"create memory {self.name[role]}")["id"]   # noqa: E731
        root = mk("root", description="What this team keeps.", provider=eng)
        self.mem = {"root": root,
                    "notes": mk("notes", description="What the agent learns while working.", parent_id=root),
                    "archive": mk("archive", description="Older decisions and passphrases.", parent_id=root),
                    "client": mk("client", description="What is known about one client.", parent_id=root),
                    "vault": mk("vault", description="Kept to the owners.", parent_id=root, restricted=True)}
        self.hid = self.writer = self.harness("Agent")
        self.grant(self.hid, "root", ["read"])
        for m in ("notes", "client"):
            self.grant(self.hid, m, ["read", "write"])
        self._must(c("PUT", f"/v1/harnesses/{self.hid}/memories", {"default_memory_id": self.mem["notes"]}), "set the default memory")
        if not self.files:
            why = "agents on this instance are not offered a file to keep (run with --files where they are)"
            self.unserved = {"asset": why, "document": why}

    def _adopt(self) -> None:
        """Take the world as it stands: five memories by role, an agent on this base that reads the
        root, writes notes (its default) and client, and holds nothing on the vault."""
        w = self.world or {}
        agent = next(a for a in w["agents"] if a["base"] == self.base)
        self.mem = {k: str(w["memories"][k]) for k in ROLES}
        for k, mid in self.mem.items():
            self.name[k] = str(self._must(self.m("GET", f"/v1/memories/{mid}"), f"read the {k} memory").get("name") or "")
        self.hid, self.reader = str(agent["harness_id"]), str(agent.get("reader_harness_id") or "")
        self.writer = str(agent.get("writer") or self.hid)
        self.unserved = {str(k): str(v) for k, v in (w.get("not_served") or {}).items()}
        if not self.reader:
            self.unserved.setdefault("viewer", "the world names no agent that may only read")
        self.sweep()

    def sweep(self) -> None:
        """A given world is the matrix's own: forget what an earlier run, or this one, left in it. A
        record that follows a source kept elsewhere is not the matrix's to forget, and is left."""
        left = 0
        for k in ROLES:
            for r in self.records(k):
                if not r.get("follows"):
                    left += self.m("DELETE", f"/v1/memories/{self.mem[k]}/records/{r['id']}")[0] != 200
        if left:
            self.log(f"note {self.engine['id']} {self.base}: {left} record(s) in the given memories could not be forgotten")

    def harness(self, role: str) -> str:
        body = {"name": f"Memories matrix {self.base} {role} {self.tag}", "base": self.base}
        if self.model:
            body["default_model"] = self.model
        return self._must(self.call("POST", "/v1/harnesses", body), "create harness")["id"]

    def grant(self, hid: str, mem: str, privs: list[str]) -> None:
        self._must(self.call("POST", f"/v1/memories/{self.mem[mem]}/grants", {"principal": f"member:{hid}", "privileges": privs}),
                   f"grant {mem}")

    def viewer(self) -> str:
        """An agent that reads the root and writes nowhere: the world's, or one made for this cell."""
        if not self.reader and self.world is None:
            self.reader = self.harness("Viewer")
            self.grant(self.reader, "root", ["read"])
            self.call("PUT", f"/v1/harnesses/{self.reader}/memories", {"observe": False})
        return self.reader

    def remember(self, mem: str, **record) -> dict:
        return self._must(self.m("POST", f"/v1/memories/{self.mem[mem]}/records", record), f"seed {mem}")

    def teardown(self) -> None:
        if self.world is not None:
            return self.sweep()
        for hid in (self.hid, self.reader):
            if hid:
                self.call("DELETE", f"/v1/harnesses/{hid}")
        if self.mem.get("root"):
            self.call("DELETE", f"/v1/memories/{self.mem['root']}")

    # ── reading the service ────────────────────────────────────────────────────────────────
    def records(self, mem: str, include: str = "active") -> list[dict]:
        out, cursor = [], ""
        for _ in range(10):
            code, d = self.m("GET", f"/v1/memories/{self.mem[mem]}/records?limit=200&include={include}" + (f"&cursor={cursor}" if cursor else ""))
            if code != 200:
                break
            out += d.get("data") or []
            cursor = d.get("next") or ""
            if not cursor:
                break
        return out

    def content(self, mem: str, rid: str, index: int, who=None):
        """(status, bytes) of one file part, read at the part's own address."""
        return (who or self.m)("GET", f"/v1/memories/{self.mem[mem]}/records/{rid}/content/{index}", raw=True)

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
        out["session"] = str((d.get("metadata") or {}).get("session_id") or "")
        out["s"] = int(time.time() - t0)
        self.turns.append({"asked": text[:60], **{k: out[k] for k in ("status", "tools", "s", "model")}})
        return out


def _done(t: dict) -> str:
    """'' when the task completed, else why it did not."""
    return "" if t["status"] == "completed" else f"the task ended {t['status'] or 'unknown'}" + (f": {t['error']}" if t["error"] else "")


# ── scenarios: each returns (ok, why); `why` is said on a pass too when it is worth reading ────
def s_remember(c: Cell):
    """The agent keeps something it was told, in a memory it may write, as itself."""
    t = c.ask(f"Please remember this for later conversations: the working title of our launch is {c.word['launch']}.")
    if _done(t):
        return False, _done(t)

    def kept():
        return [(m, r) for m in ("notes", "client") for r in c.holding(m, c.word["launch"]) if (r.get("written_by") or {}).get("id") == c.writer]
    got = c.wait(kept)
    if not got:
        return False, f"no record holds the title after the task (tools: {', '.join(t['tools']) or 'none'}); answered {t['answer'][-120:]!r}"
    where, rec = got[0]
    w = rec.get("written_by") or {}
    if (w.get("kind"), w.get("type")) != ("member", "agent"):
        return False, f"the record's writer is {w}, expected the agent as a member"
    # Which of the memories it may write is the agent's choice; the default is where a write goes
    # when it names none.
    return True, ("" if where == "notes" else "kept in the client memory, by the agent's choice")


def s_recall(c: Cell):
    """A later conversation, sharing nothing with the first, answers from the memory."""
    if not (c.holding("notes", c.word["launch"]) or c.holding("client", c.word["launch"])):
        c.remember("notes", type="fact", title=f"The working title of our launch is {c.word['launch']}")
        c.wait(lambda: c.holding("notes", c.word["launch"]))
    t = c.ask("What is the working title of our launch? You were told in an earlier conversation.")
    if _done(t):
        return False, _done(t)
    return (True, "") if c.word["launch"].lower() in t["answer"].lower() else (False, f"answered without the title: {t['answer'][-160:]!r}")


def s_subtree(c: Cell):
    """Asked high in the tree, the agent finds what is kept below and says where."""
    t = c.ask("What is the archive shelf label, and what is the name of the memory it is kept in?")
    if _done(t):
        return False, _done(t)
    a = t["answer"].lower()
    if c.word["archive"].lower() not in a:
        return False, f"answered without the shelf label: {t['answer'][-160:]!r}"
    return (True, "") if c.name["archive"].lower() in a else (False, f"found it and did not name the memory it is in: {t['answer'][-160:]!r}")


def s_reach(c: Cell):
    """What the agent was not granted does not exist for it, whatever it is asked."""
    t = c.ask("What is the vault folder number? Look everywhere in your memory. If you cannot find it, say NOT FOUND.")
    if _done(t):
        return False, _done(t)
    return (False, "THE AGENT READ A MEMORY IT WAS NOT GRANTED: the vault folder number is in its answer") if c.word["vault"].lower() in t["answer"].lower() else (True, "")


def s_revise(c: Cell):
    """The agent corrects what it holds; nothing still says the old thing."""
    if not c.holding("notes", c.word["launch"]):
        c.remember("notes", type="fact", title=f"The working title of our launch is {c.word['launch']}")
        c.wait(lambda: c.holding("notes", c.word["launch"]))
    t = c.ask(f"The working title of our launch has changed: it is now {c.word['launch2']}, no longer {c.word['launch']}. "
              "Correct what you have in memory so that nothing there still gives the old title.")
    if _done(t):
        return False, _done(t)
    # A record that gives both ("it changed from A to B") states the change; one that gives the old
    # codeword alone still says the old thing.
    def stale():
        return [r for r in c.holding("notes", c.word["launch"]) if c.word["launch2"].lower() not in c.said(r).lower()]
    ok = c.wait(lambda: c.holding("notes", c.word["launch2"]) and not stale())
    if not ok:
        return False, (f"the new title is in memory and {len(stale())} record(s) still give the old one alone, written by "
                       + ", ".join(sorted({str((r.get('written_by') or {}).get('kind')) for r in stale()}))
                       if c.holding("notes", c.word["launch2"]) else
                       f"the new title is not in memory (tools: {', '.join(t['tools']) or 'none'})")
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
            code, g = c.m("POST", f"/v1/memories/{c.mem[m]}/graph", {"limit": 300})
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
        c.remember("notes", type="fact", title=f"The working title of our launch is {word}")
        c.wait(lambda: c.holding("notes", word))
    t = c.ask("Forget the working title of our launch: it must not be in your memory any more.")
    if _done(t):
        return False, _done(t)
    return (True, "") if c.wait(lambda: not c.holding("notes", word)) else (False, f"the title is still an active record (tools: {', '.join(t['tools']) or 'none'})")


def s_task_memory(c: Cell):
    """A task names the memory it is for, and that conversation writes there."""
    t = c.ask(f"Remember that this client's preferred greeting is {c.word['client']}.", memory="client")
    if _done(t):
        return False, _done(t)
    if c.wait(lambda: c.holding("client", c.word["client"])):
        return True, ""
    return False, ("it was written in the harness's default memory, not in the one the task named" if c.holding("notes", c.word["client"]) else
                   f"no record holds it (tools: {', '.join(t['tools']) or 'none'})")


def s_viewer(c: Cell):
    """An agent granted only read cannot write, however it is asked."""
    t = c.ask(f"Please remember this for later: the name of the reading room is {c.word['viewer']}.", hid=c.viewer())
    if _done(t):
        return False, _done(t)
    time.sleep(8)
    wrote = [m for m in c.mem if c.holding(m, c.word["viewer"])]
    return (False, "A READ-ONLY AGENT WROTE: the name is in " + ", ".join(wrote)) if wrote else (True, "")


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


_IMAGE = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8", b"RIFF")


def _file_of(c: Cell, word: str):
    """(memory, record, part index) of the agent's own active record whose file is said to show `word`."""
    for m in ("notes", "client"):
        for r in c.records(m):
            if (r.get("written_by") or {}).get("id") == c.writer and word.lower() in c.said(r).lower():
                for i, p in enumerate(r.get("content") or []):
                    if p.get("type") == "file":
                        return m, r, i
    return None


def _file_kept(c: Cell, t: dict, word: str, later: str, check):
    """What keeping a file must mean, whatever the file: a record with a file part and a line that
    says what it shows; bytes that read back; bytes that outlive the conversation that made them;
    nothing for another organization; and a later conversation that finds it by that line."""
    got = c.wait(lambda: _file_of(c, word))
    if not got:
        words = c.holding("notes", word) or c.holding("client", word)
        return False, ("the agent kept words about the file and not the file" if words else
                       f"no record holds it after the task (tools: {', '.join(t['tools']) or 'none'}); answered {t['answer'][-120:]!r}")
    mem, rec, i = got
    part = rec["content"][i]
    if not str(part.get("text") or "").strip():
        return False, "the file was kept without a line that says what it shows"
    code, data = c.content(mem, rec["id"], i)
    if code != 200 or not isinstance(data, bytes) or not data:
        return False, f"the file's bytes do not read back at the part's own address: HTTP {code}"
    said = int((part.get("file") or {}).get("bytes") or 0)
    if said and said != len(data):
        return False, f"the part says {said} bytes and {len(data)} read back"
    wrong = check(part, data)
    if wrong:
        return False, wrong
    notes = []
    if t.get("session"):
        c.call("DELETE", f"/v1/sessions/{t['session']}")
        code, again = c.content(mem, rec["id"], i)
        if code != 200 or again != data:
            return False, f"THE FILE WENT WITH THE CONVERSATION THAT MADE IT: with that session deleted, its bytes answer HTTP {code}"
    else:
        notes.append("the task named no session, so the file was not read again with its conversation deleted")
    if c.outsider:
        seen = [c.outsider("GET", f"/v1/memories/{c.mem[mem]}/records/{rec['id']}")[0], c.content(mem, rec["id"], i, c.outsider)[0]]
        if 200 in seen:
            return False, "ANOTHER ORGANIZATION READ THE FILE: its record or its bytes answered 200 to a member of another one"
    else:
        notes.append("not read as another organization: the world names none")
    a = c.ask(later)
    if _done(a):
        return False, _done(a)
    if word.lower() not in a["answer"].lower():
        return False, f"a later conversation did not find the file by what it shows: {a['answer'][-160:]!r}"
    return True, "; ".join(notes)


def s_asset(c: Cell):
    """An image the agent generated is kept as the image, with a line that says what it shows."""
    word = c.word["asset"]
    t = c.ask("Generate a small image of a lighthouse on a cliff for our poster series. Then keep the image itself in your memory, "
              f"so that a later conversation can use it. Where you say what it shows, include its poster reference: {word}.")
    if _done(t):
        return False, _done(t)

    def image(part: dict, data: bytes) -> str:
        kind = str((part.get("file") or {}).get("media_type") or "")
        return "" if kind.startswith("image/") and data.startswith(_IMAGE) else f"what was kept is not an image: {kind or 'no media type'}, {len(data)} bytes"
    return _file_kept(c, t, word, "In an earlier conversation you kept an image for our poster series in your memory. "
                                  "What is its poster reference?", image)


def s_document(c: Cell):
    """A file the agent wrote in its workspace is kept as that file, byte for byte."""
    word, body = c.word["document"], f"Harbour office status {c.word['body']}: the north dock reopens on Thursday."
    t = c.ask(f"Write a file named status-{c.tag}.md in your workspace that contains exactly this one line:\n{body}\n"
              "Then keep the file itself in your memory, so that a later conversation can use it. Where you say what it shows, "
              f"include its filing reference: {word}.")
    if _done(t):
        return False, _done(t)

    def same(part: dict, data: bytes) -> str:
        return "" if data.decode("utf-8", "replace").strip() == body else f"the bytes kept are not the file that was written: {data[:80]!r}"
    return _file_kept(c, t, word, "In an earlier conversation you kept a status note, as a file, in your memory. "
                                  "What is its filing reference?", same)


SCENARIOS = [("remember", s_remember), ("recall", s_recall), ("subtree", s_subtree), ("reach", s_reach),
             ("revise", s_revise), ("graph", s_graph), ("forget", s_forget), ("task_memory", s_task_memory),
             ("viewer", s_viewer), ("observe", s_observe), ("asset", s_asset), ("document", s_document)]


def run_cell(call, engine: dict, base: str, model: str, wanted: list[str], keep: bool, log, before: dict | None = None,
             **world) -> dict:
    """One cell. `before` is its earlier record: what passed there is kept and not run again (each
    scenario seeds what it needs, so any subset stands on its own in a fresh world)."""
    t0 = time.time()
    kept = {n: s for n, s in ((before or {}).get("scenarios") or {}).items() if s.get("ok") in (True, None) and n in wanted}
    wanted = [n for n in wanted if n not in kept]
    row: dict = {"engine": engine["id"], "base": base, "model": model or (before or {}).get("model", ""), "scenarios": dict(kept), "why": ""}
    cell = Cell(call, engine, base, model, log, **world)
    try:
        cell.build()
        for name, fn in SCENARIOS:
            if name not in wanted:
                continue
            s0 = time.time()
            try:
                ok, why = (None, cell.unserved[name]) if name in cell.unserved else fn(cell)
                if ok is False:                    # once more, as every matrix column is retested
                    first = why
                    ok, why = fn(cell)
                    why = (f"passed on the second try; first: {first}" if ok else why)
            except Exception as e:  # noqa: BLE001
                ok, why = False, f"{type(e).__name__}: {e}"[:240]
            row["scenarios"][name] = {"ok": ok, "why": why, "s": int(time.time() - s0)}
            log(f"{'PASS' if ok else 'skip' if ok is None else 'FAIL'} {engine['id']} {base} {name} {int(time.time() - s0)}s {why}")
        row["model"] = model or next((t["model"] for t in cell.turns if t.get("model")), "") or row["model"]
    except Exception as e:  # noqa: BLE001
        row["why"] = f"{type(e).__name__}: {e}"[:300]
        log(f"FAIL {engine['id']} {base} could not build its world: {row['why']}")
    finally:
        row["turns"] = cell.turns
        if not keep:
            cell.teardown()
    row["s"] = int(time.time() - t0) + int((before or {}).get("s") or 0)
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
    ap.add_argument("--world", default="", help="a JSON file naming memories and agents that exist; the runner builds nothing")
    ap.add_argument("--files", action="store_true", help="the agents of this instance are offered a file to keep (asset, document)")
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
    world = m = outsider = None
    if a.world:
        world = json.load(open(a.world))
        if world.get("dedicated") is not True:
            print('FAIL the world must say "dedicated": true: the runner forgets every record in the memories it is given, '
                  "so they must be the matrix's own"); return 2
        missing = [k for k in ROLES if not (world.get("memories") or {}).get(k)] + ([] if world.get("agents") else ["agents"])
        if missing:
            print("FAIL the world does not name:", ", ".join(missing)); return 2

        def keeper(spec: dict, what: str):
            token = os.environ.get(str(spec.get("bearer_env") or ""), "")
            if not token:
                print(f"FAIL {what}: set the environment variable its bearer_env names ({spec.get('bearer_env') or 'none named'})"); sys.exit(2)
            return _client(str(spec.get("base_url") or world["memories"]["base_url"]), token)
        m = keeper(world["memories"], "the memories of the world")
        outsider = keeper(world["outsider"], "the other organization") if world.get("outsider") else None
    code, disc = call("GET", "/v1/uhp")
    disc = disc if code == 200 and isinstance(disc, dict) else {}
    if world is None and not (disc.get("capabilities") or {}).get("memories"):
        print("FAIL the instance does not report the memories capability:", code); return 2
    code, provs = (m or call)("GET", "/v1/memories/providers")
    have = {p["id"]: p for p in (provs.get("data") or [])} if code == 200 else {}
    engines = []
    if world is not None:
        code, root = m("GET", f"/v1/memories/{world['memories']['root']}")
        if code != 200 or str(root.get("provider") or "") not in have:
            print(f"FAIL the world's root memory, or its engine's capability document, does not read with the bearer given: HTTP {code}"); return 2
        engines = [have[str(root["provider"])]]
        names = [str(x["base"]) for x in world["agents"] if a.bases == "all" or str(x["base"]) in a.bases.split(",")]
        a.workers = 1                                  # every cell uses the same memories
    else:
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
        # every cell on record, this run's or an earlier one's: a run of one base must not drop the others
        order = [(e["id"], b) for e, b in cells]
        rows = [done[k] for k in list(prior) + [k for k in order if k not in prior] if k in done]
        if a.out:
            with open(a.out, "w") as f:
                json.dump({"meta": meta, "scenarios": wanted, "rows": rows}, f, indent=1)
        return rows

    def one(cell) -> None:
        e, b = cell
        row = run_cell(call, e, b, a.model, wanted, a.keep, log, None if a.rerun else prior.get((e["id"], b)),
                       world=world, m=m, outsider=outsider, files=a.files)
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
