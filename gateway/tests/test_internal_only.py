"""An internal-only route answers a service and nobody else (GHSA-p6cq-54cg-8mpv).

A console proxy that is not in self-hosted mode attaches the internal key to every request that
carries a bearer, before anything verifies the bearer. The routes that take only the internal key (an
organization's connections and routing, the /internal/* routes) took it as enough, so a junk bearer
through such a console reached them and could rewrite any organization's connections. A service calls
them with the key and nothing else; a request that also carries a bearer is a person's or a key's,
relayed, and is refused. Found live on the hosted service and closed there the same way.
"""
import ast
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

KEY = "internal-test-key"
THREE = {"put_connection", "get_connection_meta", "put_policy"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(gw, "INTERNAL_KEY", KEY)
    seen = []

    async def get_connection(org, name):
        seen.append(("read", org, name))
        return None, ""

    async def vault_put(org, key, value):
        seen.append(("write", org, key))
    monkeypatch.setattr(gw, "_get_connection", get_connection)
    monkeypatch.setattr(gw, "_vault_put", vault_put)
    monkeypatch.setattr(gw.control_store, "enabled", lambda: False)
    with TestClient(gw.app) as c:
        yield c, seen


@pytest.mark.parametrize("auth", ["Bearer junk", "Bearer eyJhbGciOiJIUzI1NiJ9.e30.x", "Basic Zm9vOmJhcg==", "sk-hr-anything"])
def test_a_relayed_request_with_a_bearer_is_refused_before_the_route_runs(client, auth):
    c, seen = client
    h = {"x-harness-internal": KEY, "authorization": auth}
    assert c.get("/v1/orgs/org.victim/connections/default", headers=h).status_code == 401
    assert c.put("/v1/orgs/org.victim/connections/default", headers=h,
                 json={"provider": "openai", "base_url": "https://attacker.example/v1", "api_key": "sk-x"}).status_code == 401
    assert c.put("/v1/orgs/org.victim/policy/codex", headers=h, json={"connections": ["default"]}).status_code == 401
    assert c.get("/internal/storage-usage", headers=h).status_code == 401
    assert seen == []


def test_a_service_with_the_key_and_nothing_else_is_answered(client):
    c, seen = client
    assert c.get("/v1/orgs/org.acme/connections/default", headers={"x-harness-internal": KEY}).status_code == 404   # ran: not found
    assert c.put("/v1/orgs/org.acme/policy/codex", headers={"x-harness-internal": KEY}, json={"connections": ["default"]}).status_code == 200
    assert seen == [("read", "org.acme", "default"), ("write", "org.acme", "harness-policy-codex")]
    assert c.get("/v1/orgs/org.acme/connections/default").status_code == 401
    assert c.get("/v1/orgs/org.acme/connections/default", headers={"x-harness-internal": "wrong"}).status_code == 401
    assert c.get("/v1/orgs/org.acme/connections/default", headers={"x-harness-internal": KEY + "x"}).status_code == 401


def test_every_internal_route_and_the_three_writers_go_through_the_one_guard():
    """No route trusts the key on its own terms: each takes _internal_only, which refuses a bearer."""
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    tree = ast.parse(src)
    guarded, internal_paths = set(), 0
    for fn in [n for n in tree.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))]:
        for d in fn.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and getattr(d.func.value, "id", "") == "app":
                if "_internal_only" in ast.unparse(d):
                    guarded.add(fn.name)
                path = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else ""
                if str(path).startswith("/internal/"):
                    internal_paths += 1
                    assert "_internal_only" in ast.unparse(d), f"{path} ({fn.name}) is not guarded"
    assert internal_paths >= 5 and THREE <= guarded, (internal_paths, sorted(guarded))
    # the key is compared in two places and no third: this guard, and _principal's own internal branch
    assert src.count('== INTERNAL_KEY') + src.count("INTERNAL_KEY.encode())") == 2


def test_the_console_proxy_does_not_forward_internal_routes_outside_a_self_hosted_box():
    route = (Path(__file__).resolve().parents[2] / "ui" / "src" / "app" / "api" / "harness" / "[...path]" / "route.ts").read_text()
    guard = route.index("if (!SELF_HOSTED && (path || [])[0] === 'internal')")
    assert guard < route.index("headers['x-harness-internal'] = INTERNAL_KEY")
    assert "if (lk === 'x-harness-internal') return;" in route          # and a browser's own copy of the header is dropped
