"""A child task terminal or a successful process exit is not parent-run success."""

import importlib.util
import json
import pathlib
import unittest

path = pathlib.Path(__file__).resolve().parents[1] / "probe-muse.py"
spec = importlib.util.spec_from_file_location("probe_muse", path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def event(kind, command="parent", terminal=None, text=None):
    payload = {"command_id": command, "run_stream": {"kind": "run", "id": command}}
    if terminal is not None:
        payload["terminal"] = terminal
    if text is not None:
        payload["text"] = text
    return {"payload_type": kind, "payload": payload}


def wire(*events):
    return "\n".join(json.dumps(e) for e in events)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.start = event("run.lifecycle.started")
        self.end = event("run.terminal.completed", terminal="completed", text="echo: hello")

    def test_success_ignores_failed_child_task(self):
        child = event("task.lifecycle.failed", terminal="failed")
        self.assertTrue(probe.summarize(wire(self.start, child, self.end), "echo: hello")["passed"])

    def test_child_completion_is_not_parent_completion(self):
        child = event("task.lifecycle.completed", terminal="completed", text="echo: hello")
        with self.assertRaises(ValueError):
            probe.summarize(wire(self.start, child), "echo: hello")

    def test_unrelated_run_cannot_complete_parent(self):
        other = event("run.terminal.completed", command="other", terminal="completed", text="echo: hello")
        with self.assertRaises(ValueError):
            probe.summarize(wire(self.start, other), "echo: hello")

    def test_failure_unknown_duplicate_or_missing_terminal_rejected(self):
        for endings in [[], [self.end, self.end],
                        [event("run.terminal.failed", terminal="failed")],
                        [event("run.terminal.completed", terminal="future-value", text="echo: hello")]]:
            with self.subTest(endings=endings), self.assertRaises(ValueError):
                probe.summarize(wire(self.start, *endings), "echo: hello")

    def test_wrong_answer_rejected(self):
        with self.assertRaises(ValueError):
            probe.summarize(wire(self.start, self.end), "different")

    def test_malformed_json_and_non_object_rejected(self):
        for raw in ["not JSON", "[]", "null"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                probe.summarize(raw, "echo: hello")


if __name__ == "__main__":
    unittest.main()
