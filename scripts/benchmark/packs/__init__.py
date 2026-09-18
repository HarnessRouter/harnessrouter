"""Task packs: public suites whose grading is deterministic, each in one module.

A pack module exposes three functions and one string:

  NAME               the pack's name in results and tables
  load(root)         -> list of tasks, each a dict with at least "id"; "root" is where the suite's
                        data lives on this machine (never inside the repository)
  stage(task, root)  -> {"prompt": str, "files": [(filename, bytes), ...]}; the turn's first
                        message and the files it starts with. Nothing here may name the suite or
                        the task: an id in a filename is a search key, and a turn that looked its
                        task up is measured on the wrong thing (see README, rule 3)
  grade(task, root, produced, workdir) -> {"reward": float in [0, 1], "resolved": bool,
                        "detail": str}; "produced" maps each file the turn produced to its local
                        path. The suite's own grader decides; a pack never re-implements one.
"""
from importlib import import_module

PACKS = {"spreadsheetbench": "packs.spreadsheetbench"}


def get(name: str):
    if name not in PACKS:
        raise SystemExit(f"unknown pack {name!r}; one of {sorted(PACKS)}")
    return import_module(PACKS[name])
