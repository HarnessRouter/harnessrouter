"""A turn addressed to a harness runs on that harness or not at all."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_an_unknown_harness_id_is_refused_and_a_base_id_or_no_id_is_not():
    """A typo'd chrn_ id used to run on the default backend and bill the caller; now it is a 404 like
    a deleted harness. A base id is a harness without a vertex and still runs; no id at all is an
    ad-hoc turn and still runs."""
    gw._turn_harness_check("", None)
    base = next(iter(gw._BASE_CATALOG))
    gw._turn_harness_check(base, None)
    gw._turn_harness_check("chrn_0123456789abcdef", {"id": "chrn_0123456789abcdef", "org": "org.a", "deleted": "0"})
    with pytest.raises(Exception) as e:
        gw._turn_harness_check("chrn_doesnotexist0000", None)
    assert "harness_not_found" in str(getattr(e.value, "detail", e.value)) or "No harness" in str(e.value)
    with pytest.raises(Exception):
        gw._turn_harness_check("chrn_0123456789abcdef", {"id": "chrn_0123456789abcdef", "deleted": "1"})


def test_capability_digest_excludes_secrets_but_changes_with_effective_plugin_composition():
    base = {
        'base': 'claude-code',
        'mcp_servers': '[{"name":"docs","transport":"http","url":"https://mcp.example/docs","headers":{"Authorization":"secret-a"}}]',
        'skills': '[{"name":"brief","description":"Write briefly"}]',
        'disabled_tools': '["shell"]',
        'plugins': '[{"name":"pack","enabled":true,"blob":"plugin_1","manifest":{"name":"pack","version":"1.0.0"},"mcpServers":[{"name":"search","transport":"stdio","command":"./search","env":{"TOKEN":"secret-a"}}],"skills":[{"name":"search-skill","description":"Search"}],"skipped":[]}]',
    }
    same_secrets = {**base, 'mcp_servers': base['mcp_servers'].replace('secret-a', 'secret-b'),
                    'plugins': base['plugins'].replace('secret-a', 'secret-b')}
    changed = {**base, 'plugins': base['plugins'].replace('1.0.0', '1.1.0')}
    assert gw._harness_capability_digest(base) == gw._harness_capability_digest(same_secrets)
    assert gw._harness_capability_digest(base) != gw._harness_capability_digest(changed)
    assert gw._harness_out({**base, 'id': 'h1'})['capabilityDigest'] == gw._harness_capability_digest(base)


def test_capability_binding_rejects_bad_or_changed_digest_and_accepts_current_one():
    harness = {'base': 'claude-code', 'mcp_servers': '[]', 'skills': '[]',
               'disabled_tools': '[]', 'plugins': '[]'}
    digest = gw._harness_capability_digest(harness)
    gw._validate_capability_binding({'capability_digest': digest}, harness)
    with pytest.raises(Exception) as bad:
        gw._validate_capability_binding({'capability_digest': 'A' * 64}, harness)
    assert 'invalid_input' in str(getattr(bad.value, 'detail', bad.value))
    with pytest.raises(Exception) as changed:
        gw._validate_capability_binding({'capability_digest': 'b' * 64}, harness)
    assert 'hexa_capability_changed' in str(getattr(changed.value, 'detail', changed.value))


def test_direct_skill_content_changes_the_digest_without_exposing_the_body():
    first = {'base': 'claude-code', 'mcp_servers': '[]', 'disabled_tools': '[]',
             'skills': json.dumps([{'name': 'guide', 'files': [{'path': 'SKILL.md', 'content': 'one'}]}]),
             'plugins': '[]'}
    second = {**first, 'skills': json.dumps([{'name': 'guide', 'files': [{'path': 'SKILL.md', 'content': 'two'}]}])}
    one = gw._harness_capability_digest(first)
    two = gw._harness_capability_digest(second)
    assert one != two
    assert 'one' not in one and 'two' not in two
