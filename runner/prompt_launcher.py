"""Run a Python CLI with its prompt taken from a file instead of from the command line.

    <the CLI's python> prompt_launcher.py <prompt file> <module:function> <prog> [args...]

Every argument equal to PROMPT_ARG is replaced by the file's text; sys.argv is then set, in this process,
to [prog, *args], and the CLI's own entry point is called. The command line this process was started with
names the file and never its text. The runner writes the file 0600 as the session (server.py,
_prompt_handover); this process runs as the session too, and removes the file as soon as it has read it.

This file ships with the runner, root-owned and read-only, never in a session's tree. Its own folder is taken
off sys.path before anything is imported: the CLI's imports come from the CLI's own environment, not from the
runner's modules beside this file.
"""
import sys

sys.path.pop(0)

import importlib  # noqa: E402
import os  # noqa: E402

PROMPT_ARG = "{hr:prompt}"


def main() -> None:
    if len(sys.argv) < 4:
        sys.stderr.write("usage: prompt_launcher.py <prompt file> <module:function> <prog> [args...]\n")
        sys.exit(2)
    path, target, prog, *args = sys.argv[1:]
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        os.unlink(path)
    except OSError:
        pass                  # the runner removes it when the turn ends in any case
    sys.argv = [prog] + [text if a == PROMPT_ARG else a for a in args]
    module, _, attr = target.partition(":")
    entry = importlib.import_module(module)
    for part in attr.split("."):
        entry = getattr(entry, part)
    sys.exit(entry())


if __name__ == "__main__":
    main()
