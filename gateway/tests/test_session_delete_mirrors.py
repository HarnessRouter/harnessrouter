"""A deleted session leaves no card behind in any mirror.

Session cards are mirrored per harness, per member and per workspace, and the delete used to
derive the mirror keys from one manifest. A session deleted before its finalize (no manifest
yet), or one whose finalize dropped a scope field, had its flat card removed and its mirrors
left holding a "running" card for a session that no longer existed — the harness tree kept
listing it. The delete now takes every source of the scope it can get, and the indexer carries
scope fields forward so a rewrite never shrinks the mirror set.
"""
import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

BASE = "local/98211493921626_hsessmirrortest"
CARD = {"session_id": "hsessmirrortest", "harness_id": "pi", "member_id": "local@localhost",
        "workspace": "dev", "status": "running", "title": "t"}


def _keys():
    return A._manifest_index_keys(BASE, "pi", "local@localhost", "dev")


async def _present():
    out = {}
    for k in _keys():
        out[k] = bool(await A._blob_get(k, kb=A.TRACE_KB))
    return out


def test_a_delete_with_a_fieldless_manifest_still_clears_every_mirror():
    async def run():
        await A._index_manifest(BASE, dict(CARD))
        assert all((await _present()).values()), "the accept-time card should sit in all four keys"
        # the finalize that lost its scope: a manifest with none of the fields, as the delete sees it
        await A._deindex_manifest(BASE, {"session_id": "hsessmirrortest", "status": "done"},
                                  {"harness_id": "pi", "member": "local@localhost", "workspace": "dev"})
        return await _present()
    left = asyncio.run(run())
    assert not any(left.values()), f"cards left behind after delete: {[k for k, v in left.items() if v]}"


def test_a_reindex_without_scope_fields_inherits_them_and_rewrites_the_mirrors():
    async def run():
        await A._index_manifest(BASE, dict(CARD))
        await A._index_manifest(BASE, {"session_id": "hsessmirrortest", "status": "done", "title": "t"})
        statuses = {}
        for k in _keys():
            b = await A._blob_get(k, kb=A.TRACE_KB)
            statuses[k] = json.loads(b)["status"] if b else None
        await A._deindex_manifest(BASE, dict(CARD))
        return statuses
    statuses = asyncio.run(run())
    assert all(v == "done" for v in statuses.values()), f"a mirror kept the stale card: {statuses}"
