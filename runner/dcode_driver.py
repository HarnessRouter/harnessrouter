"""One deepagents-code turn, as a runner subprocess.

WHY A DRIVER AT ALL. `dcode -n "<task>" -q` prints the agent's answer as prose and nothing else:
there is no event stream and no machine-readable mode for a turn (`--json` is for its `threads`,
`config` and `doctor` commands). The runner's own event loop only passes lines that parse as JSON to
a normaliser and keeps everything else as a bounded failure tail, so a text-only CLI needs a process
in front of it — the shape aider has here, for the same reason.

What this process does that the runner cannot:
  * keeps the CLI's two streams APART. The runner merges stderr into stdout, which is right for a
    CLI whose events are JSON (a stray diagnostic cannot be mistaken for an event) and wrong for one
    whose stdout IS the answer: its Tavily notice or a ripgrep install line would become part of
    what the user reads.
  * reads the THREAD ID out of the CLI's own store. Nothing in the output carries it, and the
    gateway needs it to continue the conversation: `dcode_thread_workspaces` in
    $HOME/.deepagents/.state/sessions.db has one row per thread with the cwd it ran in, so the id
    of the conversation this turn used is the row that was not there when it started.

The answer is emitted as ONE assistant message when the CLI exits rather than streamed: with `-q`
the CLI itself buffers until it has an answer, so there is nothing to stream before then.

Protocol: claude's stream-json on stdout, one object per line, which is why this backend's
normaliser in server.py is the passthrough.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import subprocess
import sys


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def threads(db: pathlib.Path, cwd: str) -> list[str]:
    """Thread ids for this workspace, newest first, from the CLI's own table."""
    if not db.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute(
            "SELECT thread_id FROM dcode_thread_workspaces WHERE cwd = ? ORDER BY created_at DESC",
            (cwd,)).fetchall()
        if not rows:
            rows = con.execute(
                "SELECT thread_id FROM dcode_thread_workspaces ORDER BY created_at DESC").fetchall()
        return [str(r[0]) for r in rows if r and r[0]]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def main() -> int:
    job = json.loads(sys.argv[1])
    cwd = str(job["cwd"])
    db = pathlib.Path(job["db"])
    before = set(threads(db, cwd))
    env = {**os.environ, **{str(k): str(v) for k, v in (job.get("env") or {}).items()}}
    try:
        proc = subprocess.run(job["argv"], cwd=cwd, env=env, text=True,
                              stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=job.get("timeout") or None)
    except subprocess.TimeoutExpired:
        emit({"type": "result", "subtype": "error", "is_error": True,
              "result": "the turn stopped at its time limit", "usage": {}})
        return 0
    except OSError as e:
        emit({"type": "result", "subtype": "error", "is_error": True,
              "result": f"dcode did not start: {e}", "usage": {}})
        return 0
    answer = (proc.stdout or "").strip()
    # Its own diagnostics, kept for a turn that failed: the reason is here, never in the answer.
    noise = (proc.stderr or "").strip()
    after = threads(db, cwd)
    fresh = [t for t in after if t not in before] or after
    if fresh:
        emit({"type": "system", "subtype": "init", "session_id": fresh[0],
              "model": job.get("model") or ""})
    ok = proc.returncode == 0
    if answer and ok:
        emit({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}})
    # 124 is the CLI's documented code for its own --timeout expiring.
    why = ""
    if not ok:
        why = ("the turn stopped at its time limit" if proc.returncode == 124
               else (noise or answer or f"dcode exited {proc.returncode}")[-2000:])
    emit({"type": "result", "subtype": "success" if ok else "error", "is_error": not ok,
          # usage is the relay's to stamp (_fill_relay_usage): the headless path reports none.
          "result": answer if ok else why, "usage": {}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
