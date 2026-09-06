"""The turn record names the connection that served it (2026-09-06): the session's last_connection
carried it once per session, and the turns feed exposed a key the record did not have."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_the_record_carries_the_connection_stamped_at_dispatch():
    tr = gw._RespTranslator("resp_1", "gemini-3.5-flash", None, True, 0.0)
    assert tr.connection == ""
    tr.connection = "integration:Google AI Studio"
    rec = tr._response_obj("completed")
    assert rec["connection"] == "integration:Google AI Studio"
