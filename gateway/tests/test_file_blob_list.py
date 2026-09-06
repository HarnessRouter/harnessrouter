"""The local blob store lists by walking only the subtree its prefix names, in key order, paged."""
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from backing import FileBlobStore  # noqa: E402


def _store(tmp_path):
    st = FileBlobStore(str(tmp_path))
    for k in ("a/idx/1", "a/idx/2", "a/idxh/x/3", "a/other/4", "b/idx/5", "top"):
        assert asyncio.run(st.put("kb", k, b"x"))
    (tmp_path / "kb" / "a" / "idx" / "9.tmp").write_bytes(b"torn")
    return st


def test_a_directory_prefix_lists_its_files_only(tmp_path):
    st = _store(tmp_path)
    r = asyncio.run(st.list("kb", "a/idx/", limit=20))
    assert [i["file_id"] for i in r["items"]] == ["a/idx/1", "a/idx/2"] and r["cursor"] is None


def test_a_name_prefix_spans_sibling_directories(tmp_path):
    st = _store(tmp_path)
    r = asyncio.run(st.list("kb", "a/idx", limit=20))
    assert [i["file_id"] for i in r["items"]] == ["a/idx/1", "a/idx/2", "a/idxh/x/3"]


def test_paging_follows_the_cursor(tmp_path):
    st = _store(tmp_path)
    first = asyncio.run(st.list("kb", "a/", limit=2))
    assert [i["file_id"] for i in first["items"]] == ["a/idx/1", "a/idx/2"] and first["cursor"] == "a/idx/2"
    rest = asyncio.run(st.list("kb", "a/", limit=2, cursor=first["cursor"]))
    assert [i["file_id"] for i in rest["items"]] == ["a/idxh/x/3", "a/other/4"] and rest["cursor"] is None


def test_the_walk_starts_at_the_prefix_directory_not_the_store(tmp_path, monkeypatch):
    st = _store(tmp_path)
    tops = []
    real = os.walk
    monkeypatch.setattr(os, "walk", lambda top, *a, **k: (tops.append(str(top)), real(top, *a, **k))[1])
    asyncio.run(st.list("kb", "a/idx/", limit=20))
    assert tops == [str((tmp_path / "kb" / "a" / "idx").resolve())]


def test_an_empty_prefix_lists_the_whole_store(tmp_path):
    st = _store(tmp_path)
    r = asyncio.run(st.list("kb", "", limit=20))
    assert [i["file_id"] for i in r["items"]] == ["a/idx/1", "a/idx/2", "a/idxh/x/3", "a/other/4", "b/idx/5", "top"]


def test_a_prefix_that_escapes_the_store_lists_nothing(tmp_path):
    st = _store(tmp_path)
    assert asyncio.run(st.list("kb", "../", limit=20)) == {"items": [], "cursor": None}
