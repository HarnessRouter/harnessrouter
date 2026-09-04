"""The protocol names the session delete.

DELETE /v1/sessions/{sid} and the older DELETE /v1/traces/{sid} are one handler: renaming would
break shipped clients for a cosmetic gain, so the new path is added and the old one kept.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402


def test_the_protocol_names_the_session_delete_and_the_old_path_is_the_same_handler():
    paths = {getattr(r, "path", ""): r for r in A.app.routes}
    a, b = paths.get("/v1/sessions/{sid}"), paths.get("/v1/traces/{sid}")
    assert a is not None and b is not None and "DELETE" in a.methods and "DELETE" in b.methods
    assert a.endpoint is b.endpoint
