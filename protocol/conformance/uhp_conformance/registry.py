"""The check registry and result model.

A check has four possible outcomes and each one means something different:

  PASS  — the behaviour the specification requires was observed.
  FAIL  — the behaviour was observed to be wrong. This is a conformance defect.
  SKIP  — the check could not run, and the reason is recorded. A skip is never a pass: a report
          that hides skips behind a green summary is how a suite starts lying.
  ERROR — the check itself broke. A bug in the suite, not necessarily in the server.

Every check states the section of the specification it enforces, so a failure points at the sentence
it violates rather than at a test name.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from enum import Enum

CLASSES = ("core", "extended", "full")


class Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


class Skip(Exception):
    """Raised by a check that cannot run. The message is the reason, shown in the report."""


@dataclass
class CheckResult:
    id: str
    title: str
    cls: str
    spec: str
    outcome: Outcome
    detail: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass
class Check:
    id: str
    title: str
    cls: str
    spec: str
    fn: callable

    def run(self, ctx) -> CheckResult:
        try:
            detail = self.fn(ctx) or ""
            return CheckResult(self.id, self.title, self.cls, self.spec, Outcome.PASS, detail)
        except Skip as e:
            return CheckResult(self.id, self.title, self.cls, self.spec, Outcome.SKIP, str(e))
        except AssertionError as e:
            return CheckResult(self.id, self.title, self.cls, self.spec, Outcome.FAIL, str(e))
        except Exception as e:  # noqa: BLE001
            return CheckResult(self.id, self.title, self.cls, self.spec, Outcome.ERROR,
                               f"{type(e).__name__}: {e}",
                               {"traceback": traceback.format_exc()[-1500:]})


REGISTRY: list[Check] = []


def check(id: str, title: str, cls: str, spec: str):
    """Register a check. `cls` is the lowest conformance class that requires the behaviour."""
    assert cls in CLASSES, f"unknown conformance class {cls!r}"

    def deco(fn):
        REGISTRY.append(Check(id, title, cls, spec, fn))
        return fn
    return deco


def checks_for(cls: str) -> list[Check]:
    """Every check required at `cls`, since the classes are cumulative."""
    upto = CLASSES[: CLASSES.index(cls) + 1]
    return [c for c in REGISTRY if c.cls in upto]
