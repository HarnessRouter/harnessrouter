"""What a check is handed: a client, a schema validator, and state shared between checks."""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

from .client import Client

SCHEMA_PATH = (pathlib.Path(__file__).resolve().parents[2]
               / "schema" / "uhp-2026-08-11.schema.json")


@dataclass
class Context:
    client: Client
    harness_id: str = ""
    model: str = ""
    task_timeout: float = 300.0
    state: dict = field(default_factory=dict)
    _schema: dict | None = None

    def validate(self, instance, definition: str) -> None:
        """Validate `instance` against a `$defs` entry, or skip loudly if that is impossible.

        A missing validator must never look like a pass, so this raises Skip rather than returning
        quietly — an unrunnable check is reported as unrun.
        """
        from .registry import Skip
        if jsonschema is None:
            raise Skip("jsonschema is not installed, so schema validation cannot run")
        if self._schema is None:
            if not SCHEMA_PATH.exists():
                raise Skip(f"schema not found at {SCHEMA_PATH}")
            self._schema = json.loads(SCHEMA_PATH.read_text())
        doc = {**self._schema, "$ref": f"#/$defs/{definition}"}
        errors = sorted(jsonschema.Draft202012Validator(doc).iter_errors(instance),
                        key=lambda e: list(e.path))
        if errors:
            e = errors[0]
            where = "/".join(str(p) for p in e.path) or "(root)"
            raise AssertionError(
                f"does not match schema {definition}: at {where}: {e.message[:200]}"
                + (f" (+{len(errors)-1} more)" if len(errors) > 1 else ""))
