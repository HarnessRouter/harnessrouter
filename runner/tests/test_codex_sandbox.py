"""Guard: codex must run WRITE-ENABLED in both the exec and app-server paths.

The regression this pins (QA CT: "codex app-server sandbox_mode 退回只读"): codex `app-server`
has no --dangerously-bypass flag and reads its policy from config.toml + the thread/start
`sandbox` field. If either drifts off `danger-full-access` (or the exec path loses its bypass
flag), codex mounts the workspace READ-ONLY and — with approval_policy "never" — silently rejects
every apply_patch/file write, so the agent produces no files and gives up ("workspace is
read-only"). That failure is invisible until a user runs a real turn. These are pure/deterministic
assertions on the rendered config, so they catch the drift at CI time without a live sandbox.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as rn  # noqa: E402

WRITE_MODE = "danger-full-access"


def _render_config(tmp_path) -> str:
    """Render config.toml exactly as a real turn would, via the shared codex setup."""
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home)}
    auth = rn.Auth(api_key="sk-test", base_url="https://example.invalid/v1", wire_api="responses")
    cfg_dir = rn._codex_prepare_env("azure", auth, "gpt-5.5", str(tmp_path), env)
    return (cfg_dir / "config.toml").read_text()


def test_exec_path_config_is_write_enabled(tmp_path):
    cfg = _render_config(tmp_path)
    # The exec path's sandbox policy lives in config.toml. Read-only here == silent write failures.
    assert f'sandbox_mode = "{WRITE_MODE}"' in cfg, (
        "codex config.toml no longer renders danger-full-access — the exec path would mount the "
        "workspace read-only and silently reject every file write"
    )
    assert 'approval_policy = "never"' in cfg   # never escalate; only safe BECAUSE sandbox is full-access


def test_appserver_default_sandbox_is_write_enabled():
    # app-server has no bypass flag; the sandbox is set purely from this value in thread/start.
    assert rn._CODEX_SANDBOX == WRITE_MODE, (
        f"CODEX_APPSERVER_SANDBOX default drifted to {rn._CODEX_SANDBOX!r} — app-server turns would "
        "run read-only. Only override to a write-enabled mode (danger-full-access / workspace-write)."
    )


def test_exec_path_passes_bypass_flag(tmp_path):
    # `codex exec` disables its own sandbox ONLY via this flag; losing it re-enables read-only.
    home = tmp_path / "home"
    home.mkdir()
    argv = rn._build_codex(
        "azure",
        rn.Auth(api_key="sk-test", base_url="https://example.invalid/v1", wire_api="responses"),
        "gpt-5.5", "hello", str(tmp_path), {"HOME": str(home)},
    )
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
