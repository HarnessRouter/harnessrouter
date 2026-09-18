"""Render benchmark results as markdown: one table per provider x pack, a row per harness x model.

A row's score counts only the runs that were what they claimed to be: a run served by another
connection, served as another model, or that reached the network is a finding listed under the
table and left out of the score, the matrix's rules 1 and 2 plus this suite's rule 3. Tokens are on
one convention — fresh input, cached input and output reported apart — and never summed across
the three, since a cached read is the same prompt read again, not new input.
Usage: python3 render.py results.json [more.json ...] > ../../docs/benchmark.md
"""
import collections
import json
import statistics
import sys


def median(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.median(xs) if xs else None


def fmt_s(x):
    return "-" if x is None else f"{x:.0f} s"


def fmt_k(n):
    return "-" if n is None else (f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.0f}k")


def render(records: list[dict]) -> str:
    by = collections.defaultdict(list)
    for r in records:
        by[(r.get("provider", "?"), r.get("pack", "?"))].append(r)
    out = ["# Harness benchmark", "",
           "How a row is measured, and the rules that decide it, are in "
           "[scripts/benchmark/README.md](../scripts/benchmark/README.md). One task is one session; "
           "the pack's own grader decides; every number is read from the turn record.", ""]
    for (prov, pack), rows in sorted(by.items()):
        out += [f"## Provider: {prov} — pack: {pack}", "",
                "| Harness | Model | Tasks | Resolved | Reward | Median wall | Median tool calls | Fresh in | Cached in | Output | Served by | Notes |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        findings, errors = [], []
        groups = collections.defaultdict(list)
        for r in rows:
            groups[(r.get("harness", "?"), r.get("model", "?"))].append(r)
        for (h, m), rs in sorted(groups.items()):
            ran = [r for r in rs if not r.get("error")]
            errors += [f"{h} x {m} {r.get('task')}: {r['error'][:120]}" for r in rs if r.get("error")]
            clean, notes = [], []
            for r in ran:
                why = []
                if r.get("foreign"):
                    why.append(f"served by {r['foreign']}")
                if r.get("substituted"):
                    why.append(f"served as {r.get('served')}")
                if r.get("network"):
                    why.append("reached the network: " + "; ".join(str(x) for x in r["network"])[:120])
                if why:
                    findings.append(f"{h} x {m} {r.get('task')}: " + ", ".join(why))
                else:
                    clean.append(r)
            unreported = sum(1 for r in ran if r.get("served_unreported"))
            if unreported:
                notes.append(f"served model unreported on {unreported} of {len(ran)} runs (rule 2 unverifiable there)")
            if len(clean) < len(ran):
                notes.append(f"{len(ran) - len(clean)} runs are findings, not counted")
            u = [r.get("usage") or {} for r in clean]
            served = sorted({str(r.get("connection") or "").replace("integration:", "") for r in ran if r.get("connection")}) or ["?"]
            resolved = sum(1 for r in clean if r.get("resolved"))
            reward = statistics.mean(float(r.get("reward") or 0) for r in clean) if clean else None
            out.append(
                f"| {h} | {m} | {len(clean)} | {resolved} ({100 * resolved / len(clean):.0f}%) | "
                f"{'-' if reward is None else f'{reward:.2f}'} | {fmt_s(median(r.get('wall_s') for r in clean))} | "
                f"{'-' if not clean else f'{median(r.get('tool_calls') for r in clean):.0f}'} | "
                f"{fmt_k(sum(x.get('fresh_input', 0) for x in u)) if u else '-'} | "
                f"{fmt_k(sum(x.get('cached_input', 0) for x in u)) if u else '-'} | "
                f"{fmt_k(sum(x.get('output', 0) for x in u)) if u else '-'} | {', '.join(served)} | "
                f"{' ; '.join(notes).replace('|', '/')} |"
                if clean else
                f"| {h} | {m} | 0 | - | - | - | - | - | - | - | {', '.join(served)} | {' ; '.join(notes) or 'no counted runs'} |")
        out.append("")
        if findings:
            out += ["Findings, runs served by another connection, as another model, or that reached the network — listed, not scored:", ""]
            out += [f"- {f}" for f in findings] + [""]
        if errors:
            out += ["Runner errors (the run never produced a record to judge; re-run them):", ""] + [f"- {e}" for e in errors] + [""]
    return "\n".join(out)


if __name__ == "__main__":
    recs: list[dict] = []
    for path in sys.argv[1:]:
        data = json.load(open(path, encoding="utf-8"))
        recs += list(data.values()) if isinstance(data, dict) else list(data)
    print(render(recs))
