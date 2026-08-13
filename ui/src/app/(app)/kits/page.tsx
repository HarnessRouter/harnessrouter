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
interface Kit {
  id: string; title: string; tagline: string; description: string;
  icon: string; accent: string; route: string;
  launched: boolean; harnessId: string | null;
  choices: Choice[];
}
interface BaseModel { id: string; available: boolean }
interface Base { id: string; label: string; models: BaseModel[] }

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

  async function launch(kit: Kit, base?: string, model?: string) {
    setBusy(kit.id); setErr('');
    try {
      const r = await harnessFetch(`/api/harness/v1/kits/${kit.id}/launch`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(base ? { base, model: model || '' } : {}),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `${r.status}`);
      const { route } = await r.json();
      // Hard navigation: the kit app is served outside this Next app, from the image.
      window.location.href = route || `/kits/${kit.id}`;
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'launch failed');
      setBusy(''); setPicking(null);
    }
  }

  return (
    <section className="view is-active"><div className="page">
      <header className="page-head">
        <div>
          <h1>Starter Kits</h1>
          <p>A working product in one click: each kit provisions the Harness it needs and opens
            its own app, with everything it uses included.</p>
        </div>
      </header>

      {err && <div className="hr-error" role="alert">{err}</div>}

      {kits === null && !err && <div className="kit-grid">
        {[0, 1].map((i) => <div key={i} className="kit-card"><span className="sk" style={{ height: 132 }} /></div>)}
      </div>}

      {kits !== null && kits.length === 0 && (
        <div className="session-empty">
          This build ships no starter kits. They come from the starter-kit repository at image
          build time — a build with <code>WITH_STARTER_KITS=0</code> has none.
        </div>
      )}

      {kits !== null && kits.length > 0 && (
        <div className="kit-grid">
          {kits.map((k) => (
            <article key={k.id} className="kit-card">
              <span className="kit-icon" style={k.accent ? { background: k.accent } : undefined}>
                <iconify-icon icon={k.icon || 'tabler:box'}></iconify-icon>
              </span>
              <div className="kit-copy">
                <h2>{k.title}</h2>
                <p className="kit-tagline">{k.tagline}</p>
                <p className="kit-desc">{k.description}</p>
              </div>
              <div className="kit-actions">
                <button className="button primary" type="button" disabled={busy === k.id}
                  onClick={() => (k.launched ? void launch(k) : setPicking(k))}>
                  {busy === k.id ? 'Opening…' : k.launched ? 'Open' : 'Launch'}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      {picking && (
        <LaunchDialog
          kit={picking} bases={bases} busy={busy === picking.id}
          onClose={() => setPicking(null)}
          onLaunch={(base, model) => void launch(picking, base, model)}
        />
      )}
    </div></section>
  );
}

function LaunchDialog({ kit, bases, busy, onClose, onLaunch }: {
  kit: Kit; bases: Base[]; busy: boolean;
  onClose: () => void; onLaunch: (base: string, model: string) => void;
}) {
  const recommended = kit.choices.find((c) => c.recommended) || null;
  const [sel, setSel] = useState<string>(recommended ? `${recommended.base}/${recommended.model}` : '');
  const [custom, setCustom] = useState(false);
  const [cBase, setCBase] = useState(bases[0]?.id || '');
  const [cModel, setCModel] = useState('');

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
  const canLaunch = custom ? Boolean(cBase && cModel) : Boolean(sel);

  function go() {
    if (custom) { onLaunch(cBase, cModel); return; }
    const [base, ...rest] = sel.split('/');
    onLaunch(base, rest.join('/'));
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
