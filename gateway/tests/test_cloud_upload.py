"""Cloud upload: a local harness pushed to a hosted workspace, one way, upsert on its own id.
The hosted side is a mock at the HTTP boundary, which pins the contract this feature depends on:
GET /v1/me resolves a key to org + workspace, PUT /v1/harnesses/{id} creates or replaces."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)

ORG = "local"
CLOUD = "https://cloud.test"


class Cloud:
    """What the hosted gateway does, as far as this feature can see."""
    def __init__(self):
        self.keys = {"sk-hr-good": {"org": "org_e", "org_name": "Epsilla", "workspace": "ws_r", "workspace_name": "Research", "member": "richard"},
                     "sk-hr-nows": {"org": "org_e", "org_name": "Epsilla", "workspace": "", "workspace_name": "", "member": "richard"}}
        self.harnesses: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.path))
        tok = req.headers.get("authorization", "").removeprefix("Bearer ")
        me = self.keys.get(tok)
        if not me:
            return httpx.Response(401, json={"error": {"message": "invalid key"}})
        if req.url.path == "/v1/me":
            return httpx.Response(200, json=me)
        if req.url.path.startswith("/v1/harnesses/") and req.method == "PUT":
            hid = req.url.path.rsplit("/", 1)[-1]
            body = json.loads(req.content)
            created = hid not in self.harnesses
            self.harnesses[hid] = {**body, "org": me["org"], "workspace": me["workspace"]}
            return httpx.Response(201 if created else 200, json={"id": hid, **body})
        return httpx.Response(404, json={"error": {"message": "no route"}})


@pytest.fixture()
def cloud(monkeypatch):
    c = Cloud()
    real = httpx.AsyncClient

    class Patched(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(c.handle)
            super().__init__(*a, **kw)
    monkeypatch.setattr(gw.httpx, "AsyncClient", Patched)
    return c


@pytest.fixture()
def api(monkeypatch):
    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    asyncio.run(gw.BACKING.secrets.put(gw.GLOBAL_TENANT, gw._CLOUD_UPLOAD_KEY, "", require_encryption=True))
    asyncio.run(gw.BACKING.secrets.put(gw.GLOBAL_TENANT, gw._CLOUD_UPLOAD_RECORDS_KEY, ""))
    return TestClient(gw.app)


def _harness(api, name="Philz one-pager", **extra) -> str:
    r = api.post("/v1/harnesses", json={"name": name, "base": "dsh", "default_model": "deepseek-v4-flash",
                                         "system_prompt": "Make decks.", **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_nothing_is_configured_until_a_key_is_saved(api, cloud):
    assert api.get("/v1/cloud-upload/targets").json() == {"targets": [], "last": ""}
    r = api.post("/v1/harnesses/upload", json={"ids": ["chrn_" + "0" * 32]})
    assert r.status_code == 400 and "no cloud workspace" in r.text
    assert cloud.calls == []


def test_test_resolves_the_key_to_a_label_without_saving_and_shows_no_ids(api, cloud):
    r = api.post("/v1/cloud-upload/targets/test", json={"api_key": "sk-hr-good", "base_url": CLOUD})
    assert r.status_code == 200
    j = r.json()
    assert j["label"] == "Research (richard)"
    assert "org_e" not in json.dumps(j) and "ws_r" not in json.dumps(j)   # internal ids never shown
    assert api.get("/v1/cloud-upload/targets").json()["targets"] == []


def test_a_bad_key_and_a_key_without_a_workspace_are_refused(api, cloud):
    assert api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-wrong", "base_url": CLOUD}).status_code == 401
    r = api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-nows", "base_url": CLOUD})
    assert r.status_code == 400 and "workspace" in r.text


def test_stored_targets_keep_the_key_out_and_can_be_removed(api, cloud):
    r = api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-good", "base_url": CLOUD})
    assert r.status_code == 200
    j = r.json()
    assert j["label"] == "Research (richard)" and "sk-hr-good" not in json.dumps(j)
    assert j["key_hint"].startswith("sk-hr-") and "…" in j["key_hint"]
    lst = api.get("/v1/cloud-upload/targets").json()
    assert len(lst["targets"]) == 1 and lst["last"] == j["id"]
    left = api.delete(f"/v1/cloud-upload/targets?id={j['id']}").json()
    assert left["targets"] == [] and left["last"] == ""


def test_upload_creates_then_replaces_on_the_same_id(api, cloud):
    api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-good", "base_url": CLOUD})
    hid = _harness(api)
    r = api.post(f"/v1/harnesses/{hid}/upload")
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "create" and r.json()["ok"] is True
    assert hid in cloud.harnesses                                    # same id on the hosted side
    sent = cloud.harnesses[hid]
    assert sent["name"] == "Philz one-pager" and sent["base"] == "dsh" and sent["system_prompt"] == "Make decks."
    assert sent["source"] == "selfhost" and sent["workspace"] == "ws_r"   # landed in the key's workspace
    assert "api_key" not in json.dumps(sent)                         # nothing secret travels
    st = api.get(f"/v1/harnesses/{hid}/upload").json()
    assert st["uploaded"] is True and st["changed"] is False and st["target"] == "Research (richard)"
    # edit locally: the chip says changed; upload again: replace, in place, same id
    api.put(f"/v1/harnesses/{hid}", json={"name": "Philz one-pager v2", "base": "dsh"})
    assert api.get(f"/v1/harnesses/{hid}/upload").json()["changed"] is True
    r = api.post(f"/v1/harnesses/{hid}/upload")
    assert r.json()["action"] == "replace" and cloud.harnesses[hid]["name"] == "Philz one-pager v2"
    assert len(cloud.harnesses) == 1
    assert api.get(f"/v1/harnesses/{hid}/upload").json()["changed"] is False


def test_skills_travel_with_their_files_inlined(api, cloud):
    api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-good", "base_url": CLOUD})
    big = "x" * (gw._SKILL_INLINE_MAX + 100)                           # forces the local blob offload
    hid = _harness(api, skills=[{"name": "deck", "files": [{"path": "SKILL.md", "content": big}]}])
    assert "blob" in json.dumps(asyncio.run(gw._vertex_get(hid)).get("skills"))   # offloaded locally
    assert api.post(f"/v1/harnesses/{hid}/upload").status_code == 200
    sk = cloud.harnesses[hid]["skills"][0]
    assert sk["name"] == "deck" and "blob" not in sk and sk["files"][0]["content"] == big


def test_batch_runs_every_row_and_skips_builtins(api, cloud):
    api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-good", "base_url": CLOUD})
    a, b = _harness(api, "A"), _harness(api, "B")
    r = api.post("/v1/harnesses/upload", json={"ids": [a, "codex", b, "chrn_" + "f" * 32]})
    assert r.status_code == 200
    rows = {x["id"]: x for x in r.json()["results"]}
    assert rows[a]["ok"] and rows[a]["action"] == "create"
    assert rows[b]["ok"] and rows[b]["action"] == "create"
    assert rows["codex"]["action"] == "skip" and rows["codex"]["error"] == "built-in"
    assert rows["chrn_" + "f" * 32]["action"] == "skip" and rows["chrn_" + "f" * 32]["error"] == "not found"
    assert set(cloud.harnesses) == {a, b}
    st = api.get("/v1/cloud-upload/status").json()["harnesses"]
    assert st[a]["uploaded"] and st[b]["uploaded"]


def test_a_cloud_error_on_one_row_does_not_stop_the_others(api, cloud, monkeypatch):
    api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-good", "base_url": CLOUD})
    a, b = _harness(api, "A"), _harness(api, "B")
    real = cloud.handle

    def flaky(req):
        if req.method == "PUT" and req.url.path.endswith(a):
            return httpx.Response(500, json={"error": {"message": "hosted hiccup"}})
        return real(req)
    cloud.handle = flaky
    rows = {x["id"]: x for x in api.post("/v1/harnesses/upload", json={"ids": [a, b]}).json()["results"]}
    assert rows[a]["ok"] is False and "hosted hiccup" in rows[a]["error"]
    assert rows[b]["ok"] is True
    assert api.get(f"/v1/harnesses/{a}/upload").json()["uploaded"] is False   # a failed upload leaves no record


def test_an_id_claimed_by_another_org_lands_under_a_minted_id(api, cloud):
    """The same local harness uploaded to a second org is legitimate: hosted ids are global and
    the hosted side answers 404 for a foreign-owned id, indistinguishable from missing. The
    upload retries once under a fresh id and every later upload replaces that same hosted copy."""
    api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-good", "base_url": CLOUD})
    hid = _harness(api, "Collision")
    real = cloud.handle

    def owned_elsewhere(req):
        if req.method == "PUT" and req.url.path.endswith(hid):
            return httpx.Response(404, json={"error": {"message": "No harness with that id."}})
        return real(req)
    cloud.handle = owned_elsewhere
    r = api.post(f"/v1/harnesses/{hid}/upload")
    assert r.status_code == 200, r.text
    remote = r.json()["remote_id"]
    assert remote != hid and remote.startswith("chrn")
    assert cloud.harnesses[remote]["name"] == "Collision"
    assert api.get(f"/v1/harnesses/{hid}/upload").json()["uploaded"] is True
    r2 = api.post(f"/v1/harnesses/{hid}/upload")
    assert r2.json()["remote_id"] == remote and r2.json()["action"] == "replace"
    assert len([k for k in cloud.harnesses if k.startswith("chrn")]) == 1

    def flaky(req):
        return httpx.Response(500, json={"error": {"message": "boom"}})
    cloud.handle = flaky
    assert api.post(f"/v1/harnesses/{hid}/upload").status_code == 502   # a non-404 mints nothing


def test_the_same_harness_uploads_to_every_workspace_a_key_points_at(api, cloud):
    """It is just an upload: wherever there is a key, it lands. Each target keeps its own hosted
    copy and its own chip state; a second workspace in the SAME org gets its own copy rather
    than silently updating the first one's."""
    cloud.keys["sk-hr-ws2"] = {"org": "org_e", "org_name": "Epsilla", "workspace": "ws_2",
                               "workspace_name": "Second", "member": "richard"}
    api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-good", "base_url": CLOUD})
    hid = _harness(api, "Everywhere")
    r1 = api.post(f"/v1/harnesses/{hid}/upload").json()
    assert r1["action"] == "create" and r1["remote_id"] == hid          # first target keeps the local id
    # switch the key to another workspace of the same org: its own copy, its own id
    api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-ws2", "base_url": CLOUD})
    assert api.get(f"/v1/harnesses/{hid}/upload").json()["uploaded"] is True    # chip: most recent upload anywhere
    r2 = api.post(f"/v1/harnesses/{hid}/upload").json()
    assert r2["action"] == "create" and r2["remote_id"] != hid
    assert cloud.harnesses[hid]["workspace"] == "ws_r"
    assert cloud.harnesses[r2["remote_id"]]["workspace"] == "ws_2"
    st = api.get(f"/v1/harnesses/{hid}/upload").json()
    assert st["uploaded"] is True and st["target"] == "Second (richard)"
    # back to the first workspace: its record is intact, replace goes to the original id
    api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-good", "base_url": CLOUD})
    r3 = api.post(f"/v1/harnesses/{hid}/upload").json()
    assert r3["action"] == "replace" and r3["remote_id"] == hid
