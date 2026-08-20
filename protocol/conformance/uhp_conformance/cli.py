"""`uhp-conformance` — run the suite against a server."""
from __future__ import annotations

import argparse
import os
import sys

from . import UHP_VERSION, checks  # noqa: F401 — importing checks populates the registry
from .client import Client
from .context import Context
from .registry import CLASSES, Outcome, checks_for
from .report import render, to_json


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="uhp-conformance",
        description=f"Run the Unified Harness Protocol {UHP_VERSION} conformance suite "
                    f"against a server.")
    p.add_argument("--base-url", required=True,
                   help="Server root, e.g. https://host or http://127.0.0.1:3000/api/harness")
    p.add_argument("--api-key", default=os.environ.get("UHP_API_KEY", ""),
                   help="Bearer token (or set UHP_API_KEY)")
    p.add_argument("--class", dest="cls", default="core", choices=CLASSES,
                   help="Conformance class to test (cumulative). Default: core")
    p.add_argument("--harness-id", default="", help="Run tasks against this harness id")
    p.add_argument("--model", default="", help="Run tasks with this model")
    p.add_argument("--task-timeout", type=float, default=300.0,
                   help="Seconds to allow one agent task. Default: 300")
    p.add_argument("--json", dest="json_out", default="", help="Write a JSON report to this path")
    p.add_argument("--only", default="", help="Comma-separated check ids to run")
    p.add_argument("--plain", action="store_true", help="No ANSI colour")
    a = p.parse_args(argv)

    ctx = Context(client=Client(a.base_url, a.api_key), harness_id=a.harness_id,
                  model=a.model, task_timeout=a.task_timeout)

    selected = checks_for(a.cls)
    if a.only:
        want = {s.strip().upper() for s in a.only.split(",") if s.strip()}
        selected = [c for c in selected if c.id.upper() in want]
        if not selected:
            print(f"no checks matched --only {a.only!r}", file=sys.stderr)
            return 2

    results = []
    for c in selected:
        results.append(c.run(ctx))
        if not a.plain:
            print(".", end="", flush=True)
    if not a.plain:
        print("\r", end="")

    print(render(results, a.base_url, a.cls, plain=a.plain))

    if a.json_out:
        with open(a.json_out, "w") as f:
            f.write(to_json(results, a.base_url, a.cls) + "\n")
        print(f"  JSON report: {a.json_out}\n")

    bad = sum(1 for r in results if r.outcome in (Outcome.FAIL, Outcome.ERROR))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
