"""Revise, forget, erase and a memory's delete on Graphiti wait for the memory's background reading to finish.

Graphiti reads what a memory is given in the background, so each of these first asks our Graphiti server how much
it still has to read (GET /groups/{group}/pending) and waits, up to a
bound for the whole call, until nothing is. Still reading at the bound: 503, nothing changed, and asking again
finishes it. A count that can't be read is a 503, and so is a server that can't give one (404, built before the
count): neither is ever taken for "nothing to wait on". An erase says a record is erased only once it reads gone
after the readings. Driven against a fake server."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_graphiti as mg  # noqa: E402
import memory_plane as mp  # noqa: E402

run = asyncio.run
MID, U = "hmem_wait", "7c1d2e3f-1111-4222-8333-444455556666"
WRITER = {"kind": "member", "id": "ada@example.com"}
TEXT = "Quillon Freight renews its contract every March."


def _node() -> dict:
    return {"uuid": U, "name": TEXT, "summary": TEXT, "labels": ["Entity"], "group_id": MID,
            "created_at": "2026-11-16T08:00:00Z", "episodes": [],
            "attributes": {"hr_stated": "1", "hr_type": "fact", "hr_version": 1, "hr_written_at": "2026-11-16T08:00:00Z",
                           "hr_text": TEXT, "hr_attributes": "{}", "hr_refs": "[]", "hr_writer": json.dumps(WRITER)}}


def _engine(monkeypatch, pending, still_there: int = 0) -> list[tuple[str, str]]:
    """`pending`: what each GET /pending answers in turn (its last answer repeats): an int is the count, an
    httpx.Response is answered as it is. `still_there`: how many node deletes the node still reads present after."""
    calls: list[tuple[str, str]] = []
    answers = list(pending)
    st = {"node": _node(), "gone": False, "back": still_there}
    monkeypatch.setattr(mg, "SETTLE_S", 0.4, raising=False); monkeypatch.delenv("HR_GRAPHITI_SETTLE_S", raising=False)
    monkeypatch.setattr(mg, "SETTLE_NAP", 0.01, raising=False)

    def handle(req: httpx.Request) -> httpx.Response:
        path, m = req.url.path, req.method
        calls.append((m, path))
        if path == f"/groups/{MID}/pending":
            a = answers.pop(0) if len(answers) > 1 else answers[0]
            return a if isinstance(a, httpx.Response) else httpx.Response(200, json={"pending": a})
        if path == "/healthz":
            return httpx.Response(200, json={"ok": True, "keeps_stated_records": True})
        if path == f"/groups/{MID}/episodes" and m == "GET":
            return httpx.Response(200, json=[])
        if path == f"/groups/{MID}/nodes/{U}":
            if m == "DELETE":
                if st["back"] > 0:
                    st["back"] -= 1          # it still reads present after this delete
                else:
                    st["gone"] = True
                return httpx.Response(200, json={"deleted": U})
            if st["gone"]:
                return httpx.Response(404, json={"detail": "no such node"})
            if m == "PUT":
                b = json.loads(req.content)
                st["node"] = {**st["node"], "name": b.get("name"), "summary": b.get("summary"), "attributes": b.get("attributes")}
            return httpx.Response(200, json=st["node"])
        return httpx.Response(200, json={"ok": True, "deleted": True, "uuid": "ep-new"})

    monkeypatch.setattr(mg, "transport", httpx.MockTransport(handle))
    mg._KEEPS.clear()
    return calls


def _g() -> mg.Graphiti:
    return mg.Graphiti("http://graphiti.test", "k")


OPS = {
    "erase": lambda g: g.erase(MID, [mg.NODE + U]),
    "revise": lambda g: g.revise(MID, mg.NODE + U, {"content": [{"type": "text", "text": "It renews every April."}]}, WRITER),
    "forget": lambda g: g.forget(MID, mg.NODE + U, WRITER),
    "drop": lambda g: g.drop(MID),
}


def _changes(calls) -> list[tuple[str, str]]:
    return [(m, p) for m, p in calls if m in ("PUT", "POST", "DELETE")]


def _pending_reads(calls) -> int:
    return sum(1 for _, p in calls if p.endswith("/pending"))


def test_an_erase_waits_for_the_reading_then_deletes(monkeypatch):
    calls = _engine(monkeypatch, [2, 1, 0])
    out = run(OPS["erase"](_g()))
    assert out["erased"] == [mg.NODE + U]
    first_change = next(i for i, c in enumerate(calls) if c[0] in ("PUT", "POST", "DELETE"))
    reads_before = sum(1 for _, p in calls[:first_change] if p.endswith("/pending"))
    assert reads_before == 3                     # 2, 1, then 0: nothing was touched while it was being read


@pytest.mark.parametrize("op", list(OPS))
def test_still_reading_at_the_bound_is_503_and_nothing_changes(monkeypatch, op):
    calls = _engine(monkeypatch, [1])
    with pytest.raises(mp.MemoryError) as e:
        run(OPS[op](_g()))
    assert e.value.status == 503 and e.value.message == mg.BUSY
    assert _pending_reads(calls) > 1             # it waited, then gave up at the bound
    assert _changes(calls) == []


@pytest.mark.parametrize("op", list(OPS))
def test_a_server_without_the_count_is_refused_never_taken_for_none(monkeypatch, op):
    calls = _engine(monkeypatch, [httpx.Response(404, json={"detail": "Not Found"})])
    with pytest.raises(mp.MemoryError) as e:
        run(OPS[op](_g()))
    assert e.value.status == 503 and "Rebuild it with deploy/memories/up.sh" in e.value.message
    assert _changes(calls) == []


@pytest.mark.parametrize("answer", [
    httpx.Response(200, json={"pending": "many"}),
    httpx.Response(200, json={}),
    httpx.Response(200, json=[3]),
    httpx.Response(200, text="not json"),
])
@pytest.mark.parametrize("op", list(OPS))
def test_an_unreadable_count_is_refused(monkeypatch, op, answer):
    calls = _engine(monkeypatch, [answer])
    with pytest.raises(mp.MemoryError) as e:
        run(OPS[op](_g()))
    assert e.value.status == 503 and e.value.message == mg.BUSY
    assert _changes(calls) == []


def test_an_erase_is_said_only_once_the_record_reads_gone(monkeypatch):
    calls = _engine(monkeypatch, [0], still_there=1)
    out = run(OPS["erase"](_g()))
    assert out["erased"] == [mg.NODE + U]
    assert calls.count(("DELETE", f"/groups/{MID}/nodes/{U}")) == 2      # read present once, deleted again


def test_a_record_that_still_reads_present_is_not_said_erased(monkeypatch):
    _engine(monkeypatch, [0], still_there=5)
    with pytest.raises(mp.MemoryError) as e:
        run(OPS["erase"](_g()))
    assert e.value.status == 503 and e.value.code == "memory_cleanup_incomplete" and e.value.message == mg.ERASE_LEFT


def test_nothing_to_erase_asks_nothing(monkeypatch):
    calls = _engine(monkeypatch, [1])
    assert run(_g().erase(MID, [])) == {"erased": [], "unreachable": []}
    assert calls == []


# ── a write that changes records already kept waits before it writes, never after ───────────────────────────────────
class _Graph:
    """The plane's own store, for the memory node alone."""

    def __init__(self):
        self.props: dict[str, dict] = {}

    async def get(self, vid, label=None):
        return self.props.get(vid)

    async def upsert(self, label, vid, props, raise_on_fail=False):
        self.props.setdefault(vid, {}).update(props)
        return True


class _Kept(mp.Provider):
    """A provider holding one fact about acct_1 (region = east). `busy`: it is still reading in the background;
    `write_fails`: the write itself fails; `refuse`: how many changes to records already kept it refuses with a 503."""
    id = "stub"

    def __init__(self, busy: bool = False, write_fails: bool = False, refuse: int = 0, gone: bool = False,
                 refuse_all: bool = False, closed_meanwhile: bool = False):
        self.busy, self.write_fails, self.refuse, self.gone, self.calls = busy, write_fails, refuse, gone, []
        self.refuse_all, self.closed_meanwhile = refuse_all, closed_meanwhile
        self.refs: dict[str, list] = {"rec_old": []}

    def capabilities(self) -> dict:
        return {"holds": True}

    async def ready_to_change(self, mid):
        self.calls.append("ready")
        if self.busy:
            raise mp.MemoryError(503, "memory_unavailable", mg.BUSY)

    async def list(self, mid, req):
        return {"records": [{"id": "rec_old", "type": "fact", "attributes": {"holds": "one", "predicate": "region", "value": "east"},
                             "references": [{"rel": "subject", "record_id": "acct_1"}],
                             "time": {"valid_from": "2026-01-01T00:00:00Z"}}]}

    async def remember(self, mid, record, writer):
        self.calls.append("remember")
        if self.write_fails:
            raise mp.MemoryError(502, "memory_unavailable", "Graphiti did not answer: ReadTimeout")
        return {"id": "rec_new", **record}

    async def revise(self, mid, rid, patch, writer):
        self.calls.append(f"revise {rid}")
        if self.gone and rid == "rec_old":
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        if self.refuse_all or (self.refuse > 0 and rid == "rec_old"):
            self.refuse = max(0, self.refuse - 1)
            raise mp.MemoryError(503, "memory_unavailable", mg.BUSY)
        if "references" in patch:
            self.refs[rid] = patch["references"]
        return {"id": rid, "version": 2}

    async def get(self, mid, rid, as_of=None):
        self.calls.append(f"get {rid}")
        if self.gone and rid == "rec_old":
            return None
        t = {"valid_to": "2026-05-01T00:00:00Z"} if self.closed_meanwhile and rid == "rec_old" else {}
        return {"id": rid, "type": "fact", "status": "active", "attributes": {}, "references": list(self.refs.get(rid, [])), "time": t}


FACT = {"type": "fact", "content": [{"type": "text", "text": "Acct 1 is in the west region."}],
        "attributes": {"holds": "one", "predicate": "region", "value": "west"},
        "references": [{"rel": "subject", "memory_id": "", "record_id": "acct_1"}], "time": {"valid_from": "2026-06-01T00:00:00Z"}}
DISPUTES = {"type": "fact", "content": [{"type": "text", "text": "Acct 1 never moved."}],
            "references": [{"rel": "contradicts", "memory_id": "", "record_id": "rec_old"}]}


@pytest.fixture
def graph(monkeypatch):
    g = _Graph()
    monkeypatch.setattr(mp, "GRAPH", g)
    return g


def _steps(p) -> list[str]:
    return [c for c in p.calls if not c.startswith("get ")]


def _owed(graph) -> list[dict]:
    return json.loads((graph.props.get("hmem_x") or {}).get(mp.OWED) or "[]")


def test_a_fact_that_closes_an_older_value_waits_before_it_is_written(graph):
    p = _Kept()
    out = run(mp.remember(p, "hmem_x", FACT, WRITER))
    assert out["closed"] == ["rec_old"] and "owed" not in out
    assert _steps(p) == ["ready", "remember", "revise rec_old"]     # wait, write, then close: never close first


def test_a_memory_still_reading_refuses_the_fact_with_nothing_written(graph):
    p = _Kept(busy=True)
    with pytest.raises(mp.MemoryError) as e:
        run(mp.remember(p, "hmem_x", FACT, WRITER))
    assert e.value.status == 503 and _steps(p) == ["ready"]        # refused before the write, never after it


def test_a_write_that_fails_leaves_the_older_value_open(graph):
    p = _Kept(write_fails=True)
    with pytest.raises(mp.MemoryError):
        run(mp.remember(p, "hmem_x", FACT, WRITER))
    assert _steps(p) == ["ready", "remember"] and _owed(graph) == []   # the older value stays open: it has no successor


def test_a_close_that_cant_be_made_yet_is_owed_and_the_write_stands(graph):
    p = _Kept(refuse=1)
    out = run(mp.remember(p, "hmem_x", FACT, WRITER))
    assert out["id"] == "rec_new" and out["closed"] == [] and out["owed"] == ["rec_old"]
    assert [(o["op"], o["rid"], o["valid_to"]) for o in _owed(graph)] == [("close", "rec_old", "2026-06-01T00:00:00Z")]


def test_what_is_owed_is_made_at_the_memorys_next_change(graph):
    p = _Kept(refuse=1)
    run(mp.remember(p, "hmem_x", FACT, WRITER))
    p.calls.clear()
    run(mp.revise(p, "hmem_x", "rec_other", {"title": "x"}, WRITER))
    assert _steps(p)[:2] == ["revise rec_old", "revise rec_other"] and _owed(graph) == []


def test_what_still_cant_be_made_stays_owed(graph):
    p = _Kept(refuse=2)
    run(mp.remember(p, "hmem_x", FACT, WRITER))
    with pytest.raises(mp.MemoryError):
        run(mp.forget(p, "hmem_x", "rec_old", WRITER))
    assert [o["rid"] for o in _owed(graph)] == ["rec_old"]


def test_a_change_owed_to_a_record_since_gone_is_owed_no_longer(graph):
    p = _Kept(refuse=1)
    run(mp.remember(p, "hmem_x", FACT, WRITER))
    p.gone = True
    run(mp.revise(p, "hmem_x", "rec_other", {"title": "x"}, WRITER))
    assert _owed(graph) == []


def test_a_contradiction_that_cant_be_kept_on_the_other_record_yet_is_owed_then_kept(graph):
    p = _Kept(refuse=1)
    out = run(mp.remember(p, "hmem_x", DISPUTES, WRITER))
    assert out["owed"] == ["rec_old"] and [(o["op"], o["with"]) for o in _owed(graph)] == [("contradicts", "rec_new")]
    run(mp.revise(p, "hmem_x", "rec_other", {"title": "x"}, WRITER))
    assert p.refs["rec_old"] == [{"rel": "contradicts", "memory_id": "", "record_id": "rec_new"}] and _owed(graph) == []


def test_a_plain_fact_never_waits(graph):
    p = _Kept(busy=True)
    plain = {"type": "fact", "content": [{"type": "text", "text": "Acct 1 likes email."}]}
    assert run(mp.remember(p, "hmem_x", plain, WRITER))["id"] == "rec_new" and _steps(p) == ["remember"]


def test_a_memory_that_owes_as_much_as_it_may_refuses_another_with_nothing_written(graph):
    graph.props["hmem_x"] = {mp.OWED: json.dumps([{"op": "close", "mid": "hmem_x", "rid": f"rec_{i}", "valid_to": "2026-06-01T00:00:00Z"}
                                                  for i in range(mp.OWED_CAP)])}
    p = _Kept(refuse_all=True)
    with pytest.raises(mp.MemoryError) as e:
        run(mp.remember(p, "hmem_x", FACT, WRITER))
    assert e.value.status == 503 and e.value.message == mp.OWED_FULL
    assert "remember" not in p.calls and len(_owed(graph)) == mp.OWED_CAP      # nothing written, nothing owed dropped


def test_an_owed_change_reaches_only_its_own_memorys_records(graph):
    graph.props["hmem_x"] = {mp.OWED: json.dumps([{"op": "close", "mid": "hmem_other", "rid": "rec_old", "valid_to": "2026-06-01T00:00:00Z"}])}
    p = _Kept()
    run(mp.revise(p, "hmem_x", "rec_other", {"title": "x"}, WRITER))
    assert "revise rec_old" not in p.calls and _owed(graph) == []


def test_a_value_closed_meanwhile_keeps_its_own_end(graph):
    p = _Kept(refuse=1)
    run(mp.remember(p, "hmem_x", FACT, WRITER))
    p.closed_meanwhile = True
    p.calls.clear()
    run(mp.revise(p, "hmem_x", "rec_other", {"title": "x"}, WRITER))
    assert "revise rec_old" not in p.calls and _owed(graph) == []


def test_what_is_owed_is_logged_as_counts_only(graph, capsys):
    p = _Kept(refuse=1)
    run(mp.remember(p, "hmem_x", FACT, WRITER))
    run(mp.revise(p, "hmem_x", "rec_other", {"title": "x"}, WRITER))
    out = capsys.readouterr().out
    assert "[memory] owed: 1 added, 1 on the memory" in out and "[memory] owed: 1 paid, 0 dropped, 0 still owed" in out
    assert "rec_" not in out and "hmem_" not in out and "Acct" not in out


def test_the_bound_can_be_set_for_a_slower_server(monkeypatch):
    monkeypatch.delenv("HR_GRAPHITI_SETTLE_S", raising=False)
    assert mg._settle_s() == mg.SETTLE_S == 120.0
    monkeypatch.setenv("HR_GRAPHITI_SETTLE_S", "300")
    assert mg._settle_s() == 300.0
    monkeypatch.setenv("HR_GRAPHITI_SETTLE_S", "soon")
    assert mg._settle_s() == 120.0


def test_changes_owed_at_once_on_one_memory_are_all_kept(monkeypatch):
    class Slow(_Graph):
        async def get(self, vid, label=None):
            v = await super().get(vid, label)
            await asyncio.sleep(0)               # another request runs between the read and the write
            return {**v} if v else v
    g = Slow()
    monkeypatch.setattr(mp, "GRAPH", g)

    async def owe_all():
        await asyncio.gather(*(mp._owe("hmem_x", {"op": "close", "mid": "hmem_x", "rid": f"rec_{i}"}) for i in range(8)))
    run(owe_all())
    assert sorted(o["rid"] for o in _owed(g)) == sorted(f"rec_{i}" for i in range(8))
