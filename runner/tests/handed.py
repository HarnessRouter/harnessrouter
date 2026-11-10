"""What a builder hands its CLI as the prompt (server._prompt_handover), for tests that call a builder on its
own: build() runs it as a turn would, with a turn's prompt record, reads the record the way the CLI reads it,
and keeps the text by the session folder it was made in (by_folder)."""
import os
import pathlib
import stat
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

_BY_FOLDER: dict[str, list] = {}


def build(fn, *args, **kwargs):
    """What `fn` returns. The prompt file is gone afterwards, as at the end of a turn."""
    rec: dict = {}
    tok = server._TURN_PROMPT.set(rec)
    try:
        out = fn(*args, **kwargs)
        if rec.get("cwd"):
            _BY_FOLDER.setdefault(os.path.realpath(rec["cwd"]), []).append(text(rec))
        return out
    finally:
        server._TURN_PROMPT.reset(tok)
        server._prompt_discard(rec)


def by_folder(d) -> list:
    """The text each build() in session folder `d` handed its CLI, in order."""
    return list(_BY_FOLDER.get(os.path.realpath(str(d)), []))


def text(rec: dict) -> str | None:
    """On stdin: the open descriptor, from its start (a pipe, to its end). By path: the file the argv names."""
    if rec.get("stdin") and rec.get("fd") is not None:
        if stat.S_ISFIFO(os.fstat(rec["fd"]).st_mode):
            out = b""
            while chunk := os.read(rec["fd"], 1 << 16):
                out += chunk
            return out.decode()
        return os.pread(rec["fd"], 1 << 22, 0).decode()
    if rec.get("path") and os.path.exists(rec["path"]):
        return pathlib.Path(rec["path"]).read_text()
    return None
