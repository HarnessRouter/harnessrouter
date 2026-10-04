"""UHP conformance suite — the definition of "conformant" for the Unified Harness Protocol."""
__version__ = "2026.9.12.post4"
UHP_VERSION = "2026-10-04"
# The MCP server the plugin checks point a plugin at. It must resolve and answer: a host is
# allowed to refuse a server it cannot reach at configuration time and record that in `skipped`,
# so an unresolvable placeholder made those checks measure the refusal instead of the plugin. The
# suite ships the server (`uhp-conformance-fixture`, see fixture.py); this is a public copy of it.
DEFAULT_PLUGIN_MCP_URL = "https://uhp-fixture.harnessrouter.ai/mcp"
