"""An address somebody else names is connected to only as it was classified.

The check resolved the name and the client resolved it again when it opened the socket, so a name
that answered a public address to the check and an internal one a moment later (a DNS rebind)
reached the internal one. `_CheckedNetwork` resolves once, classifies every answer and connects to
one of those very addresses. These tests answer the lookup themselves, differently each time.
"""
import asyncio
import pathlib
import socket
import sys

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


async def _server():
    """A plain HTTP server on 127.0.0.1 that counts the connections it accepts."""
    seen = {"connections": 0, "hosts": []}

    async def handle(reader, writer):
        seen["connections"] += 1
        head = (await reader.readuntil(b"\r\n\r\n")).decode()
        seen["hosts"] += [ln.split(":", 1)[1].strip() for ln in head.split("\r\n") if ln.lower().startswith("host:")]
        writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: 11\r\n"
                     b"connection: close\r\n\r\n{\"ok\":true}")
        await writer.drain()
        writer.close()
    srv = await asyncio.start_server(handle, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1], seen


def _answers(*addrs):
    """A resolver that answers each call with the next address, and counts the calls."""
    calls = []

    async def resolve(host, port):
        calls.append(host)
        addr = addrs[min(len(calls), len(addrs)) - 1]
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (addr, port))]
    return resolve, calls


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(gw, "_checked_clients", {})


def test_a_name_that_rebinds_to_an_internal_address_is_never_connected_to(monkeypatch):
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)          # shared by several organizations

    async def go():
        srv, port, seen = await _server()
        resolve, calls = _answers("140.82.112.3", "127.0.0.1")       # public to the check, then internal
        monkeypatch.setattr(gw, "_resolve", resolve)
        assert await gw._cloud_base_refused(f"https://rebind.test:{port}") is None
        with pytest.raises(httpx.ConnectError) as e:
            await gw._checked_http().get(f"https://rebind.test:{port}/v1/me")
        srv.close()
        return seen, calls, str(e.value)
    seen, calls, err = asyncio.run(go())
    assert "cannot be used" in err and "internal" in err
    assert len(calls) == 2                       # the connection classified the name itself
    assert seen["connections"] == 0              # and opened nothing to the internal answer


def test_the_socket_goes_to_the_address_that_was_classified(monkeypatch):
    """`pinned.test` resolves nowhere for the system: a request that reaches the server got there
    through the classified address. The Host header still names the name."""
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)
    monkeypatch.setattr(gw, "_ip_internal", lambda addr: False)       # let this one test address pass

    async def go():
        srv, port, seen = await _server()
        resolve, _ = _answers("127.0.0.1")
        monkeypatch.setattr(gw, "_resolve", resolve)
        r = await gw._checked_http().get(f"http://pinned.test:{port}/")
        srv.close()
        return r, seen, port
    r, seen, port = asyncio.run(go())
    assert r.status_code == 200 and seen["connections"] == 1 and seen["hosts"] == [f"pinned.test:{port}"]


def test_a_self_hosted_box_still_reaches_its_own_network_for_addresses_its_owner_typed(monkeypatch):
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)

    async def go():
        srv, port, seen = await _server()
        r = await gw._checked_http().get(f"http://127.0.0.1:{port}/")
        srv.close()
        return r, seen
    r, seen = asyncio.run(go())
    assert r.status_code == 200 and seen["connections"] == 1


def test_a_providers_file_address_is_checked_on_every_deployment(monkeypatch):
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)

    async def go():
        srv, port, seen = await _server()
        resolve, _ = _answers("140.82.112.3", "127.0.0.1")
        monkeypatch.setattr(gw, "_resolve", resolve)
        assert await gw._provider_url_check(f"http://cdn.test:{port}/clip.mp4") is None
        with pytest.raises(httpx.ConnectError):
            await gw._media_fetch_client().get(f"http://cdn.test:{port}/clip.mp4")
        srv.close()
        return seen
    assert asyncio.run(go())["connections"] == 0


def test_these_clients_follow_no_redirect_and_use_no_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    c = gw._checked_http()
    assert c.follow_redirects is False and not c._mounts


# ── a database connection: the address it reached, before any query ───────────────────────────
class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _fake_pg(monkeypatch, peer):
    """asyncpg as far as run_query uses it, with a connection that reached `peer`."""
    import types
    ran = []

    class Conn:
        _transport = types.SimpleNamespace(get_extra_info=lambda k: (peer, 5432) if k == "peername" else None)

        def transaction(self, readonly=False):
            return _Tx()

        async def fetch(self, sql):
            ran.append(sql)
            return []

        async def close(self):
            pass

    async def connect(dsn):
        return Conn()
    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=connect))
    return ran


def test_a_database_that_now_answers_inside_is_closed_before_any_query(monkeypatch):
    import sql_plane
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)
    ran = _fake_pg(monkeypatch, "10.0.0.5")
    with pytest.raises(sql_plane.SqlError) as e:
        asyncio.run(sql_plane.run_query("postgres", "postgres://u:p@db.example/app", "SELECT 1"))
    assert "private, local or metadata" in str(e.value) and ran == []


def test_a_database_outside_runs_and_a_self_hosted_one_inside_runs_too(monkeypatch):
    import sql_plane
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)
    ran = _fake_pg(monkeypatch, "140.82.112.3")
    asyncio.run(sql_plane.run_query("postgres", "postgres://u:p@db.example/app", "SELECT 1"))
    assert len(ran) == 1
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)
    ran = _fake_pg(monkeypatch, "127.0.0.1")
    asyncio.run(sql_plane.run_query("postgres", "postgres://u:p@localhost/app", "SELECT 1"))
    assert len(ran) == 1


def test_a_self_hosted_database_on_a_local_socket_runs(monkeypatch):
    """A Unix socket has no peer address. 0.32.1 refused it everywhere; only a shared deployment
    should, where an address that cannot be read is not one this server vouches for."""
    import sql_plane
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)
    ran = _fake_pg(monkeypatch, "")
    asyncio.run(sql_plane.run_query("postgres", "postgres://u:p@/app?host=/var/run/postgresql", "SELECT 1"))
    assert len(ran) == 1
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)
    ran = _fake_pg(monkeypatch, "")
    with pytest.raises(sql_plane.SqlError):
        asyncio.run(sql_plane.run_query("postgres", "postgres://u:p@/app?host=/var/run/postgresql", "SELECT 1"))
    assert ran == []


def test_the_checked_clients_limits_are_the_ones_applied():
    pool = gw._checked_http()._transport._pool
    assert pool._max_connections == 200 and pool._max_keepalive_connections == 40


def test_a_plugin_vendor_address_a_member_typed_cannot_reach_inside_even_by_redirect(monkeypatch):
    """An InsForge plug names its backend by a typed url, and the answer goes back to the agent."""
    import plugs_plane
    monkeypatch.setattr(plugs_plane, "transport", None)
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)

    async def classify(host, port):
        return (["127.0.0.1"], None) if host == "public.test" else ([], "target resolves to a disallowed (internal) address")
    monkeypatch.setattr(gw, "_classify_target", classify)

    async def go():
        inside, iport, iseen = await _server()

        async def bounce(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(f"HTTP/1.1 302 Found\r\nlocation: http://inside.test:{iport}/api/secrets\r\n"
                         f"content-length: 0\r\nconnection: close\r\n\r\n".encode())
            await writer.drain()
            writer.close()
        outside = await asyncio.start_server(bounce, "127.0.0.1", 0)
        oport = outside.sockets[0].getsockname()[1]
        errors = []
        for url in (f"http://inside.test:{iport}/api/health", f"http://public.test:{oport}/api/health"):
            try:
                async with plugs_plane.client() as c:
                    await c.get(url)
            except httpx.ConnectError as e:
                errors.append(str(e))
        inside.close()
        outside.close()
        return iseen, errors
    seen, errors = asyncio.run(go())
    assert len(errors) == 2 and all("cannot be used" in e for e in errors)
    assert seen["connections"] == 0


def test_a_self_hosted_plugin_vendor_on_the_boxs_own_network_still_works(monkeypatch):
    import plugs_plane
    monkeypatch.setattr(plugs_plane, "transport", None)
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)

    async def go():
        srv, port, seen = await _server()
        async with plugs_plane.client() as c:
            r = await c.get(f"http://127.0.0.1:{port}/api/health")
        srv.close()
        return r, seen
    r, seen = asyncio.run(go())
    assert r.status_code == 200 and seen["connections"] == 1
