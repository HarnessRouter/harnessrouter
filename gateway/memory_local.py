"""The agent tools' seam bound to this gateway's own memory plane: the agent is the principal
`member:<harness id>`, every call goes through memory_plane's one access check, and every answer
is presented to that reader. `entries` is what app.py worked out the agent holds (its grants, its
default, the memory a task named)."""
from __future__ import annotations

import memory_plane as mp
from memory_tools import Refused


class Local:
    def __init__(self, org: str, hid: str, entries: list[dict]):
        self.org, self.hid, self._entries = org, hid, entries
        self.pr = [f"member:{hid}"]
        self.writer = mp.writer_of(hid, agent=True)

    async def _do(self, coro):
        try:
            return await coro
        except mp.MemoryError as e:
            raise Refused(e.code, e.message) from None

    async def entries(self) -> list[dict]:
        out = []
        for e in self._entries:
            m = await mp._load(self.org, str(e.get("memory_id") or ""))
            privs = await mp.effective(self.org, m, self.pr) if m else []
            if m and "read" in privs:
                out.append({"memory": mp._brief(await mp.out(self.org, m, self.pr, privs)),
                            "write": e.get("access") == "write", "default": bool(e.get("default"))})
        return out

    async def languages(self) -> list[str]:
        out: list[str] = []
        for p in mp.PROVIDERS.values():
            out += [x for x in ((p.capabilities().get("queries") or {}).get("free") or {}).get("languages", []) if x not in out]
        return out

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
            names = {str(x["id"]): x.get("name") or "" for x in reach}
            res = await mp.recall(self.org, reach, {k: body.get(k) for k in ("query", "text", "filters", "types", "limit")})
            if cut:
                res["degraded"].append(f"subtree:capped_at_{mp.RECALL_MAX_MEMORIES}_memories")
            seen: dict = {}
            results = []
            for x in res.get("results") or []:
                at = str(x.get("memory_id") or mid)
                results.append({"record": await mp.present(self.org, at, x["record"], self.pr, seen),
                                "memory": {"id": at, "name": names.get(at, "")}, "score": x.get("score"), "why": x.get("why")})
            return {"results": results, **await mp.neighbours(self.org, m, self.pr),
                    "degraded": res.get("degraded") or [], "abstain": bool(res.get("abstain"))}
        return await self._do(go())

    async def graph(self, mid, body):
        async def go():
            m, _ = await mp.need(self.org, mid, self.pr, "read")
            return await mp.graph(self.org, m, self.pr, around=str(body.get("around") or ""), hops=int(body.get("hops", 1)),
                                  types=body.get("types") or None, limit=body.get("limit") or 200)
        return await self._do(go())

    async def _prov(self, mid, privilege):
        m, privs = await mp.need(self.org, mid, self.pr, privilege)
        return await mp.provider_of(m), privs

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
            return await mp.present(self.org, mid, await prov.remember(mid, mp._record_in(record), self.writer), self.pr)
        return await self._do(go())

    async def revise(self, mid, rid, patch):
        async def go():
            prov, _ = await self._prov(mid, "write")
            patch2 = dict(patch)
            if "title" in patch2:
                patch2["title"] = mp.title_of(patch2["title"])
            if "content" in patch2:
                patch2["content"] = mp.parts_of(patch2["content"])
            return await mp.present(self.org, mid, await prov.revise(mid, rid, patch2, self.writer), self.pr)
        return await self._do(go())

    async def forget(self, mid, rid):
        async def go():
            prov, _ = await self._prov(mid, "write")
            return await prov.forget(mid, rid, self.writer)
        return await self._do(go())

    async def run_query(self, mid, name, params):
        async def go():
            prov, privs = await self._prov(mid, "read")
            q = next((x for x in await prov.queries(mid) if x["name"] == name), None)
            if not q:
                raise Refused("memory_invalid", "No such query on this memory.")
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
            if needs not in privs or (needs == "write" and not any(e.get("access") == "write" for e in self._entries)):
                raise Refused("memory_forbidden", f"That operation needs `{needs}` on the memory.")
            return await prov.operate(mid, rid, name, body, self.writer)
        return await self._do(go())

    async def prime(self, mid):
        async def go():
            m = await mp._load(self.org, mid)
            return await (await mp.provider_of(m)).prime(mid) if m else {"text": "", "tokens": 0}
        return await self._do(go())
