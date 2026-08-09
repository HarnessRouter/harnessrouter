'use client';

import { useState } from 'react';
import type { Harness } from '@/lib/api';

/** Promote local harnesses to a hosted HarnessRouter account.
 *
 *  Deliberately one-way. Local is where you iterate; the hosted copy becomes the authority once
 *  promoted. There is no "pull from cloud" here or anywhere in this repo, so a harness can never
 *  be edited in two places with each claiming to be current.
 *
 *  The hosted key is held in component state for the duration of the request and nothing else —
 *  not localStorage, not the local secret store, not the server. Close the dialog and it's gone. */
export function PushToCloud({ harnesses, onClose }: { harnesses: Harness[]; onClose: () => void }) {
  const [apiKey, setApiKey] = useState('');
  const [cloudUrl, setCloudUrl] = useState('');
  const [picked, setPicked] = useState<Set<string>>(new Set(harnesses.map((h) => h.id)));
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ name: string; ok: boolean; error?: string }[] | null>(null);
  const [err, setErr] = useState('');

  const toggle = (id: string) => {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id); else next.add(id);
    setPicked(next);
  };

  const push = async () => {
    setBusy(true); setErr('');
    try {
      const r = await fetch('/api/cloud/push', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          apiKey: apiKey.trim(),
          cloudUrl: cloudUrl.trim() || undefined,
          harnesses: harnesses.filter((h) => picked.has(h.id)),
        }),
      });
      const d = await r.json();
      if (!r.ok) { setErr(String(d?.detail || `HTTP ${r.status}`)); return; }
      setDone(d.results || []);
    } catch (e) {
      setErr(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  };

  const okCount = done?.filter((d) => d.ok).length ?? 0;

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Push to cloud</h2>
        <p className="muted">
          Copy these harnesses into your hosted HarnessRouter account. This is one-way — hosted
          harnesses are never copied back down, so the cloud copy stays the source of truth once
          promoted.
        </p>

        {done ? (
          <>
            <div className={`banner ${okCount === done.length ? 'banner-ok' : 'banner-err'}`} style={{ marginTop: 14 }}>
              Pushed {okCount} of {done.length}.
            </div>
            {done.filter((d) => !d.ok).map((d) => (
              <div key={d.name} className="muted">· {d.name}: {d.error}</div>
            ))}
            <div className="card-row" style={{ marginTop: 16 }}>
              <div className="spacer" />
              <button className="btn btn-primary" onClick={onClose}>Done</button>
            </div>
          </>
        ) : (
          <>
            {err ? <div className="banner banner-err" style={{ marginTop: 12 }}>{err}</div> : null}

            <div className="field" style={{ marginTop: 14 }}>
              <label htmlFor="ck">Hosted API key</label>
              <input id="ck" className="input" type="password" value={apiKey} autoFocus
                     placeholder="sk-hr-…" onChange={(e) => setApiKey(e.target.value)} />
              <div className="muted" style={{ marginTop: 4 }}>
                Used for this request only — never stored on this machine.
              </div>
            </div>

            <div className="field">
              <label htmlFor="cu">Hosted API URL (optional)</label>
              <input id="cu" className="input" value={cloudUrl} placeholder="https://api.harnessrouter.ai"
                     onChange={(e) => setCloudUrl(e.target.value)} />
            </div>

            <div className="field">
              <label>Harnesses ({picked.size} selected)</label>
              {harnesses.map((h) => (
                <label key={h.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0' }}>
                  <input type="checkbox" checked={picked.has(h.id)} onChange={() => toggle(h.id)} />
                  <span style={{ fontSize: 13 }}>{h.name}</span>
                  <span className="muted">{h.base}</span>
                </label>
              ))}
            </div>

            <div className="card-row" style={{ marginTop: 16 }}>
              <div className="spacer" />
              <button className="btn" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" disabled={!apiKey.trim() || !picked.size || busy} onClick={push}>
                {busy ? 'Pushing…' : `Push ${picked.size}`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
