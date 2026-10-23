"""A new task that brings its earlier turns (Tasks §2.1, capability input_history).

Richard, 2026-10-22 (as on the hosted service, 2026-10-19): a recorded demo task continues like any
chat. The console forks it into a task of the person's own whose input is the recording's request and
answer as earlier messages, then the new message with the recording's files. The gateway gives the
agent those messages as the conversation so far on every base, runs only the new message, and keeps
the earlier ones as the task's first turn, marked imported: completed, no model, cost 0, never
metered. A continuation (previous_response_id, or a session named) reads its input as before.

Through the real app on local backing; the turn's execution is a fake that records what it was given,
and one test drives the real execution up to the runner's /turn call on every backend."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

_REAL_EXECUTE = gw._resp_execute
REQUEST = "Make a product image of a mug on a light oak table."
ANSWER = "Here is the mug on a light oak table, soft daylight from the left. Saved as mug.png."
NEW = "Make the background white."
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def fork_input(answer=ANSWER, new=NEW) -> list:
    """What the console sends (ui/src/components/hrui/start/fork.ts, forkInput)."""
    return [
        {"role": "user", "content": [{"type": "input_text", "text": REQUEST}]},
        {"role": "assistant", "content": answer},
        {"role": "user", "content": [{"type": "input_text", "text": new},
                                     {"type": "input_file", "filename": "mug.png", "file_data": PNG}]},
    ]


# ── the split ────────────────────────────────────────────────────────────────────────────────────
def test_a_string_one_message_or_instructions_alone_bring_no_earlier_turns():
    assert gw._input_history("hi") == ([], "hi")
    one = [{"role": "user", "content": "hi"}]
    assert gw._input_history(one) == ([], one)
    ins = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}]
    assert gw._input_history(ins) == ([], ins)
    assert gw._input_history(None) == ([], None)


def test_the_last_user_message_is_the_turn_and_the_ones_before_it_are_history():
    inp = [{"role": "developer", "content": "Answer in English."}, *fork_input()]
    turns, rest = gw._input_history(inp)
    assert [(t["user"], t["assistant"]) for t in turns] == [(REQUEST, ANSWER)]
    assert rest == [inp[0], inp[3]]                       # instructions stay the turn's, with its message
    prompt, files, _items = gw._parse_input(rest)
    assert prompt == f"Answer in English.\n\n{NEW}"
    assert [f["filename"] for f in files] == ["mug.png"]


def test_exchanges_are_grouped_and_an_assistant_message_may_be_text_parts():
    inp = [{"role": "assistant", "content": "Hello, what shall we make?"},
           {"role": "user", "content": "A mug."},
           {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]},
           {"role": "assistant", "content": [{"type": "output_text", "text": "Anything else?"}]},
           {"role": "user", "content": "And a cup."},
           {"type": "function_call", "name": "x", "arguments": "{}"},      # not a message: left as it was
           {"role": "user", "content": "Now both together."}]
    turns, rest = gw._input_history(inp)
    assert [(t["user"], t["assistant"]) for t in turns] == [
        ("", "Hello, what shall we make?"), ("A mug.", "Done.\n\nAnything else?"), ("And a cup.", "")]
    assert rest == [inp[5], inp[6]]


def test_control_characters_are_cleaned_and_line_breaks_tabs_and_joiners_kept():
    dirty = "Line one\r\nline\ttwo\x00\x1b[31m red\x7f‮evil‬ family \U0001F468‍\U0001F469 \ud800end\r"
    turns, _ = gw._input_history([{"role": "user", "content": dirty}, {"role": "user", "content": "go"}])
    assert turns[0]["user"] == "Line one\nline\ttwo[31m redevil family \U0001F468‍\U0001F469 end"
    turns[0]["user"].encode("utf-8")                       # always an argument a CLI can be given


def test_over_either_cap_nothing_is_imported_the_input_stays_whole_and_it_is_counted(capsys):
    """No new refusal for an API caller. Over a cap the request is read as before."""
    before = gw._input_history_over_cap["n"]
    many = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
            for i in range(gw._IMPORT_MAX_MESSAGES + 1)] + [{"role": "user", "content": "go"}]
    assert gw._input_history(many, "org.many") == ([], many)
    assert gw._input_history(many[1:])[0]                  # exactly at the cap is taken
    long = [{"role": "user", "content": "x" * (gw._IMPORT_MAX_CHARS // 2)},
            {"role": "assistant", "content": "y" * (gw._IMPORT_MAX_CHARS // 2 + 1)},
            {"role": "user", "content": "go"}]
    assert gw._input_history(long, "org.long") == ([], long)
    assert gw._input_history_over_cap["n"] == before + 2
    log = capsys.readouterr().out
    assert "[input-history] over the messages cap org=org.many earlier_messages=21" in log
    assert "[input-history] over the characters cap org=org.long" in log
    assert "xxxx" not in log and "m1" not in log            # counts only, never the text


def test_file_data_is_not_text_a_large_image_on_the_first_message_is_imported_not_fallen_back():
    """The recorded fork puts its images on the FIRST user message, base64 far past 24,000
    characters: only text counts toward the cap, so the fork is imported, and its file travels."""
    big = "data:image/png;base64," + "A" * 400_000
    inp = [{"role": "user", "content": [{"type": "input_text", "text": REQUEST},
                                        {"type": "input_file", "filename": "mug.png", "file_data": big}]},
           {"role": "assistant", "content": ANSWER},
           {"role": "user", "content": [{"type": "input_text", "text": NEW}]}]
    before = gw._input_history_over_cap["n"]
    turns, rest = gw._input_history(inp, "org.bigfile")
    assert gw._input_history_over_cap["n"] == before
    assert [(t["user"], t["assistant"]) for t in turns] == [(REQUEST, ANSWER)]
    assert [p["filename"] for p in turns[0]["files"]] == ["mug.png"] and rest == [inp[2]]


def test_the_whole_accepted_history_reaches_the_prompt_uncut():
    """The follow-up transcript cuts each message at 4,000 characters; an imported one is read whole,
    because the caps already bound it under what a CLI argument may hold."""
    big = "z" * 20_000
    turns, _ = gw._input_history([{"role": "user", "content": REQUEST}, {"role": "assistant", "content": big},
                                  {"role": "user", "content": NEW}])
    out = gw._history_prompt(turns, NEW, max_turns=gw._IMPORT_MAX_MESSAGES, clip=gw._IMPORT_MAX_CHARS,
                             max_bytes=gw._IMPORT_MAX_CHARS + 20 * gw._IMPORT_MAX_MESSAGES)
    assert big in out and out.endswith(NEW) and len(out.encode()) < 128 * 1024


def test_a_follow_up_transcript_keeps_its_own_caps():
    """The follow-up on a base that cannot resume is cut as it always was (its defaults unchanged)."""
    turns = [{"user": "u" * 5000, "assistant": "a"}]
    out = gw._history_prompt(turns, NEW)
    assert "u" * 4000 in out and "u" * 4001 not in out


# ── through the route ────────────────────────────────────────────────────────────────────────────
class Turns:
    """The turn's execution: records what it was given, answers at once."""

    def __init__(self):
        self.ran: list[dict] = []

    async def execute(self, tr, *, sid, prompt, user_text, files_in, backend, **_kw):
        self.ran.append({"sid": sid, "prompt": prompt, "user_text": user_text, "backend": backend,
                         "files": [f["filename"] for f in files_in],
                         "title_text": (gw._session_trace.get(sid) or {}).get("title_text")})
        tr.output.append({"id": f"msg_{len(self.ran)}", "type": "message", "status": "completed", "role": "assistant",
                          "content": [{"type": "output_text", "text": "Done: white background.", "annotations": []}]})
        tr.usage = {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}
        return "completed", [], {"status": "completed"}


@pytest.fixture
def env(monkeypatch):
    who = {"p": {"org": "org.forks", "member": "ada@acme.example"}}
    t = Turns()
    metered: list = []

    async def principal(_request):
        return dict(who["p"])

    async def chain(*_a, **_k):
        return ["c1"]

    async def none(*_a, **_k):
        return None
    monkeypatch.setattr(gw, "_principal", principal)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    monkeypatch.setattr(gw, "_mapped_integration_conn", none)
    monkeypatch.setattr(gw, "_report_usage", lambda *a, **k: metered.append((a, k)))
    monkeypatch.setattr(gw, "_resp_execute", t.execute)
    yield {"c": TestClient(gw.app), "who": who, "turns": t, "metered": metered}


_n = [0]


def _setup(env, base: str = "claude-code", org: str = "") -> str:
    _n[0] += 1
    org = org or f"org.forks{_n[0]}"
    env["who"]["p"] = {**env["who"]["p"], "org": org}
    hid = f"chrn_fork{_n[0]}"
    asyncio.run(gw.BACKING.graph.upsert("Harness", hid, {
        "org": org, "member": "ada@acme.example", "workspace": "", "name": hid, "base": base,
        "custom": "1", "deleted": "0", "created_at": str(int(time.time() * 1000))}))
    return hid


def _post(env, hid: str, inp, **extra):
    return env["c"].post("/v1/responses", json={"input": inp, "store": True, "metadata": {"harness_id": hid},
                                                **extra})


def test_a_fork_gives_the_agent_its_history_and_runs_only_the_new_message(env):
    hid = _setup(env)
    r = _post(env, hid, fork_input())
    assert r.status_code == 200, r.text
    ran = env["turns"].ran[0]
    assert ran["user_text"] == NEW                           # the turn's own text: the last user message
    assert ran["files"] == ["mug.png"]
    p = ran["prompt"]
    assert p.startswith("[Attached files saved in your working directory: mug.png]")
    assert f"user: {REQUEST}\nassistant: {ANSWER}\n</conversation_so_far>" in p
    assert p.endswith(f"</conversation_so_far>\n\n{NEW}")
    assert ran["title_text"] == REQUEST                      # the card is named after the first message


def test_the_imported_turn_reads_back_first_completed_and_free_of_cost(env):
    hid = _setup(env)
    live = _post(env, hid, fork_input()).json()
    sid = env["turns"].ran[0]["sid"]
    feed = env["c"].get(f"/v1/sessions/{sid}/turns").json()
    turns = feed["turns"]
    assert len(turns) == 2 and feed["last_response_id"] == live["id"]
    first, own = turns
    assert first["imported"] is True and first["cost_usd"] == 0 and first["status"] == "completed"
    assert first["user"] == REQUEST and first["assistant"] == ANSWER
    assert first["tools"] == [] and first["files"] == []
    assert own["imported"] is False and "cost_usd" not in own and own["id"] == live["id"]
    assert own["user"] == NEW and own["user_files"] == [{"name": "mug.png"}]
    # the imported turn is a response like any other, of the same task, saying what it is
    rec = env["c"].get(f"/v1/responses/{first['id']}").json()
    assert rec["status"] == "completed" and rec["metadata"] == {"session_id": sid, "imported": True}
    assert rec["usage"] == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    assert rec["output"][0]["content"][0]["text"] == ANSWER
    assert not any(k.startswith("_") for k in rec)
    # no file bytes are kept on a record
    raw = asyncio.run(gw._blob_get(f"responses/{first['id']}.json", kb=gw.RESP_BLOB_KB)).decode()
    assert "base64" not in raw and "iVBOR" not in raw


def test_a_fork_with_its_images_on_the_first_message_keeps_them_with_the_imported_turn(env):
    hid = _setup(env)
    big = "data:image/png;base64," + "A" * 400_000
    inp = [{"role": "user", "content": [{"type": "input_text", "text": REQUEST},
                                        {"type": "input_file", "filename": "mug.png", "file_data": big}]},
           {"role": "assistant", "content": ANSWER},
           {"role": "user", "content": [{"type": "input_text", "text": NEW}]}]
    r = _post(env, hid, inp)
    assert r.status_code == 200, r.text
    ran = env["turns"].ran[0]
    assert ran["files"] == ["mug.png"] and ran["user_text"] == NEW       # the file reaches the workspace
    assert "<conversation_so_far>" in ran["prompt"] and "AAAA" not in ran["prompt"]
    turns = env["c"].get(f"/v1/sessions/{ran['sid']}/turns").json()["turns"]
    assert [t["imported"] for t in turns] == [True, False]
    assert turns[0]["user_files"] == [{"name": "mug.png"}] and turns[1]["user_files"] == []
    raw = asyncio.run(gw._blob_get(f"responses/{turns[0]['id']}.json", kb=gw.RESP_BLOB_KB)).decode()
    assert "AAAA" not in raw                                                  # no file bytes on a record


def test_the_running_card_is_named_after_the_first_imported_message(monkeypatch):
    written: list[dict] = []

    async def index(_base, manifest, **_k):
        written.append(manifest)

    async def no_prior(_prefix):
        return {}
    monkeypatch.setattr(gw, "_index_manifest", index)
    monkeypatch.setattr(gw, "_prior_manifest", no_prior)
    tr = {"prefix": "org.forks/inv_hsessx", "title_text": REQUEST}
    asyncio.run(gw._write_running_card(tr, sid="hsessx", org="org.forks", member="m", harness_id="h",
                                       backend="claude", model="m", user_text=NEW))
    assert written[0]["title"] == REQUEST and written[0]["user_prompt"] == NEW
    tr.pop("title_text")                                     # any other turn: named as always
    asyncio.run(gw._write_running_card(tr, sid="hsessx", org="org.forks", member="m", harness_id="h",
                                       backend="claude", model="m", user_text=NEW))
    assert written[1]["title"] == NEW
    import inspect
    assert 'tr.get("title_text") or prompt' in inspect.getsource(gw._trace_finalize)   # the finish names it the same


def test_a_later_turn_of_the_fork_is_named_as_any_turn(env):
    hid = _setup(env)
    live = _post(env, hid, fork_input()).json()
    r = _post(env, hid, "And add a saucer.", previous_response_id=live["id"])
    assert r.status_code == 200, r.text
    assert env["turns"].ran[1]["title_text"] is None


def test_over_the_caps_a_request_runs_exactly_as_it_did_before(env):
    """Over either cap: 200, every user message joined into the one turn as before this existed,
    nothing imported, and the count on /readyz."""
    hid = _setup(env)
    before = gw._input_history_over_cap["n"]
    many = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
            for i in range(gw._IMPORT_MAX_MESSAGES + 1)] + [{"role": "user", "content": NEW}]
    long = fork_input(answer="y" * (gw._IMPORT_MAX_CHARS + 1))
    for inp in (many, long):
        r = _post(env, hid, inp)
        assert r.status_code == 200, r.text
        old_prompt, _old_files, _ = gw._parse_input(inp)        # the reading before input_history
        ran = env["turns"].ran[-1]
        assert ran["user_text"] == old_prompt and "<conversation_so_far>" not in ran["prompt"]
        assert ran["prompt"].endswith(old_prompt) and ran["title_text"] is None
        turns = env["c"].get(f"/v1/sessions/{ran['sid']}/turns").json()["turns"]
        assert len(turns) == 1 and turns[0]["imported"] is False
    assert "\n\n".join(f"m{i}" for i in range(0, 21, 2)) + f"\n\n{NEW}" == env["turns"].ran[0]["user_text"]
    assert gw._input_history_over_cap["n"] == before + 2
    ready = asyncio.run(gw.readyz(gw.Response()))
    assert ready["input_history_over_cap"] == before + 2


def test_an_imported_turn_that_cannot_be_written_ends_the_task_failed_at_once(env, monkeypatch):
    """The 502: nothing ran, and the task reads failed at once rather than running until the sweep
    settles it."""
    hid = _setup(env)
    real_put = gw._blob_put

    async def store_down(file_id, data, kb=gw.BLOB_KB):
        if kb == gw.RESP_BLOB_KB and b'"_imported": true' in data:
            return False
        return await real_put(file_id, data, kb=kb)
    monkeypatch.setattr(gw, "_blob_put", store_down)
    r = _post(env, hid, fork_input())
    assert r.status_code == 502 and r.json()["error"]["code"] == "store_write_failed"
    assert env["turns"].ran == []
    org = env["who"]["p"]["org"]
    rows = asyncio.run(gw.BACKING.graph.find("HarnessSession", {"tenant": org}))
    assert rows and all(str(v.get("status")) == "failed" and str(v.get("turn_status")) == "failed"
                        and not v.get("running_response_id") for v in rows)


def test_imported_turns_stay_out_of_usage_and_files_and_every_read_says_so(env, monkeypatch):
    hid = _setup(env)
    live = _post(env, hid, fork_input()).json()
    ran = env["turns"].ran[0]
    sid = ran["sid"]
    turns = env["c"].get(f"/v1/sessions/{sid}/turns").json()["turns"]
    imp = turns[0]["id"]
    # produced files: the imported turn has none, and the recording's files arrive as this turn's input
    assert turns[0]["files"] == [] and ran["files"] == ["mug.png"]
    # nothing metered for it; the imported record carries no usage
    assert env["metered"] == []
    stored = json.loads(asyncio.run(gw._blob_get(f"responses/{imp}.json", kb=gw.RESP_BLOB_KB)))
    assert stored["usage"] == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    assert not {"_elapsed", "charge"} & set(stored) and "charge" not in stored["metadata"]
    # the card: the turn's finish adds this turn's usage alone, and is named after the first message
    live_usage = {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}
    asyncio.run(gw._trace_finalize(sid, {"user_text": NEW, "status": "completed", "backend": "claude",
                                         "usage": live_usage}))
    card = asyncio.run(gw._prior_manifest(gw._session_trace[sid]["prefix"]))
    assert card["usage"] == {k: float(v) for k, v in live_usage.items()}
    assert card["title"] == REQUEST and card["user_prompt"] == NEW
    # every read of the imported turn says it is one
    assert env["c"].get(f"/v1/responses/{imp}").json()["metadata"]["imported"] is True
    items = env["c"].get(f"/v1/responses/{imp}/input_items").json()
    assert items["imported"] is True and items["data"][0]["content"][0]["text"] == REQUEST
    assert "imported" not in env["c"].get(f"/v1/responses/{live['id']}/input_items").json()
    share = env["c"].post(f"/v1/sessions/{sid}/share", json={})
    assert share.status_code == 200, share.text
    token = share.json().get("id") or share.json().get("token")
    shared = env["c"].get(f"/share/{token}/turns").json()["turns"]
    assert [t["imported"] for t in shared] == [True, False] and shared[0]["cost_usd"] == 0


def test_a_continuation_reads_its_input_exactly_as_before(env):
    hid = _setup(env)
    first = _post(env, hid, "Make a mug.").json()
    sid = env["turns"].ran[0]["sid"]
    arr = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
    r = _post(env, hid, arr, previous_response_id=first["id"])
    assert r.status_code == 200, r.text
    hinted = _post(env, hid, arr, metadata={"harness_id": hid, "session_id": sid})
    assert hinted.status_code == 200, hinted.text
    for ran in env["turns"].ran[1:]:
        assert ran["sid"] == sid
        assert ran["prompt"] == "a\n\nc" and ran["user_text"] == "a\n\nc"     # joined, as it always was
    turns = env["c"].get(f"/v1/sessions/{sid}/turns").json()["turns"]
    assert len(turns) == 3 and not any(t["imported"] for t in turns)


@pytest.mark.parametrize("base", sorted(gw._BASE_CATALOG))
def test_every_base_is_handed_the_history(env, base):
    """Every base, through the route: the turn is given the history in its prompt and only the new
    message as its own text."""
    hid = _setup(env, base=base)
    r = _post(env, hid, fork_input())
    assert r.status_code == 200, r.text
    ran = env["turns"].ran[-1]
    assert ran["backend"] == gw._BASE_CATALOG[base]["backend"]
    assert f"user: {REQUEST}\nassistant: {ANSWER}\n" in ran["prompt"] and ran["user_text"] == NEW


# ── the runner's own request ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("backend", sorted({b["backend"] for b in gw._BASE_CATALOG.values()}))
def test_the_runner_is_given_the_history_on_every_backend(monkeypatch, backend):
    """The real execution, up to the runner's /turn: the prompt it is given is the one the route made,
    with the history, on every backend (a base that cannot resume does not wrap it again)."""
    seen: list[dict] = []

    async def sandbox_json(path, sid, method="POST", body=None, **_kw):
        if path == "/turn":
            seen.append(body)
            return {"turn_id": "t1", "status": "running"}
        if path.startswith("/turn/"):
            return {"done": True, "status": "done", "events": [], "n_total": 0}
        return {}

    async def nothing(*_a, **_kw):
        return None

    # a provider the wiring says drives this backend (anthropic for claude, google for gemini ...)
    provider = next((p for (p, b) in sorted(gw._INTEGRATION_WIRING) if b == backend and p in gw._PROVIDER_CATALOG
                     and p != "custom"), "anthropic")

    async def get_connection(_org, name):
        return ({"name": name, "backend": backend, "provider": provider, "model": "m", "_model_resolved": True,
                 "api_key": "k", "base_url": "https://proxy.example/v1"}, "tenant-1")

    async def harness_plugins(*_a, **_kw):
        return ([], [], [], [], [])

    async def harness_env(*_a, **_kw):
        return ({}, [])

    async def auth_from_conn(*_a, **_kw):
        return {"token": "t", "base_url": "https://proxy.example/v1"}

    async def no(*_a, **_kw):
        return False

    async def empty(*_a, **_kw):
        return []
    monkeypatch.setattr(gw, "_sandbox_json", sandbox_json)
    monkeypatch.setattr(gw, "_vertex_get", nothing)
    monkeypatch.setattr(gw, "_vertex_upsert", nothing)
    monkeypatch.setattr(gw, "_hydrate", nothing)
    monkeypatch.setattr(gw, "_harness_plugins", harness_plugins)
    monkeypatch.setattr(gw, "_harness_env", harness_env)
    monkeypatch.setattr(gw, "_image_auth", nothing)
    monkeypatch.setattr(gw, "_get_connection", get_connection)
    monkeypatch.setattr(gw, "_mapped_integration_conn", nothing)
    monkeypatch.setattr(gw, "_auth_from_conn", auth_from_conn)
    monkeypatch.setattr(gw, "_turn_cancelled", no)
    monkeypatch.setattr(gw, "_collect_produced", empty)
    monkeypatch.setattr(gw, "_blob_put", nothing)
    monkeypatch.setattr(gw, "_checkpoint", nothing)
    monkeypatch.setattr(gw, "_trace_finalize", nothing)
    monkeypatch.setattr(gw, "_write_running_card", nothing)
    monkeypatch.setattr(gw, "_browser_close", nothing)
    monkeypatch.setattr(gw, "_recover_trace_cursor", nothing)
    monkeypatch.setattr(gw, "_conn_serves", lambda *a, **k: True)
    monkeypatch.setattr(gw, "RESP_POLL_S", 0)
    monkeypatch.setattr(gw.control_store, "enabled", lambda: False)
    turns, rest = gw._input_history(fork_input())
    prompt = gw._history_prompt(turns, gw._parse_input(rest)[0], max_turns=gw._IMPORT_MAX_MESSAGES,
                                clip=gw._IMPORT_MAX_CHARS, max_bytes=gw._IMPORT_MAX_CHARS + 20 * gw._IMPORT_MAX_MESSAGES)
    sid = f"hsesshist{backend}"
    tr = gw._RespTranslator(f"resp_hist{backend}", "m", None, True, time.time(), sid=sid)
    _st, _pr, _rec = asyncio.run(_REAL_EXECUTE(tr, org="org.forks", member="m", sid=sid, backend=backend, chain=["c1"],
                              prompt=prompt, files_in=[], resume=None, emit=lambda ev: asyncio.sleep(0),
                              user_text=NEW))
    assert len(seen) == 1, f"{backend}: the turn never reached the runner's /turn: {_st} {str(_rec)[:600]}"
    assert seen[0]["prompt"] == prompt
    assert f"user: {REQUEST}\nassistant: {ANSWER}\n" in seen[0]["prompt"]
    gw._session_trace.pop(sid, None)


# ── discovery ────────────────────────────────────────────────────────────────────────────────────
def test_the_capability_is_said_where_the_protocol_and_the_console_read_it(env):
    assert env["c"].get("/v1/uhp").json()["capabilities"]["input_history"] is True
    assert env["c"].get("/v1/bases").json()["capabilities"] == {"input_history": True}
