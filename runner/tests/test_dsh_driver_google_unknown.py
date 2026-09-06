"""dsh's own relay drops the top-level field Google refused as unknown and remembers it."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dsh_driver  # noqa: E402


def test_the_refusal_names_the_field():
    assert dsh_driver._google_unknown_field(b'{"error": {"message": "Invalid JSON payload received. Unknown name \\"seed\\": Cannot find field."}}') == "seed"
    assert dsh_driver._google_unknown_field(b'{"error": {"message": "Unknown name \\"strict\\" at \'tools[0]\': Cannot find field."}}') == ""


def test_the_fields_are_dropped_from_the_body():
    body = b'{"model": "m", "store": false, "seed": 1, "messages": []}'
    out = dsh_driver._drop_top_level_fields(body, ["store", "seed"])
    assert b"store" not in out and b"seed" not in out and b'"messages": []' in out
    assert dsh_driver._drop_top_level_fields(b"not json", ["store"]) == b"not json"
