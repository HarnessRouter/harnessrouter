"""A memory provider that lives in this process, for tests and for the conformance suite.

It is not a product: nothing is kept across a restart, recall is word overlap, and it exists so the
protocol's own behaviour (versions, forgetting, erasing, references, queries, consolidation runs,
what `degraded` and `abstain` mean) can be exercised without an account anywhere. Registered only
when HR_MEMORY_FIXTURE=1.
"""
from __future__ import annotations

import json
import re
import time
import uuid

from memory_plane import MemoryError, Provider, text_of

_OPEN = None


def _iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t if t is not None else time.time())) + \
        f".{int(((t if t is not None else time.time()) % 1) * 1000):03d}Z"


def _words(s) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", json.dumps(s).lower() if not isinstance(s, str) else s.lower()))


class FixtureProvider(Provider):
    id = "fixture"

    def __init__(self):
        self.mem: dict[str, list[dict]] = {}          # memory id -> every version of every record
        self.named: dict[str, dict[str, dict]] = {}
        self.runs: dict[str, list[dict]] = {}
        self.primed: dict[str, str] = {}

    def capabilities(self) -> dict:
        return {"id": self.id, "isolation": "container", "derivation": "background",
                "recall": {"signals": ["query", "text", "filters"], "abstain": True, "max_depth": 0},
                "history": {"content": "versions", "structure": "none"},
                "revise": "native", "forget": "native", "erase": {"unreachable": "reported"},
                "prime": True, "consolidate": "runs",
                "queries": {"named": True, "free": {"languages": ["fixture-filter"], "write": False}},
                "types": True,
                # it keeps the reference of any file; the bytes stay with the server's file store
                "content": {"media": ["*/*"], "bytes": "referenced", "describes": []}}

    # ── storage ───────────────────────────────────────────────────────────────────────────────
    async def create(self, mid, memory):
        self.mem.setdefault(mid, [])

    async def drop(self, mid):
        for d in (self.mem, self.named, self.runs, self.primed):
            d.pop(mid, None)

    def _rows(self, mid) -> list[dict]:
        if mid not in self.mem:
            raise MemoryError(404, "memory_not_found", "No memory with that id.", "memory_id")
        return self.mem[mid]

    def _current(self, mid, as_of=None, include="active") -> list[dict]:
        out = []
        for r in self._rows(mid):
            t = r["time"]
            if as_of:
                if not (t["written_at"] <= as_of and (t["invalidated_at"] is None or t["invalidated_at"] > as_of)):
                    continue
                if r["status"] == "forgotten_marker":
                    continue
                out.append({**r, "status": "active"})
            elif include == "all" or r["status"] == "active":
                out.append(r)
        return [r for r in out if not r.get("erased")]

    def _append(self, mid, rec: dict, writer: dict, *, rid=None, version=1, supersedes=None) -> dict:
        row = {"id": rid or "hrec_" + uuid.uuid4().hex, "type": rec["type"], "content": rec["content"],
               "attributes": rec.get("attributes") or {}, "references": rec.get("references") or [],
               "version": version, "status": "active", "supersedes": supersedes,
               "time": {"valid_from": (rec.get("time") or {}).get("valid_from"),
                        "valid_to": (rec.get("time") or {}).get("valid_to"),
                        "written_at": _iso(), "invalidated_at": _OPEN},
               "written_by": writer}
        self._rows(mid).append(row)
        time.sleep(0.002)          # two writes never share a written_at: as_of has an instant between them
        return row

    def _head(self, mid, rid) -> dict | None:
        vs = [r for r in self._rows(mid) if r["id"] == rid and not r.get("erased")]
        return max(vs, key=lambda r: r["version"]) if vs else None

    async def count(self, mid):
        return len(self._current(mid)) if mid in self.mem else 0

    # ── writes ────────────────────────────────────────────────────────────────────────────────
    async def observe(self, mid, episodes, writer):
        return {"records": [self._append(mid, {"type": "episode", "content": e.get("content"),
                                               "attributes": e.get("attributes") or {}, "time": e.get("time")}, writer)
                            for e in episodes], "job": None}

    async def remember(self, mid, record, writer):
        return self._append(mid, record, writer)

    async def revise(self, mid, rid, patch, writer):
        head = self._head(mid, rid)
        if not head or head["status"] != "active":
            raise MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        new = {"type": head["type"], "content": patch.get("content", head["content"]),
               "attributes": {**head["attributes"], **(patch.get("attributes") or {})},
               "references": patch.get("references", head["references"]),
               "time": {**{k: head["time"][k] for k in ("valid_from", "valid_to")}, **(patch.get("time") or {})}}
        row = self._append(mid, new, writer, rid=rid, version=head["version"] + 1, supersedes=head["version"])
        head["status"], head["time"]["invalidated_at"] = "superseded", row["time"]["written_at"]
        return row

    async def forget(self, mid, rid, writer):
        head = self._head(mid, rid)
        if not head or head["status"] != "active":
            raise MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        head["status"], head["time"]["invalidated_at"] = "forgotten", _iso()
        head["forgotten_by"] = writer
        time.sleep(0.002)
        return head

    async def erase(self, mid, rids):
        erased, unreachable = [], []
        for rid in rids:
            hit = False
            for r in self._rows(mid):
                if r["id"] == rid:
                    r["erased"], r["content"], r["attributes"] = True, "", {}
                    hit = True
            if hit:
                erased.append(rid)
                # what was derived from it still says what it said: named, never silently kept
                unreachable += [r["id"] for r in self._rows(mid) if not r.get("erased") and any(
                    x.get("record_id") == rid and x.get("rel") == "derived_from" for x in r["references"])]
        return {"erased": erased, "unreachable": sorted(set(unreachable))}

    # ── reads ─────────────────────────────────────────────────────────────────────────────────
    async def get(self, mid, rid, as_of=None):
        if as_of:
            return next((r for r in self._current(mid, as_of) if r["id"] == rid), None)
        return self._head(mid, rid)

    async def history(self, mid, rid):
        vs = sorted((r for r in self._rows(mid) if r["id"] == rid and not r.get("erased")), key=lambda r: r["version"])
        if not vs:
            raise MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        return vs

    @staticmethod
    def _field(r, field):
        cur = r
        for part in str(field).split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        return cur

    def _match(self, r, flt) -> bool:
        if not flt:
            return True
        if "and" in flt:
            return all(self._match(r, f) for f in flt["and"])
        if "or" in flt:
            return any(self._match(r, f) for f in flt["or"])
        v, op, want = self._field(r, flt.get("field")), flt.get("op", "eq"), flt.get("value")
        if op == "eq":
            return v == want
        if op == "in":
            return v in (want or [])
        if op in ("gte", "lte", "gt", "lt"):
            if v is None:
                return False
            return {"gte": v >= want, "lte": v <= want, "gt": v > want, "lt": v < want}[op]
        if op == "contains":
            return str(want).lower() in str(v or "").lower()
        raise MemoryError(422, "memory_invalid", f"Unknown filter operator `{op}`.", "filters")

    def _select(self, mid, req) -> list[dict]:
        rows = self._current(mid, req.get("as_of"), req.get("include") or "active")
        if req.get("types"):
            rows = [r for r in rows if r["type"] in req["types"]]
        return [r for r in rows if self._match(r, req.get("filters"))]

    async def list(self, mid, req):
        rows = sorted(self._select(mid, req), key=lambda r: (r["time"]["written_at"], r["id"]))
        start = int(req.get("cursor") or 0)
        page = rows[start:start + int(req.get("limit") or 50)]
        nxt = start + len(page)
        return {"records": page, "next": str(nxt) if nxt < len(rows) else None}

    async def recall(self, mid, req):
        degraded = []
        if int(req.get("depth") or 0) > 0:
            degraded.append("depth:capped_at_0")
        q, tx = _words(req.get("query") or ""), _words(req.get("text") or "")
        scored = []
        for r in self._select(mid, req):
            w, why, score = _words(text_of(r["content"])) | _words(r["attributes"]), [], 0.0
            if tx:
                if not tx <= w:
                    continue           # words are a match or they are not
                why.append("text")
                score = 1.0
            if q:
                overlap = len(q & w) / len(q)
                if overlap:
                    why.append("query")
                    score = max(score, overlap) if not tx else (1.0 + overlap) / 2
                elif not tx:
                    continue           # a question this record shares no word with
            if req.get("filters"):
                why.append("filters")
            if not q and not tx:
                score = 1.0            # fields alone: every record that matches, unranked
            scored.append({"record": r, "score": round(score, 4), "why": why})
        scored.sort(key=lambda x: (-x["score"], x["record"]["id"]))
        results = scored[: int(req.get("limit") or 8)]
        # a question whose best answer shares under half its words is one this memory cannot answer
        abstain = bool(q) and not any(x["score"] >= 0.5 for x in results)
        return {"results": results, "degraded": degraded, "abstain": abstain}

    async def prime(self, mid):
        text = self.primed.get(mid, "")
        return {"text": text, "tokens": len(text.split())}

    # ── queries: the "language" is a JSON filter with {param} placeholders ───────────────────────
    async def queries(self, mid):
        return sorted(self.named.get(mid, {}).values(), key=lambda q: q["name"])

    async def define_query(self, mid, q):
        if q.get("language") != "fixture-filter":
            raise MemoryError(422, "memory_invalid", "This provider's query language is `fixture-filter`.", "language")
        try:
            json.loads(q["body"])
        except (ValueError, KeyError, TypeError):
            raise MemoryError(422, "memory_invalid", "The query body is not a filter.", "body")
        self.named.setdefault(mid, {})[q["name"]] = q
        return q

    def _run(self, mid, body: str, params: dict) -> dict:
        for k, v in (params or {}).items():
            body = body.replace("{" + k + "}", json.dumps(v)[1:-1] if isinstance(v, str) else json.dumps(v))
        try:
            flt = json.loads(body)
        except ValueError:
            raise MemoryError(422, "memory_invalid", "The statement is not a filter.", "statement")
        rows = [r for r in self._current(mid) if self._match(r, flt)]
        return {"results": [{"record": r, "score": 1.0, "why": ["filters"]} for r in rows], "degraded": [], "abstain": False}

    async def run_query(self, mid, name, params):
        q = self.named.get(mid, {}).get(name)
        if not q:
            raise MemoryError(404, "memory_not_found", "No such query on this memory.", "name")
        missing = [k for k in (q.get("params") or {}).get("required", []) if k not in (params or {})]
        if missing:
            raise MemoryError(422, "memory_invalid", f"Missing parameter: {', '.join(missing)}.", "params")
        return self._run(mid, q["body"], params)

    async def free_query(self, mid, language, statement, params, write):
        if language != "fixture-filter":
            raise MemoryError(422, "memory_invalid", "This provider's query language is `fixture-filter`.", "language")
        if write:
            raise MemoryError(422, "memory_unsupported", "This memory's provider does not let a free query write.")
        return self._run(mid, statement, params)      # `mid` is the container: the statement cannot name another

    # ── an extension type with one operation ──────────────────────────────────────────────────
    async def types(self):
        return [{"type": "x.fixture.counter", "description": "A number that can be raised.",
                 "schema": {"type": "object", "properties": {"n": {"type": "integer"}}},
                 "text": "the counter's name and value",
                 "operations": [{"name": "increment", "description": "Add to the counter.",
                                 "input": {"type": "object", "properties": {"by": {"type": "integer"}}},
                                 "requires": "write"},
                                {"name": "peek", "description": "Read the counter.", "input": {"type": "object"},
                                 "requires": "read"}]}]

    async def operation_requires(self, mid, rid, name):
        head = self._head(mid, rid)
        if not head or head["type"] != "x.fixture.counter" or name not in ("increment", "peek"):
            raise MemoryError(404, "memory_record_not_found", "No such operation on this record.", "name")
        return "write" if name == "increment" else "read"

    async def operate(self, mid, rid, name, body, writer):
        head = self._head(mid, rid)
        if name == "peek":
            return {"n": int(head["attributes"].get("n") or 0)}
        row = await self.revise(mid, rid, {"attributes": {"n": int(head["attributes"].get("n") or 0) + int(body.get("by") or 1)}}, writer)
        return {"n": row["attributes"]["n"], "version": row["version"]}

    # ── consolidation: every unconsolidated episode becomes one fact derived from it ────────────
    async def consolidate(self, mid, budget, trigger):
        writer = {"kind": "consolidator", "id": self.id}
        limit = int((budget or {}).get("limit") or 0)
        run = {"id": "hcon_" + uuid.uuid4().hex, "object": "memory.consolidation", "memory_id": mid,
               "status": "running", "trigger": trigger, "started_at": int(time.time()), "finished_at": None,
               "read": {"episodes": 0, "through": None}, "changes": {"created": 0, "superseded": 0, "forgotten": 0},
               "usage": {"input_tokens": 0, "output_tokens": 0},
               "budget": {"limit": limit or None, "unit": "episodes", "exhausted": False},
               "written_by": writer, "error": "", "_made": [], "reverted": False}
        done = {x["record_id"] for r in self._rows(mid) if r["written_by"].get("kind") == "consolidator"
                and r["status"] == "active" for x in r["references"] if x.get("rel") == "derived_from"}
        for ep in [r for r in self._current(mid) if r["type"] == "episode" and r["id"] not in done]:
            if limit and run["read"]["episodes"] >= limit:
                run["budget"]["exhausted"] = True
                break
            made = self._append(mid, {"type": "fact", "content": ep["content"],
                                      "references": [{"rel": "derived_from", "memory_id": "", "record_id": ep["id"]}]}, writer)
            run["_made"].append(made["id"])
            run["read"]["episodes"] += 1
            run["read"]["through"] = ep["time"]["written_at"]
            run["changes"]["created"] += 1
        run["status"] = "stopped" if run["budget"]["exhausted"] else "completed"
        run["finished_at"] = int(time.time())
        self.runs.setdefault(mid, []).insert(0, run)
        return self._run_out(run)

    @staticmethod
    def _run_out(run):
        return {k: v for k, v in run.items() if not k.startswith("_")}

    async def consolidations(self, mid):
        return [self._run_out(r) for r in self.runs.get(mid, [])]

    async def consolidation(self, mid, run):
        r = next((x for x in self.runs.get(mid, []) if x["id"] == run), None)
        return self._run_out(r) if r else None

    async def consolidation_changes(self, mid, run):
        r = next((x for x in self.runs.get(mid, []) if x["id"] == run), None)
        if not r:
            raise MemoryError(404, "memory_not_found", "No such consolidation run.", "run")
        return [{"change": "created", "record": self._head(mid, rid)} for rid in r["_made"] if self._head(mid, rid)]

    async def revert_consolidation(self, mid, run, writer):
        r = next((x for x in self.runs.get(mid, []) if x["id"] == run), None)
        if not r:
            raise MemoryError(404, "memory_not_found", "No such consolidation run.", "run")
        if not r["reverted"]:
            for rid in r["_made"]:
                head = self._head(mid, rid)
                if head and head["status"] == "active":
                    await self.forget(mid, rid, writer)
            r["reverted"] = True
        return self._run_out(r)
