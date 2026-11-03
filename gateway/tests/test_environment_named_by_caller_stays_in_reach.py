"""A caller names only an environment its workspace can reach.

The environment routes hold the workspace rule, but a task's `metadata.environment` and a harness's field checked only the
organization, so a workspace's key could mount another workspace's project files (GHSA-gf7m). A caller with no workspace of
its own to compare, such as an internal call, is not judged here.
"""
import asyncio
import pathlib
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

ENV = "henv_" + "0" * 32


@pytest.fixture
def env_in_workspace_a(monkeypatch):
    async def vertex(org, env_id):
        return {"id": env_id, "org": org, "workspace": "workspace-a"} if env_id == ENV and org == "org1" else None
    monkeypatch.setattr(gw, "_environment_vertex", vertex)


def _call(env_id, principal):
    asyncio.run(gw._environment_in_reach("org1", env_id, principal))


def test_its_own_workspace_reaches_it(env_in_workspace_a):
    _call(ENV, {"org": "org1", "workspace": "workspace-a"})


def test_another_workspace_does_not_and_is_told_it_does_not_exist(env_in_workspace_a):
    with pytest.raises(HTTPException) as e:
        _call(ENV, {"org": "org1", "workspace": "workspace-b"})
    assert e.value.status_code == 404


def test_a_caller_with_no_workspace_and_a_task_with_no_environment_are_not_judged(env_in_workspace_a):
    _call(ENV, {"org": "org1"})
    _call(ENV, None)
    _call("", {"org": "org1", "workspace": "workspace-b"})


def test_a_harness_naming_one_is_held_to_the_same_rule(env_in_workspace_a):
    with pytest.raises(HTTPException):
        asyncio.run(gw._environment_check_ref("org1", ENV, {"org": "org1", "workspace": "workspace-b"}))
    asyncio.run(gw._environment_check_ref("org1", ENV, {"org": "org1", "workspace": "workspace-a"}))
    asyncio.run(gw._environment_check_ref("org1", None, {"org": "org1", "workspace": "workspace-b"}))
