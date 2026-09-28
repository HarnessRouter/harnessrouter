"""Rendering a run. Human-readable to a terminal, machine-readable to JSON."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from . import UHP_VERSION, __version__
from . import checks as _checks  # noqa: F401 — populate the complete check registry
from .registry import CLASSES, Outcome, checks_for

GREEN, RED, YELLOW, GREY, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[1m", "\033[0m")
MARK = {Outcome.PASS: f"{GREEN}PASS{RESET}", Outcome.FAIL: f"{RED}FAIL{RESET}",
        Outcome.SKIP: f"{YELLOW}SKIP{RESET}", Outcome.ERROR: f"{RED}ERR {RESET}"}


def served_version(discovery: dict | None) -> str:
    """The version the server says it serves by default. The suite measures the contract of
    UHP_VERSION; the claim a run supports names the version the server actually answered
    with, because a 2026-08-11 server that passes every applicable check is 2026-08-11
    conformant, not 2026-09-12 conformant, and the label must not promote it."""
    d = discovery or {}
    return str(d.get("default_version") or (d.get("versions") or [""])[0] or "unknown")


def _coverage(results, required_checks):
    """Compare the results with the registry, including duplicate or unexpected results."""
    expected = Counter((c.cls, c.id) for c in required_checks)
    observed = Counter((r.cls, r.id) for r in results)
    missing = list((expected - observed).elements())
    extra = list((observed - expected).elements())
    return not missing and not extra, missing, extra


def render(results, target: str, cls: str, plain: bool = False, discovery: dict | None = None,
           required_checks=None) -> str:
    if required_checks is None:
        required_checks = checks_for(cls)
    def c(s, colour):
        return s if plain else f"{colour}{s}{RESET}"

    mark = ({o: {Outcome.PASS: "PASS", Outcome.FAIL: "FAIL", Outcome.SKIP: "SKIP",
                 Outcome.ERROR: "ERR "}[o] for o in Outcome} if plain else MARK)

    lines = [""]
    lines.append(c(f"UHP conformance — {target}", BOLD))
    served = served_version(discovery)
    lines.append(f"suite {UHP_VERSION} · server serves {served} · requested class: {cls}")
    if served != UHP_VERSION and served in ("2026-08-11",):
        lines.append(f"    ({served} is the previous version; {UHP_VERSION} is additive to it, so every "
                     f"check applies and the plugin series skips)")
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

    complete, missing, extra = _coverage(results, required_checks)
    achieved = highest_class(results, required_checks)
    if n[Outcome.FAIL] or n[Outcome.ERROR]:
        lines.append(c(f"    NOT CONFORMANT at class '{cls}'", RED))
        if achieved:
            lines.append(f"    Highest class fully passed: {achieved}")
    elif not complete:
        lines.append(c(f"    PARTIAL RUN — class '{cls}' not verified", YELLOW))
        if achieved:
            lines.append(f"    Highest class fully passed: {achieved}")
    elif n[Outcome.SKIP]:
        # Same vocabulary as the JSON report: skips demote the verdict, they never vanish into it.
        lines.append(c(f"    CONFORMANT WITH SKIPS — UHP {served} ({cls})", YELLOW))
        lines.append(c("    Note: skipped checks were not verified. A skip is not a pass.", YELLOW))
    else:
        lines.append(c(f"    CONFORMANT — UHP {served} ({cls})", GREEN))
    if not complete:
        lines.append(f"    Required coverage: {len(required_checks) - len(missing)}/"
                     f"{len(required_checks)} checks")
        if missing:
            lines.append(f"    Not run ({len(missing)}):")
            lines.extend(f"      {chunk}" for chunk in
                         _wrap(", ".join(check_id for _, check_id in missing), 88))
        if extra:
            lines.append(f"    Duplicate or unknown results ({len(extra)}):")
            lines.extend(f"      {chunk}" for chunk in
                         _wrap(", ".join(check_id for _, check_id in extra), 88))
    lines.append("")
    return "\n".join(lines)


def highest_class(results, required_checks=None) -> str:
    """The highest class every check of which — and of the classes below it — ran and passed.

    "Fully passed" means exactly that: a fail or error anywhere at or below the class breaks
    the ladder, and so does a skip, because a skipped check was not verified. A class with no
    results at all breaks it too — before this rule, a run that only exercised `core` reported
    `highest_class_passed: "full"`, crediting classes that never ran (issue #7's green-summary
    shape, in class form)."""
    if required_checks is None:
        required_checks = checks_for("full")
    best = ""
    for k in CLASSES:
        upto = CLASSES[: CLASSES.index(k) + 1]
        required = [c for c in required_checks if c.cls in upto]
        group = [r for r in results if r.cls in upto]
        if not any(c.cls == k for c in required_checks):
            break
        if not _coverage(group, required)[0]:
            break
        if any(r.outcome is not Outcome.PASS for r in group):
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


def to_json(results, target: str, cls: str, discovery: dict | None = None, label: str = "",
            required_checks=None) -> str:
    if required_checks is None:
        required_checks = checks_for(cls)
    complete, missing, extra = _coverage(results, required_checks)
    n = {o.value: sum(1 for r in results if r.outcome is o) for o in Outcome}
    return json.dumps({
        "protocol": "uhp",
        # The version the server served, which is what the verdict is a claim about; the
        # suite's own version is the contract it measured against.
        "protocol_version": served_version(discovery),
        "suite_protocol_version": UHP_VERSION,
        # The suite revision and the moment of the run, because this file is published as
        # EVIDENCE (GOVERNANCE.md § Conformance claims) and evidence that cannot be dated or
        # tied to the suite that produced it has to be dated in prose somewhere else — which is
        # exactly what happened to the 0.3.0 report. A report without these fields predates
        # suite 2026.9.12.
        "suite_version": __version__,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": target,
        # What was measured, as a name a reader recognises; the site shows this on the measured
        # implementations list. The implementation block is what the server said about itself.
        "target_label": label,
        "implementation": (discovery or {}).get("implementation") or {},
        "requested_class": cls,
        # A skip is never a pass (README), and the consumer of this file is frequently not the
        # person who ran the suite — so the verdict field itself goes strict: a run in which
        # checks never executed is not "conformant", however green the rest of it is.
        # `conformant_with_skips` means every required check ran without failure or error;
        # `skipped_not_verified` names attempted checks that were skipped.
        "conformant": complete and n["fail"] == 0 and n["error"] == 0 and n["skip"] == 0,
        "conformant_with_skips": complete and n["fail"] == 0 and n["error"] == 0,
        "skipped_not_verified": [r.id for r in results if r.outcome is Outcome.SKIP],
        "coverage": {"complete": complete, "required": len(required_checks),
                     "reported": len(results),
                     "not_run": [check_id for _, check_id in missing],
                     "duplicate_or_unknown": [check_id for _, check_id in extra]},
        "highest_class_passed": highest_class(results, required_checks),
        "summary": {**n, "total": len(results)},
        "checks": [{"id": r.id, "title": r.title, "class": r.cls, "spec": r.spec,
                    "outcome": r.outcome.value, "detail": r.detail, **r.evidence}
                   for r in results],
    }, indent=2)
