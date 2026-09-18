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


# The other way to look a task up: on the machine. Two turns that recognised the suite from its
# vocabulary grepped the whole filesystem for its data and tried to download it by name
# (measured 2026-09-18). A recursive grep or find rooted outside the workspace, or a package
# fetched under a suite's name, is a lookup; the workspace itself (/data/workspaces/…) is not.
OUTSIDE = r"(?:/|/(?:data|root|home|usr|opt|srv|var|etc)(?!/workspaces/)\S*)"
LOOKUP_IN_SHELL = re.compile(r"\bgrep\b[^|;&\n]*\s-[A-Za-z]*[rR][A-Za-z]*\b[^|;&\n]*\s" + OUTSIDE + r"(?:\s|$)"
                             r"|\brg\b[^|;&\n]*\s" + OUTSIDE + r"(?:\s|$)"
                             r"|\bfind\s+" + OUTSIDE + r"(?:\s|$)"
                             r"|\bpip3?\s+(?:download|install)\b[^\n]*\b\S*(?:bench|dataset)\S*", re.I)


def _command_of(t: dict) -> str:
    args = t.get("arguments") or ""
    if isinstance(args, str) and args.startswith("{"):
        try:
            return str(json.loads(args).get("command", ""))
        except ValueError:
            return args
    return args if isinstance(args, str) else ""


def network_use(tools: list[dict]) -> list[str]:
    hits = []
    for t in tools or []:
        name = str(t.get("name") or "")
        if WEB_TOOL.search(name):
            hits.append(name)
            continue
        cmd = _command_of(t)
        if NET_IN_SHELL.search(cmd):
            hits.append(f"{name}: {cmd[:120]}")
    return hits


def lookup_use(tools: list[dict]) -> list[str]:
    return [f"{t.get('name')}: {_command_of(t)[:120]}" for t in tools or [] if LOOKUP_IN_SHELL.search(_command_of(t))]


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


# ── tool outcomes ─────────────────────────────────────────────────────────────────────────────────
# The canonical stream pairs every tool_use with a tool_result. is_error is what the CLI flagged;
# it is not the whole story: opencode returns a shell that died with "[exit code: 1]" and a
# Traceback as an ordinary result (measured 2026-09-18), so a non-zero exit code or an interpreter
# traceback in the result counts as a failed call too. What is counted is calls that did not do
# what the agent asked, whatever the agent did next.
FAILED_RESULT = re.compile(r"\[exit code:? [1-9]\d*\]|\bexit(?:ed with)? code[:=]? ?[1-9]\d*\b"
                           r"|Traceback \(most recent call last\)|\bcommand not found\b", re.I)


def tool_outcomes(trace_ndjson: str) -> dict:
    calls = results = failed = 0
    for line in trace_ndjson.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        m = e.get("message") if isinstance(e, dict) else None
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                calls += 1
            elif b.get("type") == "tool_result":
                results += 1
                body = b.get("content")
                text = body if isinstance(body, str) else json.dumps(body)[:4000]
                if b.get("is_error") or FAILED_RESULT.search(text[:4000]):
                    failed += 1
    return {"trace_tool_calls": calls, "tool_results": results, "tool_failed": failed}


PROVIDER_ERROR = re.compile(r"\b(?:40[1239]|429|5\d\d)\b|insufficient balance|rate ?limit|quota|overloaded|api key|unauthori[sz]ed|billing",
                            re.I)


_streak = [0]
_streak_lock = threading.Lock()   # its own lock: log() takes _lock, and a caller may hold this while logging


def provider_streak(rec: dict, limit: int = 3) -> bool:
    """True once `limit` provider failures have arrived in a row; any other record resets the count."""
    with _streak_lock:
        _streak[0] = _streak[0] + 1 if str(rec.get("error") or "").startswith("provider failure") else 0
        return _streak[0] >= limit


def provider_failure(turn_error) -> str:
    """The provider's refusal in a failed turn's error, or '' when the error is something else."""
    msg = turn_error.get("message") if isinstance(turn_error, dict) else turn_error
    msg = str(msg or "")
    return msg[:160] if msg and PROVIDER_ERROR.search(msg) else ""


def prompt_matches(stored: str, prompt: str) -> bool:
    """Whether a session's stored prompt is this prompt. The session list keeps the prompt's head
    (1500 characters, measured), sometimes behind an attachment line, so the stored head — whole,
    or after that line — must be found in the prompt sent; its tail is not there to compare."""
    probes = [stored[:800]] + ([stored.split("\n\n", 1)[1][:600]] if "\n\n" in stored else [])
    return any(p and p in prompt for p in probes)


TASK_CAP_S = int(os.environ.get("TASK_CAP_S", "900"))


def recover_session(before: set[str], harness_id: str, prompt: str, t0: float, cap_s: int = TASK_CAP_S) -> dict | None:
    """The session this harness opened for this prompt since t0 that was not there before, once
    it has finished: an instance whose console proxy cuts a synchronous request at five minutes
    (fixed by #214) still ran the turn, and the record is the record. With several workers the
    prompt tells the sessions apart; a session whose stored prompt cannot be read is taken only
    when it is the sole new one. A turn still running at the task's time cap is cancelled and
    returned as it stands: the cap is part of the task, and two turns that grepped the whole
    filesystem for their answer ran for half an hour before this existed."""
    cancelled = False
    while True:
        new = [s for s in api("GET", "/v1/sessions?limit=100").get("sessions", [])
               if s["session_id"] not in before and harness_id in (s.get("harness_id"), s.get("backend"))]
        mine = [s for s in new if prompt_matches(str(s.get("user_prompt") or ""), prompt)]
        if not mine and len(new) == 1:
            mine = new
        if not mine:
            return None
        sess = mine[0]
        if sess.get("status") not in ("running", "queued", "starting", None):
            if cancelled:
                sess["capped"] = cap_s
            return sess
        if time.time() - t0 >= cap_s and not cancelled:
            try:
                api("POST", f"/v1/sessions/{sess['session_id']}/cancel", {})
            except urllib.error.HTTPError:
                pass
            cancelled = True
        if cancelled and time.time() - t0 >= cap_s + 180:
            sess["capped"] = cap_s   # the runner did not confirm the stop; the record is what it is
            return sess
        time.sleep(10)


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
        # the request waits as long as the task may; past that, the session is cancelled below
        resp = api("POST", "/v1/responses", body, timeout=TASK_CAP_S)
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
                   usage=usage_of(sess.get("usage")), turn_error=None, capped=sess.get("capped"))
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
               network=network_use(tools), lookup=lookup_use(tools),
               files=[f.get("filename") for f in (turn.get("files") or [])],
               assistant=(turn.get("assistant") or "")[:200])
    if rec.get("turn_error") is None and turn.get("error"):
        rec["turn_error"] = turn.get("error")
    # A turn the provider refused before the agent did anything measures the account, not the
    # harness: 150 records of "402 Insufficient Balance" arrived in eleven minutes once a key ran
    # dry (2026-09-18). That is this runner's problem to re-run, never the harness's failure.
    if not tools and rec.get("status") not in ("completed", "done") and provider_failure(rec.get("turn_error")):
        rec["error"] = "provider failure, not a result: " + provider_failure(rec.get("turn_error"))
        if os.environ.get("KEEP") != "1":
            try:
                api("DELETE", f"/v1/sessions/{sid}")
            except Exception:  # noqa: BLE001
                pass
        return rec
    # tool outcomes come from the stored trace: each tool_use has its tool_result, and a result the
    # CLI flagged or a shell that exited non-zero is a failed call (the record's own count of calls
    # stays the turn record's)
    try:
        trace = api("GET", f"/v1/traces/{sid}/all?org={os.environ.get('ORG', 'local')}", raw=True).decode("utf-8", "replace")
        rec.update(tool_outcomes(trace))
    except Exception as e:  # noqa: BLE001 — a trace that cannot be read leaves the outcome columns empty, noted
        rec["trace_error"] = repr(e)[:120]
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
    if rec.get("capped") and not rec["resolved"]:
        rec["detail"] = f"time cap {rec['capped']} s; " + rec["detail"]
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

    halt = threading.Event()
    for label, hid in harnesses:
        for model in models:
            if halt.is_set():
                break
            todo = []
            res = load()
            for t in tasks:
                k = f"{provider}|{label}|{model}|{pack.NAME}|{t['id']}"
                if k in res and not res[k].get("error"):
                    continue
                todo.append(t)
            log(f"HARNESS {label} ({hid}) x {model}: {len(todo)} of {len(tasks)} tasks to run")

            def one(t):
                if halt.is_set():
                    return
                try:
                    rec = run_task(pack, root, t, label, hid, model, provider, workdir)
                except Exception as e:  # noqa: BLE001 — this runner's own failure, re-run next launch
                    rec = {"provider": provider, "harness": label, "harness_id": hid, "model": model,
                           "pack": pack.NAME, "task": t["id"], "error": repr(e)[:300]}
                if expect and rec.get("connection") and rec["connection"] != expect:
                    rec["foreign"] = rec["connection"]
                # three provider refusals in a row: the account, the key or the provider is down,
                # and every further task would only record the same line
                if provider_streak(rec) and not halt.is_set():
                    halt.set()
                    log(f"HALT after three provider failures in a row: {rec['error'][:160]}")
                save(rec)
                verdict = ("ERROR " + rec["error"][:80]) if rec.get("error") else \
                    ("FINDING network" if rec.get("network") else "FINDING lookup" if rec.get("lookup") else
                     "FINDING foreign" if rec.get("foreign") else "FINDING substituted" if rec.get("substituted") else
                     ("pass" if rec.get("resolved") else f"FAIL {rec.get('detail', '')[:60]}"))
                log(f"TASK {label} x {model} {t['id']}: {verdict} {rec.get('wall_s', '?')}s tools={rec.get('tool_calls', '?')} "
                    f"served={rec.get('served') or 'unreported'} tokens={json.dumps(rec.get('usage') or {})}")

            with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
                list(ex.map(one, todo))
    if halt.is_set():
        log("HALTED: fix the provider and relaunch; records carrying error are re-run")
        sys.exit(2)
    log("DONE")


if __name__ == "__main__":
    main()
