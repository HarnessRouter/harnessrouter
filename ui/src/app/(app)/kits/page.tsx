// Starter Kits — a whole product in a folder.
//
// A kit is a configured Harness plus a UI that talks to it as its backend. Both are baked into
// the image (docker/install-kits.sh), so Launch provisions the Harness and opens an app that is
// already here — nothing is deployed and nothing is configured.
//
// Launch asks one question first: what to run it on. The kit declares which pairings suit its
// work (kit.json `harness.recommended`) and the server marks which of those the caller's
// integrations can actually serve, so the dialog offers real choices and preselects the best
// available one. "Choose a different one" opens the full catalog as two cascading selects.
//
// Launch is idempotent server-side, so this page does not have to guard against a second click:
// the second one returns the Harness the first one made.
'use client';

import { useCallback, useEffect, useState } from 'react';
import { authHeaders } from '@/lib/chat';
import { harnessFetch } from '@/lib/hfetch';

interface Choice {
  base: string; model: string; baseLabel: string;
  available: boolean; recommended: boolean;
}
interface Datasource { engine: string; host: string; database: string; sampleRows: boolean }
interface Kit {
  id: string; title: string; tagline: string; description: string;
  icon: string; accent: string; route: string;
  /** The kit's own mark, served from its directory. Empty when it ships none — then `icon` (an
   *  iconify name) is what the card draws instead. */
  iconUrl: string;
  launched: boolean; harnessId: string | null;
  skills: string[];
  runningOn: { base: string; model: string } | null;
  choices: Choice[];
  /** Set when this kit reads a database, listing the kinds it accepts. Null when it does not. */
  datasource: { required: boolean; engines: string[] } | null;
  /** What a launched kit is actually reading. Never carries the credential. */
  connected: Datasource | null;
}

/** What to call each kind of database in front of a person. */
const ENGINE_LABEL: Record<string, string> = {
  postgres: 'PostgreSQL',
  mysql: 'MySQL / MariaDB',
};

/** Placeholder for a connection string, per kind — the format is the question people ask. */
const ENGINE_EXAMPLE: Record<string, string> = {
  postgres: 'postgresql://user:password@host:5432/database',
  mysql: 'mysql://user:password@host:3306/database',
};
interface BaseModel { id: string; available: boolean }
interface Base { id: string; label: string; models: BaseModel[] }

/** What the card should say about the runtime.
 *
 *  A LAUNCHED kit reports what its Harness is really running — the person may have chosen
 *  something other than the recommendation at launch, or changed it since, and showing the
 *  recommendation instead would state something about their setup that is not true. Only a kit
 *  that has never been launched shows a recommendation, and says so.
 */
function runtimeOf(kit: Kit): { label: string; model: string; suggested: boolean } | null {
  if (kit.launched && kit.runningOn?.base) {
    const c = kit.choices?.find((x) => x.base === kit.runningOn!.base);
    return { label: c?.baseLabel || kit.runningOn.base, model: kit.runningOn.model, suggested: false };
  }
  const rec = kit.choices?.find((c) => c.recommended);
  return rec ? { label: rec.baseLabel, model: rec.model, suggested: true } : null;
}

export default function KitsPage() {
  const [kits, setKits] = useState<Kit[] | null>(null);
  const [bases, setBases] = useState<Base[]>([]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [picking, setPicking] = useState<Kit | null>(null);

  const reload = useCallback(() => {
    harnessFetch('/api/harness/v1/kits', { headers: authHeaders(), cache: 'no-store' })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `${r.status}`);
        setKits((await r.json()).kits || []);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : 'load failed'));
  }, []);
  useEffect(() => reload(), [reload]);

  // Only needed by the "choose a different one" path, but it is one small request and having it
  // already loaded means that panel opens instantly instead of flashing empty selects.
  useEffect(() => {
    harnessFetch('/api/harness/v1/bases', { headers: authHeaders(), cache: 'no-store' })
      .then(async (r) => (r.ok ? setBases((await r.json()).bases || []) : undefined))
      .catch(() => {});
  }, []);

  /** A kit app runs outside this Next app, so it gets its own tab. */
  function openApp(route: string) {
    window.open(route, '_blank', 'noopener,noreferrer');
  }

  async function launch(kit: Kit, base?: string, model?: string, db?: DbDraft) {
    // Open the tab NOW, on the click, and navigate it when the launch returns. Opening it after
    // the await is a popup the browser is entitled to block, because by then it is no longer a
    // user gesture.
    const tab = window.open('', '_blank', 'noopener,noreferrer');
    setBusy(kit.id); setErr('');
    try {
      const r = await harnessFetch(`/api/harness/v1/kits/${kit.id}/launch`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          ...(base ? { base, model: model || '' } : {}),
          // Sent only when the person filled the database step in. The connection string goes
          // straight to the server and is never held anywhere else.
          ...(db?.connectionString.trim()
            ? { engine: db.engine, connection_string: db.connectionString.trim(),
                sample_rows: db.sampleRows }
            : {}),
        }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `${r.status}`);
      const { route } = await r.json();
      const url = route || `/kits/${kit.id}`;
      if (tab) tab.location.href = url; else openApp(url);
      setPicking(null); setBusy('');
      reload();
    } catch (e) {
      tab?.close();
      setErr(e instanceof Error ? e.message : 'launch failed');
      setBusy(''); setPicking(null);
    }
  }

  return (
    // Same chrome as every other collection page (Harnesses, Integrations, Keys…). This page
    // used `page-head`, which is styled nowhere — that is why its heading and spacing did not
    // match the rest of the console.
    <section className="view is-active collection-view" id="view-kits"><div className="page">
      <div className="page-header">
        <div>
          <h1>Starter Kits</h1>
          <p>A working product in one click: each kit provisions the Harness it needs and opens
            its own app, with everything it uses included.</p>
        </div>
      </div>

      {err && <div className="hr-error" role="alert">{err}</div>}

      {kits === null && !err && <div className="kit-grid">
        {[0, 1].map((i) => <div key={i} className="kit-card"><span className="sk" style={{ height: 236 }} /></div>)}
      </div>}

      {kits !== null && kits.length === 0 && (
        <div className="session-empty">
          This build ships no starter kits. They come from the starter-kit repository at image
          build time — a build with <code>WITH_STARTER_KITS=0</code> has none.
        </div>
      )}

      {kits !== null && kits.length > 0 && (
        <div className="kit-grid">
          {kits.map((k) => {
            const run = runtimeOf(k);
            return (
              <article key={k.id} className="kit-card">
                {/* A wash of the kit's own accent, so a card reads as the product it opens. */}
                <span className="kit-wash" style={k.accent ? { background: k.accent } : undefined} />

                <header className="kit-head">
                  {/* The kit's own product mark when it ships one — the same drawing its app puts
                      in its own title bar, so the card and the thing it opens are recognisably one
                      product. A kit without a mark keeps the icon name from its manifest, tinted
                      with its accent; the mark supplies its own colour and needs no tile. */}
                  {k.iconUrl ? (
                    <span className="kit-icon is-mark">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={k.iconUrl} alt="" width={40} height={40} />
                    </span>
                  ) : (
                    <span className="kit-icon" style={k.accent ? { background: k.accent } : undefined}>
                      <iconify-icon icon={k.icon || 'tabler:box'}></iconify-icon>
                    </span>
                  )}
                  <div className="kit-titles">
                    <h2>{k.title}</h2>
                    <p className="kit-tagline">{k.tagline}</p>
                  </div>
                  {k.launched && <span className="kit-live" title="This kit is already running">Running</span>}
                </header>

                <p className="kit-desc">{k.description}</p>

                {/* Everything here is a fact from the kit's own config or the server's view of
                    this org's integrations — never a guess about what the kit might do. */}
                <ul className="kit-facts">
                  {run && (
                    <li>
                      <iconify-icon icon="tabler:cpu"></iconify-icon>
                      {run.suggested ? 'Will run on ' : 'Running on '}{run.label}
                      <span className="kit-fact-dim"> · {run.model}</span>
                    </li>
                  )}
                  {!run && (
                    <li className="kit-fact-warn">
                      <iconify-icon icon="tabler:plug-connected-x"></iconify-icon>
                      No connected provider can run this yet
                    </li>
                  )}
                  {k.skills.length > 0 && (
                    <li>
                      <iconify-icon icon="tabler:sparkles"></iconify-icon>
                      Installs {k.skills.join(', ')}
                    </li>
                  )}
                  {/* A launched kit reports the database it actually reads; one that has not been
                      launched reports what it will ask for. Neither is a guess. */}
                  {k.connected && (
                    <li>
                      <iconify-icon icon="tabler:database"></iconify-icon>
                      Reading {k.connected.database}
                      <span className="kit-fact-dim"> · {k.connected.host}</span>
                    </li>
                  )}
                  {!k.connected && k.datasource && (
                    <li>
                      <iconify-icon icon="tabler:database"></iconify-icon>
                      Reads your {k.datasource.engines.map((e) => ENGINE_LABEL[e] || e).join(' or ')} database
                    </li>
                  )}
                </ul>

                <footer className="kit-actions">
                  {k.launched && k.harnessId && (
                    <a className="kit-link" href={`/harnesses/${k.harnessId}`}>Harness settings</a>
                  )}
                  <span className="kit-actions-spacer" />
                  <button className="button primary" type="button" disabled={busy === k.id}
                    onClick={() => (k.launched ? openApp(k.route || `/kits/${k.id}`) : setPicking(k))}>
                    {busy === k.id ? 'Launching…' : k.launched ? 'Open' : 'Launch'}
                    <iconify-icon icon={k.launched ? 'tabler:external-link' : 'tabler:arrow-right'}></iconify-icon>
                  </button>
                </footer>
              </article>
            );
          })}
        </div>
      )}

      {picking && (
        <LaunchDialog
          kit={picking} bases={bases} busy={busy === picking.id}
          onClose={() => setPicking(null)}
          onLaunch={(base, model, db) => void launch(picking, base, model, db)}
        />
      )}
    </div></section>
  );
}

interface DbDraft { engine: string; connectionString: string; sampleRows: boolean }

function LaunchDialog({ kit, bases, busy, onClose, onLaunch }: {
  kit: Kit; bases: Base[]; busy: boolean;
  onClose: () => void; onLaunch: (base: string, model: string, db?: DbDraft) => void;
}) {
  const recommended = kit.choices.find((c) => c.recommended) || null;
  const [sel, setSel] = useState<string>(recommended ? `${recommended.base}/${recommended.model}` : '');
  const [custom, setCustom] = useState(false);
  const [cBase, setCBase] = useState(bases[0]?.id || '');
  const [cModel, setCModel] = useState('');
  // Sampling defaults on: the agent designs better dashboards when it can see what a column
  // actually contains. Off is one click away, and it is a real switch — off means the agent
  // receives table and column names and not one value.
  const [db, setDb] = useState<DbDraft>({
    engine: kit.datasource?.engines[0] || 'postgres', connectionString: '', sampleRows: true,
  });

  // Models are per base, so changing the agent has to re-pick the model rather than keep one the
  // new agent cannot run. First available, not first listed — an unavailable default is a trap.
  const baseModels = bases.find((b) => b.id === cBase)?.models || [];
  useEffect(() => {
    if (!baseModels.some((m) => m.id === cModel && m.available)) {
      setCModel(baseModels.find((m) => m.available)?.id || '');
    }
  }, [cBase, baseModels, cModel]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const nothingAvailable = !kit.choices.some((c) => c.available);
  const needsDb = Boolean(kit.datasource?.required) && !kit.connected;
  const hasDb = db.connectionString.trim().length > 0;
  const canLaunch = (custom ? Boolean(cBase && cModel) : Boolean(sel)) && (!needsDb || hasDb);

  function go() {
    const draft = hasDb ? db : undefined;
    if (custom) { onLaunch(cBase, cModel, draft); return; }
    const [base, ...rest] = sel.split('/');
    onLaunch(base, rest.join('/'), draft);
  }

  return (
    <div className="kit-overlay" role="dialog" aria-modal="true" aria-labelledby="kit-launch-title"
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="kit-dialog">
        <button className="kit-dialog-x" type="button" onClick={onClose} aria-label="Close">
          <iconify-icon icon="tabler:x"></iconify-icon>
        </button>
        <h2 id="kit-launch-title">Launch {kit.title}</h2>
        <p className="kit-dialog-sub">Choose what it runs on. You can change this later in the
          Harness settings.</p>

        {nothingAvailable && !custom && (
          <div className="hr-error" role="alert">
            None of these can run yet — connect a provider on the Integrations page first.
          </div>
        )}

        {!custom && (
          <div className="kit-choices">
            {kit.choices.map((c) => {
              const id = `${c.base}/${c.model}`;
              return (
                <label key={id} className={`kit-choice${c.available ? '' : ' is-off'}`}>
                  <input type="radio" name="kit-choice" value={id} checked={sel === id}
                         disabled={!c.available} onChange={() => setSel(id)} />
                  <span className="kit-choice-body">
                    <span className="kit-choice-top">
                      <strong>{c.baseLabel}</strong>
                      {c.recommended && <span className="kit-badge">Recommended</span>}
                    </span>
                    <span className="kit-choice-model">{c.model}</span>
                    {!c.available && (
                      <span className="kit-choice-why">Not connected — add a provider that serves
                        this model to use it.</span>
                    )}
                  </span>
                </label>
              );
            })}
          </div>
        )}

        {custom && (
          <div className="kit-custom">
            <label className="kit-field">
              <span>Harness</span>
              <select value={cBase} onChange={(e) => setCBase(e.target.value)}>
                {bases.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
              </select>
            </label>
            <label className="kit-field">
              <span>Model</span>
              <select value={cModel} onChange={(e) => setCModel(e.target.value)}>
                {baseModels.length === 0 && <option value="">No models</option>}
                {baseModels.map((m) => (
                  <option key={m.id} value={m.id} disabled={!m.available}>
                    {m.id}{m.available ? '' : ' — not connected'}
                  </option>
                ))}
              </select>
            </label>
            {cBase && !baseModels.some((m) => m.available) && (
              <p className="kit-choice-why">Nothing you have connected can run this harness.</p>
            )}
          </div>
        )}

        {kit.datasource && <DatabaseStep kit={kit} db={db} onChange={setDb} />}

        <div className="kit-dialog-actions">
          <button className="button ghost" type="button" onClick={() => setCustom((v) => !v)}>
            {custom ? 'Back to recommended' : 'Choose a different one'}
          </button>
          <span className="kit-dialog-spacer" />
          <button className="button" type="button" onClick={onClose}>Cancel</button>
          <button className="button primary" type="button" disabled={busy || !canLaunch} onClick={go}>
            {busy ? 'Launching…' : 'Launch'}
          </button>
        </div>
      </div>
    </div>
  );
}

/** The database step of the launch dialog.
 *
 *  Shown only for a kit that declares it reads one (kit.json `harness.datasource`), so no other
 *  kit grows a field it has no use for. The connection string is sent to the server and held
 *  nowhere else: it is not stored in this component's URL, not put in local storage, and the
 *  server never sends it back — a saved connection reads back as its host and database only.
 */
function DatabaseStep({ kit, db, onChange }: {
  kit: Kit; db: DbDraft; onChange: (d: DbDraft) => void;
}) {
  const [test, setTest] = useState<{ state: 'idle' | 'busy' | 'ok' | 'err'; message: string }>(
    { state: 'idle', message: '' });
  const engines = kit.datasource?.engines || [];

  async function runTest() {
    setTest({ state: 'busy', message: '' });
    try {
      const r = await harnessFetch('/api/harness/v1/datasource-test', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ engine: db.engine, connection_string: db.connectionString.trim() }),
      });
      const body = await r.json().catch(() => null);
      if (!r.ok) { setTest({ state: 'err', message: body?.detail || `${r.status}` }); return; }
      if (!body?.ok) { setTest({ state: 'err', message: body?.error || 'could not connect' }); return; }
      // The table count is the server's answer, not an estimate — and it is the number that tells
      // someone whether the account they used can actually see their data.
      setTest({ state: 'ok', message: `${body.database} · ${body.tableCount} tables` });
    } catch {
      setTest({ state: 'err', message: 'could not reach the server' });
    }
  }

  return (
    <div className="kit-db">
      <h3 className="kit-db-title">
        {kit.connected ? 'Change the database it reads' : 'Connect your database'}
      </h3>
      {kit.connected && (
        <p className="kit-choice-why">
          Currently reading {kit.connected.database} on {kit.connected.host}. Leave this blank to
          keep it.
        </p>
      )}

      <div className="kit-db-fields">
        {engines.length > 1 && (
          <label className="kit-field kit-db-engine">
            <span>Type</span>
            <select value={db.engine}
                    onChange={(e) => { onChange({ ...db, engine: e.target.value }); setTest({ state: 'idle', message: '' }); }}>
              {engines.map((e) => <option key={e} value={e}>{ENGINE_LABEL[e] || e}</option>)}
            </select>
          </label>
        )}
        <label className="kit-field kit-db-conn">
          <span>Connection string</span>
          <input type="text" value={db.connectionString} spellCheck={false} autoComplete="off"
                 placeholder={ENGINE_EXAMPLE[db.engine] || ''}
                 onChange={(e) => { onChange({ ...db, connectionString: e.target.value }); setTest({ state: 'idle', message: '' }); }} />
        </label>
      </div>

      <div className="kit-db-test">
        <button className="button" type="button"
                disabled={!db.connectionString.trim() || test.state === 'busy'} onClick={() => void runTest()}>
          {test.state === 'busy' ? 'Testing…' : 'Test connection'}
        </button>
        {test.state === 'ok' && (
          <span className="kit-test-status ok"><span className="kit-test-dot" />Connected · {test.message}</span>
        )}
        {test.state === 'err' && (
          <span className="kit-test-status err"><span className="kit-test-dot" />{test.message}</span>
        )}
      </div>

      <label className="kit-db-sample">
        <input type="checkbox" checked={db.sampleRows}
               onChange={(e) => onChange({ ...db, sampleRows: e.target.checked })} />
        <span>
          <strong>Let it see a few example rows</strong>
          <em>
            With this on the agent reads a handful of rows per table, so it can tell what a column
            holds. With it off it sees table and column names and no values at all.
          </em>
        </span>
      </label>

      <p className="kit-choice-why">
        Use an account that can only read. Your connection is encrypted and is never shown again.
      </p>
    </div>
  );
}
