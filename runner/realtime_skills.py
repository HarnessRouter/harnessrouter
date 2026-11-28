"""Skills on a base whose model reads no files: a list in the instructions, and a tool that loads one.

A skill is a folder with a SKILL.md: a name and a description up front, instructions below, and
sometimes reference files and scripts beside it (agentskills.io). An agent with a file tool reads
the folder itself. A realtime model has none, so this is the route the format's own client guide
gives for that case: the names and descriptions go into the session's instructions, and a function
tool returns a skill's instructions when the model asks for them. A second tool returns a
reference file of a skill, where a skill has any.

The runner has already written the turn's skills into the workspace (server.py _write_skills,
`.harness/skills/<name>/`) and hands this base their names, descriptions and entry files. Nothing
here trusts a path from the model: a resource is read only when its path is one this module
listed, and only from inside the skill's own folder.

WHAT IS LEFT OUT, AND SAID. This base has no shell, so a skill that carries scripts cannot do what
its instructions say. It is not offered, and neither is one whose SKILL.md is missing or empty or
one the list has no room for. Each is named with its reason (`left_out`), which the driver emits
as `system/skills_unavailable`: a person is told, the model is not offered half a skill.

No dependency beyond the standard library: the driver imports this in the Realtime Harness's own
environment, and the runner's tests import it in theirs.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re

LOAD, READ = "load_skill", "read_skill_resource"
# One tool answer. The Realtime Harness cuts a tool's output at 16,000 characters; a longer skill
# is handed over in parts, each asked for by number, so nothing is cut in silence.
PART_CHARS = 12000
DESCRIPTION_MAX = 1024          # the format's own ceiling on a description
# The list rides in the instructions of every turn. A realtime session's instructions and tools
# share one ceiling (16,384 tokens on gpt-realtime-2.1, as its API reports when exceeded), which
# the harness's own instructions and its MCP tools also draw on.
CATALOG_CHARS = 6000
RESOURCE_BYTES = 256 * 1024     # a reference file larger than this is listed as too large to read
RESOURCES_LISTED = 40
_FRONTMATTER = re.compile(r"^﻿?---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)", re.S)
_SCRIPT_SUFFIXES = frozenset((".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl",
                              ".php", ".ps1", ".bat", ".cmd", ".exe", ".jar", ".go", ".rs"))

NO_ENTRY = "its SKILL.md could not be read"
NO_BODY = "its SKILL.md holds no instructions"
HAS_SCRIPTS = "it runs scripts, and this base has no shell"
NO_ROOM = "the list of skills this base can carry is full"
NAME_TAKEN = "an MCP server has a tool named {name}"
SWITCHED_OFF = "the load_skill tool is disabled on this harness"

INTRO = ("## Skills\n\n"
         "A skill is a set of instructions for one kind of task. Before you do a task that one of these "
         f"covers, call `{LOAD}` with its name and follow what it returns.\n")


@dataclasses.dataclass(frozen=True)
class Skill:
    name: str
    description: str
    root: pathlib.Path
    body: str
    resources: tuple[str, ...] = ()         # reference files the model may read, relative to the folder
    unreadable: tuple[str, ...] = ()        # files it holds that are not text, or are too large


def _inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _is_script(rel: pathlib.PurePosixPath) -> bool:
    return "scripts" in rel.parts[:-1] or rel.suffix.lower() in _SCRIPT_SUFFIXES


def _read_text(path: pathlib.Path) -> str | None:
    """A file's text, or None when it is not text or is too large to hand to the model."""
    try:
        if path.stat().st_size > RESOURCE_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read(cwd: str | pathlib.Path, metas: list | None) -> tuple[list[Skill], list[dict]]:
    """The skills this base can offer, and [{"name", "reason"}] for each it cannot.

    `metas` is what the runner wrote: [{"name", "desc", "entry"}], `entry` the SKILL.md's path
    relative to the workspace."""
    cwd = pathlib.Path(cwd)
    skills: list[Skill] = []
    left_out: list[dict] = []
    room = CATALOG_CHARS - len(INTRO)
    seen: set[str] = set()
    for m in metas or []:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        entry = cwd / str(m.get("entry") or "")
        root = entry.parent
        text = _read_text(entry) if entry.name.lower() == "skill.md" and _inside(cwd, entry) else None
        if text is None:
            left_out.append({"name": name, "reason": NO_ENTRY})
            continue
        body = _FRONTMATTER.sub("", text, count=1).strip()
        if not body:
            left_out.append({"name": name, "reason": NO_BODY})
            continue
        resources, unreadable, scripted = [], [], False
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = pathlib.PurePosixPath(path.relative_to(root).as_posix())
            if path == entry:
                continue
            if _is_script(rel):
                scripted = True
                break
            if _inside(root, path) and _read_text(path) is not None:
                resources.append(str(rel))
            else:
                unreadable.append(str(rel))
        if scripted:
            left_out.append({"name": name, "reason": HAS_SCRIPTS})
            continue
        description = " ".join(str(m.get("desc") or "").split())[:DESCRIPTION_MAX]
        cost = len(_line(name, description))
        if cost > room:
            left_out.append({"name": name, "reason": NO_ROOM})
            continue
        room -= cost
        skills.append(Skill(name=name, description=description, root=root, body=body,
                            resources=tuple(resources), unreadable=tuple(unreadable)))
    return skills, left_out


def _line(name: str, description: str) -> str:
    return f"- {name}: {description}\n" if description else f"- {name}\n"


def catalog(skills: list[Skill]) -> str:
    """The list that goes into the instructions; "" with no skills, so a harness without any is
    told nothing about them."""
    if not skills:
        return ""
    return INTRO + "\n" + "".join(_line(s.name, s.description) for s in skills)


def with_catalog(instructions: str, skills: list[Skill]) -> str:
    block = catalog(skills)
    if not block:
        return instructions
    return (instructions.rstrip() + "\n\n" + block) if instructions.strip() else block


def _parts(text: str) -> list[str]:
    return [text[i:i + PART_CHARS] for i in range(0, len(text), PART_CHARS)] or [""]


def _part_of(text: str, arguments: dict, what: str) -> dict:
    parts = _parts(text)
    try:
        n = int(arguments.get("part") or 1)
    except (TypeError, ValueError):
        return {"error": "refused", "detail": "part is a number, starting at 1"}
    if not 1 <= n <= len(parts):
        return {"error": "refused", "detail": f"{what} has {len(parts)} part{'' if len(parts) == 1 else 's'}"}
    out = parts[n - 1]
    if len(parts) > 1:
        more = f" Call again with part {n + 1} for the next." if n < len(parts) else " This is the last."
        out = f"[part {n} of {len(parts)}.{more}]\n" + out
    return {"status": "done", "output": out}


class SkillTools:
    """The tool executor a turn runs on, with the skill tools beside the MCP servers' tools.

    Wraps the Realtime Harness's ToolExecutor: `functions()` and `call()` are what a turn uses,
    and everything else (open, close, tools, left_out) is the wrapped executor's own."""

    def __init__(self, inner, skills: list[Skill], disabled: list[str] | None = None):
        self._inner = inner
        self._skills = {s.name: s for s in skills}
        self._disabled = {str(t) for t in disabled or []}
        self.not_offered: list[dict] = []       # skills withdrawn here, with the reason

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    def settle(self) -> None:
        """After the wrapped executor has listed its tools: withdraw the skills when their tool is
        disabled on the harness, or when an MCP server already has a tool of that name (the
        server's tool is the one the harness was configured with, so it keeps the name)."""
        why = ""
        if LOAD in self._disabled:
            why = SWITCHED_OFF
        elif LOAD in getattr(self._inner, "tools", {}):
            why = NAME_TAKEN.format(name=LOAD)
        if why and self._skills:
            self.not_offered = [{"name": n, "reason": why} for n in self._skills]
            self._skills = {}

    @property
    def skills(self) -> list[Skill]:
        return list(self._skills.values())

    def _reads_resources(self) -> bool:
        return (any(s.resources for s in self._skills.values()) and READ not in self._disabled
                and READ not in getattr(self._inner, "tools", {}))

    def own_functions(self) -> list[dict]:
        if not self._skills:
            return []
        names = sorted(self._skills)
        out = [{"type": "function", "name": LOAD,
                "description": "Load a skill's instructions. Call it before a task the skill covers.",
                "parameters": {"type": "object", "additionalProperties": False, "required": ["name"],
                               "properties": {"name": {"type": "string", "enum": names},
                                              "part": {"type": "integer", "minimum": 1,
                                                       "description": "For a skill that says it has more than one part."}}}}]
        if self._reads_resources():
            out.append({"type": "function", "name": READ,
                        "description": "Read a reference file of a skill, by the path the skill's instructions list.",
                        "parameters": {"type": "object", "additionalProperties": False, "required": ["name", "path"],
                                       "properties": {"name": {"type": "string",
                                                               "enum": sorted(n for n, s in self._skills.items() if s.resources)},
                                                      "path": {"type": "string"},
                                                      "part": {"type": "integer", "minimum": 1}}}})
        return out

    def functions(self) -> list[dict]:
        return self._inner.functions() + self.own_functions()

    def owns(self, name: str) -> bool:
        return bool(self._skills) and (name == LOAD or (name == READ and self._reads_resources()))

    async def call(self, name: str, arguments: str | dict) -> dict:
        if not self.owns(name):
            return await self._inner.call(name, arguments)
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except ValueError:
                return {"error": "refused", "detail": "the arguments are not JSON"}
        if not isinstance(arguments, dict):
            return {"error": "refused", "detail": "the arguments are not a JSON object"}
        skill = self._skills.get(str(arguments.get("name") or ""))
        if skill is None:
            return {"error": "refused", "detail": "no skill of that name; the skills are " + ", ".join(sorted(self._skills))}
        return self._load(skill, arguments) if name == LOAD else self._read(skill, arguments)

    @staticmethod
    def _load(skill: Skill, arguments: dict) -> dict:
        text = f'<skill_content name="{skill.name}">\n{skill.body}\n</skill_content>'
        if skill.resources:
            listed = skill.resources[:RESOURCES_LISTED]
            text += (f"\n\nReference files of this skill, read with `{READ}`:\n"
                     + "".join(f"- {r}\n" for r in listed))
            if len(skill.resources) > len(listed):
                text += f"- and {len(skill.resources) - len(listed)} more\n"
        if skill.unreadable:
            text += ("\n\nFiles of this skill that cannot be read here (not text, or too large): "
                     + ", ".join(skill.unreadable[:RESOURCES_LISTED]) + "\n")
        return _part_of(text, arguments, "this skill")

    @staticmethod
    def _read(skill: Skill, arguments: dict) -> dict:
        rel = str(arguments.get("path") or "").strip().replace("\\", "/").removeprefix("./")
        if rel not in skill.resources:
            return {"error": "refused", "detail": (f"the skill {skill.name} has no file at that path; its files are "
                                                   + (", ".join(skill.resources[:RESOURCES_LISTED]) or "none"))}
        path = skill.root / rel
        text = _read_text(path) if _inside(skill.root, path) else None
        if text is None:
            return {"error": "tool_error", "detail": "the file can no longer be read"}
        return _part_of(text, arguments, "this file")
