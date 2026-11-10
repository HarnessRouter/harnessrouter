"""A memory vendor's address is connected to only as it was classified, on every call.

The address is one a member typed. put_plug checks it once when it's saved, and every read and
write after that calls it again, with what it answers shown to the reader. A name that answered a
public address to that check and an internal one later (a DNS rebind) must not be reached through
any of them: the vendors' clients open their connections through `_CheckedNetwork`, as the plugs'
client does. These tests answer the lookup themselves, public first and internal after.
"""
import asyncio
import pathlib
import socket
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402
import memory_graphiti  # noqa: E402
import memory_hindsight  # noqa: E402
import memory_mem0  # noqa: E402
import memory_plane as mp  # noqa: E402
import memory_reme  # noqa: E402

VENDORS = {
    "mem0": (memory_mem0, lambda base: memory_mem0.Mem0Server("k", base)),
    "graphiti": (memory_graphiti, lambda base: memory_graphiti.Graphiti(base_url=base, api_key="k")),
    "hindsight": (memory_hindsight, lambda base: memory_hindsight.Hindsight(base_url=base, api_key="k")),
    "reme": (memory_reme, lambda base: memory_reme.ReMe(base_url=base, api_key="k")),
}


async def _server():
    """A plain HTTP server on 127.0.0.1 that counts the connections it accepts."""
    seen = {"connections": 0}

    async def handle(reader, writer):
        seen["connections"] += 1
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: 2\r\n"
                     b"connection: close\r\n\r\n{}")
        await writer.drain()
        writer.close()
    srv = await asyncio.start_server(handle, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1], seen


def _rebinding():
    """Public to the first lookup (the check when the address is saved), internal to every one after."""
    calls = []

    async def resolve(host, port):
        calls.append(host)
        addr = "140.82.112.3" if len(calls) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (addr, port))]
    return resolve, calls


@pytest.fixture(autouse=True)
def shared(monkeypatch):
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)          # shared by several organizations
    for mod, _ in VENDORS.values():
        monkeypatch.setattr(mod, "transport", None)                    # the real client, not a test double


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_connecting_a_vendor_whose_address_rebinds_reaches_nothing_internal(vendor, monkeypatch):
    mod, _ = VENDORS[vendor]

    async def go():
        srv, port, seen = await _server()
        resolve, calls = _rebinding()
        monkeypatch.setattr(gw, "_resolve", resolve)
        base = f"https://rebind.test:{port}"
        assert await gw._ssrf_check(base) is None                     # what put_plug asks first: passes
        refusal = await mod.check("k", base)                          # then it tries the vendor
        srv.close()
        return seen, calls, refusal
    seen, calls, refusal = asyncio.run(go())
    assert refusal and "could not be reached" in refusal
    assert len(calls) == 2                                            # the connection classified the name itself
    assert seen["connections"] == 0


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_a_kept_vendor_address_that_rebinds_is_refused_on_every_call(vendor, monkeypatch):
    _, make = VENDORS[vendor]

    async def go():
        srv, port, seen = await _server()
        resolve, calls = _rebinding()
        monkeypatch.setattr(gw, "_resolve", resolve)
        base = f"https://rebind.test:{port}"
        assert await gw._ssrf_check(base) is None                     # it was fine when it was saved
        with pytest.raises(mp.MemoryError) as e:
            await make(base)._call("GET", "/anything")
        srv.close()
        return seen, calls, e.value
    seen, calls, err = asyncio.run(go())
    assert err.status in (502, 503) and err.code == "memory_unavailable"
    assert "internal" in err.message or "ConnectError" in err.message
    assert len(calls) == 2                                            # the call classified the name itself
    assert seen["connections"] == 0


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_a_self_hosted_instance_keeps_its_vendor_clients_as_they_were(vendor, monkeypatch):
    """There the check refuses nothing, and a client left to build its own transport keeps the
    environment's proxy: a box that reaches the Mem0 Platform through one still does."""
    mod, _ = VENDORS[vendor]
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)
    assert mod._transport() is None
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)
    assert isinstance(mod._transport()._pool._network_backend, gw._CheckedNetwork)
