"""A harness saved before 0.41.3 holds tool ids the catalog no longer offers.

0.41.3 renamed OpenSquilla's `exec` and `grep` to the names 0.5.6 has (exec_command, grep_search). A
harness saved earlier still stores the old ids: the agent doc asked the model off tools it does not
have by those names, and the console's Shell and Search switches showed on for a harness that had them
off. Read, they are now the current names; the stored record is not touched on a read, and a save
writes the current ids.

0.41.3 also took codex's `read_file`, `write_file` and `git` out of the catalog (codex 0.154 has no
tool by those names). Those are kept exactly as stored: a turn still asks the model off them and a
save keeps them, so nothing an old harness restricted is loosened, and the console, which draws its
switches from the catalog, shows none for them, as before.

The rule throughout: an old harness ends up as restricted as it was or more, never less. Every other
base, and every harness saved with current ids, reads back exactly as stored.
"""
import asyncio
import json
import os
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402

H = {"x-harness-internal": "test-internal-key", "x-harness-org": "org.storedtools", "x-harness-member": "tester@example.com"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app.app) as c:
        yield c


def _offered(base: str) -> list[str]:
    return [n for n, _ in app._BASE_CATALOG[base]["tools"]]


def _old_harness(client, base: str, stored: list) -> str:
    """A harness as a release before 0.41.3 left it: the list written straight into the record."""
    r = client.post("/v1/harnesses", json={"name": f"old {base}", "base": base}, headers=H)
    assert r.status_code == 200, r.text
    hid = r.json()["id"]
    asyncio.run(app.BACKING.graph.upsert("Harness", hid, {"disabled_tools": json.dumps(stored)}))
    return hid


def _stored(hid: str) -> list:
    return json.loads(asyncio.run(app.BACKING.graph.get(hid, label="Harness"))["disabled_tools"])


def _console_switches(base: str, disabled: list) -> dict[str, bool]:
    """The tool switches the console draws for a harness, name -> on, the way setupTools does:
    one per tool the base offers, off when the harness's list names it."""
    return {n: n not in disabled for n in _offered(base)}


def _turn_tools_off(hid: str) -> list:
    """What the gateway hands the runner for a turn on this harness."""
    hv = asyncio.run(app.BACKING.graph.get(hid, label="Harness"))
    return asyncio.run(app._harness_plugins(hid, H["x-harness-org"], hv=hv))[3]


# ── an old harness ──────────────────────────────────────────────────────────────────────────────

def test_an_old_opensquilla_harness_reads_its_tools_by_their_current_names(client):
    hid = _old_harness(client, "opensquilla", ["exec", "grep", "web_search"])
    got = client.get(f"/v1/harnesses/{hid}", headers=H).json()["disabledTools"]
    assert got == ["exec_command", "grep_search", "web_search"]
    assert _turn_tools_off(hid) == ["exec_command", "grep_search", "web_search"]


def test_an_old_codex_harness_still_asks_off_the_three_and_shows_only_real_switches(client):
    old = ["read_file", "shell", "write_file", "git", "web_search"]
    hid = _old_harness(client, "codex", old)
    # the turn's request names the three, exactly as before
    assert _turn_tools_off(hid) == old
    got = client.get(f"/v1/harnesses/{hid}", headers=H).json()["disabledTools"]
    assert got == old
    # the console draws a switch for each tool codex has, and none for the three
    switches = _console_switches("codex", got)
    assert set(switches) == set(_offered("codex"))
    assert not {"read_file", "write_file", "git"} & set(switches)
    assert switches["shell"] is False and switches["web_search"] is False
    assert switches["apply_patch"] is True
    # saving what the console read keeps them: the client never saw them, so it cannot drop them
    r = client.put(f"/v1/harnesses/{hid}", json=client.get(f"/v1/harnesses/{hid}", headers=H).json(), headers=H)
    assert r.status_code == 200, r.text
    assert _stored(hid) == old and _turn_tools_off(hid) == old


def test_an_old_id_and_its_current_name_together_are_one_entry(client):
    hid = _old_harness(client, "opensquilla", ["exec", "exec_command", "grep (Search)"])
    assert client.get(f"/v1/harnesses/{hid}", headers=H).json()["disabledTools"] == ["exec_command", "grep_search"]


def test_an_old_opensquilla_harness_shows_its_switches_off(client):
    """Before, the stored `exec` and `grep` matched no switch: the console showed Shell and Search
    on for a harness that had them off. Read now, every id is a switch the base offers and each
    one the harness had off is drawn off."""
    hid = _old_harness(client, "opensquilla", ["exec", "grep", "read_file"])
    got = client.get(f"/v1/harnesses/{hid}", headers=H).json()["disabledTools"]
    assert set(got) <= set(_offered("opensquilla")), sorted(set(got) - set(_offered("opensquilla")))
    switches = _console_switches("opensquilla", got)
    assert not switches["exec_command"] and not switches["grep_search"] and not switches["read_file"]
    assert switches["write_file"] and switches["web_search"]
    listed = {h["id"]: h for h in client.get("/v1/harnesses", headers=H).json()["harnesses"]}
    assert listed[hid]["disabledTools"] == got          # the list and the single read agree


def test_a_read_does_not_rewrite_the_stored_record(client):
    hid = _old_harness(client, "opensquilla", ["exec", "web_fetch"])
    client.get(f"/v1/harnesses/{hid}", headers=H)
    client.get("/v1/harnesses", headers=H)
    _turn_tools_off(hid)
    assert _stored(hid) == ["exec", "web_fetch"]


def test_saving_writes_the_current_ids(client):
    hid = _old_harness(client, "opensquilla", ["exec", "grep"])
    got = client.get(f"/v1/harnesses/{hid}", headers=H).json()
    r = client.put(f"/v1/harnesses/{hid}", json=got, headers=H)
    assert r.status_code == 200, r.text
    assert _stored(hid) == ["exec_command", "grep_search"]
    # an API client that sends an old id gets the same treatment as one read back
    r = client.put(f"/v1/harnesses/{hid}", json={**got, "disabledTools": ["exec", "git"]}, headers=H)
    assert r.status_code == 200 and r.json()["disabledTools"] == ["exec_command", "git"]


# ── never less restricted ───────────────────────────────────────────────────────────────────────

def test_nothing_an_old_list_asked_off_leaves_the_turn(client):
    """Each stored entry reaches the runner, by its own name or the current name of the tool it
    meant: a turn is asked off at least what it was asked off before, on every base."""
    for base, old in (("codex", ["read_file", "write_file", "git", "shell (runs commands)"]),
                      ("opensquilla", ["exec", "grep (Search)", "list_dir"]),
                      ("nanobot", ["exec", "grep"]), ("claude-code", ["Task", "Bash"])):
        hid = _old_harness(client, base, old)
        turn = _turn_tools_off(hid)
        renames = app._STORED_TOOL_IDS.get(app._backend_of_harness({"base": base})) or {}
        for t in old:
            assert t in turn or renames.get(t.split(" (")[0]) in turn, (base, t, turn)


def test_codex_hard_switches_answer_the_same_for_an_old_list():
    """codex's hard switches key on the shell's names and web_search; the runner withholds exactly
    what it withheld before, since an old codex list reaches it as stored."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
    import server as rs  # noqa: PLC0415 — the runner is not a gateway import

    for old in (["read_file", "write_file", "git"], ["git", "shell"], ["web_search", "read_file"],
                ["shell (runs commands)", "git"]):
        new = app._stored_tools_current("codex", old)
        assert new == old
        assert rs._codex_shell_off(new) == rs._codex_shell_off(old), old
        assert rs._codex_web_search_off(new) == rs._codex_web_search_off(old), old


def test_an_opensquilla_id_is_only_ever_replaced_by_the_tool_it_named():
    old = ["exec", "grep", "web_fetch"]
    assert app._stored_tools_current("opensquilla", old) == ["exec_command", "grep_search", "web_fetch"]


# ── everything else is as stored ────────────────────────────────────────────────────────────────

def test_a_new_harness_reads_back_as_saved(client):
    for base in ("opensquilla", "codex", "nanobot", "claude-code"):
        ids = _offered(base)[:3]
        r = client.post("/v1/harnesses", json={"name": f"new {base}", "base": base, "disabledTools": ids}, headers=H)
        assert r.status_code == 200, r.text
        assert r.json()["disabledTools"] == ids
        assert _stored(r.json()["id"]) == ids


def test_the_same_names_on_another_base_are_left_alone(client):
    """`exec` and `grep` are real tools elsewhere (nanobot's shell, omp's search); `read_file` and
    `git` too on some bases. Only the base whose CLI renamed or lacks them is touched."""
    for base, stored in (("nanobot", ["exec", "grep", "read_file"]), ("omp", ["grep", "read"]),
                         ("hermes", ["read_file", "write_file"])):
        hid = _old_harness(client, base, stored)
        assert client.get(f"/v1/harnesses/{hid}", headers=H).json()["disabledTools"] == stored
        assert _turn_tools_off(hid) == stored
