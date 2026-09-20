"""POST /v1/files on the local backing (#198, CE 0.17.3).

The upload streamed into the blob plane through the VG-only URL/header helpers, unconditionally;
the file-backed store has neither, so on every self-hosted instance the endpoint answered 500
(`'FileBlobStore' object has no attribute 'headers'`) and the only way to attach a file was the
inline `data:` form. The other relays (checkpoint, hydrate, workspace tar) already branch on the
backing; this one did not. X-05 passes with the inline form, which is why the suite did not see it.
"""
import io
import json
import os

from fastapi.testclient import TestClient

os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": "local", "x-harness-member": "m"}


def _upload(client, name: str, data: bytes, media: str = "text/plain"):
    return client.post("/v1/files", headers=HEADERS, data={"purpose": "user_data"},
                       files={"file": (name, io.BytesIO(data), media)})


def test_an_upload_lands_in_the_local_store_and_answers_the_file_object():
    c = TestClient(gw.app)
    r = _upload(c, "brief.txt", b"The secret token is uhp-198.\n")
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["object"] == "file" and f["id"].startswith("file_")
    assert f["filename"] == "brief.txt" and f["bytes"] == 29 and f["purpose"] == "user_data"
    assert isinstance(f["created_at"], int)
    # the bytes and the sidecar the turn reads (the input_file resolver in create_response)
    import asyncio
    assert asyncio.run(gw._blob_get(f"uploads/{f['id']}", kb=gw.RESP_BLOB_KB)) == b"The secret token is uhp-198.\n"
    meta = json.loads(asyncio.run(gw._blob_get(f"uploads/{f['id']}.meta", kb=gw.RESP_BLOB_KB)))
    assert meta == {"filename": "brief.txt", "media_type": "text/plain", "org": "local"}


def test_an_upload_is_served_to_its_owner_only_and_an_unknown_id_is_a_404():
    """Files §5: a file_id from another principal answers 404, never the bytes. The sidecar carried
    no owner, so a task by any org that named a file_id was handed the file; and an unknown id
    was dropped in silence, the task running without its file."""
    import asyncio
    import base64
    from fastapi import HTTPException
    c = TestClient(gw.app)
    f = _upload(c, "brief.txt", b"The secret token is uhp-198.\n").json()
    mine = [{"file_id": f["id"], "content_b64": None, "filename": ""}]
    asyncio.run(gw._resolve_uploads(mine, "local"))
    assert mine[0]["filename"] == "brief.txt"
    assert mine[0]["content_b64"] == base64.b64encode(b"The secret token is uhp-198.\n").decode()
    theirs = [{"file_id": f["id"], "content_b64": None, "filename": ""}]
    try:
        asyncio.run(gw._resolve_uploads(theirs, "another-org"))
    except HTTPException as e:
        assert e.status_code == 404 and e.detail["code"] == "file_not_found"
        assert theirs[0]["content_b64"] is None          # never the bytes
    else:
        raise AssertionError("another org was handed the upload")
    try:
        asyncio.run(gw._resolve_uploads([{"file_id": "file_doesnotexist", "content_b64": None, "filename": ""}], "local"))
    except HTTPException as e:
        assert e.status_code == 404 and e.detail["code"] == "file_not_found"
    else:
        raise AssertionError("an unknown file_id was dropped in silence")
    # an upload made before the owner was recorded has no org in its sidecar and is served
    asyncio.run(gw._blob_put(f"uploads/{f['id']}.meta", json.dumps({"filename": "brief.txt", "media_type": "text/plain"}).encode(), kb=gw.RESP_BLOB_KB))
    legacy = [{"file_id": f["id"], "content_b64": None, "filename": ""}]
    asyncio.run(gw._resolve_uploads(legacy, "another-org"))
    assert legacy[0]["content_b64"]


def test_an_oversized_upload_is_refused_as_file_too_large_and_stores_nothing(monkeypatch):
    monkeypatch.setattr(gw, "_UPLOAD_MAX_BYTES", 64)
    c = TestClient(gw.app)
    r = _upload(c, "big.bin", b"\x00" * 65)
    assert r.status_code == 413, r.text
    assert r.json()["error"]["code"] == "file_too_large"
    import asyncio
    listing = asyncio.run(gw.BACKING.blob.list(gw.RESP_BLOB_KB, "uploads/", limit=100))
    names = json.dumps(listing)
    assert "big.bin" not in names and names.count("file_") == names.count("file_") // 2 * 2  # only pairs (data + .meta) ever land
