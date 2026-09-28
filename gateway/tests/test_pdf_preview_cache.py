"""PDF previews follow the current source when stable file IDs are replaced."""
import asyncio
import hashlib
import threading

import pytest
from fastapi import HTTPException

import app as gw


@pytest.mark.asyncio
async def test_replacement_uses_new_pdf_and_deleted_source_does_not_hit_cache(monkeypatch):
    sid, fid = "hsess_preview", "wf_c2xpZGVzLm9kcA"
    source = [b"version A"]
    filename = ["slides.odp"]
    cache = {}
    conversions = []
    deleted = []

    async def owned(*_args):
        return None

    async def file_bytes(_sid, _fid):
        if source[0] is None:
            return None
        return source[0], "application/vnd.oasis.opendocument.presentation", filename[0]

    async def blob_get(key, kb=None):
        assert kb == gw.RESP_BLOB_KB
        return cache.get(key)

    async def blob_put(key, data, kb=None):
        assert kb == gw.RESP_BLOB_KB
        cache[key] = data
        return True

    async def blob_list(prefix, kb=None, hard_cap=None):
        assert kb == gw.RESP_BLOB_KB and hard_cap == 1000
        return [{"file_id": key} for key in cache if key.startswith(prefix)]

    async def blob_delete(key, kb=None):
        assert kb == gw.RESP_BLOB_KB
        deleted.append(key)
        cache.pop(key, None)
        return True

    def convert(data, _ext):
        conversions.append(data)
        return b"pdf:" + data

    monkeypatch.setattr(gw, "_owned_session", owned)
    monkeypatch.setattr(gw, "_container_file_bytes", file_bytes)
    monkeypatch.setattr(gw, "_blob_get", blob_get)
    monkeypatch.setattr(gw, "_blob_put", blob_put)
    monkeypatch.setattr(gw, "_blob_list_all", blob_list)
    monkeypatch.setattr(gw, "_blob_delete", blob_delete)
    monkeypatch.setattr(gw, "_convert_to_pdf", convert)
    monkeypatch.setattr(gw, "_SOFFICE", "soffice")

    first = await gw.container_file_pdf(sid, fid, request=None)
    assert first.body == b"pdf:version A"
    source[0] = b"version B"
    second = await gw.container_file_pdf(sid, fid, request=None)
    assert second.body == b"pdf:version B"
    again = await gw.container_file_pdf(sid, fid, request=None)
    assert again.body == b"pdf:version B"
    assert conversions == [b"version A", b"version B"]
    assert any(key.endswith(".pdf") and key == f"previews/{sid}/{fid}.pdf" for key in deleted)
    assert len(cache) == 1 and next(iter(cache.values())) == b"pdf:version B"

    filename[0] = "slides.txt"
    with pytest.raises(HTTPException) as unsupported:
        await gw.container_file_pdf(sid, fid, request=None)
    assert unsupported.value.status_code == 415

    source[0] = None
    with pytest.raises(HTTPException) as exc:
        await gw.container_file_pdf(sid, fid, request=None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_concurrent_versions_never_overwrite_each_others_cache(monkeypatch):
    sid, fid = "hsess_race", "wf_c2xpZGVzLm9kcA"
    source = [b"version A"]
    cache = {}
    a_started = threading.Event()
    release_a = threading.Event()

    async def owned(*_args):
        return None

    async def file_bytes(_sid, _fid):
        return source[0], "application/vnd.oasis.opendocument.presentation", "slides.odp"

    async def blob_get(key, kb=None):
        return cache.get(key)

    async def blob_put(key, data, kb=None):
        cache[key] = data
        return True

    async def blob_list(prefix, kb=None, hard_cap=None):
        return [{"file_id": key} for key in cache if key.startswith(prefix)]

    async def blob_delete(key, kb=None):
        cache.pop(key, None)
        return True

    def convert(data, _ext):
        if data == b"version A":
            a_started.set()
            assert release_a.wait(timeout=10)
        return b"pdf:" + data

    monkeypatch.setattr(gw, "_owned_session", owned)
    monkeypatch.setattr(gw, "_container_file_bytes", file_bytes)
    monkeypatch.setattr(gw, "_blob_get", blob_get)
    monkeypatch.setattr(gw, "_blob_put", blob_put)
    monkeypatch.setattr(gw, "_blob_list_all", blob_list)
    monkeypatch.setattr(gw, "_blob_delete", blob_delete)
    monkeypatch.setattr(gw, "_convert_to_pdf", convert)
    monkeypatch.setattr(gw, "_SOFFICE", "soffice")

    stale_request = asyncio.create_task(gw.container_file_pdf(sid, fid, request=None))
    assert await asyncio.to_thread(a_started.wait, 10)
    source[0] = b"version B"
    fresh = await gw.container_file_pdf(sid, fid, request=None)
    assert fresh.body == b"pdf:version B"
    release_a.set()
    assert (await stale_request).body == b"pdf:version A"

    # A finishing last may evict B's cached object as best-effort cleanup, but it cannot replace
    # B's bytes under B's key. A later request therefore always returns B, even if reconversion is needed.
    latest = await gw.container_file_pdf(sid, fid, request=None)
    assert latest.body == b"pdf:version B"
    current_key = f"previews/{sid}/{fid}/{hashlib.sha256(b'version B').hexdigest()}.pdf"
    assert cache[current_key] == b"pdf:version B"
