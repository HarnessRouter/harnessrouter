#!/usr/bin/env python3
"""Offline Muse JSONL probe, not a HarnessRouter backend or conformance test."""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

PROMPT = "HarnessRouter probe: hello"


def summarize(stdout: str, expected_text: str) -> dict:
    """Require exactly one parent run and its matching successful terminal."""
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    if not all(isinstance(event, dict) for event in events):
        raise ValueError("JSONL contains a non-object event")
    starts = [e for e in events if e.get("payload_type") == "run.lifecycle.started"]
    if len(starts) != 1:
        raise ValueError("Expected exactly one parent run start")
    start = starts[0]
    payload = start.get("payload", {})
    command = payload.get("command_id")
    run = payload.get("run_stream", {})
    if not command or run.get("kind") != "run" or not run.get("id"):
        raise ValueError("Parent run identity is missing")
    terminals = [e for e in events
                 if str(e.get("payload_type", "")).startswith("run.terminal.")
                 and e.get("payload", {}).get("command_id") == command
                 and e.get("payload", {}).get("run_stream") == run]
    if len(terminals) != 1:
        raise ValueError("Expected exactly one matching parent terminal")
    terminal = terminals[0]
    if (terminal.get("payload_type") != "run.terminal.completed"
            or terminal["payload"].get("terminal") != "completed"):
        raise ValueError("Parent run did not complete successfully")
    if terminal["payload"].get("text") != expected_text:
        raise ValueError("Parent result did not match the echo prompt")
    return {"probe": "muse-offline-echo", "passed": True,
            "records": len(events), "terminal": "completed",
            "real_model_tested": False, "backend_registered": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="muse", help="Previously verified Muse executable")
    args = parser.parse_args()
    binary = shutil.which(args.binary)
    if binary is None:
        parser.error("Muse executable not found; install and verify it separately")
    binary = str(pathlib.Path(binary).resolve())
    try:
        with tempfile.TemporaryDirectory(prefix="hr-muse-probe-") as workspace:
            result = subprocess.run(
                [binary, "exec", "--provider", "echo", "--json", "--no-session-log",
                 "--no-foreign-personal-context", "--workspace", workspace, PROMPT],
                cwd=workspace, capture_output=True, text=True, timeout=30, check=False,
            )
        if result.returncode != 0:
            raise ValueError(f"Muse exited with code {result.returncode}")
        report = summarize(result.stdout, "echo: " + PROMPT)
        report["stderr_present"] = bool(result.stderr.strip())
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
        # Do not dump raw stdout/stderr: startup diagnostics can contain local context.
        print(f"Muse probe failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
