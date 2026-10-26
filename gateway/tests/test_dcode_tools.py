"""dcode's catalog must offer exactly the tools that can be withheld on the surface it is driven
through, and the surface it is driven through is ACP — not its headless flag.

Both halves are MEASURED on deepagents-code 0.1.84, off the request bodies of real turns rather
than from its documentation:

  * Fourteen tools reach the model over ACP: ls, read_file, write_file, edit_file, delete, glob,
    grep, execute, task, compact_conversation, update_goal, ask_user, fetch_url and
    get_current_thread_id. TWO of them differ from its headless mode — `js_eval` is absent (ACP
    leaves `enable_interpreter` at its False default) and `ask_user` is present (its
    `enable_ask_user` default is True there) — which is why reading the docs, or the other mode,
    would have produced the wrong list.
  * `--allow-fs-tools` is the single door, and on this surface it governs the shell as well:
    FS_TOOL_NAMES includes `execute`, and a turn launched with `--allow-fs-tools read_file,ls`
    declared neither the shell nor the five write tools. read_file stays because the flag's own
    parser rejects a list without it.

So the offer is the filesystem set minus read_file: seven. The other six have no switch, and a
toggle for a tool the runtime cannot withhold disables nothing while the console reports it as off
— the overstatement UHP section 4.3 forbids.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import ALL_DCODE_TOOLS, DCODE_PROVIDERS, _DCODE_FS_TOOLS  # noqa: E402


def _offered(base: str) -> set:
    return {tid for tid, _label in A._BASE_CATALOG[base]["tools"]}


def test_the_catalog_offers_exactly_the_seven_that_can_be_withheld():
    offered = _offered("dcode")
    want = set(ALL_DCODE_TOOLS)
    assert offered == want, (
        f"only in catalog: {offered - want}, only in the runner: {want - offered}")
    assert len(want) == 7


def test_the_offer_is_the_filesystem_set_minus_read_file():
    # read_file is in the door's own list and never withheld: the flag's parser requires it
    assert set(ALL_DCODE_TOOLS) == set(_DCODE_FS_TOOLS) - {"read_file"}
    assert "read_file" not in _offered("dcode")


def test_the_tools_with_no_switch_are_not_offered():
    # declared to the model, and nothing withholds them: offering a toggle would disable nothing
    for tool in ("read_file", "task", "compact_conversation", "update_goal", "ask_user",
                 "fetch_url", "get_current_thread_id"):
        assert tool not in _offered("dcode"), tool
    # js_eval is not even declared on this surface, so it is not a toggle either
    assert "js_eval" not in _offered("dcode")


def test_the_claim_is_hard_because_a_withheld_tool_is_never_declared():
    assert A._BASE_CATALOG["dcode"]["tool_enforcement"] == "hard"


def test_it_is_a_responses_client_and_NOT_chat_only():
    # the only base here besides codex that speaks /v1/responses; a custom integration declaring
    # chat/completions cannot serve it, which is what this set decides
    assert "dcode" in A._CUSTOM_FORMAT_BACKENDS["responses"]
    assert "dcode" not in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "dcode" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]
    assert "dcode" not in A.CHAT_ONLY_BACKENDS


def test_no_provider_is_wired_that_has_no_responses_endpoint():
    wired = {kind for (kind, base) in A._INTEGRATION_WIRING if base == "dcode"}
    assert wired, "dcode is not routable at all"
    # An Anthropic or Google native endpoint has no /v1/responses to post to, and this builder
    # only ever sets OPENAI_BASE_URL — so those connections are absent by intent, as on codex.
    assert "anthropic" not in wired
    assert "google" not in wired
    assert wired <= {kind for (kind, base) in A._INTEGRATION_WIRING if base == "codex"}


def test_every_wired_provider_type_is_one_the_runner_accepts():
    for (_kind, base), ptype in A._INTEGRATION_WIRING.items():
        if base == "dcode":
            assert ptype in DCODE_PROVIDERS, (base, ptype)


def test_the_catalog_lists_models_and_a_default_it_also_lists():
    entry = A._MODEL_CATALOG["dcode"]
    assert entry["models"]
    assert entry["default"] in entry["models"]
