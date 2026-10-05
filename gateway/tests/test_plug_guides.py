"""An agent is told which plug tools it has. GitHub, Vercel and InsForge had no section in the
agent's instructions, and an agent that is told nothing looks where these vendors usually live (a
token in the environment, a signed-in CLI) and reports the job impossible with the plug connected."""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


def test_an_agent_is_told_the_tools_of_each_connected_plug_and_that_no_token_is_in_the_environment():
    doc = gw._agent_doc_with_plugs("Be brief.", ["github", "vercel", "insforge"])
    assert doc.startswith("Be brief.")
    for name in ("github_push_files", "github_create_pull_request", "vercel_deploy_from_repo",
                 "vercel_get_deployment_logs", "insforge_create_table", "insforge_get_project"):
        assert name in doc, name
    assert "no VERCEL_TOKEN" in doc and "`vercel` CLI is not signed in" in doc
    assert "## GitHub" in doc and "## Vercel" in doc and "## InsForge" in doc
    # the backend's real routes are named, so an agent does not walk its not-found page looking for them
    assert "GET /api/metadata" in doc and "POST /api/auth/sessions" in doc and "Do not guess a route" in doc
    assert "—" not in doc and "–" not in doc            # no dash punctuation in copy an agent and a person read
    # every tool the plane has is named, so a new tool cannot be left out of the section
    for plug in ("github", "vercel", "insforge"):
        for t in gw.plugs_plane._TOOLS[plug]:
            assert f"{plug}_{t['name']}" in doc


def test_a_harness_without_those_plugs_gets_no_section():
    assert gw._agent_doc_with_plugs("Be brief.", []) == "Be brief."
    assert "## Vercel" not in gw._agent_doc_with_plugs("", ["browser"])
