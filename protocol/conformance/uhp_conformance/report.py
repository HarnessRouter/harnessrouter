"""Rendering a run. Human-readable to a terminal, machine-readable to JSON."""
from __future__ import annotations

import json
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
    else:
        lines.append(c(f"    CONFORMANT — UHP 2026-08-11 ({cls})", GREEN))
        if n[Outcome.SKIP]:
            lines.append(c("    Note: skipped checks were not verified. A skip is not a pass.", YELLOW))
    lines.append("")
    return "\n".join(lines)


def highest_class(results) -> str:
    """The highest class with no failures or errors, counting the classes below it too."""
    best = ""
    for k in CLASSES:
        upto = CLASSES[: CLASSES.index(k) + 1]
        group = [r for r in results if r.cls in upto]
        if not group:
            continue
        if any(r.outcome in (Outcome.FAIL, Outcome.ERROR) for r in group):
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
        "target": target,
        "requested_class": cls,
        "conformant": n["fail"] == 0 and n["error"] == 0,
        "highest_class_passed": highest_class(results),
        "summary": {**n, "total": len(results)},
        "checks": [{"id": r.id, "title": r.title, "class": r.cls, "spec": r.spec,
                    "outcome": r.outcome.value, "detail": r.detail, **r.evidence}
                   for r in results],
    }, indent=2)
