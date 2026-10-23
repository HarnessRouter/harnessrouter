'use client';
// Setting a kit up in this workspace, as the design's sheets are drawn (`.sheet`, the Publish
// sheet's `.ship-opt` choices, `.set-f` fields). The questions are the kit's own: what to run it
// on (its recommended pairings, each marked with whether this organization can serve it, or any
// agent harness and model), and, for a kit that reads a database, which one. Opening a kit that is
// already set up asks nothing; this sheet is for the first time, and for pointing a kit at another
// database. The connection string lives in this sheet's state and the one request that carries it.
import Link from 'next/link';
import { useEffect, useMemo, useRef, useState } from 'react';
import { testDatabase } from '@/lib/harness';
import { Sheet, SheetTop } from '../Sheet';
import { toast } from '../toast';
import { ENGINE_EXAMPLE, ENGINE_LABEL, launchError, launchKit, type Base, type Kit, type Launched } from './kits';
import { HLogo } from './parts';

const CHECK = <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;

export type LaunchMode = 'try' | 'launch' | 'reconnect';
type Db = { engine: string; connectionString: string; sampleRows: boolean };

export function LaunchSheet({ kit, bases, basesFailed = false, onRetryBases, mode, onClose, onDone }: {
  kit: Kit;
  /** what this organization can run, for choosing another pairing: null while it is read */
  bases: Base[] | null;
  /** that read failed: said where the choice is made, with Try again (onRetryBases) */
  basesFailed?: boolean;
  onRetryBases?: () => void;
  mode: LaunchMode; onClose: () => void; onDone: (r: Launched) => void;
}) {
  const reconnect = mode === 'reconnect';
  // only what this organization can run is offered: the recommended one when it can, else the first
  const runnable = kit.choices.filter((c) => c.available);
  const rec = runnable.find((c) => c.recommended) || runnable[0] || null;
  const [sel, setSel] = useState(rec ? `${rec.base}/${rec.model}` : '');
  const [custom, setCustom] = useState(false);
  const [cBase, setCBase] = useState('');
  const [cModel, setCModel] = useState('');
  // sampling defaults on: the agent designs better when it can see what a column holds; off is a
  // real switch, it then receives table and column names and not one value
  const [db, setDb] = useState<Db>(() => ({ engine: kit.database?.engines[0] || 'postgres', connectionString: '', sampleRows: true }));
  const [test, setTest] = useState<null | { busy?: boolean; ok?: boolean; msg?: string }>(null);
  const [busy, setBusy] = useState(false);
  const dbRef = useRef<HTMLInputElement | null>(null);

  // only an agent harness something connected can run is offered, and only the models it can run
  const runBases = useMemo(() => (bases || []).filter((b) => b.models.some((m) => m.available)), [bases]);
  useEffect(() => { if (!cBase && runBases[0]) setCBase(runBases[0].id); }, [runBases, cBase]);
  // models are per agent harness: changing it re-picks one it can run, the first available
  const baseModels = (bases || []).find((b) => b.id === cBase)?.models || [];
  useEffect(() => {
    if (!baseModels.some((m) => m.id === cModel && m.available)) setCModel(baseModels.find((m) => m.available)?.id || '');
  }, [cBase, baseModels, cModel]);

  const nothingAvailable = !runnable.length;
  // a kit that reads a database cannot be set up the first time without one; once set up, a blank
  // field keeps what it reads today
  const missing = !!kit.database && !kit.launched && !db.connectionString.trim();
  const canGo = reconnect ? !!db.connectionString.trim()
    : (custom ? !!(cBase && cModel) : !!sel) && !missing;
  const setD = (p: Partial<Db>) => { setDb((d) => ({ ...d, ...p })); if ('engine' in p || 'connectionString' in p) setTest(null); };

  async function runTest() {
    setTest({ busy: true });
    const r = await testDatabase(db.engine, db.connectionString.trim()).catch(() => null);
    // the table count is the server's own answer: it tells whether this account can see the data. A
    // test that got no answer says that, not that the connection string is wrong
    setTest(!r ? { ok: false, msg: 'The connection could not be checked just now. Try again.' }
      : r.ok ? { ok: true, msg: `Connected${r.database ? `, ${r.database}` : ''}${r.tableCount != null ? `, ${r.tableCount} tables` : ''}.` }
        : { ok: false, msg: 'Could not connect. Check the connection string, and that the account can read.' });
  }

  async function go() {
    if (!canGo || busy) return;
    let base = '', model = '';
    if (!reconnect) {
      if (custom) { base = cBase; model = cModel; }
      else { const [b, ...rest] = sel.split('/'); base = b; model = rest.join('/'); }
    }
    setBusy(true);
    try {
      const r = await launchKit(kit.id, { base, model, database: kit.database ? db : undefined });
      onDone(r);
    } catch (e) {
      setBusy(false);
      toast(launchError(e, kit, reconnect));
    }
  }

  const title = reconnect ? `Reconnect ${kit.title}` : mode === 'try' ? `Try ${kit.title}` : `Launch ${kit.title}`;
  const goLabel = busy ? (reconnect ? 'Connecting…' : 'Setting up…') : reconnect ? 'Reconnect' : mode === 'try' ? 'Try it' : 'Launch';

  return (
    <Sheet onClose={onClose} labelledBy="klh" className="ship-sheet kl-sheet" busy={busy} initialFocus={reconnect ? dbRef : 'dialog'}>
      <SheetTop id="klh" title={title} onClose={onClose} />

      {!reconnect && !custom ? (
        <div className="set-f">
          <span className="kl-l" id="klRun">Runs on</span>
          {nothingAvailable ? (
            <p className="keywarn kl-warn">None of these can run yet. Add a provider key in <Link className="link-q inl" href="/byok">Bring your own key</Link>, or choose a different one.</p>
          ) : null}
          <div className="ship-opts" role="radiogroup" aria-labelledby="klRun">
            {runnable.map((c) => {
              const id = `${c.base}/${c.model}`, on = sel === id;
              return (
                <button key={id} type="button" role="radio" aria-checked={on} className={'ship-opt' + (on ? ' on' : '')}
                  onClick={() => setSel(id)}>
                  <span className="so-box">{CHECK}</span>
                  <span>
                    <b><HLogo base={c.base} />{c.baseLabel || c.base}{c.recommended ? <span className="h-pre"><span className="sr">, </span>Recommended</span> : null}</b>
                    <small className="mono">{c.model}</small>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      {!reconnect && custom && basesFailed ? (
        <p className="set-help kl-bad" role="alert">The agent harnesses you can run could not be read just now.{' '}
          <button type="button" className="link-q inl" onClick={onRetryBases}>Try again</button></p>
      ) : null}
      {!reconnect && custom && !basesFailed ? (
        <>
          <div className="set-f"><label htmlFor="klBase">Agent harness</label>
            <select id="klBase" className="set-in" value={cBase} onChange={(e) => setCBase(e.target.value)}>
              {runBases.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
            </select></div>
          <div className="set-f"><label htmlFor="klModel">Model</label>
            <select id="klModel" className="set-in" value={cModel} onChange={(e) => setCModel(e.target.value)}>
              {!baseModels.some((m) => m.available) ? <option value="">No models</option> : null}
              {baseModels.filter((m) => m.available).map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
            </select>
            {bases && !runBases.length ? <p className="set-help">Nothing you have connected can run an agent harness yet.</p> : null}
          </div>
        </>
      ) : null}

      {kit.database ? (
        <>
          <div className="set-f">
            <label htmlFor="klDb">{kit.launched ? 'Change the database it reads' : 'Connect your database'}</label>
            {kit.launched && !reconnect ? <p className="set-help kl-help">Leave this blank to keep reading what it reads today.</p> : null}
            {kit.database.engines.length > 1 ? (
              <select className="set-in kl-eng" aria-label="Type" value={db.engine} onChange={(e) => setD({ engine: e.target.value })}>
                {kit.database.engines.map((e) => <option key={e} value={e}>{ENGINE_LABEL[e] || e}</option>)}
              </select>
            ) : null}
            <input id="klDb" ref={dbRef} className="set-in mono" type="text" spellCheck={false} autoComplete="off" value={db.connectionString}
              placeholder={ENGINE_EXAMPLE[db.engine] || ''} onChange={(e) => setD({ connectionString: e.target.value })}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void go(); } }} />
            <p className="set-help">Use an account that can only read.</p>
            <div className="kl-test">
              <button type="button" className="btn small line" disabled={!db.connectionString.trim() || !!test?.busy} onClick={() => void runTest()}>
                {test?.busy ? 'Testing…' : 'Test connection'}
              </button>
              <span className={'set-help' + (test && !test.busy ? (test.ok ? ' kl-ok' : ' kl-bad') : '')} role="status">{test && !test.busy ? test.msg : ''}</span>
            </div>
          </div>
          <div className="ship-opts">
            <button type="button" role="checkbox" aria-checked={db.sampleRows} className={'ship-opt' + (db.sampleRows ? ' on' : '')}
              onClick={() => setD({ sampleRows: !db.sampleRows })}>
              <span className="so-box">{CHECK}</span>
              <span><b>Let it see a few example rows</b></span>
            </button>
          </div>
        </>
      ) : null}

      <div className="sheet-actions">
        {!reconnect ? (
          <button type="button" className="link-q kl-alt" onClick={() => setCustom((v) => !v)}>{custom ? 'Back to recommended' : 'Choose a different one'}</button>
        ) : null}
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={busy || !canGo} onClick={() => void go()}>{goLabel}</button>
      </div>
    </Sheet>
  );
}
