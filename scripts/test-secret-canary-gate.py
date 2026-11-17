"""The secret-canary gate's scan of the session folders while the turns run never opens a prompt file the runner
handed a CLI (tmp/.hr-prompt/): opening one can make the runner remove it before the CLI reads it, which blinds
the gate to that harness on that run. The scan after the turns still reads everything."""
import ast
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).with_name("secret-canary-gate.py")
spec = importlib.util.spec_from_file_location("gate", HERE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class Recorder(gate.Table):
    def __init__(self):
        super().__init__()
        self.seen = []

    def scan(self, data, where, *, only=None):
        self.seen.append(where)


class ScanTreeTests(unittest.TestCase):
    def tree(self, root: Path):
        (root / "s1" / "tmp" / ".hr-prompt").mkdir(parents=True)
        (root / "s1" / "tmp" / ".hr-prompt" / "p1").write_text("the prompt")
        (root / "s1" / "notes.txt").write_text("a file of the session's")

    def test_a_prompt_folder_is_never_opened_when_named(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.tree(root)
            t = Recorder()
            n = gate.scan_tree(str(root), t, "session folder", skip_names=(gate.PROMPT_DIR,))
            self.assertEqual(n, 1)
            self.assertEqual(t.seen, ["session folder:s1/notes.txt"])

    def test_without_the_name_everything_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.tree(root)
            t = Recorder()
            self.assertEqual(gate.scan_tree(str(root), t, "session folder"), 2)

    def test_the_scan_while_turns_run_skips_prompt_folders_and_the_one_after_does_not(self):
        src = HERE.read_text()
        main = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "main")
        body = ast.get_source_segment(src, main)
        watch = body[body.index("def watch_folders"):body.index("watchers =")]
        self.assertIn("skip_names=(PROMPT_DIR,)", watch)
        after = body[body.index("# After the turns"):]
        self.assertNotIn("skip_names", after.split("\n")[1])


if __name__ == "__main__":
    unittest.main()
