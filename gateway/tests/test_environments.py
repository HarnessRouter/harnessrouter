"""Environments (UHP 2026-09-28, Environments chapter), driven through the public surface with the
runner's own environment module answering behind the gateway's runner call: create and scope, the
source files, an archive import, a build that becomes the active read-only layer, versions and
rollback, the harness and task references, deletion."""
from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "runner"))
import app  # noqa: E402
import environments as E  # noqa: E402  (the runner's module)

ORG = "envorg"
H = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "tester@example.com"}


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    """The gateway's app, with the runner's environment routes answering its `_env_runner` calls
    in-process: real bytes on a temp volume, real builds (a venv with nothing in it, so no network)."""
    root = tmp_path_factory.mktemp("envstore")
    E.ENV_ROOT, E.ENV_MOUNT = str(root / "environments"), str(root / "env")
    E._tool_env = lambda: {**os.environ, "PIP_NO_CACHE_DIR": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    mini = FastAPI()
    mini.include_router(E.router)
    rc = TestClient(mini)

    async def fake_env_runner(method, path, env_id, *, params=None, content=None, timeout=120.0):
        if content is not None and hasattr(content, "__aiter__"):
            content = b"".join([c async for c in content])
        return rc.request(method, path, params={"identifier": env_id, **(params or {})}, content=content)

    app._env_runner = fake_env_runner
    with TestClient(app.app) as c:
        class Api:
            def __getattr__(self, m):
                def call(path, **kw):
                    kw["headers"] = {**H, **(kw.get("headers") or {})}
                    return getattr(c, m)(path, **kw)
                return call
        yield Api()


def _wait_build(api, eid, n, seconds=240):
    for _ in range(seconds * 4):
        b = api.get(f"/v1/environments/{eid}/builds/{n}").json()
        if b["status"] in ("ready", "failed"):
            return b
        time.sleep(0.25)
    raise AssertionError("build did not finish")


def test_an_environment_is_created_with_a_slug_and_an_empty_status(api):
    r = api.post("/v1/environments", json={"name": "Content Studio", "description": "the studio", "entry": "python3 run.py"})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["object"] == "environment" and e["id"].startswith("henv_") and e["slug"] == "content-studio"
    assert e["mount"] == "/env/content-studio" and e["status"] == "empty" and e["version"] is None
    assert e["entry"] == "python3 run.py" and e["files"] == {"count": 0, "bytes": 0}
    # one mount per instance: the same name again is refused, a name that is no slug is refused
    r = api.post("/v1/environments", json={"name": "content studio"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "environment_exists"
    r = api.post("/v1/environments", json={"name": "###"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "environment_invalid"
    assert any(x["id"] == e["id"] for x in api.get("/v1/environments").json()["environments"])


def test_files_go_in_and_come_back_and_a_path_out_of_the_tree_is_refused(api):
    eid = api.post("/v1/environments", json={"name": "files-env"}).json()["id"]
    assert api.put(f"/v1/environments/{eid}/files/scripts/render.py", content=b"print('render')\n").status_code == 200
    assert api.post(f"/v1/environments/{eid}/directories", json={"path": "assets/brand"}).status_code == 200
    r = api.get(f"/v1/environments/{eid}/files/scripts/render.py")
    assert r.status_code == 200 and r.content == b"print('render')\n"
    t = api.get(f"/v1/environments/{eid}/files").json()
    assert {x["path"] for x in t["entries"]} == {"assets", "assets/brand", "scripts", "scripts/render.py"} and t["count"] == 1
    r = api.put(f"/v1/environments/{eid}/files/../escape.txt", content=b"x")
    assert r.status_code in (404, 422)          # the router normalises `..` away or the runner refuses it
    assert api.get(f"/v1/environments/{eid}/files/escape.txt").status_code == 404
    assert api.delete(f"/v1/environments/{eid}/files/scripts").status_code == 200
    assert api.get(f"/v1/environments/{eid}/files").json()["count"] == 0
    assert api.get(f"/v1/environments/{eid}").json()["files"]["count"] == 0


def test_an_archive_import_keeps_the_tree(api):
    eid = api.post("/v1/environments", json={"name": "import-env"}).json()["id"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("proj-main/run.py", "print(1)\n")
        zf.writestr("proj-main/scripts/lib/util.py", "x = 1\n")
        zf.writestr("proj-main/requirements.txt", "")
    r = api.post(f"/v1/environments/{eid}/import", content=buf.getvalue(), headers={"content-type": "application/zip"})
    assert r.status_code == 200 and r.json()["written"] == 3, r.text
    assert {x["path"] for x in api.get(f"/v1/environments/{eid}/files").json()["entries"] if not x["dir"]} == \
        {"run.py", "scripts/lib/util.py", "requirements.txt"}
    r = api.post(f"/v1/environments/{eid}/import", json={"git": {}})
    assert r.status_code == 422


def test_a_build_becomes_the_active_version_and_a_task_may_read_it(api):
    eid = api.post("/v1/environments", json={"name": "build-env", "entry": "python3 run.py"}).json()["id"]
    # nothing to read yet: a harness may name it, a task may not run on it
    h = api.post("/v1/harnesses", json={"name": "env-harness", "base": next(iter(app._BASE_CATALOG)), "environment": eid}).json()
    assert h["environment"] == eid
    with pytest.raises(Exception) as ex:
        import asyncio
        asyncio.run(app._environment_for_turn(ORG, eid))
    assert "environment_not_ready" in str(getattr(ex.value, "detail", ex.value))
    api.put(f"/v1/environments/{eid}/files/run.py", content=b"import sys\nprint(sys.prefix)\n")
    api.put(f"/v1/environments/{eid}/files/requirements.txt", content=b"")
    r = api.post(f"/v1/environments/{eid}/build")
    assert r.status_code == 200 and r.json() == {"id": eid, "object": "environment.build", "version": 1, "status": "building"}
    assert api.post(f"/v1/environments/{eid}/build").status_code == 409     # one at a time
    b = _wait_build(api, eid, 1)
    assert b["status"] == "ready", b.get("log")
    assert any(pk["manager"] == "pip" for pk in b["packages"]) and "run.py" not in b.get("error", "")
    e = api.get(f"/v1/environments/{eid}").json()
    assert e["status"] == "ready" and e["version"] == 1 and e["latestVersion"] == 1
    assert e["build"]["status"] == "ready" and e["packages"] == b["packages"]
    spec = __import__("asyncio").run(app._environment_for_turn(ORG, eid))
    assert spec == {"id": eid, "slug": "build-env", "entry": "python3 run.py", "version": 1, "path": "/env/build-env"}
    # the runner's view agrees: the mount points at version 1, read-only
    assert E.active_version(eid) == 1 and os.path.islink(E.mount_path("build-env"))
    # a second build, then rollback by pointer
    api.put(f"/v1/environments/{eid}/files/run.py", content=b"print('v2')\n")
    api.post(f"/v1/environments/{eid}/build")
    assert _wait_build(api, eid, 2)["status"] == "ready"
    assert api.get(f"/v1/environments/{eid}").json()["version"] == 2
    r = api.post(f"/v1/environments/{eid}/versions/1/activate")
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["latestVersion"] == 2
    assert api.post(f"/v1/environments/{eid}/versions/9/activate").status_code == 409
    v = api.get(f"/v1/environments/{eid}/versions").json()
    assert v["active"] == 1 and [x["version"] for x in v["versions"]] == [1, 2]
    assert api.get(f"/v1/environments/{eid}/harnesses").json()["harnesses"][0]["id"] == h["id"]
    # the session detail names the environment a turn ran with (stamped by the turn)
    api.delete(f"/v1/harnesses/{h['id']}")
    assert api.delete(f"/v1/environments/{eid}").status_code == 200
    assert api.get(f"/v1/environments/{eid}").status_code == 404
    assert not os.path.lexists(E.mount_path("build-env"))


def test_a_harness_cannot_name_an_environment_that_is_not_there(api):
    r = api.post("/v1/harnesses", json={"name": "bad-env", "base": next(iter(app._BASE_CATALOG)),
                                        "environment": "henv_00000000000000000000000000000000"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "environment_not_found"


def test_environments_are_scoped_to_the_workspace(api):
    ws = {"x-harness-workspace": "ws1"}
    eid = api.post("/v1/environments", json={"name": "ws-env"}, headers=ws).json()["id"]
    assert any(x["id"] == eid for x in api.get("/v1/environments", headers=ws).json()["environments"])
    assert not any(x["id"] == eid for x in api.get("/v1/environments", headers={"x-harness-workspace": "ws2"}).json()["environments"])
    assert api.get(f"/v1/environments/{eid}", headers={"x-harness-workspace": "ws2"}).status_code == 404
    assert any(x["id"] == eid for x in api.get("/v1/environments").json()["environments"])   # an org-wide key sees all


def test_declared_packages_and_the_runtime_are_kept_and_handed_to_the_build(api, monkeypatch):
    eid = api.post("/v1/environments", json={"name": "declared-env", "packages": {"pip": ["pyyaml==6.0.2", " bad spec!", "pyyaml==6.0.2"], "npm": ["sharp@0.33.5", "@scope/pkg@1.0.0"], "apt": ["ffmpeg"]}, "runtime": {"python": "3.12"}}).json()["id"]
    e = api.get(f"/v1/environments/{eid}").json()
    assert [x["spec"] for x in e["declared"]["pip"]] == ["pyyaml==6.0.2"] and e["declared"]["pip"][0] == {"name": "pyyaml", "version": "6.0.2", "spec": "pyyaml==6.0.2"}
    assert e["declared"]["npm"][1] == {"name": "@scope/pkg", "version": "1.0.0", "spec": "@scope/pkg@1.0.0"}
    assert e["declared"]["apt"] == [{"name": "ffmpeg", "version": "", "spec": "ffmpeg"}] and e["runtime"] == {"python": "3.12"}
    # an update without packages leaves them; one with packages replaces them
    api.put(f"/v1/environments/{eid}", json={"name": "declared-env", "entry": "python3 run.py"})
    assert [x["spec"] for x in api.get(f"/v1/environments/{eid}").json()["declared"]["pip"]] == ["pyyaml==6.0.2"]
    api.put(f"/v1/environments/{eid}", json={"name": "declared-env", "packages": {"pip": [], "npm": [], "apt": []}, "runtime": {"python": ""}})
    e = api.get(f"/v1/environments/{eid}").json()
    assert e["declared"] == {"pip": [], "npm": [], "apt": []} and e["runtime"] == {"python": ""}
    # the build receives the declared lists and the runtime as its body
    seen = {}
    real = app._env_runner

    async def spy(method, path, env_id, **kw):
        if path.endswith("/build") and method == "POST":
            seen["body"] = json.loads(kw.get("content") or b"{}")
        return await real(method, path, env_id, **kw)
    monkeypatch.setattr(app, "_env_runner", spy)
    api.put(f"/v1/environments/{eid}", json={"name": "declared-env", "packages": {"pip": ["pyyaml==6.0.2"]}, "runtime": {"python": "3.12"}})
    api.put(f"/v1/environments/{eid}/files/run.py", content=b"print(1)\n")
    assert api.post(f"/v1/environments/{eid}/build").status_code == 200
    assert seen["body"] == {"pip": ["pyyaml==6.0.2"], "npm": [], "apt": [], "python": "3.12"}
    _wait_build(api, eid, 1)   # the runner installs it (network) or fails; either way the record answers
    monkeypatch.setattr(app, "_env_runner", real)
    r = api.get("/v1/environments/runtimes")
    assert r.status_code == 200 and isinstance(r.json().get("python"), list) and "os" in r.json()


def test_the_task_names_its_environment_in_metadata_like_the_harness():
    """The task request is a Responses request: its environment travels in metadata beside
    harness_id (environments.md §5), never as a top-level field; the harness's is the default."""
    from types import SimpleNamespace as NS
    hv = {"environment": "henv_harness"}
    assert app._task_environment_ref(NS(metadata={"harness_id": "chrn_1", "environment": "henv_task"}), hv) == "henv_task"
    assert app._task_environment_ref(NS(metadata={"harness_id": "chrn_1"}), hv) == "henv_harness"
    assert app._task_environment_ref(NS(metadata=None), hv) == "henv_harness"
    assert app._task_environment_ref(NS(metadata={}), None) == ""
    assert not hasattr(app.CreateResponseBody.model_fields, "environment") and "environment" not in app.CreateResponseBody.model_fields
