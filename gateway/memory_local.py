"""The agent tools' seam bound to this gateway's own memory plane: the agent is the principal
`member:<harness id>`, every call goes through memory_plane's one access check, and every answer
is presented to that reader. `entries` is what app.py worked out the agent holds (its grants, its
default, the memory a task named).

In a task for one person of an agent that keeps each person apart (`person`), the reader is the agent AND
that person's principal (memory_plane.end_user_node), and the writer is that principal alone. So the task
reads the agent's memory and its own person's, never another person's, and writes only its own person's:
one person's task can't plant a "fact" where the next person's recall would read it."""
from __future__ import annotations

import asyncio

import memory_plane as mp
from memory_tools import Refused


PERSON_NAME = "This person's memory"


class Local:
    """`counts`: each memory's record count in `entries`, which asks its engine once per memory. Only `memory_list`
    shows it. `around`: a recall names the memory's parent and children, as the recall tool shows them. A turn's
    start asks for neither (app.py's _memories_turn_start), and a tool list doesn't ask for counts."""

    def __init__(self, org: str, hid: str, entries: list[dict], person: dict | None = None, *,
                 counts: bool = True, around: bool = True, session: str = ""):
        self.org, self.hid, self._entries, self.person = org, hid, entries, person or None
        self.pr = [f"member:{hid}"] + ([self.person["principal"]] if self.person else [])
        self.wpr = [self.person["principal"]] if self.person else self.pr
        # what the agent keeps names the task it was kept in (`session`), as what a finished turn sends does: a later
        # turn of the same task leaves it out of what it recalls at its start (memory_tools.same_session)
        self.writer = {**mp.writer_of(hid, agent=True), **({"session_id": session} if session else {})}
        self.counts, self.around = counts, around
        # what this agent kept with memory_remember through this seam, each {"id", "memory_id"}: a turn's record links them
        self.kept: list[dict] = []
        self._once: dict[tuple, tuple[object, asyncio.Future]] = {}

    async def _shared(self, key: tuple, make):
        """One answer per seam to what is asked more than once, at the same time or one after the other: a turn's
        start asks for its entries from the recall and from the Memory section together, and for each memory's
        standing records before the section is written. The first ask runs and every ask awaits it. A seam lives
        for one turn's start or one tool call, so nothing kept here outlives what it answers. Shielded: one asker
        giving up (the recall's time running out) never takes the answer from another."""
        loop = asyncio.get_running_loop()
        hit = self._once.get(key)
        if hit is None or hit[0] is not loop:
            fut = asyncio.ensure_future(make())
            fut.add_done_callback(lambda f: f.cancelled() or f.exception())    # read here when no asker is left
            hit = self._once[key] = (loop, fut)
        return await asyncio.shield(hit[1])

    async def _do(self, coro):
        try:
            return await coro
        except mp.MemoryError as e:
            raise Refused(e.code, e.message) from None

    async def entries(self) -> list[dict]:
        return list(await self._shared(("entries",), self._entries_now))

    async def _entries_now(self) -> list[dict]:
        async def one(e: dict) -> dict | None:
            m = await mp._load(self.org, str(e.get("memory_id") or ""))
            privs = await mp.effective(self.org, m, self.pr) if m else []
            if not (m and "read" in privs):
                return None
            brief = mp._brief(await mp.out(self.org, m, self.pr, privs, count=self.counts))
            if self.person and str(m["id"]) == self.person["node"]:
                brief = {**brief, "name": PERSON_NAME}        # who it is, the agent isn't told
            return {"memory": brief, "write": e.get("access") == "write", "default": bool(e.get("default"))}
        return [x for x in await asyncio.gather(*(one(e) for e in self._entries)) if x]

    async def offers(self) -> dict:
        return dict(await self._shared(("offers",), self._offers_now))

    async def _offers_now(self) -> dict:
        """From the engines of the memories this agent holds: a memory below one of them uses the
        same engine, so these are all it can meet."""
        caps = []
        for m in await asyncio.gather(*(mp._load(self.org, str(e.get("memory_id") or "")) for e in self._entries)):
            p = mp.PROVIDERS.get(str((m or {}).get("provider") or ""))
            if p is not None and p.capabilities() not in caps:
                caps.append(p.capabilities())
        langs: list[str] = []
        for c in caps:
            langs += [x for x in ((c.get("queries") or {}).get("free") or {}).get("languages", []) if x not in langs]
        return {"files": False,          # see keep_file
                "queries": any((c.get("queries") or {}).get("named") for c in caps),
                "operations": any(c.get("types") for c in caps), "languages": langs,
                "standing": any(c.get("prime") for c in caps)}

    async def keep_file(self, mid, file, record):
        # This gateway does not yet turn a media item or a workspace file an agent names into a
        # file of its own store, so the argument is not offered here (offers) and a call that
        # carries it anyway is refused in words.
        raise Refused("memory_unsupported", "A file cannot be kept in memory here. Keep what it says, in words.")

    async def memory(self, mid):
        async def go():
            m, privs = await mp.need(self.org, mid, self.pr, "read")
            prov = await mp.provider_of(m)
            return {"memory": mp._brief(await mp.out(self.org, m, self.pr, privs)), **await mp.neighbours(self.org, m, self.pr),
                    "queries": [{k: q.get(k) for k in ("name", "description", "params")} for q in await prov.queries(mid)]}
        return await self._do(go())

    async def recall(self, mid, body):
        async def go():
            m, _ = await mp.need(self.org, mid, self.pr, "read")
            reach, cut = await mp.reach_below(self.org, m, self.pr, body.get("depth"))
            if self.person and mid == self.person["node"]:
                # a person's memory is read with the agent's own: what it knows for everyone, and about them
                shared = await mp._load(self.org, self.person["shared"])
                if shared and "read" in await mp.effective(self.org, shared, self.pr) and \
                        str(shared["id"]) not in {str(x["id"]) for x in reach}:
                    reach.append(shared)
            names = {str(x["id"]): x.get("name") or "" for x in reach}
            if self.person:
                names[self.person["node"]] = PERSON_NAME
            await mp.used(self.org, m)
            res = await mp.recall(self.org, reach, {k: body.get(k) for k in ("query", "text", "filters", "types", "limit")})
            if cut:
                res["degraded"].append(f"subtree:capped_at_{mp.RECALL_MAX_MEMORIES}_memories")
            seen: dict = {}
            results = []
            for x in res.get("results") or []:
                at = str(x.get("memory_id") or mid)
                results.append({"record": await mp.present(self.org, at, x["record"], self.pr, seen),
                                "memory": {"id": at, "name": names.get(at, "")}, "score": x.get("score"), "why": x.get("why")})
            return {"results": results, **(await mp.neighbours(self.org, m, self.pr) if self.around else {}),
                    "degraded": res.get("degraded") or [], "abstain": bool(res.get("abstain"))}
        return await self._do(go())

    async def graph(self, mid, body):
        async def go():
            m, _ = await mp.need(self.org, mid, self.pr, "read")
            return await mp.graph(self.org, m, self.pr, around=str(body.get("around") or ""), hops=int(body.get("hops", 1)),
                                  types=body.get("types") or None, limit=body.get("limit") or 200)
        return await self._do(go())

    async def _prov(self, mid, privilege):
        m, privs = await mp.need(self.org, mid, self.wpr if privilege == "write" else self.pr, privilege)
        try:
            return await mp.provider_of(m), privs
        except mp.MemoryError as e:
            await mp.mark(self.org, mid, e.message)      # its engine isn't connected or reached: said on the memory
            raise

    async def _wrote(self, mid, coro):
        """A write through the agent's tools, its outcome kept on the memory (memory_plane.mark)."""
        try:
            out = await coro
        except mp.MemoryError as e:
            if e.code not in ("memory_not_found", "memory_forbidden", "memory_invalid", "memory_record_not_found"):
                await mp.mark(self.org, mid, e.message)
            raise
        await mp.mark(self.org, mid)
        m = await mp._load(self.org, mid)
        if m:
            await mp.used(self.org, m)
        return out

    async def get(self, mid, rid):
        async def go():
            prov, _ = await self._prov(mid, "read")
            rec = await prov.get(mid, rid)
            return await mp.present(self.org, mid, rec, self.pr) if rec else None
        return await self._do(go())

    async def history(self, mid, rid):
        async def go():
            prov, _ = await self._prov(mid, "read")
            return [await mp.present(self.org, mid, h, self.pr) for h in await prov.history(mid, rid)]
        return await self._do(go())

    async def remember(self, mid, record):
        async def go():
            prov, _ = await self._prov(mid, "write")
            made = await self._wrote(mid, mp.remember(prov, mid, mp._record_in(record), self.writer))
            if made.get("id"):
                self.kept.append({"id": str(made["id"]), "memory_id": str(mid)})
            return {**await mp.present(self.org, mid, made, self.pr), **{k: made[k] for k in ("closed", "conflicts") if k in made}}
        return await self._do(go())

    async def revise(self, mid, rid, patch):
        async def go():
            prov, _ = await self._prov(mid, "write")
            patch2 = dict(patch)
            if "title" in patch2:
                patch2["title"] = mp.title_of(patch2["title"])
            if "content" in patch2:
                patch2["content"] = mp.parts_of(patch2["content"])
            if "title" in patch2:
                patch2["title"] = mp.clean_text(patch2["title"])
            if "content" in patch2:
                patch2["content"] = mp._clean_parts(patch2["content"])
            if isinstance(patch2.get("attributes"), dict):
                patch2["attributes"] = {k: mp.clean_text(v) if isinstance(v, str) else v for k, v in patch2["attributes"].items()}
            return await mp.present(self.org, mid, await self._wrote(mid, prov.revise(mid, rid, patch2, self.writer)), self.pr)
        return await self._do(go())

    async def forget(self, mid, rid):
        async def go():
            prov, _ = await self._prov(mid, "write")
            return await mp.forget(prov, mid, rid, self.writer)
        return await self._do(go())

    async def run_query(self, mid, name, params):
        async def go():
            prov, privs = await self._prov(mid, "read")
            q = next((x for x in await prov.queries(mid) if x["name"] == name), None)
            if not q:
                raise Refused("memory_invalid", "No such query on this memory.")
            if q.get("requires", "read") == "write":
                _, privs = await self._prov(mid, "write")
            if q.get("requires", "read") not in privs:
                raise Refused("memory_forbidden", f"That query needs `{q['requires']}` on the memory.")
            res = await prov.run_query(mid, name, params)
            return {"results": [{"record": await mp.present(self.org, mid, x["record"], self.pr)} for x in res.get("results") or []]}
        return await self._do(go())

    async def free_query(self, mid, language, statement, params):
        async def go():
            prov, _ = await self._prov(mid, "read")
            res = await prov.free_query(mid, language, statement, params, False)
            if "results" in res:
                return {"results": [{"record": await mp.present(self.org, mid, x["record"], self.pr)} for x in res["results"]]}
            return {"rows": res.get("rows") or []}
        return await self._do(go())

    async def operate(self, mid, rid, name, body):
        async def go():
            prov, privs = await self._prov(mid, "read")
            needs = await prov.operation_requires(mid, rid, name)
            if needs == "write":
                _, privs = await self._prov(mid, "write")
            if needs not in privs or (needs == "write" and not any(e.get("access") == "write" for e in self._entries)):
                raise Refused("memory_forbidden", f"That operation needs `{needs}` on the memory.")
            return await prov.operate(mid, rid, name, body, self.writer)
        return await self._do(go())

    async def prime(self, mid, budget):
        async def go():
            m, _ = await mp.need(self.org, mid, self.pr, "read")
            got = await mp.prime(self.org, [m], budget)
            return {**got, "records": [await mp.present(self.org, mid, r, self.pr) for r in got["records"]]}
        return await self._shared(("prime", str(mid), int(budget)), lambda: self._do(go()))
