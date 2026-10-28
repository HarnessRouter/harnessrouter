"""A streamed tool call that arrives with no `index` gets one, because a client merges by it.

THE BUG, found by vibe's Google column (2026-10-19, the artifact scenario, 211 s): the turn failed
with `Tool call chunk missing index` AFTER the model had answered and written nothing back. The
message is the CLIENT's — vibe 2.26.1 raises it in `core/types.py` while merging a streamed tool
call's chunks — and the cause is the PROVIDER's shape. MEASURED straight at
generativelanguage.googleapis.com/v1beta/openai (gemini-3.8-flash, one function tool, stream=true):

    "tool_calls":[{"extra_content":{"google":{"thought_signature":"…"}},
                   "function":{"arguments":"{\\"content\\":\\"HELLO\\",\\"path\\":\\"hello.txt\\"}",
                               "name":"write_file"},
                   "id":"call_4217092","type":"function"}]

No `index`, where OpenAI's streaming shape has one on every tool-call delta. The index is
positional information only the stream has, so the relay supplies it — the same standing as
`_usage_without_nulls`, which writes a null token count as 0 for a client whose parser takes only
a number there.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
from server import (_hermes_relay_route, _rewrite_stream_line,  # noqa: E402
                    _rewrites_stream_lines, _tool_call_index_line)

# The line as Google really sends it, fields and order kept.
GOOGLE = (b'data: {"choices":[{"delta":{"role":"assistant","tool_calls":[{"extra_content":'
          b'{"google":{"thought_signature":"EuYCCuMC"}},"function":{"arguments":'
          b'"{\\"content\\":\\"HELLO\\",\\"path\\":\\"hello.txt\\"}","name":"write_file"},'
          b'"id":"call_4217092","type":"function"}]},"index":0}],'
          b'"model":"gemini-3.8-flash","object":"chat.completion.chunk"}')


def _calls(line: bytes) -> list:
    obj = json.loads(line.split(b"data:", 1)[1])
    return obj["choices"][0]["delta"]["tool_calls"]


def test_the_index_is_supplied_and_nothing_else_is_touched():
    out = _tool_call_index_line(GOOGLE, {})
    call = _calls(out)[0]
    assert call["index"] == 0
    # everything the provider sent is still there, Google's own signature included
    assert call["id"] == "call_4217092" and call["type"] == "function"
    assert call["function"]["name"] == "write_file"
    assert json.loads(call["function"]["arguments"]) == {"content": "HELLO", "path": "hello.txt"}
    assert call["extra_content"]["google"]["thought_signature"] == "EuYCCuMC"
    assert json.loads(out.split(b"data:", 1)[1])["model"] == "gemini-3.8-flash"


def test_two_calls_in_one_answer_stay_two():
    line = (b'data: {"choices":[{"delta":{"tool_calls":['
            b'{"id":"call_a","type":"function","function":{"name":"ls","arguments":"{}"}},'
            b'{"id":"call_b","type":"function","function":{"name":"grep","arguments":"{}"}}'
            b']},"index":0}]}')
    calls = _calls(_tool_call_index_line(line, {}))
    assert [c["index"] for c in calls] == [0, 1]


def test_a_calls_later_chunks_keep_its_own_index():
    # the same call across three chunks: the id comes once, the arguments follow without it
    state: dict = {}
    first = _calls(_tool_call_index_line(
        b'data: {"choices":[{"delta":{"tool_calls":[{"id":"call_a","type":"function",'
        b'"function":{"name":"write_file","arguments":""}}]},"index":0}]}', state))
    more = _calls(_tool_call_index_line(
        b'data: {"choices":[{"delta":{"tool_calls":[{"function":{"arguments":"{\\"a\\":1}"}}]},'
        b'"index":0}]}', state))
    assert first[0]["index"] == 0 and more[0]["index"] == 0


def test_a_second_call_after_a_continuation_is_still_the_next_index():
    state: dict = {}
    _tool_call_index_line(b'data: {"choices":[{"delta":{"tool_calls":[{"id":"call_a",'
                          b'"function":{"arguments":""}}]},"index":0}]}', state)
    _tool_call_index_line(b'data: {"choices":[{"delta":{"tool_calls":[{"function":'
                          b'{"arguments":"{}"}}]},"index":0}]}', state)
    out = _calls(_tool_call_index_line(b'data: {"choices":[{"delta":{"tool_calls":[{"id":"call_b",'
                                       b'"function":{"arguments":"{}"}}]},"index":0}]}', state))
    assert out[0]["index"] == 1


def test_each_choice_counts_its_own_calls():
    state: dict = {}
    _tool_call_index_line(b'data: {"choices":[{"delta":{"tool_calls":[{"id":"a"}]},"index":0}]}', state)
    out = _tool_call_index_line(b'data: {"choices":[{"delta":{"tool_calls":[{"id":"b"}]},"index":1}]}',
                                state)
    obj = json.loads(out.split(b"data:", 1)[1])
    assert obj["choices"][0]["delta"]["tool_calls"][0]["index"] == 0


def test_an_index_the_provider_sent_is_never_overwritten():
    line = (b'data: {"choices":[{"delta":{"tool_calls":[{"index":3,"id":"call_a",'
            b'"function":{"name":"ls","arguments":"{}"}}]},"index":0}]}')
    assert _tool_call_index_line(line, {}) is line          # untouched, byte for byte
    assert _calls(line)[0]["index"] == 3


def test_a_line_with_no_tool_call_is_passed_through_byte_for_byte():
    for line in (b'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}',
                 b'data: [DONE]',
                 b': OPENROUTER PROCESSING',
                 b'',
                 b'data: not json at all',
                 b'event: ping'):
        assert _tool_call_index_line(line, {}) is line


def test_the_repair_runs_only_where_the_route_asked_for_it():
    assert _rewrite_stream_line(GOOGLE, {}, {}) is GOOGLE
    assert _calls(_rewrite_stream_line(GOOGLE, {"tool_index_fill": True}, {}))[0]["index"] == 0


def test_a_route_carries_the_flag():
    base, tok = _hermes_relay_route("https://up.example/v1", "k", tool_index_fill=True)
    import server as S
    _up, _key, flags = S._HERMES_RELAY["routes"][tok]
    assert flags.get("tool_index_fill") is True
    plain_base, plain_tok = _hermes_relay_route("https://up.example/v1", "k")
    assert S._HERMES_RELAY["routes"][plain_tok][2].get("tool_index_fill") is False


def test_vibes_own_route_asks_for_it():
    # the one base measured to need it; its builder is where the flag is turned on
    src = (pathlib.Path(__file__).resolve().parents[1] / "server.py").read_text()
    vibe = src.split("def _build_vibe(", 1)[1].split("\ndef ", 1)[0]
    assert "tool_index_fill=True" in vibe


def test_every_rewrite_flag_is_named_in_the_gate_THAT_FORWARDS_THE_REWRITE():
    """The invariant that would have saved a column run.

    `_rewrite_stream_line` is only reached when the streaming loop decides to forward rewritten
    lines instead of the raw read, and that decision is its own expression. `tool_index_fill` was
    added to the rewriter, this file's other nine tests passed, and the Google column failed again
    with the identical error — because the gate still named only the two older flags, so the bytes
    went through untouched. Any flag the rewriter reads must turn the gate on too.

    The gate is one function now, _rewrites_stream_lines, shared by the streaming loop and the
    stream's last line (#382), so the expression is checked to be that function and the function is
    asked about each flag, rather than the expression's text searched for the flag's name.
    """
    import re
    src = (pathlib.Path(__file__).resolve().parents[1] / "server.py").read_text()
    rewriter = src.split("def _rewrite_stream_line(", 1)[1].split("\ndef ", 1)[0]
    read = set(re.findall(r'flags\.get\("([a-z_]+)"\)', rewriter))
    assert read, "the rewriter reads no flags; this test is looking at the wrong function"
    gate = src.split("out_lines = [] if", 1)[1].split("else None", 1)[0]
    assert gate.strip() == "_rewrites_stream_lines(flags)", gate
    tail = src.split("tail_bytes = _rewrite_stream_line(", 1)[0].rsplit("\n", 2)[-2]
    assert "_rewrites_stream_lines(flags)" in tail, tail   # the last line goes through the same gate
    missing = sorted(f for f in read if not _rewrites_stream_lines({f: True}))
    assert not missing, f"the rewriter acts on {missing}, which the gate never turns on"
