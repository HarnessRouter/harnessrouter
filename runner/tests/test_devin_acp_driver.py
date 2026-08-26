import os
import pathlib
import threading

from server import _turns

FAKE_DEVIN = pathlib.Path(__file__).with_suffix("").parent / "fake_devin_acp.py"


def test_devin_acp_driver():
    turn_id = "t-driver-1"
    _turns[turn_id] = {"events": [], "cancelled": False, "capped": False, "done": False}
    env = {**os.environ, "PATH": f"{FAKE_DEVIN.parent}:{os.environ.get('PATH', '')}"}
    # Override the binary name so we can point at our fake
    os.environ.setdefault("DEVIN_ACP_BINARY", str(FAKE_DEVIN))
    from server import _run_devin_acp_bg
    t = threading.Thread(target=_run_devin_acp_bg,
                         args=(turn_id, "/tmp", env, "devin-swe", "say hello", None, 60, None, None),
                         daemon=True)
    t.start()
    t.join(timeout=10)
    rec = _turns[turn_id]
    assert rec["done"]
    texts = [e["message"]["content"][0]["text"] for e in rec["events"]
             if e.get("type") == "assistant" and e["message"]["content"][0].get("type") == "text"]
    assert "Fake " in texts
    assert "Devin" in texts
