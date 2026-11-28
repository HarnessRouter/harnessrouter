from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plugs_plane  # noqa: E402


@pytest.fixture
def vendor_requests():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT" and request.url.path == "/repos/acme/site/pulls/7/merge":
            return httpx.Response(200, json={"sha": "abc", "merged": True, "message": "merged"})
        if request.method == "GET" and request.url.path == "/repos/acme/site/commits":
            return httpx.Response(200, json=[])
        if request.method == "POST" and request.url.path == "/repos/acme/site/actions/runs/123/rerun":
            return httpx.Response(204)
        return httpx.Response(404, json={"message": "unexpected request"})

    previous = plugs_plane.transport
    plugs_plane.transport = httpx.MockTransport(handler)
    try:
        yield requests
    finally:
        plugs_plane.transport = previous


def _call(name: str, args: dict) -> str:
    return asyncio.run(plugs_plane.call(
        "github", name, args, {"token": "test-token"},
        {"repo": "acme/site", "default_branch": "main"},
    ))


@pytest.mark.parametrize("number", [7.9, True, "#7", "abc", [7], "9" * 5000])
def test_write_tool_refuses_non_whole_numbers_without_calling_vendor(vendor_requests, number):
    with pytest.raises(plugs_plane.PlugToolError, match="number must be a whole number"):
        _call("merge_pull_request", {"number": number})
    assert vendor_requests == []


def test_write_tool_requires_its_number_without_calling_vendor(vendor_requests):
    with pytest.raises(plugs_plane.PlugToolError, match="number is required"):
        _call("merge_pull_request", {})
    assert vendor_requests == []


@pytest.mark.parametrize("number", [7, "7", 7.0, "+7", " 7 "])
def test_write_tool_accepts_whole_number_forms(vendor_requests, number):
    _call("merge_pull_request", {"number": number})
    assert vendor_requests[-1].url.path == "/repos/acme/site/pulls/7/merge"


def test_count_arguments_are_validated_defaulted_and_clamped(vendor_requests):
    with pytest.raises(plugs_plane.PlugToolError, match="per_page must be a whole number"):
        _call("list_commits", {"per_page": "ten"})
    assert vendor_requests == []

    for per_page, expected in (
        ("50", 50), (50, 50), (500, 100), (0, 30), ("0", 30), ("", 30), ("  ", 30), (None, 30),
    ):
        args = {} if per_page is None else {"per_page": per_page}
        _call("list_commits", args)
        assert vendor_requests[-1].url.params["per_page"] == str(expected)


def test_non_github_count_is_validated_without_calling_vendor(vendor_requests):
    with pytest.raises(plugs_plane.PlugToolError, match="top must be a whole number"):
        asyncio.run(plugs_plane.call(
            "microsoft365", "find_people", {"query": "Ada", "top": "ten"}, {}, {},
        ))
    assert vendor_requests == []


def test_read_file_refuses_max_chars_before_reading_the_file(vendor_requests):
    with pytest.raises(plugs_plane.PlugToolError, match="max_chars must be a whole number"):
        asyncio.run(plugs_plane.call(
            "microsoft365", "read_file", {"path": "notes.txt", "max_chars": "lots"}, {}, {},
        ))
    assert vendor_requests == []


def test_rerun_workflow_returns_normalized_run_id(vendor_requests):
    out = json.loads(_call("rerun_workflow_run", {"run_id": "123"}))
    assert out == {"rerun": True, "run_id": 123}
    assert vendor_requests[-1].url.path == "/repos/acme/site/actions/runs/123/rerun"
