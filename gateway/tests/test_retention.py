"""What a delete removes, and when: Richard's rule (2026-10-08), the same as the hosted service's.

For good, at once: a task (its session, with everything it left), an API key, a credential.
Kept 30 days, restorable, then removed by the retention sweep: a harness, a response deleted on
its own, an environment, an upload.

Every test reads the stores back on disk: a record that is only marked deleted, or a file that is
only unreachable through the API, fails it.
"""
import asyncio
import json
import pathlib
import sqlite3
import sys
import uuid

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

ORG = "local"
ME = {"org": ORG, "member": "owner", "workspace": "", "workspace_default": False}
DAY = 86_400_000


class _Req:
    def __init__(self):
        self.headers, self.method = {}, "DELETE"
        self.url = type("U", (), {"path": "/"})()


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def as_owner(monkeypatch):
    async def who(request):
        return dict(ME)

    async def owned_org(request, org):
        return dict(ME)
    monkeypatch.setattr(gw, "_principal", who)
    monkeypatch.setattr(gw, "_pub_principal", who)
    monkeypatch.setattr(gw, "_owned_org", owned_org)
    monkeypatch.setattr(gw.control_store, "enabled", lambda: False)


def _files_naming(token: str) -> list[str]:
    """Every stored file whose path names the token, in the blob and secret stores the server
    uses (read off the stores: another test module may have pointed them elsewhere)."""
    roots = (gw.BACKING.blob._root, gw.BACKING.secrets._root)
    return [str(p) for r in roots if r.exists() for p in r.rglob("*") if p.is_file() and token in str(p)]


def _rows_naming(token: str) -> list[tuple]:
    """Every graph record whose id or properties name the token."""
    with sqlite3.connect(gw.BACKING.graph._path) as c:
        return c.execute("SELECT vid, label FROM vertices WHERE vid LIKE ? OR props LIKE ?",
                         (f"%{token}%", f"%{token}%")).fetchall()


def _blob(key, kb=None):
    return run(gw._blob_get(key, kb=kb or gw.BLOB_KB))


def _put(key, data: bytes, kb=None):
    assert run(gw._blob_put(key, data, kb=kb or gw.BLOB_KB))


def _sweep(at_ms=None, **kw):
    """The sweep as it runs on a given day."""
    real = gw._now_ms
    if at_ms is not None:
        gw._now_ms = lambda: at_ms
    try:
        return run(gw._retention_sweep(kw.pop("dry_run", False), **kw))
    finally:
        gw._now_ms = real


def _restore(kind, iid):
    return run(gw.retention_restore(gw.RetentionRestoreBody(kind=kind, id=iid)))


def _status(coro) -> int:
    with pytest.raises(HTTPException) as e:
        asyncio.run(coro)
    return e.value.status_code


# ── a task: everything it left, at once ─────────────────────────────────────────────────────
def _a_session_with_everything() -> tuple[str, str]:
    sid = "hsess_" + uuid.uuid4().hex
    rid = "resp_" + uuid.uuid4().hex
    base = f"{ORG}/9999_{sid}"
    run(gw.BACKING.graph.upsert("HarnessSession", sid, {
        "tenant": ORG, "workspace": "", "harness_id": "chrn_x", "member_id": "owner", "status": "idle",
        "title": "Quarterly numbers for the board", "trace_blob": base, "checkpoint_bytes": "10"}))
    # the transcript and trace
    _put(gw._manifest_key(base), json.dumps({"session_id": sid, "chunks": ["events/0001.jsonl"]}).encode(), gw.TRACE_KB)
    _put(f"{base}/events/0001.jsonl", b'{"text": "the board numbers"}', gw.TRACE_KB)
    _put(f"{base}/all.jsonl", b"transcript", gw.TRACE_KB)
    # a response
    run(gw._resp_put(rid, {"id": rid, "status": "completed", "output": [{"text": "the answer"}]},
                     ORG, sid, None, "completed", 1.0, True))
    # produced files, their previews, the change list, the checkpoint, media and its scene
    _put(f"containers/{sid}/report.pdf", b"%PDF report", gw.RESP_BLOB_KB)
    _put(f"containers/{sid}/report.pdf.meta", b"{}", gw.RESP_BLOB_KB)
    _put(f"previews/{sid}/f1/page-1.png", b"png", gw.RESP_BLOB_KB)
    _put(f"sessions/{sid}/changed.json", b'{"files": ["report.pdf"]}', gw.RESP_BLOB_KB)
    _put(gw._ws_blob(sid), b"tarball")
    _put(f"media/{sid}/m1.mp4", b"video")
    _put(gw._media_scene_key(sid), b"{}")
    # a torn write: the temporary file a listing does not show
    torn = gw.BACKING.blob._root / gw.RESP_BLOB_KB / "sessions" / sid / "changed.json.tmp"
    torn.parent.mkdir(parents=True, exist_ok=True)
    torn.write_bytes(b'{"files": [')
    run(gw.BACKING.graph.upsert(gw._MEDIA_JOB_LABEL, "mjob_" + uuid.uuid4().hex[:16],
                                {"session": sid, "status": "done", "prompt": "a sunrise"}))
    # a plugin call
    run(gw.BACKING.graph.upsert(gw._PLUG_CALL_LABEL, "pcall_" + uuid.uuid4().hex,
                                {"session": sid, "tool": "create_issue", "usd": "0.0"}))
    return sid, rid


def test_a_deleted_task_leaves_no_file_and_no_record_but_a_marker():
    sid, rid = _a_session_with_everything()
    assert len(_files_naming(sid)) >= 9 and len(_rows_naming(sid)) >= 4      # the fixture is real

    out = run(gw.delete_trace(sid, _Req()))
    assert out == {"id": sid, "object": "session", "deleted": True}

    assert _files_naming(sid) == []
    assert _files_naming(rid) == []
    assert _rows_naming(sid) == [(sid, "HarnessSession")]        # the marker, and nothing else
    marker = run(gw.BACKING.graph.get(sid))
    assert marker["status"] == "deleted" and marker["shared"] == "0" and marker.get("deleted_at")
    assert set(marker) - {"id"} <= set(gw._SESSION_MARKER)
    assert "title" not in marker and "checkpoint_bytes" not in marker
    assert _status(gw._owned_session(_Req(), sid)) == 404


def test_the_marker_goes_a_day_later_and_cannot_be_restored():
    sid, _ = _a_session_with_everything()
    run(gw.delete_trace(sid, _Req()))
    now = gw._now_ms()
    assert sid not in _sweep(now + DAY // 2)["removed"]["sessions"]
    assert _sweep(now + DAY + 1000)["removed"]["sessions"].count(sid) == 1
    assert _rows_naming(sid) == []
    assert _status(gw.retention_restore(gw.RetentionRestoreBody(kind="sessions", id=sid))) == 409


def test_a_task_deleted_before_this_version_loses_what_it_left_on_the_first_sweep():
    """The volumes this version starts on: a tombstone with everything still beside it."""
    sid, rid = _a_session_with_everything()
    run(gw.BACKING.graph.upsert("HarnessSession", sid, {"status": "deleted", "shared": "0"}))
    assert _files_naming(sid)
    res = _sweep()
    assert sid in res["removed"]["sessions"] and res["no_delete_time"].get("sessions", 0) >= 1
    assert _files_naming(sid) == [] and _files_naming(rid) == [] and _rows_naming(sid) == []


# ── a response: 30 days, restorable ─────────────────────────────────────────────────────────
def _a_response() -> str:
    sid = "hsess_" + uuid.uuid4().hex
    rid = "resp_" + uuid.uuid4().hex
    run(gw.BACKING.graph.upsert("HarnessSession", sid, {"tenant": ORG, "workspace": "", "status": "idle"}))
    run(gw._resp_put(rid, {"id": rid, "_org": ORG, "_session_id": sid, "status": "completed"},
                     ORG, sid, None, "completed", 1.0, True))
    return rid


def test_a_deleted_response_is_kept_30_days_restorable_then_removed():
    rid = _a_response()
    run(gw.delete_response(rid, _Req()))
    assert run(gw._resp_get(rid)) is None                         # unreadable at once
    now = gw._now_ms()
    assert rid not in _sweep(now + 29 * DAY)["removed"]["responses"]
    assert _restore("responses", rid) == {"kind": "responses", "id": rid, "restored": True}
    assert run(gw._resp_get(rid))["status"] == "completed"
    assert run(gw.BACKING.graph.get(rid))["status"] == "completed"

    run(gw.delete_response(rid, _Req()))
    assert rid in _sweep(gw._now_ms() + 30 * DAY + 1000)["removed"]["responses"]
    assert _files_naming(rid) == [] and _rows_naming(rid) == []
    assert _status(gw.retention_restore(gw.RetentionRestoreBody(kind="responses", id=rid))) == 410


# ── a harness: its credentials at once, the rest after 30 days ─────────────────────────────
def _a_harness(*, blob="", plugin_blob="") -> tuple[str, str]:
    hid = "chrn_" + uuid.uuid4().hex
    key = gw._hosted_secret_key(hid, "mcp.database")
    run(gw._hosted_put_record(ORG, key, {"server": "database", "harness": hid, "engine": "postgres",
                                         "dsn": "postgres://u:hunter2@db.example/x"}))
    servers = [{"id": "mcp.database", "name": "database", "url": "https://gateway.example/x", "auth": f"vault:{key}"}]
    skills = [{"name": "big", "blob": blob}] if blob else []
    plugins = [{"name": "kit", "blob": plugin_blob}] if plugin_blob else []
    run(gw.BACKING.graph.upsert("Harness", hid, {
        "org": ORG, "workspace": "", "name": "Analyst", "deleted": "0", "mcp_servers": json.dumps(servers),
        "skills": json.dumps(skills), "plugins": json.dumps(plugins), "updated_at": str(gw._now_ms())}))
    run(gw._connection_vertex_put(ORG, hid, {"workspace": ""}, "mcp.database", key, "postgres", "db.example", "x", False))
    return hid, key


def _secret_file(key: str) -> list[str]:
    return [str(p) for p in gw.BACKING.secrets._root.rglob("*") if p.is_file() and p.name == key]


def test_a_deleted_harness_loses_its_credential_at_once_and_comes_back_without_it():
    hid, key = _a_harness()
    assert _secret_file(key) and run(gw.BACKING.graph.find(gw._CONNECTION_LABEL, {"harness": hid}))
    run(gw.delete_harness_public(hid, _Req()))
    assert _secret_file(key) == []                                # removed, not overwritten
    assert run(gw.BACKING.graph.find(gw._CONNECTION_LABEL, {"harness": hid})) == []
    v = run(gw.BACKING.graph.get(hid))
    assert v["deleted"] == "1" and v.get("deleted_at")
    assert _status(gw._harness_in_reach(ME, hid)) == 404

    assert _restore("harnesses", hid)["restored"] is True
    assert run(gw._harness_in_reach(ME, hid))["name"] == "Analyst"
    assert _secret_file(key) == []


def test_a_harness_is_removed_after_30_days_with_its_bundles_unless_another_names_one():
    shared = "skb_" + uuid.uuid4().hex
    own = "skb_" + uuid.uuid4().hex
    pkg = uuid.uuid4().hex
    hid, _ = _a_harness(blob=own, plugin_blob=pkg)
    other, _ = _a_harness(blob=shared)
    run(gw.BACKING.graph.upsert("Harness", hid, {"skills": json.dumps([{"name": "a", "blob": own}, {"name": "b", "blob": shared}])}))
    for b in (own, shared):
        _put(f"skills/{b}.json", b"[]")
    _put(gw._plugin_blob_key(ORG, pkg), b"{}")

    run(gw.delete_harness_public(hid, _Req()))
    assert _blob(f"skills/{own}.json") and _blob(gw._plugin_blob_key(ORG, pkg))    # kept for a restore
    assert hid not in _sweep(gw._now_ms() + 29 * DAY)["removed"]["harnesses"]
    assert hid in _sweep(gw._now_ms() + 30 * DAY + 1000)["removed"]["harnesses"]
    assert run(gw.BACKING.graph.get(hid)) is None and _rows_naming(hid) == []
    assert _blob(f"skills/{own}.json") is None and _blob(gw._plugin_blob_key(ORG, pkg)) is None
    assert _blob(f"skills/{shared}.json") == b"[]"                 # the other harness still names it
    assert _status(gw.retention_restore(gw.RetentionRestoreBody(kind="harnesses", id=hid))) == 410
    assert run(gw.BACKING.graph.get(other))["deleted"] == "0"


def test_a_harness_deleted_before_this_version_counts_from_its_last_task_too():
    """Its last edit was 40 days ago, but it ran a task 3 days ago, so its delete came after that."""
    hid, _ = _a_harness()
    now = gw._now_ms()
    run(gw.BACKING.graph.upsert("Harness", hid, {"deleted": "1", "updated_at": str(now - 40 * DAY)}))
    run(gw.BACKING.graph.upsert("HarnessSession", "hsess_" + uuid.uuid4().hex,
                                {"tenant": ORG, "harness_id": hid, "status": "idle", "updated_at": str(now - 3 * DAY)}))
    assert hid not in _sweep(dry_run=True, kinds=["harnesses"])["would_remove"]["harnesses"]
    assert hid in _sweep(now + 28 * DAY, dry_run=True, kinds=["harnesses"])["would_remove"]["harnesses"]


def test_a_harness_deleted_before_this_version_counts_from_its_last_write():
    old, _ = _a_harness()
    recent, _ = _a_harness()
    now = gw._now_ms()
    run(gw.BACKING.graph.upsert("Harness", old, {"deleted": "1", "updated_at": str(now - 40 * DAY)}))
    run(gw.BACKING.graph.upsert("Harness", recent, {"deleted": "1", "updated_at": str(now - 5 * DAY)}))
    dry = _sweep(dry_run=True, kinds=["harnesses"])
    assert old in dry["would_remove"]["harnesses"] and recent not in dry["would_remove"]["harnesses"]
    assert dry["no_delete_time"]["harnesses"] >= 1 and dry["done"] is False
    assert run(gw.BACKING.graph.get(old)) is not None                 # a dry run removes nothing
    res = _sweep(kinds=["harnesses"])
    assert old in res["removed"]["harnesses"] and run(gw.BACKING.graph.get(old)) is None
    assert run(gw.BACKING.graph.get(recent))["deleted"] == "1"


# ── an API key: at once ─────────────────────────────────────────────────────────────────────
def test_a_revoked_key_is_removed_at_once_and_no_longer_opens_anything():
    tok = "sk-hr-" + uuid.uuid4().hex
    sha = gw._hash_key(tok)
    run(gw.BACKING.graph.upsert("HarnessApiKey", sha, {"kind": "harness_api_key", "org": ORG, "member": "owner",
                                                       "name": "laptop", "revoked": "0"}))
    assert run(gw._apikey_resolve(tok))["org"] == ORG
    assert run(gw.revoke_key(ORG, sha, _Req())) == {"id": sha, "revoked": True}
    assert run(gw.BACKING.graph.get(sha)) is None and _rows_naming(sha) == []
    assert run(gw._apikey_resolve(tok)) is None
    assert _status(gw.retention_restore(gw.RetentionRestoreBody(kind="api_keys", id=sha))) == 409


def test_keys_revoked_before_this_version_are_removed_by_the_sweep():
    sha = gw._hash_key("sk-hr-" + uuid.uuid4().hex)
    run(gw.BACKING.graph.upsert("HarnessApiKey", sha, {"kind": "harness_api_key", "org": ORG, "revoked": "1"}))
    assert sha in _sweep(kinds=["api_keys"])["removed"]["api_keys"]
    assert run(gw.BACKING.graph.get(sha)) is None


# ── credentials blanked by an older version ─────────────────────────────────────────────────
def test_credentials_an_older_version_only_blanked_are_removed():
    blank = "harness-hosted-" + uuid.uuid4().hex[:12]
    kept = "harness-mcp-" + uuid.uuid4().hex[:12]
    run(gw.BACKING.secrets.put(ORG, blank, "", require_encryption=True))
    run(gw.BACKING.secrets.put(ORG, kept, "a-live-token"))
    cid = "hconn_" + uuid.uuid4().hex[:24]
    run(gw.BACKING.graph.upsert(gw._CONNECTION_LABEL, cid, {"harness": "chrn_x", "host": "db.example", "deleted": "1"}))
    res = _sweep(kinds=["credentials"])
    assert f"secret:{ORG}/{blank}" in res["removed"]["credentials"] and cid in res["removed"]["credentials"]
    assert _secret_file(blank) == [] and run(gw.BACKING.graph.get(cid)) is None
    assert run(gw.BACKING.secrets.get(ORG, kept)) == "a-live-token"


def test_a_stored_tool_token_can_be_deleted():
    run(gw.put_mcp_secret(ORG, "Linear Token", gw.McpSecretBody(token="lin_live"), _Req()))
    key = gw._MCP_SECRET_PREFIX + "linear-token"
    assert _secret_file(key)
    assert run(gw.delete_mcp_secret(ORG, "Linear Token", _Req()))["deleted"] is True
    assert _secret_file(key) == []


# ── an environment: its path at once, its files after 30 days ───────────────────────────────
def _an_environment(monkeypatch, slug=None):
    calls = []

    class _R:
        status_code = 200

    async def runner(method, path, env_id, **kw):
        calls.append((method, path, (kw.get("params") or {}).get("slug", "")))
        return _R()
    monkeypatch.setattr(gw, "_env_runner", runner)

    async def refresh(v):
        return v
    monkeypatch.setattr(gw, "_environment_refresh", refresh)
    eid = "henv_" + uuid.uuid4().hex
    slug = slug or "env-" + uuid.uuid4().hex[:8]
    run(gw.BACKING.graph.upsert("Environment", eid, {"org": ORG, "workspace": "", "name": slug, "slug": slug,
                                                     "status": "ready", "deleted": "0", "updated_at": str(gw._now_ms())}))
    return eid, slug, calls


def test_a_deleted_environment_frees_its_path_keeps_its_files_30_days_then_goes(monkeypatch):
    eid, slug, calls = _an_environment(monkeypatch)
    run(gw.delete_environment(eid, _Req()))
    assert calls == [("DELETE", f"/environments/{eid}/mount", slug)]     # the path, not the files
    assert run(gw.BACKING.graph.get(eid))["deleted"] == "1"
    assert _restore("environments", eid)["restored"] is True
    run(gw.delete_environment(eid, _Req()))
    calls.clear()
    assert eid in _sweep(gw._now_ms() + 30 * DAY + 1000, kinds=["environments"])["removed"]["environments"]
    assert calls == [("DELETE", f"/environments/{eid}", "")]             # never the name: it may be another's
    assert run(gw.BACKING.graph.get(eid)) is None


def test_an_environment_whose_name_was_taken_is_not_restored_over_the_new_one(monkeypatch):
    eid, slug, _ = _an_environment(monkeypatch)
    run(gw.delete_environment(eid, _Req()))
    _an_environment(monkeypatch, slug=slug)
    assert _status(gw.retention_restore(gw.RetentionRestoreBody(kind="environments", id=eid))) == 409


def test_an_environment_whose_runner_did_not_answer_is_left_and_said_so(monkeypatch):
    eid, _, _ = _an_environment(monkeypatch)
    run(gw.delete_environment(eid, _Req()))

    async def down(method, path, env_id, **kw):
        raise gw.uhp_error(502, "environment_unavailable", "The runner did not answer.")
    monkeypatch.setattr(gw, "_env_runner", down)
    res = _sweep(gw._now_ms() + 31 * DAY, kinds=["environments"])
    assert eid not in res["removed"]["environments"] and res["left"]["environments"] and res["done"] is False
    assert run(gw.BACKING.graph.get(eid)) is not None


# ── an upload: DELETE /v1/files/{id}, 30 days, restorable ───────────────────────────────────
def _an_upload(org=ORG) -> str:
    fid = "file_" + uuid.uuid4().hex
    _put(f"uploads/{fid}", b"q3 numbers", gw.RESP_BLOB_KB)
    _put(f"uploads/{fid}.meta", json.dumps({"filename": "q3.csv", "media_type": "text/csv", "org": org}).encode(), gw.RESP_BLOB_KB)
    return fid


def test_a_deleted_upload_is_refused_to_tasks_restorable_then_removed():
    fid = _an_upload()
    assert run(gw.delete_file(fid, _Req())) == {"id": fid, "object": "file", "deleted": True}
    assert _status(gw._resolve_uploads([{"file_id": fid}], ORG)) == 404
    assert _status(gw.delete_file(fid, _Req())) == 404
    assert _restore("uploads", fid)["restored"] is True
    files = [{"file_id": fid}]
    run(gw._resolve_uploads(files, ORG))
    assert files[0]["filename"] == "q3.csv"

    run(gw.delete_file(fid, _Req()))
    assert fid not in _sweep(gw._now_ms() + 29 * DAY, kinds=["uploads"])["removed"]["uploads"]
    assert fid in _sweep(gw._now_ms() + 30 * DAY + 1000, kinds=["uploads"])["removed"]["uploads"]
    assert _files_naming(fid) == []
    assert _status(gw.retention_restore(gw.RetentionRestoreBody(kind="uploads", id=fid))) == 410


def test_another_organizations_upload_cannot_be_deleted():
    fid = _an_upload(org="org-other")
    assert _status(gw.delete_file(fid, _Req())) == 404
    assert _blob(f"uploads/{fid}", gw.RESP_BLOB_KB) == b"q3 numbers"


# ── the sweep itself ────────────────────────────────────────────────────────────────────────
def test_a_capped_sweep_says_when_it_is_done():
    rids = [_a_response() for _ in range(3)]
    for rid in rids:
        run(gw.delete_response(rid, _Req()))
    later = gw._now_ms() + 31 * DAY
    first = _sweep(later, kinds=["responses"], limit=2)
    assert len(first["removed"]["responses"]) == 2 and first["done"] is False
    rest = _sweep(later, kinds=["responses"], limit=50)
    assert set(first["removed"]["responses"]) | set(rest["removed"]["responses"]) >= set(rids)
    assert rest["done"] is True


def test_the_sweep_route_refuses_a_kind_it_does_not_know_and_skips_hosted_only_ones():
    assert _status(gw.retention_sweep(gw.RetentionSweepBody(dry_run=True, kinds=["sessionz"]))) == 400
    out = run(gw.retention_sweep(gw.RetentionSweepBody(dry_run=True, kinds=["arenas"])))
    assert out["dry_run"] is True and "would_remove" in out and out["done"] is True   # nothing due
