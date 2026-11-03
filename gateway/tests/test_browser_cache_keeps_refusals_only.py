"""The browser's private-address check remembers a refusal and nothing else.

A public answer was kept for the session, so a host could answer with a public address once and a private one ever after
(GHSA-3vf8). The check only sees what this side resolves; the page still loads where the browser resolves it.
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import browser_plane  # noqa: E402


class _S:
    vendor_id = "vendor-browser"
    allow: list = []
    deny: list = []

    def __init__(self):
        self.host_cache = {}


def _check(s, url):
    return asyncio.run(browser_plane._allowed(s, url))


def test_a_host_that_turns_private_is_refused_though_it_answered_public_before(monkeypatch):
    answers = [False, True]
    asked = []

    async def resolves(host):
        asked.append(host)
        return answers.pop(0)
    monkeypatch.setattr(browser_plane, "resolves_private", resolves)
    s = _S()
    assert _check(s, "https://rebinds.example/") is None
    assert _check(s, "https://rebinds.example/") == "a private or local address"
    assert asked == ["rebinds.example", "rebinds.example"], "a public answer must not be remembered"


def test_a_refusal_is_remembered(monkeypatch):
    asked = []

    async def resolves(host):
        asked.append(host)
        return True
    monkeypatch.setattr(browser_plane, "resolves_private", resolves)
    s = _S()
    assert _check(s, "https://internal.example/") == "a private or local address"
    assert _check(s, "https://internal.example/") == "a private or local address"
    assert asked == ["internal.example"]
