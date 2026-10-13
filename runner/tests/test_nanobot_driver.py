"""runner/nanobot_driver.py — the in-process nanobot turn (HKUDS/nanobot, MIT, pinned to 0.3.5).

nanobot is not installed in the test environment (it lives in its own venv on the data volume), so
a FAKE `nanobot` module stands in for it. The fake is built from the SDK surface measured on 0.3.5
— the event constants, the StreamEvent fields, the RunResult fields, `Nanobot.from_config` and the
async context manager — and the entrypoint pins that surface at install time, so a release that
renames one of them fails the install rather than the first live turn.

What each test pins is one thing that would otherwise be wrong SILENTLY:
  * usage reported GROSS (it is a measured fact that cache_read is a SUBSET of input_tokens, so a
    pass-through would bill the cached part at ~10x)
  * a run that FAILED reported as a turn that completed with no answer
  * a tool policy set on the registry instead of the session, which would withhold the built-ins
    and let every MCP tool through
"""
import asyncio
import dataclasses
import json
import pathlib
import subprocess
import sys
import tempfile
import types

DRIVER = pathlib.Path(__file__).resolve().parents[1] / "nanobot_driver.py"

_CONSTS = {
    "STREAM_EVENT_RUN_STARTED": "run.started",
    "STREAM_EVENT_TEXT_DELTA": "text.delta",
    "STREAM_EVENT_TEXT_COMPLETED": "text.completed",
    "STREAM_EVENT_REASONING_DELTA": "reasoning.delta",
    "STREAM_EVENT_REASONING_COMPLETED": "reasoning.completed",
    "STREAM_EVENT_TOOL_STARTED": "tool.started",
    "STREAM_EVENT_TOOL_COMPLETED": "tool.completed",
    "STREAM_EVENT_TOOL_FAILED": "tool.failed",
    "STREAM_EVENT_RUN_COMPLETED": "run.completed",
    "STREAM_EVENT_RUN_FAILED": "run.failed",
}


def _fake_nanobot_source(events: list, usage: dict | None = None) -> str:
    """A `nanobot` package whose Nanobot.stream yields the events a real turn yields."""
    return f'''
import dataclasses, sys, types
_consts = {_CONSTS!r}
mod = types.ModuleType("nanobot")
for k, v in _consts.items():
    setattr(mod, k, v)

@dataclasses.dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens = None

@dataclasses.dataclass
class RunResult:
    content: str = ""
    tools_used: list = dataclasses.field(default_factory=list)
    usage: object = None
    stop_reason: str = "completed"
    error: str = ""

@dataclasses.dataclass
class StreamEvent:
    type: str
    delta: str = ""
    name: str = None
    tool_call_id: str = None
    arguments: dict = None
    error: str = None
    metadata: dict = dataclasses.field(default_factory=dict)
    usage: object = None
    result: object = None

# Faithful to nanobot/session/manager.py on 0.3.5: SessionPolicy is a FROZEN dataclass on a
# mutable Session, which is what makes dataclasses.replace the way to change it.
@dataclasses.dataclass(frozen=True)
class SessionPolicy:
    persist: bool = True
    log_content: bool = True
    disabled_tools: frozenset = frozenset()

@dataclasses.dataclass
class Session:
    key: str
    policy: SessionPolicy = dataclasses.field(default_factory=SessionPolicy)

class _Sessions:
    def __init__(self): self.calls = []
    def get_or_create(self, key):
        self.calls.append(key)
        s = POLICY.get("session") or Session(key=key)
        POLICY["session"] = s
        return s

class _Loop:
    def __init__(self): self.sessions = _Sessions()

POLICY = {{}}

class Nanobot:
    def __init__(self): self._loop = _Loop(); self.runtime = types.SimpleNamespace(model="m")
    @classmethod
    def from_config(cls, config_path=None, workspace=None):
        POLICY["config_path"] = config_path; POLICY["workspace"] = workspace
        return cls()
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def stream(self, message, session_key="sdk:default"):
        POLICY["prompt"] = message; POLICY["session_key"] = session_key
        for spec in {events!r}:
            kind = spec.pop("_kind")
            if kind == "run.completed":
                u = LLMUsage(**{usage or {}!r})
                yield StreamEvent(type=kind, result=RunResult(usage=u, **spec))
            else:
                yield StreamEvent(type=kind, **spec)

mod.Nanobot = Nanobot
mod.LLMUsage = LLMUsage
mod.RunResult = RunResult
mod.StreamEvent = StreamEvent
mod.POLICY = POLICY
mod.SessionPolicy = SessionPolicy
mod.Session = Session
mod._Sessions = _Sessions
sys.modules["nanobot"] = mod
'''


def _run(events, usage=None, job_extra=None):
    """Run the driver in a subprocess with the fake package injected, and parse its NDJSON."""
    d = tempfile.mkdtemp()
    (pathlib.Path(d) / "sitecustomize.py").write_text(_fake_nanobot_source(events, usage))
    job = {"config_path": f"{d}/config.json", "workspace": d, "model": "gpt-5.4",
           "prompt": "do it", "session_key": "hr:one", "tools_disabled": []}
    job.update(job_extra or {})
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": d}
    p = subprocess.run([sys.executable, str(DRIVER), json.dumps(job)],
                       capture_output=True, text=True, env=env)
    out = [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip().startswith("{")]
    return p, out


def _result(out):
    return next(e for e in out if e.get("type") == "result")


def test_a_normal_turn_becomes_claude_stream_json():
    p, out = _run([
        {"_kind": "run.started"},
        {"_kind": "tool.started", "name": "write_file", "tool_call_id": "c1",
         "arguments": {"path": "probe.txt"}},
        {"_kind": "tool.completed", "name": "write_file", "tool_call_id": "c1",
         "metadata": {"detail": "Written 6 bytes"}},
        {"_kind": "text.delta", "delta": "DONE"},
        {"_kind": "run.completed", "content": "DONE", "tools_used": ["write_file"]},
    ], usage={"input_tokens": 11107, "output_tokens": 29, "cache_read_tokens": 5503})
    assert p.returncode == 0, p.stderr
    assert out[0] == {"type": "system", "subtype": "init", "session_id": "hr:one", "model": "gpt-5.4"}
    use = next(e for e in out if "tool_use" in json.dumps(e))
    blk = use["message"]["content"][0]
    assert blk["name"] == "write_file" and blk["input"] == {"path": "probe.txt"}
    res_blk = next(e for e in out if "tool_result" in json.dumps(e))["message"]["content"][0]
    assert res_blk["is_error"] is False and res_blk["content"] == "Written 6 bytes"
    r = _result(out)
    assert r["subtype"] == "success" and r["is_error"] is False and r["result"] == "DONE"


def test_usage_is_netted_because_nanobot_reports_it_gross():
    # MEASURED on 0.3.5: a two-request turn reported input_tokens 11107 with cache_read_tokens
    # 5503, while its two requests reported 5506 and 5601 — the cached read is a SUBSET of the
    # input, not a sibling of it. Passing it through would bill 5503 cached tokens at the full
    # input rate, the exact overcharge _norm_token_usage's own comment describes.
    _p, out = _run([{"_kind": "run.completed", "content": "ok"}],
                   usage={"input_tokens": 11107, "output_tokens": 29, "cache_read_tokens": 5503})
    u = _result(out)["usage"]
    assert u["input_tokens"] == 11107 - 5503
    assert u["cache_read_tokens"] == 5503
    assert u["output_tokens"] == 29
    # cache_write_tokens is None on an endpoint that reports no write; it is read defensively and
    # simply left out rather than becoming a 0 the biller has to interpret.
    assert "cache_write_tokens" not in u


def test_a_failed_run_is_a_failed_turn_with_the_reason():
    _p, out = _run([
        {"_kind": "text.delta", "delta": "let me try"},
        {"_kind": "run.failed", "error": "provider returned 401"},
    ])
    r = _result(out)
    assert r["is_error"] is True and r["result"] == "provider returned 401"


def test_a_stop_reason_that_is_not_completion_fails_the_turn_and_is_the_reason():
    # A run that stopped on its iteration cap has not answered the question, and reporting its last
    # text as the answer is the failure-as-prose shape every normaliser here is written against.
    _p, out = _run([{"_kind": "run.completed", "content": "partial", "stop_reason": "max_iterations"}])
    r = _result(out)
    assert r["is_error"] is True and r["reason"] == "max_iterations"


def test_a_stream_that_ends_with_no_terminal_event_is_not_a_success():
    _p, out = _run([{"_kind": "text.delta", "delta": "half"}])
    r = _result(out)
    # An EMPTY result on purpose: the runner's stderr tail is the reason, and a sentence invented
    # here would shadow it.
    assert r["is_error"] is True and r["result"] == ""


def test_the_tool_policy_is_set_on_the_session_not_on_the_registry():
    # The loop re-reads session.policy.disabled_tools per turn and applies it to the registry it is
    # about to use — by which time the MCP provider has registered ITS tools into that registry
    # too. A registry filtered when the driver started would withhold the built-ins and let every
    # MCP tool through, which is openhands' half-policy defect.
    d = tempfile.mkdtemp()
    (pathlib.Path(d) / "sitecustomize.py").write_text(_fake_nanobot_source(
        [{"_kind": "run.completed", "content": "ok"}]) + '''
import json, atexit, sys
def _dump():
    s = sys.modules["nanobot"].POLICY.get("session")
    sys.stderr.write("POLICY=" + json.dumps(sorted(s.policy.disabled_tools) if s else None) + "\\n")
atexit.register(_dump)
''')
    job = {"config_path": f"{d}/config.json", "workspace": d, "model": "m", "prompt": "hi",
           "session_key": "hr:one", "tools_disabled": ["write_file (File Write)", "exec"]}
    p = subprocess.run([sys.executable, str(DRIVER), json.dumps(job)],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": d})
    line = next(l for l in p.stderr.splitlines() if l.startswith("POLICY="))
    assert json.loads(line[len("POLICY="):]) == ["exec", "write_file"]


def test_a_crashed_driver_fails_the_turn_rather_than_answering_nothing():
    d = tempfile.mkdtemp()
    (pathlib.Path(d) / "sitecustomize.py").write_text(
        'import sys, types\nm = types.ModuleType("nanobot")\nsys.modules["nanobot"] = m\n')
    job = {"config_path": f"{d}/c.json", "workspace": d, "model": "m", "prompt": "hi",
           "session_key": "s", "tools_disabled": []}
    p = subprocess.run([sys.executable, str(DRIVER), json.dumps(job)],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": d})
    assert p.returncode == 1
    out = [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip().startswith("{")]
    assert out and out[-1]["is_error"] is True
    # the reason reaches stderr too, which is what the runner collects into the turn's failure text
    assert "ImportError" in p.stderr or "nanobot driver:" in p.stderr


def test_a_tool_policy_that_does_not_take_fails_the_turn_rather_than_running_without_it():
    # The worst shape of this defect is the quiet one: the console reports the tool as off, the
    # model is offered it anyway, and nothing says so. Here the session's policy refuses the
    # assignment, which is what a release that changed SessionPolicy would look like from outside.
    d = tempfile.mkdtemp()
    (pathlib.Path(d) / "sitecustomize.py").write_text(
        _fake_nanobot_source([{"_kind": "run.completed", "content": "ok"}]) + '''
import sys
_m = sys.modules["nanobot"]
class _Stuck:
    key = "s"
    @property
    def policy(self): return _m.SessionPolicy()
    @policy.setter
    def policy(self, v): pass
_m._Sessions.get_or_create = lambda self, key: _Stuck()
''')
    job = {"config_path": f"{d}/c.json", "workspace": d, "model": "m", "prompt": "hi",
           "session_key": "s", "tools_disabled": ["write_file"]}
    p = subprocess.run([sys.executable, str(DRIVER), json.dumps(job)],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": d})
    assert p.returncode == 1, p.stdout + p.stderr
    out = [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip().startswith("{")]
    assert out[-1]["is_error"] is True
    assert "tool policy" in out[-1]["result"]
