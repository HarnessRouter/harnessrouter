"""Rendering a run. Human-readable to a terminal, machine-readable to JSON."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import __version__
from .registry import CLASSES, Outcome

GREEN, RED, YELLOW, GREY, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[1m", "\033[0m")
MARK = {Outcome.PASS: f"{GREEN}PASS{RESET}", Outcome.FAIL: f"{RED}FAIL{RESET}",
        Outcome.SKIP: f"{YELLOW}SKIP{RESET}", Outcome.ERROR: f"{RED}ERR {RESET}"}


def render(results, target: str, cls: str, plain: bool = False) -> str:
    def c(s, colour):
        return s if plain else f"{colour}{s}{RESET}"

    mark = ({o: {Outcome.PASS: "PASS", Outcome.FAIL: "FAIL", Outcome.SKIP: "SKIP",
                 Outcome.ERROR: "ERR "}[o] for o in Outcome} if plain else MARK)

    lines = [""]
    lines.append(c(f"UHP conformance — {target}", BOLD))
    lines.append(f"protocol 2026-08-11 · requested class: {cls}")
    lines.append("")

    for k in CLASSES[: CLASSES.index(cls) + 1]:
        group = [r for r in results if r.cls == k]
        if not group:
            continue
        lines.append(c(f"  {k.upper()}", BOLD))
        for r in group:
            line = f"    {mark[r.outcome]}  {r.id:<5} {r.title}"
            if r.detail and r.outcome is Outcome.PASS:
                line += c(f"  — {r.detail}", GREY)
            lines.append(line)
            if r.outcome in (Outcome.FAIL, Outcome.ERROR):
                for chunk in _wrap(r.detail, 92):
                    lines.append(c(f"           {chunk}", RED))
                lines.append(c(f"           spec: {r.spec}", GREY))
            elif r.outcome is Outcome.SKIP:
                lines.append(c(f"           {r.detail}", YELLOW))
        lines.append("")

    n = {o: sum(1 for r in results if r.outcome is o) for o in Outcome}
    total = len(results)
    lines.append(c("  Summary", BOLD))
    lines.append(f"    {n[Outcome.PASS]}/{total} passed · {n[Outcome.FAIL]} failed · "
                 f"{n[Outcome.SKIP]} skipped · {n[Outcome.ERROR]} errored")

    achieved = highest_class(results)
    if n[Outcome.FAIL] or n[Outcome.ERROR]:
        lines.append(c(f"    NOT CONFORMANT at class '{cls}'", RED))
        if achieved:
            lines.append(f"    Highest class fully passed: {achieved}")
    elif n[Outcome.SKIP]:
        # Same vocabulary as the JSON report: skips demote the verdict, they never vanish into it.
        lines.append(c(f"    CONFORMANT WITH SKIPS — UHP 2026-08-11 ({cls})", YELLOW))
        lines.append(c("    Note: skipped checks were not verified. A skip is not a pass.", YELLOW))
    else:
        lines.append(c(f"    CONFORMANT — UHP 2026-08-11 ({cls})", GREEN))
    lines.append("")
    return "\n".join(lines)


def highest_class(results) -> str:
    """The highest class every check of which — and of the classes below it — ran and passed.

    "Fully passed" means exactly that: a fail or error anywhere at or below the class breaks
    the ladder, and so does a skip, because a skipped check was not verified. A class with no
    results at all breaks it too — before this rule, a run that only exercised `core` reported
    `highest_class_passed: "full"`, crediting classes that never ran (issue #7's green-summary
    shape, in class form)."""
    best = ""
    for k in CLASSES:
        upto = CLASSES[: CLASSES.index(k) + 1]
        group = [r for r in results if r.cls in upto]
        if any(r.outcome is not Outcome.PASS for r in group):
            break
        if not any(r.cls == k for r in results):
            break
        best = k
    return best


def _wrap(text: str, width: int):
    words, line = (text or "").split(), ""
    out = []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out or [""]


def to_json(results, target: str, cls: str) -> str:
    n = {o.value: sum(1 for r in results if r.outcome is o) for o in Outcome}
    return json.dumps({
        "protocol": "uhp",
        "protocol_version": "2026-08-11",
        # The suite revision and the moment of the run, because this file is published as
        # EVIDENCE (GOVERNANCE.md § Conformance claims) and evidence that cannot be dated or
        # tied to the suite that produced it has to be dated in prose somewhere else — which is
        # exactly what happened to the 0.3.0 report. A report without these fields predates
        # suite 2026.8.11.post1.
        "suite_version": __version__,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": target,
        "requested_class": cls,
        # A skip is never a pass (README), and the consumer of this file is frequently not the
        # person who ran the suite — so the verdict field itself goes strict: a run in which
        # checks never executed is not "conformant", however green the rest of it is.
        # `conformant_with_skips` keeps the old meaning under an honest name, and
        # `skipped_not_verified` names the checks a reader must not assume anything about.
        "conformant": n["fail"] == 0 and n["error"] == 0 and n["skip"] == 0,
        "conformant_with_skips": n["fail"] == 0 and n["error"] == 0,
        "skipped_not_verified": [r.id for r in results if r.outcome is Outcome.SKIP],
        "highest_class_passed": highest_class(results),
        "summary": {**n, "total": len(results)},
        "checks": [{"id": r.id, "title": r.title, "class": r.cls, "spec": r.spec,
                    "outcome": r.outcome.value, "detail": r.detail, **r.evidence}
                   for r in results],
    }, indent=2)
