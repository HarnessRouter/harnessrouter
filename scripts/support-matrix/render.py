"""Render the support matrix JSON as markdown: one table per provider, a row per harness x model."""
import json
import pathlib, sys, collections, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from samemodel import alias_of  # noqa: E402
# The gateway's own tables say what each provider serves and what each harness offers, so a pair a
# provider serves but a harness cannot run is listed as NOT RUN with its reason, per provider, the
# same way for every harness, rather than being absent from the table.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gateway"))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402
LABEL_VENDOR = {"tokenrouter": "tokenrouter", "vercel": "vercel", "openrouter": "openrouter", "openai": "openai",
                "azure-e2": "azure-foundry", "azure-openai": "azure-foundry", "anthropic": "anthropic",
                "google": "google", "harnessrouter": "tokenrouter"}   # the hosted door serves TokenRouter's table
HARNESS_BACKEND = {"claude-code": "claude", "gemini-cli": "gemini"}
def vendor_of(label):
    for pre in ("gemini-cli-", "gemini-", "dsh-", "omp-", "codex-", "goose-", "cline-", "qwen-", "pi-", "hermes-", "opencode-", "claude-code-", "claude-"):
        if label.startswith(pre) and label[len(pre):] in LABEL_VENDOR: return LABEL_VENDOR[label[len(pre):]]
    return LABEL_VENDOR.get(label)
def not_run(label, rows):
    vendor = vendor_of(label)
    if not vendor: return []
    served = set(gw._VENDOR_MODELS.get(vendor) or {})
    out = []
    for h in sorted({r["harness"] for r in rows}):
        backend = HARNESS_BACKEND.get(h, h)
        offered = set((gw._MODEL_CATALOG.get(backend) or {}).get("models") or [])
        ran = {r["model"] for r in rows if r["harness"] == h}
        for m in sorted(served - ran):
            if m in gw.RESPONSES_ONLY_MODELS and backend in gw.CHAT_ONLY_BACKENDS:
                why = "the model answers on the Responses API only and this harness speaks chat/completions only"
            elif (vendor, backend) not in gw._INTEGRATION_WIRING:
                why = "this harness is not wired to this provider (the gateway's integration wiring)"
            elif m not in offered:
                why = "not in this harness's catalog (unmeasured or excluded, see the catalog's note)"
            else:
                why = "not run in this column"
            out.append(f"- {h} x {m}: not run, {why}")
    return out
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
        # The runner records a served id other than the id asked for, exactly. An aggregator's
        # vendor prefix or a provider's version suffix is the same model (the gateway's rule, in
        # samemodel.py): noted and counted. Another family, number or tier is a finding, not counted.
        aliases = [x for x in (r.get('substituted') or []) if alias_of(r['model'], x)]
        others = [x for x in (r.get('substituted') or []) if not alias_of(r['model'], x)]
        if aliases:
            notes.insert(0, f"served as {', '.join(aliases)} (the provider's alias of the same model)")
        if others:
            findings.append(f"{r['harness']} x {r['model']}: served as {', '.join(others)} (the CLI reports the model it ran)")
            notes.insert(0, f"served as {', '.join(others)} (finding below)")
        # A turn that names no served model is a turn rule 2 could not judge: a finding, not a pass.
        if r.get('wrong_model'):
            findings.append(f"{r['harness']} x {r['model']}: no turn asked for this model (the turns ran {', '.join(r['wrong_model'])}), so the row measured something else")
            notes.insert(0, "no turn ran this model (finding below)")
        if r.get('unlabelled'):
            findings.append(f"{r['harness']} x {r['model']}: {r['unlabelled']} turn(s) report no served model, so rule 2 could not judge them")
            notes.insert(0, f"{r['unlabelled']} turn(s) unlabelled (finding below)")
        # A Claude pair that read no prompt cache across its turns paid full price for every token
        # of its system prompt and tools on every call: a finding, whatever the scenarios say.
        tk = r.get('tokens') or {}
        if r['model'].startswith('claude') and tk.get('turns_with_usage') and (r.get('artifact') or {}).get('ok') and not tk.get('cache_read'):
            findings.append(f"{r['harness']} x {r['model']}: no prompt cache reads over {tk.get('input', 0)} input tokens (every call paid full price)")
            notes.insert(0, "no prompt cache reads (finding below)")
        elif tk.get('turns_with_usage') and tk.get('input'):
            share = tk.get('cache_read', 0) / max(tk.get('input', 0) + tk.get('cache_read', 0), 1)
            notes.append(f"cache {round(share * 100)}% of input")
        out.append(f"| {r['harness']} | {r['model']} | {mark(r.get('first'))} | {mark(r.get('followup'))} | {mark(sw)}{(' ('+sw['to']+')') if sw.get('to') else ''} | {mark(r.get('artifact'))} | {mark(r.get('recycle'))} | {served} | {' ; '.join(notes).replace('|', '/')} |")
    clean = [r for r in rows if not r.get('foreign') and not r.get('unlabelled') and not r.get('wrong_model')
             and all(alias_of(r['model'], x) for x in (r.get('substituted') or []))]
    ok = sum(1 for r in clean for sc in ('first','followup','switch','artifact','recycle') if (r.get(sc) or {}).get('ok') is True)
    tot = sum(1 for r in clean for sc in ('first','followup','switch','artifact','recycle') if (r.get(sc) or {}).get('ok') is not None)
    out += ["", f"{len(rows)} pairs, {ok} of {tot} scenario runs passed" + (f"; {len(rows) - len(clean)} pairs served by another connection or as another model are findings, not counted." if len(clean) < len(rows) else "."), ""]
    if findings:
        out += ["Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:", ""] + [f"- {f}" for f in findings] + [""]
    nr = not_run(prov, rows)
    if nr:
        out += [f"Not run in this column, {len(nr)} pairs the provider serves that the harness did not run, with the reason:", ""] + nr + [""]
# The browser column: every base but System One driving the browser plugin, rendered from the
# checked-in docs/browser-column.json that plugs/browser.py writes (see its docstring).
bc = pathlib.Path(__file__).resolve().parent.parent.parent / "docs" / "browser-column.json"
if bc.is_file():
    doc = json.load(open(bc))
    out += ["## Browser plugin, every base", "",
            f"Measured {doc.get('measured', '')} on {doc.get('instance', '')}. One task in plain words, "
            f"\"{doc.get('prompt', '')}\" A base passes when the task completed, the trace shows the browser "
            "navigating and clicking, the answer names the page the link leads to, and the browser session was "
            "stopped and billed; a failure is retested once. System One is not in the column: its models choose "
            "among offered actions and call no tools. The run's findings are in "
            "[support-matrix-notes.md](support-matrix-notes.md).", "",
            "| base | model | browser | tools seen | seconds | notes |", "|---|---|---|---|---:|---|"]
    for r in doc.get("rows", []):
        note = r.get("why", "") or ""
        if r.get("retested"):
            note = "retested once; first try: " + (r["retested"].get("why", "") or "")[:120] + (" ; " + note if note else "")
        out.append(f"| {r['base']} | {r.get('model', '')} | {'pass' if r.get('ok') else 'FAIL'} | {', '.join(r.get('tools') or []) or '-'} | {r.get('s', '')} | {note.replace('|', '/')} |")
    okn = sum(1 for r in doc.get("rows", []) if r.get("ok"))
    out += ["", f"{okn} of {len(doc.get('rows', []))} bases drive the browser.", ""]
print("\n".join(out))
