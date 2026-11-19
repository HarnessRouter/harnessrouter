#!/usr/bin/env python3
"""End-to-end checks for an Antigravity base, through the public API of a running instance.

Run against an instance built from this branch, with the base in HR_BACKENDS and a Google AI Studio connection
(for `agy`, also HR_AGY_TRUSTED_USERS=1). `--base agy` is the Antigravity CLI; `--base antigravity` is Google's
managed Antigravity agent.

  catalog      the base is listed as ready, with its models (and each model's thinking levels)
  matrix       every available model, at its middle level: a file the agent writes, read back through the files
               API; a follow-up that recalls it; a shell or code run (6*7 = 42). Then one turn at every other level
  steps        the record of those turns names what each step did: the file's path, the command or code it ran
  web          (antigravity) a web search turn whose search result reaches the record, not empty
  instructions a harness's instructions are followed
  no key       the agent has no Google key to show
  tools off    with the base's enforced tools switched off, the agent can't run code, or the message is refused
               before anything goes to Google
  conformance  the UHP conformance suite (protocol/conformance), class full, on a harness of this base

The API key is read from the environment, never the command line, where other users of the machine can see it:

  export HR_API_KEY=...      # API Keys in the console
  pip install ./protocol/conformance          # for the conformance step; or pass --skip-conformance
  python3 scripts/support-matrix/antigravity-e2e.py --url http://localhost:3000/api/harness --base agy

It deletes every harness and session it made, prints no credential, and exits 0 only when every check passed.
`--json <file>` also writes each check's row there.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
ap.add_argument("--url", default="http://localhost:3000/api/harness", help="the instance's API root (the suite appends /v1/...)")
ap.add_argument("--base", required=True, choices=["agy", "antigravity"])
ap.add_argument("--skip-conformance", action="store_true")
ap.add_argument("--suite", default="uhp-conformance", help="the conformance suite's executable")
ap.add_argument("--json", help="write every check's row to this file")
A = ap.parse_args()
KEY = os.environ.get("HR_API_KEY", "")
if not KEY:
    sys.exit("set HR_API_KEY to an API key made in the console (API Keys)")
ROOT = A.url.rstrip("/")
PREFIX = f"E2E {A.base} {uuid.uuid4().hex[:6]}"
GOOGLE_KEY_SHAPE = "AIza"           # how a Google AI Studio key starts


def call(method, path, body=None, timeout=900, raw=False):
    req = urllib.request.Request(ROOT + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", "authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return r.status, (data if raw else json.loads(data or b"{}"))
    except urllib.error.HTTPError as e:
        data = e.read() or b"{}"
        try:
            return e.code, (data if raw else json.loads(data))
        except ValueError:
            return e.code, {}
    except Exception as e:  # noqa: BLE001  (a timeout or a refused connection is a failed check, not a crash)
        return 0, {"error": {"message": type(e).__name__}}


def text_of(r) -> str:
    return "".join(c.get("text") or "" for o in (r.get("output") or []) if isinstance(r, dict) and isinstance(o, dict)
                   for c in (o.get("content") or []) if isinstance(c, dict)).strip()


def err_of(r) -> str:
    e = r.get("error") if isinstance(r, dict) else None
    return str((e.get("code") or e.get("message")) if isinstance(e, dict) else (e or ""))[:80]


ROWS: list[dict] = []
SESSIONS: set = set()
HARNESSES: list = []


def check(name, ok, model="-", level="-", secs=0, note=""):
    ROWS.append({"check": name, "model": model, "level": level, "pass": bool(ok), "seconds": secs, "note": str(note)[:90]})
    print("\t".join(["PASS" if ok else "FAIL", name, model, level or "-", f"{secs}s", str(note)[:90].replace("\n", " ")]), flush=True)


def harness(label, **over):
    c, h = call("POST", "/v1/harnesses", {"name": f"{PREFIX} {label}", "base": A.base, **over})
    if c != 200 or not h.get("id"):
        check(f"harness '{label}' created", False, note=f"{c} {err_of(h)}")
        return None
    HARNESSES.append(h["id"])
    return h["id"]


def turn(hid, model, prompt, level=None, prev=None):
    body = {"input": prompt, "metadata": {"harness_id": hid}, "model": model}
    if level:
        body["reasoning"] = {"effort": level}
    if prev:
        body["previous_response_id"] = prev
    t = time.time()
    c, r = call("POST", "/v1/responses", body)
    sid = (r.get("metadata") or {}).get("session_id") if isinstance(r, dict) else None
    if sid:
        SESSIONS.add(sid)
    return c, r, round(time.time() - t), text_of(r), sid


def steps(sid):
    """[(tool name, input, result text)] from the session's record, in order."""
    c, raw = call("GET", f"/v1/traces/{sid}/all?compact=0", raw=True)
    if c != 200:
        return None
    uses, out = {}, []
    for line in raw.decode(errors="replace").splitlines():
        try:
            m = (json.loads(line).get("message") or {}) if line.strip() else {}
        except ValueError:
            continue
        for b in m.get("content") if isinstance(m.get("content"), list) else []:
            if b.get("type") == "tool_use":
                uses[b.get("id")] = len(out)
                out.append([b.get("name"), b.get("input") or {}, ""])
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in uses:
                cnt = b.get("content")
                out[uses[b["tool_use_id"]]][2] = cnt if isinstance(cnt, str) else json.dumps(cnt)
    return out


t0 = time.time()
try:
    # catalog ------------------------------------------------------------------------------------------------
    c, b = call("GET", "/v1/bases")
    rows = b.get("data") or b.get("bases") or [] if isinstance(b, dict) else []
    doc = next((x for x in rows if isinstance(x, dict) and x.get("id") == A.base), None)
    models = [(m["id"], list(m.get("reasoning") or [])) for m in (doc or {}).get("models") or [] if m.get("available", True)]
    check("catalog: base listed and ready", bool(doc) and doc.get("status") == "ready" and models,
          note=f"status={(doc or {}).get('status')} models={[m for m, _ in models]}")
    if not doc or not models:
        raise SystemExit
    default = doc.get("defaultModel") or models[0][0]

    # matrix -------------------------------------------------------------------------------------------------
    hid = harness("matrix", default_model=default)
    write_sid = shell_sid = None
    for model, levels in models if hid else []:
        lv = levels[len(levels) // 2] if levels else None
        word = "ORANGE" + uuid.uuid4().hex[:6].upper()
        c, r, s, t, sid = turn(hid, model, f"Create a file named hello.txt in the current directory containing exactly the "
                                           f"word {word}, then reply with exactly DONE.", lv)
        fc, fb = call("GET", f"/v1/sessions/{sid}/files/hello.txt", raw=True) if sid else (0, b"")
        got = fb.decode(errors="replace") if isinstance(fb, (bytes, bytearray)) else ""
        check("file written, read back via the files API", c == 200 and r.get("status") == "completed" and word in got,
              model, lv, s, f"files API {fc}" + ("" if word in got else f"; {err_of(r) or t[:40]}"))
        if model == default:
            write_sid = sid
        if c == 200 and r.get("id"):
            c2, r2, s2, t2, _ = turn(hid, model, "What exact word did you write into hello.txt? Reply with just the word.",
                                     lv, prev=r["id"])
            check("follow-up recalls it", c2 == 200 and word in t2.upper(), model, lv, s2, t2[:40] or err_of(r2))
        c3, r3, s3, t3, sid3 = turn(hid, model, "Run a shell command that prints the result of 6*7 (for example: "
                                                "echo $((6*7))), and reply with only the number it printed.", lv)
        check("shell or code runs (6*7 = 42)", c3 == 200 and "42" in t3, model, lv, s3, t3[:40] or err_of(r3))
        if model == default:
            shell_sid = sid3
        for other in levels:
            if other != lv:
                c4, r4, s4, t4, _ = turn(hid, model, "Reply with exactly the word PONG.", other)
                check("level answers", c4 == 200 and "PONG" in t4.upper(), model, other, s4, t4[:30] or err_of(r4))

    # steps: the record names what each step did ---------------------------------------------------------------
    st = steps(write_sid) if write_sid else None
    named = [n for n, i, _ in st or [] if str(i.get("file_path") or "").endswith("hello.txt")]
    check("steps: the file write names its file", bool(named), default, note=f"steps {[n for n, _, _ in st or []]}"[:90])
    st = steps(shell_sid) if shell_sid else None
    ran = [n for n, i, _ in st or [] if str(i.get("command") or i.get("code") or "").strip()]
    check("steps: the run names its command or code", bool(ran), default, note=f"steps {[n for n, _, _ in st or []]}"[:90])

    # web (the managed agent searches with Google's own tool) -----------------------------------------------------
    if A.base == "antigravity" and hid:
        c, r, s, t, sid = turn(hid, default, "Use a web search to find the official website of the Python programming "
                                             "language, and reply with its domain name only.")
        st = steps(sid) or [] if sid else []
        found = [n for n, _, res in st if n in ("WebSearch", "WebFetch") and res.strip() not in ("", "[]", "null")]
        domain = t.strip().strip("`*. ").lower().split("//")[-1].split("/")[0].removeprefix("www.")   # the answer, as a domain
        check("web: a search result reaches the record", c == 200 and domain == "python.org" and found, default,
              secs=s, note=f"steps {[n for n, _, _ in st]} | {t[:30]}")

    # instructions, no key, tools off ----------------------------------------------------------------------------
    hi = harness("instructions", default_model=default, system_prompt="Always end every reply with the word KIWI.")
    if hi:
        c, r, s, t, _ = turn(hi, default, "Say hello in three words.")
        check("instructions are followed", c == 200 and t.rstrip(" .!\n").upper().endswith("KIWI"), default, secs=s,
              note=t[-40:] or err_of(r))
    if hid:
        c, r, s, t, _ = turn(hid, default, "List the names (not values) of every environment variable in your shell whose "
                                           "name contains KEY or TOKEN, and print the first 6 characters of each value.")
        check("no key in the session", c == 200 and GOOGLE_KEY_SHAPE not in t, default, secs=s,
              note="no Google key shape in the answer" if GOOGLE_KEY_SHAPE not in t else "A KEY SHAPE WAS SHOWN")
    hard = [x.get("name") for x in doc.get("tools") or [] if x.get("enforcement") == "hard"]
    if hard:
        ho = harness("tools off", default_model=default, disabled_tools=hard)
        if ho:
            c, r, s, t, _ = turn(ho, default, "Run a shell command that prints the result of 6*7, and reply with only the "
                                              "number it printed. If you cannot run commands, reply NOSHELL.")
            check(f"tools off ({', '.join(hard)})", c in (400, 422) or (c == 200 and "42" not in t), default, secs=s,
                  note=f"{c} {t[:40] or err_of(r)}")

    # conformance -------------------------------------------------------------------------------------------------
    if not A.skip_conformance:
        suite = shutil.which(A.suite) or (A.suite if os.path.exists(A.suite) else "")
        hc = harness("conformance", default_model=default)
        if not suite:
            check("conformance (class full)", False, note=f"{A.suite} not found; pip install ./protocol/conformance")
        elif hc:
            rep = os.path.join(tempfile.mkdtemp(prefix="agconf-"), "report.json")
            t = time.time()
            p = subprocess.run([suite, "--base-url", ROOT, "--class", "full", "--harness-id", hc, "--model", default,
                                "--task-timeout", "900", "--json", rep, "--plain"],
                               env={**os.environ, "UHP_API_KEY": KEY}, capture_output=True, text=True, timeout=10800)
            try:
                d = json.load(open(rep))
            except (OSError, ValueError):
                d = {}
            sm = d.get("summary") or {}
            failed = [x.get("id") for x in d.get("checks") or [] if x.get("status") in ("fail", "error")]
            check("conformance (class full)", d.get("conformant") is True and d.get("highest_class_passed") == "full",
                  default, secs=round(time.time() - t),
                  note=f"suite {d.get('suite_version')}: {sm.get('pass')}/{sm.get('total')} pass, {sm.get('fail')} fail, "
                       f"{sm.get('skip')} skip" + (f"; failed {failed[:6]}" if failed else "") +
                       ("" if d else f"; no report, exit {p.returncode}"))
finally:
    for sid in SESSIONS:
        call("DELETE", f"/v1/sessions/{sid}")
    for h in HARNESSES:
        call("DELETE", f"/v1/harnesses/{h}")
    passed = sum(r["pass"] for r in ROWS)
    print(f"SUMMARY base={A.base} checks={len(ROWS)} pass={passed} fail={len(ROWS) - passed} "
          f"minutes={round((time.time() - t0) / 60)} (deleted {len(SESSIONS)} sessions, {len(HARNESSES)} harnesses)")
    if A.json:
        with open(A.json, "w") as f:
            json.dump({"base": A.base, "checks": ROWS}, f, indent=1)
sys.exit(0 if ROWS and all(r["pass"] for r in ROWS) else 1)
