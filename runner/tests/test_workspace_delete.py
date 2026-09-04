"""A session's working folder is removed on session delete, by the runner (Sessions §6).

Sessions own their folders (per-session uid, mode 700), so the gateway asks the runner, the one
process with the authority. The root is never removed, and a missing folder is not an error.
"""
import asyncio
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as S  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def test_the_folder_goes_and_the_root_and_a_missing_folder_are_safe(monkeypatch):
    # The module reads its root at import, and another test module may have imported it first:
    # point the root at a fresh directory for this test rather than depend on import order.
    _ROOT = tempfile.mkdtemp(prefix="hr-runner-ws-")
    monkeypatch.setattr(S, "WORKSPACE_ROOT", _ROOT)
    monkeypatch.setattr(S, "_SANDBOX_PER_SESSION", False)
    sid = "hsess0123456789abcdef0123456789abcdef"
    ws = S._ws(sid)
    os.makedirs(os.path.join(ws, "sub"), exist_ok=True)
    open(os.path.join(ws, "sub", "f.txt"), "w").write("x")
    out = asyncio.run(S.delete_workspace(sid))
    assert out["removed"] is True and not os.path.isdir(ws)
    assert os.path.isdir(_ROOT), "the workspace root must survive"
    again = asyncio.run(S.delete_workspace(sid))
    assert again["removed"] is False and again["reason"] == "no folder"
    try:
        asyncio.run(S.delete_workspace(""))
        assert False, "an empty identifier must be refused"
    except HTTPException as e:
        assert e.status_code == 400
