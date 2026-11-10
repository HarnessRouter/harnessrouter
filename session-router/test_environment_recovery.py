"""Real environment routes behind two runners, with router persistence and failure injection."""
import asyncio
import importlib.util
import pathlib
import sys
import time
import os

import httpx
import pytest
from fastapi import FastAPI

pytest.importorskip("grp")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runner"))
import environment_snapshots
import environments as E

spec = importlib.util.spec_from_file_location("session_router_recovery", pathlib.Path(__file__).with_name("server.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def test_environment_recovers_on_another_runner_after_router_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_root", lambda: False)
    monkeypatch.setattr(E, "_tool_env", lambda: dict(os.environ))
    monkeypatch.setattr(E, "ENV_ROOT", str(tmp_path / "a"))
    roots = {"a": str(tmp_path / "a"), "b": str(tmp_path / "b")}
    monkeypatch.setattr(E, "ENV_MOUNT", str(tmp_path / "mounts"))
    mini = FastAPI()
    mini.include_router(E.router)

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            E.ENV_ROOT = roots[request.url.host]
            await request.aread()
            return await httpx.ASGITransport(mini).handle_async_request(request)

    def router():
        return R.create_app(db_path=str(tmp_path / "router.db"), static_runners=[("a", "http://a"), ("b", "http://b")],
                            client_factory=lambda: httpx.AsyncClient(transport=Transport()))

    async def go():
        first = router()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(first), base_url="http://router") as c:
            assert (await c.put("/environments/henv_a/source?identifier=henv_a&path=main.py", content=b"print(1)")).status_code == 200
            r = await c.post("/environments/henv_a/build?identifier=henv_a&version=1&slug=project", json={})
            assert r.status_code == 200
            for _ in range(100):
                r = await c.get("/environments/henv_a/build?identifier=henv_a&version=1")
                if r.status_code == 404:
                    await asyncio.sleep(.02)
                    continue
                assert r.status_code == 200, r.text
                if r.json()["status"] == "ready":
                    break
                await asyncio.sleep(.02)
            assert r.json()["status"] == "ready", r.text
        restarted = router()
        restarted.state._runners["a"].last_ok = time.time() - 1000
        async with httpx.AsyncClient(transport=httpx.ASGITransport(restarted), base_url="http://router") as c:
            r = await c.get("/environments/henv_a/source?identifier=henv_a&path=main.py")
            assert r.status_code == 200, r.text
            assert r.content == b"print(1)"
            assert restarted.state._affinity["henv_a"] == "b"
            assert E.active_version("henv_a") == 1
            assert (E.version_dir("henv_a", 1) / "main.py").read_bytes() == b"print(1)"
    asyncio.run(go())
