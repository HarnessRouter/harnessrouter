"""GET /v1/bases is in the published schema, and what the gateway serves there validates against it.

A client that calls only what the vendored UHP schema defines could not use /v1/bases: it was
served and read by the console, and described nowhere a client could generate from. These pin
both halves:

  the OpenAPI document names the path, and its 200 is a `BaseCatalog`
  the JSON Schema is the one build.py derives from that document, and the conformance package
      carries the same bytes
  every base the gateway lists validates, both installed and not installed, with models
      available and not, and every tool's `enforcement` is one of the schema's two words
"""
import asyncio
import json
import os
import pathlib
import sys

import jsonschema
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_VERSION = "2026-10-19"
_OPENAPI = _ROOT / "protocol" / "schema" / f"uhp-{_VERSION}.openapi.yaml"
_SCHEMA = _ROOT / "protocol" / "schema" / f"uhp-{_VERSION}.schema.json"


def _validator(name: str):
    s = json.loads(_SCHEMA.read_text())
    return jsonschema.Draft202012Validator({"$defs": s["$defs"], **s["$defs"][name]})


def _bases(monkeypatch, installed, servable):
    async def org_member(_request):
        return "local", "owner"

    async def servable_models(_org, backend):
        return servable(backend)

    monkeypatch.setattr(gw, "_pub_org_member", org_member)
    monkeypatch.setattr(gw, "_servable_models", servable_models)
    monkeypatch.setattr(gw, "_backend_installed", installed)
    # one bundled skill, so the skill objects are checked too (a bare checkout bundles none)
    monkeypatch.setattr(gw, "_builtin_skills", lambda: {"pdf": {
        "title": "PDF", "description": "Read and write PDF files.", "default_enabled": True,
        "origin": "bundled", "files": []}})
    return asyncio.run(gw.list_bases(None))


def test_the_openapi_document_names_the_route_and_its_objects():
    spec = yaml.safe_load(_OPENAPI.read_text())
    op = spec["paths"]["/v1/bases"]["get"]
    assert op["operationId"] == "listBases"
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/BaseCatalog"}
    for name in ("BaseCatalog", "Base", "BaseModel", "BaseTool", "BaseSkill"):
        assert name in spec["components"]["schemas"], name


def test_the_json_schema_is_built_from_the_openapi_document_and_shipped_with_the_suite():
    sys.path.insert(0, str(_ROOT / "protocol" / "schema"))
    import build  # noqa: E402 - protocol/schema/build.py
    built = json.dumps(build.build(), indent=2, ensure_ascii=False) + "\n"
    assert _SCHEMA.read_text() == built, "run: python protocol/schema/build.py"
    bundled = _ROOT / "protocol" / "conformance" / "uhp_conformance" / _SCHEMA.name
    assert bundled.read_bytes() == _SCHEMA.read_bytes()


def test_every_base_validates_when_installed_and_its_models_are_served(monkeypatch):
    every = {m for c in gw._MODEL_CATALOG.values() for m in [x["id"] if isinstance(x, dict) else x
                                                              for x in c.get("models", [])]}
    doc = _bases(monkeypatch, lambda _b: True, lambda _b: set(every))
    errors = sorted(_validator("BaseCatalog").iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:10])
    assert len(doc["bases"]) == len(gw._BASE_CATALOG)
    assert all(b["status"] == "ready" and "statusReason" not in b for b in doc["bases"])
    assert any(m["available"] and m["reasoning"] for b in doc["bases"] for m in b["models"])
    assert any(b["builtinSkills"] for b in doc["bases"])


def test_every_base_validates_when_not_installed_and_nothing_is_served(monkeypatch):
    doc = _bases(monkeypatch, lambda _b: False, lambda _b: set())
    errors = sorted(_validator("BaseCatalog").iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:10])
    assert all(b["status"] == "not_installed" and b["statusReason"] for b in doc["bases"])


def test_a_field_the_schema_does_not_know_still_validates_but_a_wrong_type_does_not(monkeypatch):
    """Additive within a version (VERSIONING): a new field on a base passes; a changed type fails."""
    doc = _bases(monkeypatch, lambda _b: True, lambda _b: set())
    base = dict(doc["bases"][0])
    v = _validator("Base")
    assert not list(v.iter_errors({**base, "takesSomethingNew": True}))
    assert list(v.iter_errors({**base, "tools": [{"name": "x", "enforcement": "soft"}]}))
    assert list(v.iter_errors({**base, "models": [{"id": "m", "available": "yes"}]}))
