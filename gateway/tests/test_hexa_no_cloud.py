"""Hexa's product surface has no HarnessRouter Cloud deployment or account features."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_cloud_routes_and_hosted_provider_are_absent_from_hexa():
    paths = {getattr(route, "path", "") for route in gw.app.routes}
    assert not [p for p in paths if p.startswith("/v1/cloud-upload")]
    assert "/v1/admin/connect" not in paths
    assert "/v1/admin/connect/{code}" not in paths
    assert "/v1/harnesses/upload" not in paths
    assert "/v1/harnesses/{hid}/upload" not in paths
    assert "harnessrouter" not in gw._PROVIDER_CATALOG
    assert not any(provider == "harnessrouter" for provider, _backend in gw._INTEGRATION_WIRING)
    assert "harnessrouter" not in {entry["id"] for entry in gw._provider_catalog_public()}


def test_public_openapi_and_local_provider_catalog_remain_available():
    doc = gw._openapi_public()
    paths = set(doc["paths"])
    assert not [p for p in paths if p.startswith("/v1/cloud-upload")]
    assert "/v1/harnesses" in paths
    assert "/v1/uhp" in paths
    ids = {entry["id"] for entry in gw._provider_catalog_public()}
    assert {"anthropic", "openai", "custom"}.issubset(ids)
