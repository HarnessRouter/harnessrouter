"""Render the support matrix JSON as markdown: one table per provider, a row per harness x model."""
import json, sys, collections
res = json.load(open(sys.argv[1]))
mark = lambda r: 'n/a' if not r or r.get('ok') is None else ('pass' if r.get('ok') else 'FAIL')
by = collections.defaultdict(list)
for k, r in res.items(): by[r['provider']].append(r)
out = ["# Harness support matrix", "", "The run's notes, per column, are in [support-matrix-notes.md](support-matrix-notes.md).", "", "Scenarios: first turn, follow-up in the same session, switch model mid-session, artifact (a file the task must produce), recycle (the sandbox is let go on purpose, then a follow-up must recall the first message). pass = ran and answered as asked, FAIL = failed (reason in the notes), n/a = not run.", ""]
for prov, rows in sorted(by.items()):
    out += [f"## Provider: {prov}", "", "| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |", "|---|---|---|---|---|---|---|---|---|"]
    findings = []
    for r in sorted(rows, key=lambda r: (r['harness'], r['model'])):
        notes = []
        for sc in ('first', 'followup', 'switch', 'artifact', 'recycle'):
            x = r.get(sc) or {}
            if x.get('ok') is False and x.get('why'): notes.append(f"{sc}: {x['why'][:140]}")
        if r.get('error'): notes.append(f"runner: {r['error'][:100]}")
        if r.get('note'): notes.append(str(r['note'])[:120])
        ft = r.get('first_try') or {}
        if ft: notes.append('retested once; first try: ' + '; '.join(f"{sc} {(ft.get(sc) or {}).get('why', '')[:80]}" for sc in ('first', 'followup', 'switch', 'artifact', 'recycle') if (ft.get(sc) or {}).get('ok') is False))
        sw = r.get('switch') or {}
        served = ', '.join(c.replace('integration:', '') for c in (r.get('connections') or ([r['connection']] if r.get('connection') else []))) or '?'
        if r.get('foreign'):
            # a turn served by a connection other than the one under test is a finding, never a pass
            findings.append(f"{r['harness']} x {r['model']}: served by {', '.join(r['foreign'])} (turn records: {', '.join(r.get('connections') or [])})")
            notes.insert(0, "served by another connection (finding below)")
        if r.get('substituted'):
            # the CLI ran a model other than the id asked for: the id is not served as itself, a finding
            findings.append(f"{r['harness']} x {r['model']}: served as {', '.join(r['substituted'])} (the CLI reports the model it ran)")
            notes.insert(0, f"served as {', '.join(r['substituted'])} (finding below)")
        out.append(f"| {r['harness']} | {r['model']} | {mark(r.get('first'))} | {mark(r.get('followup'))} | {mark(sw)}{(' ('+sw['to']+')') if sw.get('to') else ''} | {mark(r.get('artifact'))} | {mark(r.get('recycle'))} | {served} | {' ; '.join(notes).replace('|', '/')} |")
    clean = [r for r in rows if not r.get('foreign') and not r.get('substituted')]
    ok = sum(1 for r in clean for sc in ('first','followup','switch','artifact','recycle') if (r.get(sc) or {}).get('ok') is True)
    tot = sum(1 for r in clean for sc in ('first','followup','switch','artifact','recycle') if (r.get(sc) or {}).get('ok') is not None)
    out += ["", f"{len(rows)} pairs, {ok} of {tot} scenario runs passed" + (f"; {len(rows) - len(clean)} pairs served by another connection or as another model are findings, not counted." if len(clean) < len(rows) else "."), ""]
    if findings:
        out += ["Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:", ""] + [f"- {f}" for f in findings] + [""]
print("\n".join(out))
