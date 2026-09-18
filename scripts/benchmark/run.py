"""Benchmark runner: harness x model x pack x task, through the instance's own API.

One task is one session: the pack stages the files and the first message, the turn runs, the
produced files come back from the session, the pack's grader decides, and every number in the
record is read from the turn record the runner already stores. Nothing is instrumented here.
Resumable: a task already recorded for a harness x model x pack is skipped; a record carrying
`error` (this runner's own failure, not the turn's) is re-run.

Env: BASE (the API base, e.g. http://127.0.0.1:3000/api/harness), HR_API_KEY, PACK, PACK_ROOT,
HARNESSES (comma list of label=id; a custom harness is its chrn_ id, a built-in its backend name),
MODELS (comma), PROVIDER (a label for the column), EXPECT_CONNECTION (the connection under test,
integration:<name>; any other one is a finding), TASKS (first:N, or a comma list of ids; default
all), RESULTS (json path), LOG (append log), WORKDIR (produced files), WORKERS (parallel tasks per
harness, default 1), KEEP=1 to leave sessions on the instance (they are deleted once graded, as
the support matrix does, since a pack's worth of workspaces fills a disk).
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "support-matrix"))
import packs  # noqa: E402
from samemodel import alias_of  # noqa: E402  — the matrix's rule 2, verbatim

BASE = os.environ.get("BASE", "http://127.0.0.1:3000/api/harness").rstrip("/")
KEY = os.environ.get("HR_API_KEY", "")
LOG = os.environ.get("LOG", "")
_lock = threading.Lock()


def log(s: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {s}"
    with _lock:
        print(line, flush=True)
        if LOG:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")


def api(method: str, path: str, body=None, raw: bool = False, timeout: int = 1800):
    req = urllib.request.Request(BASE + path, method=method, headers={"authorization": f"Bearer {KEY}"})
    data = None
    if body is not None:
        req.add_header("content-type", "application/json")
        data = json.dumps(body).encode()
    with urllib.request.urlopen(req, data, timeout=timeout) as r:
        return r.read() if raw else json.loads(r.read())


# ── rule 3: a turn that reached the network is a finding, never a score ──────────────────────────
# The first pilot's third task fetched its own ground truth from the suite's public data because
# the task id was in a filename and the sandbox has internet. Packs anonymise; this reads the tool
# calls the runner stored for the turn and names any that went out for anything but pip.
WEB_TOOL = re.compile(r"web|fetch|search|browse|http", re.I)
# What makes a request from a shell or a script, not what merely spells a URL: the XML namespaces
# inside an xlsx are http:// strings, and a turn parsing one with zipfile went nowhere. Package
# installs (pip, npm) are the sandbox's normal traffic and are not the task's answer.
NET_IN_SHELL = re.compile(r"\b(curl|wget|git\s+clone)\b|\burllib\.request\b|\brequests\.(?:get|post|request|Session)\b"
                          r"|\bhttpx\.|\baiohttp\b", re.I)


def network_use(tools: list[dict]) -> list[str]:
    hits = []
    for t in tools or []:
        name = str(t.get("name") or "")
        args = t.get("arguments") or ""
        if WEB_TOOL.search(name):
            hits.append(name)
            continue
        cmd = args
        if isinstance(args, str) and args.startswith("{"):
            try:
                cmd = json.loads(args).get("command", "")
            except ValueError:
                cmd = args
        if isinstance(cmd, str) and NET_IN_SHELL.search(cmd):
            hits.append(f"{name}: {cmd[:120]}")
    return hits


# ── usage on one convention ───────────────────────────────────────────────────────────────────────
# The runner's contract is input_tokens = fresh input, cache reads and writes beside it (codex,
# gemini and, since #209, cline are netted to it). The table reports fresh, cached and output
# separately and never adds a cached read to the input it was read from.
def usage_of(u: dict | None) -> dict:
    u = u or {}
    fresh = int(u.get("input_tokens") or 0)
    cached = int(u.get("cache_read_tokens") or 0)
    written = int(u.get("cache_write_tokens") or 0)
    out = int(u.get("output_tokens") or 0)
    return {"fresh_input": fresh, "cached_input": cached, "cache_write": written, "output": out,
            "prompt_total": fresh + cached + written}


def recover_session(before: set[str], harness_id: str, prompt: str, t0: float, wait_s: int = 1800) -> dict | None:
    """The session this harness opened for this prompt since t0 that was not there before, once
    it has finished: an instance whose console proxy cuts a synchronous request at five minutes
    (fixed by #214) still ran the turn, and the record is the record. With several workers the
    prompt tells the sessions apart; a session whose stored prompt cannot be read is taken only
    when it is the sole new one."""
    deadline = t0 + wait_s
    mark = prompt.strip()[-160:]
    while time.time() < deadline:
        new = [s for s in api("GET", "/v1/sessions?limit=100").get("sessions", [])
               if s["session_id"] not in before and harness_id in (s.get("harness_id"), s.get("backend"))]
        mine = [s for s in new if mark and mark in str(s.get("user_prompt") or "")]
        if not mine and len(new) == 1:
            mine = new
        if not mine:
            return None
        if mine[0].get("status") not in ("running", "queued", None):
            return mine[0]
        time.sleep(10)
    return None


def run_task(pack, root: str, task: dict, label: str, harness_id: str, model: str, provider: str, workdir: str) -> dict:
    staged = pack.stage(task, root)
    content = [{"type": "input_text", "text": staged["prompt"]}]
    for name, data in staged["files"]:
        content.append({"type": "input_file", "filename": name,
                        "file_data": "data:application/octet-stream;base64," + b64encode(data).decode()})
    body = {"input": [{"role": "user", "content": content}], "metadata": {"harness_id": harness_id},
            "model": model, "stream": False}
    rec = {"provider": provider, "harness": label, "harness_id": harness_id, "model": model, "pack": pack.NAME,
           "task": task["id"], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    before = {s["session_id"] for s in api("GET", "/v1/sessions?limit=50").get("sessions", [])}
    t0 = time.time()
    sid = rid = None
    try:
        resp = api("POST", "/v1/responses", body)
        rid = resp.get("id")
        while resp.get("status") in ("in_progress", "queued"):
            time.sleep(5)
            resp = api("GET", f"/v1/responses/{rid}")
        rec.update(status=resp.get("status"), wall_s=round(time.time() - t0, 1), sid=(resp.get("metadata") or {}).get("session_id"),
                   usage=usage_of(resp.get("usage")), turn_error=resp.get("error"))
        sid = rec["sid"]
    except (urllib.error.HTTPError, TimeoutError, OSError) as e:
        err = f"{e.code} {e.read()[:200]!r}" if isinstance(e, urllib.error.HTTPError) else repr(e)[:200]
        sess = recover_session(before, harness_id, staged["prompt"], t0)
        if sess is None:
            rec.update(error=f"request failed and no session found: {err}", wall_s=round(time.time() - t0, 1))
            return rec
        rec.update(status="completed" if sess.get("status") == "done" else sess.get("status"), recovered=err,
                   wall_s=sess.get("elapsed") or round(time.time() - t0, 1), sid=sess["session_id"],
                   usage=usage_of(sess.get("usage")), turn_error=None)
        sid, rid = sess["session_id"], sess.get("last_response_id")
    if not sid:
        rec["error"] = "no session id on the response"
        return rec
    turns = api("GET", f"/v1/sessions/{sid}/turns").get("turns", [])
    turn = next((t for t in turns if t.get("id") == rid), turns[-1] if turns else {})
    tools = turn.get("tools") or []
    served = str(turn.get("served_model") or "")
    rec.update(connection=turn.get("connection"), served=served,
               substituted=bool(served) and not alias_of(model, served),
               served_unreported=not served,
               tool_calls=len(tools), tools=sorted({str(t.get("name")) for t in tools}),
               network=network_use(tools), files=[f.get("filename") for f in (turn.get("files") or [])],
               assistant=(turn.get("assistant") or "")[:200])
    if rec.get("turn_error") is None and turn.get("error"):
        rec["turn_error"] = turn.get("error")
    # the produced files, downloaded from the session so the pack grades what was stored
    tdir = os.path.join(workdir, provider, label, model, pack.NAME, task["id"])
    os.makedirs(tdir, exist_ok=True)
    produced = {}
    for f in turn.get("files") or []:
        name = f.get("filename") or ""
        if not name or f.get("download_url") is None:
            continue
        path = os.path.join(tdir, os.path.basename(name))
        with open(path, "wb") as fh:
            fh.write(api("GET", f["download_url"], raw=True))
        produced[name] = path
    g = pack.grade(task, root, produced, tdir)
    rec.update(reward=g["reward"], resolved=bool(g["resolved"]), detail=g.get("detail", ""))
    if os.environ.get("KEEP") != "1":
        try:
            api("DELETE", f"/v1/sessions/{sid}")
        except Exception as e:  # noqa: BLE001
            rec["not_deleted"] = repr(e)[:80]
    return rec


def main() -> None:
    pack = packs.get(os.environ["PACK"])
    root = os.environ["PACK_ROOT"]
    provider = os.environ.get("PROVIDER", "unlabelled")
    expect = os.environ.get("EXPECT_CONNECTION", "")
    results_path = os.environ.get("RESULTS", os.path.join(HERE, "results.json"))
    workdir = os.environ.get("WORKDIR", os.path.join(HERE, "work"))
    workers = int(os.environ.get("WORKERS", "1"))
    harnesses = [(h.split("=", 1)[0], h.split("=", 1)[-1]) for h in os.environ["HARNESSES"].split(",") if h]
    models = [m for m in os.environ["MODELS"].split(",") if m]
    tasks = pack.load(root)
    sel = os.environ.get("TASKS", "")
    if sel.startswith("first:"):
        tasks = tasks[:int(sel[6:])]
    elif sel:
        want = set(sel.split(","))
        tasks = [t for t in tasks if t["id"] in want]

    def load():
        try:
            return json.load(open(results_path, encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(rec):
        with _lock:
            res = load()
            res[key(rec)] = rec
            json.dump(res, open(results_path, "w", encoding="utf-8"), indent=1)

    def key(rec):
        return f"{rec['provider']}|{rec['harness']}|{rec['model']}|{rec['pack']}|{rec['task']}"

    for label, hid in harnesses:
        for model in models:
            todo = []
            res = load()
            for t in tasks:
                k = f"{provider}|{label}|{model}|{pack.NAME}|{t['id']}"
                if k in res and not res[k].get("error"):
                    continue
                todo.append(t)
            log(f"HARNESS {label} ({hid}) x {model}: {len(todo)} of {len(tasks)} tasks to run")

            def one(t):
                try:
                    rec = run_task(pack, root, t, label, hid, model, provider, workdir)
                except Exception as e:  # noqa: BLE001 — this runner's own failure, re-run next launch
                    rec = {"provider": provider, "harness": label, "harness_id": hid, "model": model,
                           "pack": pack.NAME, "task": t["id"], "error": repr(e)[:300]}
                if expect and rec.get("connection") and rec["connection"] != expect:
                    rec["foreign"] = rec["connection"]
                save(rec)
                verdict = ("ERROR " + rec["error"][:80]) if rec.get("error") else \
                    ("FINDING network" if rec.get("network") else "FINDING foreign" if rec.get("foreign") else
                     "FINDING substituted" if rec.get("substituted") else
                     ("pass" if rec.get("resolved") else f"FAIL {rec.get('detail', '')[:60]}"))
                log(f"TASK {label} x {model} {t['id']}: {verdict} {rec.get('wall_s', '?')}s tools={rec.get('tool_calls', '?')} "
                    f"served={rec.get('served') or 'unreported'} tokens={json.dumps(rec.get('usage') or {})}")

            with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
                list(ex.map(one, todo))
    log("DONE")


if __name__ == "__main__":
    main()
