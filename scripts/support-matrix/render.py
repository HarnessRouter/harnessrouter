"""Render the support matrix JSON as markdown: one table per provider, a row per harness x model."""
import json, sys, collections
res = json.load(open(sys.argv[1]))
mark = lambda r: 'n/a' if not r or r.get('ok') is None else ('pass' if r.get('ok') else 'FAIL')
by = collections.defaultdict(list)
for k, r in res.items(): by[r['provider']].append(r)
out = ["# Harness support matrix", "", "Scenarios: first turn, follow-up in the same session, switch model mid-session, artifact (a file the task must produce). pass = ran and answered as asked, FAIL = failed (reason in the notes), n/a = not run.", ""]
for prov, rows in sorted(by.items()):
    out += [f"## Provider: {prov}", "", "| Harness | Model | First | Follow-up | Switch | Artifact | Notes |", "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r['harness'], r['model'])):
        notes = []
        for sc in ('first', 'followup', 'switch', 'artifact'):
            x = r.get(sc) or {}
            if x.get('ok') is False and x.get('why'): notes.append(f"{sc}: {x['why'][:140]}")
        if r.get('error'): notes.append(f"runner: {r['error'][:100]}")
        sw = r.get('switch') or {}
        out.append(f"| {r['harness']} | {r['model']} | {mark(r.get('first'))} | {mark(r.get('followup'))} | {mark(sw)}{(' ('+sw['to']+')') if sw.get('to') else ''} | {mark(r.get('artifact'))} | {' ; '.join(notes).replace('|', '/')} |")
    ok = sum(1 for r in rows for sc in ('first','followup','switch','artifact') if (r.get(sc) or {}).get('ok') is True)
    tot = sum(1 for r in rows for sc in ('first','followup','switch','artifact') if (r.get(sc) or {}).get('ok') is not None)
    out += ["", f"{len(rows)} pairs, {ok} of {tot} scenario runs passed.", ""]
print("\n".join(out))
