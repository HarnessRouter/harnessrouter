"""A produced file too large to attach is said in the turn's answer, never dropped in silence, and never
read into the gateway.

_collect_produced skipped a file over RESP_MAX_FILE_BYTES with no card and no word in the answer, while
the file sat in the task's files (hosted, 2026-10-19: two turns, nine images of 25.5 to 49.1 MB). Each
was also read whole into the gateway before it was measured. The answer now ends with a plain sentence
naming each one, its size and, only when the turn's save landed and the files listing shows it, where it
is; and its size is learned before any byte of it is read.

These run the real fetch (_sandbox_file) against a stand-in runner, so "never read" is observed on the
wire: the runner's listing size means the file is never asked for; a stated length over the cap means
its body is never read; with no length, the read stops one chunk past the cap.
"""
import asyncio
import io
import os
import pathlib
import sys
import tarfile

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

MB = 1024 * 1024
CAP = 1000


class _Body(httpx.AsyncByteStream):
    """A file's body that records how many of its chunks were read."""
    def __init__(self, data: bytes, chunk: int = 100):
        self.chunks = [data[i:i + chunk] for i in range(0, len(data), chunk)]
        self.read = 0

    async def __aiter__(self):
        for c in self.chunks:
            self.read += 1
            yield c

    async def aclose(self):
        pass


class _Runner:
    """A stand-in runner: /produced lists the files (with sizes when `sized`), /file serves each one
    with or without a stated length, and every request and body read is recorded."""
    def __init__(self, files: dict[str, bytes], *, sized: bool, stated: bool = True):
        self.files, self.sized, self.stated = files, sized, stated
        self.asked: list[str] = []
        self.bodies: dict[str, _Body] = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/produced":
            return httpx.Response(200, json={"files": [
                {"path": p, "mtime": i, **({"size": len(d)} if self.sized else {})}
                for i, (p, d) in enumerate(self.files.items())]})
        if req.url.path == "/file":
            path = req.url.params["path"]
            self.asked.append(path)
            body = self.bodies[path] = _Body(self.files[path])
            headers = {"content-type": "image/png"}
            if self.stated:
                headers["content-length"] = str(len(self.files[path]))
            return httpx.Response(200, headers=headers, stream=body)
        return httpx.Response(200, json={})


def _wire(monkeypatch, runner: _Runner, cap: int = CAP):
    client = httpx.AsyncClient(transport=httpx.MockTransport(runner))
    stored: dict[str, bytes] = {}

    async def blob_put(fid, data, kb=None):
        stored[fid] = data
        return True
    monkeypatch.setattr(A, "_client", lambda: client)
    monkeypatch.setattr(A, "_pool_headers", lambda: {})
    monkeypatch.setattr(A, "POOL_ENDPOINT", "http://runner")
    monkeypatch.setattr(A, "_blob_put", blob_put)
    monkeypatch.setattr(A, "RESP_MAX_FILE_BYTES", cap)
    return stored


def _collect(monkeypatch, capsys, runner: _Runner):
    stored = _wire(monkeypatch, runner)
    out = asyncio.run(A._collect_produced("hsess_big"))
    logged = capsys.readouterr().out.count("file_too_big")
    return out, stored, logged


_FILES = {"small.png": b"s" * 40, "out/hero.png": b"h" * (CAP * 3)}


def test_the_cap_is_64_mib_by_default():
    assert int(os.environ.get("HARNESS_RESP_MAX_FILE_BYTES", 64 * MB)) == A.RESP_MAX_FILE_BYTES == 64 * MB


def test_a_file_the_listing_says_is_over_the_cap_is_never_asked_for(monkeypatch, capsys):
    runner = _Runner(dict(_FILES), sized=True)
    out, stored, logged = _collect(monkeypatch, capsys, runner)
    assert runner.asked == ["small.png"]                   # hero.png never requested
    assert logged == 1                                     # still logged
    assert [f for f in out if f.get("too_large")] == [{"filename": "out/hero.png", "bytes": CAP * 3, "too_large": True}]
    assert [f["filename"] for f in out if not f.get("too_large")] == ["small.png"]
    assert not any(v == _FILES["out/hero.png"] for v in stored.values())


def test_a_stated_length_over_the_cap_means_the_body_is_never_read(monkeypatch, capsys):
    runner = _Runner(dict(_FILES), sized=False)            # a runner from before the listing's sizes
    out, stored, logged = _collect(monkeypatch, capsys, runner)
    assert runner.bodies["out/hero.png"].read == 0         # asked, its length read, not one byte of it
    assert runner.bodies["small.png"].read == 1
    assert [f for f in out if f.get("too_large")] == [{"filename": "out/hero.png", "bytes": CAP * 3, "too_large": True}]
    assert logged == 1 and not any(v == _FILES["out/hero.png"] for v in stored.values())


def test_with_no_stated_length_the_read_stops_one_chunk_past_the_cap(monkeypatch, capsys):
    runner = _Runner(dict(_FILES), sized=False, stated=False)
    out, stored, logged = _collect(monkeypatch, capsys, runner)
    hero = runner.bodies["out/hero.png"]
    assert hero.read == CAP // 100 + 1 < len(hero.chunks)  # 11 of 30 chunks: the cap plus one chunk
    assert [f for f in out if f.get("too_large")] == [{"filename": "out/hero.png", "bytes": None, "too_large": True}]
    assert logged == 1
    small = [f for f in out if not f.get("too_large")]
    assert [f["bytes"] for f in small] == [40] and stored[f"containers/hsess_big/{small[0]['file_id']}"] == _FILES["small.png"]
    big = dict(next(f for f in out if f.get("too_large")), saved=True)
    monkeypatch.setattr(A, "RESP_MAX_FILE_BYTES", 64 * MB)    # a size never guessed: "over" the cap
    assert A._too_large_note([big]) == "out/hero.png is too large to attach here (over 64 MB); it's saved in the task's files."


def test_a_file_under_the_cap_is_read_as_before(monkeypatch, capsys):
    runner = _Runner({"a.png": b"a" * CAP}, sized=True)    # exactly the cap is under it
    out, stored, logged = _collect(monkeypatch, capsys, runner)
    assert logged == 0 and runner.asked == ["a.png"] and out[0]["bytes"] == CAP
    assert stored[f"containers/hsess_big/{out[0]['file_id']}"] == b"a" * CAP


def test_the_file_over_the_cap_is_listed_in_the_task_s_files_and_downloads(monkeypatch):
    """What the answer's "saved in the task's files" promises: the files listing (read from the
    turn's save) names it, and its id downloads the whole file."""
    data = _FILES["out/hero.png"]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, body in (("./out/hero.png", data), ("./small.png", b"s" * 40)):
            ti = tarfile.TarInfo(name)
            ti.size = len(body)
            tf.addfile(ti, io.BytesIO(body))
    raw = buf.getvalue()

    async def wtar(sid):
        return tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")

    async def owned(request, sid):
        return "org.t", {"tenant": "org.t"}

    async def no_captures(sid):
        return {}
    monkeypatch.setattr(A, "_workspace_tar", wtar)
    monkeypatch.setattr(A, "_owned_session", owned)
    monkeypatch.setattr(A, "_cfile_by_name", no_captures)
    monkeypatch.setattr(A, "_WS_FILES_CACHE", {})
    listing = asyncio.run(A.session_workspace_files("hsess_big", None))
    hero = next(f for f in listing["files"] if f["path"] == "out/hero.png")
    assert hero["bytes"] == len(data)
    resp = asyncio.run(A.container_file_content("hsess_big", hero["file_id"], None))
    assert resp.body == data and 'filename="hero.png"' in resp.headers["content-disposition"]


def _answer(files, text="Here are your images."):
    tr = A._RespTranslator("resp_t", "m", None, True, 0.0, sid="hsess_big")
    tr._handle("text", text)
    tr.complete("completed", files)
    return A._output_to_turn_fields(tr.output), tr


_CARD = {"container_id": "hsess_big", "file_id": "cfile_1", "filename": "small.png", "bytes": 4}


def test_the_answer_says_where_a_saved_file_is_and_the_attached_one_keeps_its_card():
    big = {"filename": "out/hero.png", "bytes": int(46.1 * MB), "too_large": True, "saved": True}
    (asst, _tools, cards), _tr = _answer([_CARD, big])
    assert asst.endswith("out/hero.png is too large to attach here (46.1 MB); it's saved in the task's files.")
    assert asst.startswith("Here are your images.")
    assert [c["filename"] for c in cards] == ["small.png"]


def test_several_files_are_named_in_one_sentence():
    big = [{"filename": f"p{i}.png", "bytes": n * MB, "too_large": True, "saved": True} for i, n in ((1, 40), (2, 49))]
    (asst, _t, cards), _tr = _answer(big)
    assert asst.endswith("These files are too large to attach here; they're saved in the task's files: "
                         "p1.png (40.0 MB), p2.png (49.0 MB).")
    assert cards == []


def test_a_file_whose_save_did_not_land_is_not_said_to_be_saved():
    big = {"filename": "hero.png", "bytes": 30 * MB, "too_large": True, "saved": False}
    (asst, _t, _c), _tr = _answer([big])
    assert asst.endswith("hero.png is too large to attach here (30.0 MB).")
    assert "saved" not in asst


def test_saved_only_when_the_checkpoint_landed_and_the_listing_shows_the_path():
    files = [{"filename": "hero.png", "too_large": True}, {"filename": "node_modules/x.bin", "too_large": True},
             {"container_id": "s", "file_id": "cfile_1", "filename": "a.png"}]
    A._too_large_saved(files, {"checkpointed": True})
    assert [f.get("saved") for f in files] == [True, False, None]
    A._too_large_saved(files, {"checkpointed": False})
    assert [f.get("saved") for f in files] == [False, False, None]
    A._too_large_saved(files, {})                          # a save skipped (stale lease, failed restore)
    assert files[0]["saved"] is False


def test_the_note_streams_as_text_and_is_kept_for_the_record():
    big = {"filename": "hero.png", "bytes": 30 * MB, "too_large": True, "saved": True}
    tr = A._RespTranslator("resp_t", "m", None, True, 0.0, sid="hsess_big")
    tr._handle("text", "Done.")
    evs = tr.complete("completed", [big])
    deltas = "".join(e.get("delta", "") for e in evs if e["type"] == "response.output_text.delta")
    assert "hero.png is too large to attach here (30.0 MB)" in deltas
    assert tr.note_item is not None and tr.note_item in tr.output
    assert evs[-1]["type"] == "response.completed"


def test_no_note_when_every_file_was_attached():
    (asst, _t, cards), tr = _answer([_CARD])
    assert asst == "Here are your images." and len(cards) == 1 and tr.note_item is None


class _Store:
    """The control store an adopter needs: it is enabled, the lease is free, the cursor is at 0."""
    @staticmethod
    def enabled():
        return True

    async def lease_admit(self, *a, **k):
        return {"fence": 7}

    async def resp_get_cursor(self, *a, **k):
        return 0

    async def resp_set_cursor(self, *a, **k):
        return None

    async def lease_renew(self, *a, **k):
        return None

    async def lease_release(self, *a, **k):
        return None


def test_an_adopted_turn_says_it_too_and_keeps_it_on_the_record(monkeypatch):
    """A gateway that adopts a turn (its owner died) settles it from the trace, which holds the
    runner's events only: the closing paragraph must still reach the stream and the record, and only
    after the save, since the save decides whether the file may be said to be there."""
    polls = iter([{"done": False, "events": [], "n_total": 0},          # the probe: still running
                  {"done": True, "status": "done", "events": [], "n_total": 0}])

    async def sandbox_json(path, sid, method="POST", body=None, params=None, **k):
        return next(polls)

    async def nothing(*a, **k):
        return None

    async def false(*a, **k):
        return False

    async def resp_get(rid):
        return {"created_at": 100.0}

    async def replay(*a, **k):
        return [{"type": "message", "content": [{"type": "output_text", "text": "Made it.", "annotations": []}]}]
    order: list[str] = []
    published: list[dict] = []
    big = {"filename": "hero.png", "bytes": 30 * MB, "too_large": True}

    async def collect(*a, **k):
        order.append("collect")
        return [dict(big)]

    async def checkpoint(sid, rec):
        order.append("save")
        rec["checkpointed"] = True
    stored: dict = {}

    async def resp_put(rid, rec, *a, **k):
        stored.update(rec)
    monkeypatch.setattr(A, "POOL_ENDPOINT", "http://runner")
    monkeypatch.setattr(A, "control_store", _Store())
    monkeypatch.setattr(A, "RESP_POLL_S", 0)
    monkeypatch.setattr(A, "_prefix_from_vertex", lambda sid, v: "traces/hsessX")
    monkeypatch.setattr(A, "_sandbox_json", sandbox_json)
    monkeypatch.setattr(A, "_turn_cancelled", false)
    monkeypatch.setattr(A, "_resp_get", resp_get)
    monkeypatch.setattr(A, "_vertex_upsert", nothing)
    monkeypatch.setattr(A, "_browser_close", nothing)
    monkeypatch.setattr(A, "_trace_finalize", nothing)
    monkeypatch.setattr(A, "_bus_publish", lambda *a: published.append(a[-1]))
    monkeypatch.setattr(A, "_collect_produced", collect)
    monkeypatch.setattr(A, "_checkpoint", checkpoint)
    monkeypatch.setattr(A, "_replay_output_from_trace", replay)
    monkeypatch.setattr(A, "_resp_put", resp_put)
    v = {"runner_turn_id": "rt1", "running_response_id": "resp_adopt", "member_id": "m", "harness_id": "h"}
    assert asyncio.run(A._adopt_orphan_turn("hsessX", "org.a", v)) is True
    assert order == ["collect", "save"]
    said = "hero.png is too large to attach here (30.0 MB); it's saved in the task's files."
    assert any(e.get("delta") == said for e in published)
    asst, _t, _c = A._output_to_turn_fields(stored["output"])
    assert asst == "Made it.\n\n" + said
