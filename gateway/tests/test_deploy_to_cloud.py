"""Deploy to Cloud: a setup's one click to HarnessRouter Cloud. The first time it opens the Cloud sign-in
hand-off (POST /v1/cloud-upload/connect), the person signs in on the page it names, and the key the
hosted side mints lands HERE as the destination (GET /v1/cloud-upload/connect/{code}): the browser
never holds it. Every deploy after that is the existing upload, which now says where the copy opens.
The hosted side is a mock at the HTTP boundary, as in test_cloud_upload."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)

from test_cloud_upload import Cloud, ORG  # noqa: E402

HOSTED = "https://api.harnessrouter.ai"


class CloudWithSignIn(Cloud):
    """The hosted side, with its pairing (/v1/connect) in front of the API the key opens."""
    def __init__(self):
        super().__init__()
        self.pairings: dict[str, dict] = {}
        # the key Cloud's sign-in mints (workspace "" with workspace_default): its /v1/me names the
        # organization's Default Workspace (Cloud, since 2026-10-23)
        self.keys["sk-hr-default"] = {"org": "org_e", "org_name": "Example Co", "workspace": "org_e__hr_default",
                                      "workspace_name": "Default Workspace", "member": "owner"}

    def handle(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/v1/connect" and req.method == "POST":
            code = f"code{len(self.pairings) + 1}"
            self.pairings[code] = {"secret": f"secret-{code}", "key": "", "instance": json.loads(req.content).get("instance")}
            self.calls.append((req.method, p))
            return httpx.Response(200, json={"code": code, "secret": f"secret-{code}",
                                             "url": f"https://app.harnessrouter.ai/get-key?code={code}", "expires_in": 1800})
        if p.startswith("/v1/connect/") and req.method == "GET":
            self.calls.append((req.method, p))
            pr = self.pairings.get(p.rsplit("/", 1)[-1])
            if not pr:
                return httpx.Response(410, json={"detail": "gone"})
            if req.headers.get("x-connect-secret") != pr["secret"]:
                return httpx.Response(403, json={"detail": "wrong connection secret"})
            if not pr["key"]:
                return httpx.Response(202, json={"status": "pending"})
            if pr.get("delivered"):
                return httpx.Response(410, json={"detail": "already handed over"})
            pr["delivered"] = True
            return httpx.Response(200, json={"status": "ready", "api_key": pr["key"], "name": "HarnessRouter API",
                                             "endpoint": f"{HOSTED}/v1/provider"})
        return super().handle(req)

    def sign_in(self, code: str, key: str = "sk-hr-good"):
        """The person finishing on the hosted page: the key minted for their workspace."""
        self.pairings[code]["key"] = key


@pytest.fixture()
def cloud(monkeypatch):
    c = CloudWithSignIn()
    real = httpx.AsyncClient

    class Patched(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(lambda r: c.handle(r))
            super().__init__(*a, **kw)
    monkeypatch.setattr(gw.httpx, "AsyncClient", Patched)
    monkeypatch.setattr(gw, "_checked_clients", {})
    monkeypatch.setattr(gw, "_CONNECTS", {})
    return c


@pytest.fixture()
def api(monkeypatch):
    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    asyncio.run(gw.BACKING.secrets.put(gw.GLOBAL_TENANT, gw._CLOUD_UPLOAD_KEY, "", require_encryption=True))
    asyncio.run(gw.BACKING.secrets.put(gw.GLOBAL_TENANT, gw._CLOUD_UPLOAD_RECORDS_KEY, ""))
    return TestClient(gw.app)


def _harness(api, name="Weekly feedback summary") -> str:
    r = api.post("/v1/harnesses", json={"name": name, "base": "hermes", "default_model": "gpt-6.1-sol",
                                         "system_prompt": "Summarize the week's feedback by theme."})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_the_first_deploy_signs_in_and_the_key_lands_here_never_in_the_browser(api, cloud):
    start = api.post("/v1/cloud-upload/connect", json={"instance": "my-box:3000"})
    assert start.status_code == 200, start.text
    code, url = start.json()["code"], start.json()["url"]
    assert url == f"https://app.harnessrouter.ai/get-key?code={code}"
    assert "secret" not in json.dumps(start.json())                       # the pairing's secret stays here
    assert cloud.pairings[code]["instance"] == "my-box:3000"
    # still on the hosted page
    assert api.get(f"/v1/cloud-upload/connect/{code}").status_code == 202
    assert api.get("/v1/cloud-upload/targets").json()["targets"] == []
    # signed in: the key is now this instance's destination, and the answer carries no key
    cloud.sign_in(code)
    r = api.get(f"/v1/cloud-upload/connect/{code}")
    assert r.status_code == 200, r.text
    t = r.json()["target"]
    assert r.json()["status"] == "ready" and t["label"] == "Research (owner)" and t["base_url"] == HOSTED
    assert "sk-hr-good" not in r.text
    lst = api.get("/v1/cloud-upload/targets").json()
    assert [x["id"] for x in lst["targets"]] == [t["id"]] and lst["last"] == t["id"]
    # the hosted side hands a key over once; polls after that answer the same destination
    again = api.get(f"/v1/cloud-upload/connect/{code}")
    assert again.status_code == 200 and again.json()["target"] == t
    # and the deploy is one call from here
    hid = _harness(api)
    up = api.post(f"/v1/harnesses/{hid}/upload")
    assert up.status_code == 200, up.text
    assert cloud.harnesses[up.json()["remote_id"]]["system_prompt"] == "Summarize the week's feedback by theme."


def test_a_deploy_hand_off_and_a_key_hand_off_are_never_each_others(api, cloud):
    deploy = api.post("/v1/cloud-upload/connect", json={}).json()["code"]
    key = api.post("/v1/admin/connect", json={}).json()["code"]
    cloud.sign_in(deploy)
    cloud.sign_in(key)
    # Bring your own key cannot read a deploy hand-off's key, and the other way around
    assert api.get(f"/v1/admin/connect/{deploy}").status_code == 410
    assert api.get(f"/v1/cloud-upload/connect/{key}").status_code == 410
    assert api.get("/v1/cloud-upload/targets").json()["targets"] == []
    assert api.get(f"/v1/cloud-upload/connect/{deploy}").status_code == 200
    assert api.get("/v1/cloud-upload/connect/nope").status_code == 410


def test_the_sign_in_key_lands_where_cloud_names_and_a_key_it_names_no_workspace_for_is_refused(api, cloud):
    """Where a deploy lands is what Cloud's /v1/me names for the key, and nothing is assumed here.
    Cloud's sign-in mints its key for the organization's Default Workspace, and Cloud names that
    workspace for it. A key Cloud names no workspace for is refused, through the sign-in as when
    pasted: before 2026-10-23 Cloud answered none for the sign-in's key, and this instance supplied
    the Default Workspace itself; that stand-in is gone."""
    code = api.post("/v1/cloud-upload/connect", json={}).json()["code"]
    cloud.sign_in(code, key="sk-hr-default")
    r = api.get(f"/v1/cloud-upload/connect/{code}")
    assert r.status_code == 200, r.text
    assert r.json()["target"]["label"] == "Default Workspace (owner)"
    hid = _harness(api)
    up = api.post(f"/v1/harnesses/{hid}/upload")
    assert up.status_code == 200
    assert cloud.harnesses[up.json()["remote_id"]]["workspace"] == "org_e__hr_default"
    code = api.post("/v1/cloud-upload/connect", json={}).json()["code"]
    cloud.sign_in(code, key="sk-hr-nows")
    r = api.get(f"/v1/cloud-upload/connect/{code}")
    assert r.status_code == 400 and "workspace" in r.text
    pasted = api.post("/v1/cloud-upload/targets", json={"api_key": "sk-hr-nows", "base_url": HOSTED})
    assert pasted.status_code == 400 and "workspace" in pasted.text
    assert [t["label"] for t in api.get("/v1/cloud-upload/targets").json()["targets"]] == ["Default Workspace (owner)"]


def test_the_deploy_and_the_status_say_where_the_copy_opens_in_cloud(api, cloud):
    code = api.post("/v1/cloud-upload/connect", json={}).json()["code"]
    cloud.sign_in(code)
    api.get(f"/v1/cloud-upload/connect/{code}")
    hid = _harness(api)
    up = api.post(f"/v1/harnesses/{hid}/upload").json()
    assert up["open_url"] == f"https://app.harnessrouter.ai/studio/{up['remote_id']}"
    assert up["target_name"] == "Research (owner)"
    st = api.get(f"/v1/harnesses/{hid}/upload").json()
    assert st["uploaded"] is True and st["changed"] is False and st["open_url"] == up["open_url"]
    # changed here: the status says so, and keeps the link to the copy in Cloud
    assert api.put(f"/v1/harnesses/{hid}", json={"name": "Weekly feedback summary", "base": "hermes",
                                                 "system_prompt": "Summarize it in five bullets."}).status_code == 200
    st = api.get(f"/v1/harnesses/{hid}/upload").json()
    assert st["changed"] is True and st["open_url"] == up["open_url"]


def test_a_destination_other_than_cloud_itself_has_no_link(api, cloud):
    assert gw._cloud_open_url({"base_url": "https://cloud.test"}, "chrn_x") == ""
    assert gw._cloud_open_url({"base_url": HOSTED + "/"}, "chrn_x") == "https://app.harnessrouter.ai/studio/chrn_x"
    assert gw._cloud_open_url({"base_url": HOSTED}, "") == ""


def test_a_copy_sent_to_a_cloud_that_takes_plugins_whole_reads_current_until_it_changes(api, cloud):
    """HarnessRouter Cloud takes plugins whole (its /v1/uhp says capabilities.plugins), so a deploy
    sends them that way, and the status compared the setup in the other form: every deploy there
    read "changed" at once, and a reload right after Deploy showed Update Cloud (the review
    instance, 10-23). The status compares in the form the copy was sent in."""
    real = cloud.handle

    def with_uhp(req):
        if req.url.path == "/v1/uhp":
            return httpx.Response(200, json={"capabilities": {"plugins": True}})
        return real(req)
    cloud.handle = with_uhp
    code = api.post("/v1/cloud-upload/connect", json={}).json()["code"]
    cloud.sign_in(code)
    api.get(f"/v1/cloud-upload/connect/{code}")
    hid = _harness(api)
    up = api.post(f"/v1/harnesses/{hid}/upload")
    assert up.status_code == 200
    assert "plugins" in cloud.harnesses[up.json()["remote_id"]]        # sent with plugins whole
    assert api.get(f"/v1/harnesses/{hid}/upload").json()["changed"] is False
    assert api.get("/v1/cloud-upload/status").json()["harnesses"][hid]["changed"] is False
    assert api.put(f"/v1/harnesses/{hid}", json={"name": "Weekly feedback summary", "base": "hermes",
                                                 "system_prompt": "Shorter."}).status_code == 200
    assert api.get(f"/v1/harnesses/{hid}/upload").json()["changed"] is True

