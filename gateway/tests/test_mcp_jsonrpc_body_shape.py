"""Regression coverage for hosted MCP JSON-RPC body shapes."""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402


ENDPOINTS = [
    ("/v1/mcp/database", "database"),
    ("/v1/mcp/media", "media"),
    ("/v1/mcp/plugs", "plugs"),
    ("/v1/mcp/memories", "memories"),
]
AUTH = {"authorization": f"Bearer {gw._mint_hosted_cred('h_shape', 'sess_shape', 'mcp.x')}"}
MALFORMED = "malformed JSON-RPC request"


@pytest.fixture(scope="module")
def client():
    with TestClient(gw.app, raise_server_exceptions=False) as c:
        yield c


def post(client, path, body):
    return client.post(path, headers={**AUTH, "content-type": "application/json"}, content=body)


@pytest.mark.parametrize("path,_name", ENDPOINTS)
@pytest.mark.parametrize("body", [b"[]", b"null", b'"x"', b"5"])
def test_non_object_json_rpc_body_is_malformed(client, path, _name, body):
    response = post(client, path, body)
    assert response.status_code == 400
    assert response.json()["detail"] == MALFORMED


@pytest.mark.parametrize("path,_name", ENDPOINTS)
@pytest.mark.parametrize(
    "body",
    [
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":[]}',
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":false}',
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":0}',
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":""}',
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":[1]}',
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":"x"}',
    ],
)
def test_non_object_json_rpc_params_are_malformed(client, path, _name, body):
    response = post(client, path, body)
    assert response.status_code == 400
    assert response.json()["detail"] == MALFORMED


@pytest.mark.parametrize("path,_name", ENDPOINTS)
def test_non_json_body_stays_malformed(client, path, _name):
    response = post(client, path, b"{")
    assert response.status_code == 400
    assert response.json()["detail"] == MALFORMED


@pytest.mark.parametrize("path,name", ENDPOINTS)
def test_initialize_still_returns_the_endpoint_name(client, path, name):
    body = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
    response = post(client, path, body)
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == name


@pytest.mark.parametrize("path,name", ENDPOINTS)
@pytest.mark.parametrize(
    "body",
    [
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":null}',
        b'{"jsonrpc":"2.0","id":1,"method":"initialize"}',
    ],
)
def test_initialize_accepts_null_or_missing_params(client, path, name, body):
    response = post(client, path, body)
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == name


@pytest.mark.parametrize("path,_name", ENDPOINTS)
def test_empty_body_stays_a_notification(client, path, _name):
    response = post(client, path, b"")
    assert response.status_code == 202
    assert response.content == b""
