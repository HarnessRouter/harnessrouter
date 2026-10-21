"""runner/tracecontext.py: the W3C trace-context rules both services apply to a caller's
`traceparent` and `tracestate` (#473). The gateway loads this module by path and the runner imports
it, so one set of rules decides what is kept, what is dropped (never refused), and what child the
relay sends to a provider."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import tracecontext  # noqa: E402

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = f"00-{TRACE_ID}-00f067aa0ba902b7-01"
STATE = "congo=t61rcWkgMzE,rojo=00f067aa0ba902b7"


def test_valid_context_is_kept_and_anything_else_is_dropped():
    assert tracecontext.parse(PARENT, STATE) == {"traceparent": PARENT, "tracestate": STATE}
    assert tracecontext.parse(PARENT) == {"traceparent": PARENT}
    assert tracecontext.parse(PARENT, "not a state") == {"traceparent": PARENT}
    for bad in ("", None, "garbage", f"ff-{TRACE_ID}-00f067aa0ba902b7-01",
                f"00-{'0' * 32}-00f067aa0ba902b7-01", f"00-{TRACE_ID}-{'0' * 16}-01",
                PARENT + "-extra", PARENT + "\r\nx-injected: 1"):
        assert tracecontext.parse(bad, STATE) == {}, bad


def test_upper_case_hex_is_not_a_trace_context():
    """The spec's ids are lower-case hex (HEXDIGLC); an upper-case value is dropped, not rewritten."""
    assert tracecontext.parse(PARENT.upper()) == {}
    assert tracecontext.parse(f"00-{TRACE_ID.upper()}-00f067aa0ba902b7-01") == {}


def test_a_future_version_keeps_its_four_fields_and_never_its_tail():
    """The spec parses the fields it knows of a newer version and ignores the rest: the trace is
    kept, and the unread tail (a long value, a control character) travels nowhere."""
    head = f"01-{TRACE_ID}-00f067aa0ba902b7-01"
    assert tracecontext.parse(head + "-what-the-future-holds") == {"traceparent": head}
    assert tracecontext.parse(head + "-" + "x" * 5000) == {"traceparent": head}
    assert tracecontext.parse(head + "-a\rb") == {"traceparent": head}


def test_a_repeated_tracestate_key_drops_the_tracestate_not_the_trace():
    """'Only one entry per key may exist': a tracestate that repeats one is dropped whole."""
    assert tracecontext.parse(PARENT, "congo=1,congo=2") == {"traceparent": PARENT}
    assert tracecontext.parse(PARENT, "a@vendor=1,a@vendor=2") == {"traceparent": PARENT}


def test_empty_tracestate_members_are_skipped():
    """The spec allows empty list-members; they are skipped, and the members around them kept."""
    assert tracecontext.parse(PARENT, "a=1,,b=2") == {"traceparent": PARENT, "tracestate": "a=1,b=2"}
    assert tracecontext.parse(PARENT, " , a=1 ,") == {"traceparent": PARENT, "tracestate": "a=1"}
    assert tracecontext.parse(PARENT, " , ") == {"traceparent": PARENT}


def test_tracestate_limits_drop_it_never_refuse():
    """At most 32 members and 512 characters: past either, the tracestate is dropped."""
    thirty_two = ",".join(f"k{i}=1" for i in range(32))
    assert tracecontext.parse(PARENT, thirty_two) == {"traceparent": PARENT, "tracestate": thirty_two}
    assert tracecontext.parse(PARENT, thirty_two + ",k32=1") == {"traceparent": PARENT}
    assert tracecontext.parse(PARENT, "k=" + "v" * 600) == {"traceparent": PARENT}


def test_a_child_keeps_the_trace_id_and_the_sampled_flag_with_a_new_span():
    child = tracecontext.child(PARENT)
    version, trace_id, span, flags = child.split("-")
    assert (version, trace_id, flags) == ("00", TRACE_ID, "01")
    assert span != "00f067aa0ba902b7" and len(span) == 16 and tracecontext.parse(child)
    assert tracecontext.child(f"00-{TRACE_ID}-00f067aa0ba902b7-00").endswith("-00")
    assert tracecontext.child(f"00-{TRACE_ID}-00f067aa0ba902b7-ff").endswith("-01")  # unknown flags dropped
    assert tracecontext.child("garbage") == ""


def test_a_child_of_a_future_version_is_version_00_with_the_sampled_bit_only():
    child = tracecontext.child(f"03-{TRACE_ID}-00f067aa0ba902b7-03-more")
    version, trace_id, _span, flags = child.split("-")
    assert (version, trace_id, flags) == ("00", TRACE_ID, "01")


def test_trace_id_reads_only_a_valid_traceparent():
    assert tracecontext.trace_id(PARENT) == TRACE_ID
    assert tracecontext.trace_id(PARENT.upper()) == ""
    assert tracecontext.trace_id("") == ""
