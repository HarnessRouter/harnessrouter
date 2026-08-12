// Starter Kits — a whole product in a folder.
//
// A kit is a configured Harness plus a UI that talks to it as its backend. Both are baked into
// the image (docker/install-kits.sh), so Launch provisions the Harness and opens an app that is
// already here — nothing is deployed and nothing is configured.
//
// Launch is idempotent server-side, so this page does not have to guard against a second click:
// the second one returns the Harness the first one made.
'use client';

import { useCallback, useEffect, useState } from 'react';
import { authHeaders } from '@/lib/chat';
import { harnessFetch } from '@/lib/hfetch';

interface Kit {
  id: string; title: string; tagline: string; description: string;
  icon: string; accent: string; route: string; base: string;
  launched: boolean; harnessId: string | null;
}

export default function KitsPage() {
  const [kits, setKits] = useState<Kit[] | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');

  const reload = useCallback(() => {
    harnessFetch('/api/harness/v1/kits', { headers: authHeaders(), cache: 'no-store' })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `${r.status}`);
        setKits((await r.json()).kits || []);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : 'load failed'));
  }, []);
  useEffect(() => reload(), [reload]);

  async function launch(kit: Kit) {
    setBusy(kit.id); setErr('');
    try {
      const r = await harnessFetch(`/api/harness/v1/kits/${kit.id}/launch`,
                                   { method: 'POST', headers: authHeaders() });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `${r.status}`);
      const { route } = await r.json();
      // Hard navigation: the kit app is served outside this Next app, from the image.
      window.location.href = route || `/kits/${kit.id}`;
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'launch failed');
      setBusy('');
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
                <span className="hr-meta">{k.base}</span>
                <button className="button primary" type="button" disabled={busy === k.id}
                  onClick={() => void launch(k)}>
                  {busy === k.id ? 'Opening…' : k.launched ? 'Open' : 'Launch'}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div></section>
  );
}
