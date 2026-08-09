'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  createHarness, listHarnesses, listModels, type Harness, type ModelCatalog,
} from '@/lib/api';
import { PushToCloud } from '@/components/PushToCloud';

export default function HarnessesPage() {
  const router = useRouter();
  const [rows, setRows] = useState<Harness[] | null>(null);
  const [catalog, setCatalog] = useState<ModelCatalog>({});
  const [err, setErr] = useState('');
  const [adding, setAdding] = useState(false);
  const [pushing, setPushing] = useState(false);

  const [name, setName] = useState('');
  const [base, setBase] = useState('');
  const [model, setModel] = useState('');
  const [saving, setSaving] = useState(false);

  const reload = () =>
    listHarnesses().then(setRows).catch((e) => { setErr(String(e.message || e)); setRows([]); });

  useEffect(() => {
    reload();
    // The backend catalog is the source of truth for which backends this build actually ships —
    // an image built without a backend must not offer it in the picker.
    listModels().then((c) => {
      setCatalog(c);
      const first = Object.keys(c)[0] || '';
      setBase((b) => b || first);
      setModel((m) => m || (first ? c[first]?.default || '' : ''));
    }).catch(() => { /* picker falls back to a free-text model */ });
  }, []);

  const backends = Object.keys(catalog);
  const models = (base && catalog[base]?.models?.map((m) => m.id)) || [];

  const create = async () => {
    if (!name.trim() || !base) return;
    setSaving(true); setErr('');
    try {
      const h = await createHarness({ name: name.trim(), base, defaultModel: model || undefined });
      setAdding(false); setName('');
      router.push(`/harnesses/${encodeURIComponent(h.id)}`);
    } catch (e) {
      setErr(String((e as Error).message || e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <h1>Harnesses</h1>
        <div className="spacer" />
        {rows?.length ? (
          <button className="btn" onClick={() => setPushing(true)}>Push to cloud</button>
        ) : null}
        <button className="btn btn-primary" onClick={() => setAdding(true)}>New harness</button>
      </div>

      {err ? <div className="banner banner-err">{err}</div> : null}

      {rows === null ? (
        <div className="empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="empty">
          <p>No harnesses in this workspace yet.</p>
          <button className="btn btn-primary" onClick={() => setAdding(true)}>Create your first</button>
        </div>
      ) : (
        rows.map((h) => (
          <div key={h.id} className="card">
            <div className="card-row">
              <div>
                <h3>{h.name}</h3>
                <div className="muted">{h.base}{h.defaultModel ? ` · ${h.defaultModel}` : ''}</div>
              </div>
              <div className="spacer" />
              <button className="btn" onClick={() => router.push(`/tasks?h=${encodeURIComponent(h.id)}`)}>
                Run a task
              </button>
              <button className="btn" onClick={() => router.push(`/harnesses/${encodeURIComponent(h.id)}`)}>
                Configure
              </button>
            </div>
          </div>
        ))
      )}

      {adding ? (
        <div className="modal-back" onClick={() => setAdding(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>New harness</h2>
            <p className="muted">A harness is an agent configuration: a backend, a model, and its instructions.</p>
            <div className="field" style={{ marginTop: 14 }}>
              <label htmlFor="hname">Name</label>
              <input id="hname" className="input" value={name} autoFocus
                     onChange={(e) => setName(e.target.value)} placeholder="e.g. Code reviewer" />
            </div>
            <div className="field">
              <label htmlFor="hbase">Backend</label>
              <select id="hbase" className="select" value={base}
                      onChange={(e) => {
                        setBase(e.target.value);
                        setModel(catalog[e.target.value]?.default || '');
                      }}>
                {backends.length === 0 ? <option value="">(no backends available)</option> : null}
                {backends.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="hmodel">Default model</label>
              {models.length ? (
                <select id="hmodel" className="select" value={model} onChange={(e) => setModel(e.target.value)}>
                  {models.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              ) : (
                <input id="hmodel" className="input" value={model}
                       onChange={(e) => setModel(e.target.value)} placeholder="model id" />
              )}
            </div>
            <div className="card-row" style={{ marginTop: 16 }}>
              <div className="spacer" />
              <button className="btn" onClick={() => setAdding(false)}>Cancel</button>
              <button className="btn btn-primary" disabled={!name.trim() || !base || saving} onClick={create}>
                {saving ? 'Creating…' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {pushing ? <PushToCloud harnesses={rows || []} onClose={() => setPushing(false)} /> : null}
    </div>
  );
}
