"""An address with a port that is not a number, or is out of range, is refused by the check that reads it.

urllib's parsers check a port only when `.port` is read, and they raise ValueError then. Every check below
parsed inside a try and read the port outside it, so "https://host:abc/" or "https://host:99999/" raised past
the check and its caller answered 500 where it answers a refusal for every other address that is not valid.
The connection-string half of this is test_database_mcp's test_an_invalid_connection_string_port_is_a_safe_error.
"""
import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

BAD_PORTS = ["abc", "99999", "-1"]


@pytest.fixture(params=[False, True], ids=["shared", "self-hosted"])
def local(request, monkeypatch):
    monkeypatch.setattr(gw, "_pool_is_local", lambda: request.param)
    return request.param


@pytest.mark.parametrize("port", BAD_PORTS)
def test_an_mcp_address_with_a_bad_port_is_an_invalid_url(port, local):
    assert asyncio.run(gw._ssrf_check(f"https://mcp.example.com:{port}/mcp")) == "invalid url"


@pytest.mark.parametrize("port", BAD_PORTS)
def test_a_cloud_address_with_a_bad_port_is_an_invalid_url(port, local):
    assert asyncio.run(gw._cloud_base_refused(f"https://cloud.example.com:{port}")) == "invalid url"


@pytest.mark.parametrize("port", BAD_PORTS)
def test_a_provider_file_address_with_a_bad_port_is_refused(port, local):
    assert asyncio.run(gw._provider_url_check(f"https://files.example.com:{port}/x.mp4")) is not None


@pytest.mark.parametrize("port", BAD_PORTS)
def test_a_memory_engine_address_with_a_bad_port_is_not_valid(port):
    assert gw._own_service_address(f"http://localhost:{port}") == "it is not a valid address"


def test_a_good_port_still_reads_as_before(monkeypatch):
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)
    assert asyncio.run(gw._ssrf_check("http://127.0.0.1:8765/mcp")) is None
    assert asyncio.run(gw._cloud_base_refused("http://10.0.0.5:3000")) is None
    assert gw._own_service_address("http://localhost:8080") == "it is this instance itself"
    assert gw._own_service_address("http://localhost:8000") == ""
