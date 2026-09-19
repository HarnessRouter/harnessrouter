"""What a check is handed: a client, a schema validator, and state shared between checks."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

from . import UHP_VERSION
from .client import Client

SCHEMA_RESOURCE = resources.files("uhp_conformance").joinpath(f"uhp-{UHP_VERSION}.schema.json")


@dataclass
class Context:
    client: Client
    harness_id: str = ""
    model: str = ""
    task_timeout: float = 300.0
    state: dict = field(default_factory=dict)
    _schema: dict | None = None

    def validate(self, instance, definition: str) -> None:
        """Validate `instance` against a `$defs` entry, or fail the check if that is impossible.

        A missing validator must never look like a pass, and it must not look like "not applicable"
        either: the schema ships inside this package and jsonschema is a declared dependency, so
        their absence is a broken installation of the suite, and the check reports ERROR (the
        suite could not run) rather than SKIP (the server offered nothing to check). Thirty
        checks once skipped this way on a pip install that lacked the schema (#203), and a report
        with thirty skips read as a partial server rather than a partial suite.
        """
        if jsonschema is None:
            raise RuntimeError("jsonschema is not installed; the suite needs it to validate "
                               "responses (pip install jsonschema)")
        if self._schema is None:
            if not SCHEMA_RESOURCE.is_file():
                raise RuntimeError(f"the UHP {UHP_VERSION} schema is missing from this installation "
                                   f"of uhp-conformance (expected {SCHEMA_RESOURCE}); reinstall the "
                                   "package")
            self._schema = json.loads(SCHEMA_RESOURCE.read_text(encoding="utf-8"))
        doc = {**self._schema, "$ref": f"#/$defs/{definition}"}
        errors = sorted(jsonschema.Draft202012Validator(doc).iter_errors(instance),
                        key=lambda e: list(e.path))
        if errors:
            e = errors[0]
            where = "/".join(str(p) for p in e.path) or "(root)"
            raise AssertionError(
                f"does not match schema {definition}: at {where}: {e.message[:200]}"
                + (f" (+{len(errors)-1} more)" if len(errors) > 1 else ""))
