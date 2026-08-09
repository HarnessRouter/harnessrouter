'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  deleteHarness, getHarness, listModels, updateHarness, type Harness, type ModelCatalog,
} from '@/lib/api';

export default function HarnessDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [h, setH] = useState<Harness | null>(null);
  const [draft, setDraft] = useState<Harness | null>(null);
  const [catalog, setCatalog] = useState<ModelCatalog>({});
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getHarness(id).then((x) => { setH(x); setDraft(x); })
      .catch((e) => setErr(String(e.message || e)));
    listModels().then(setCatalog).catch(() => { /* free-text fallback */ });
  }, [id]);

  if (err && !draft) return <div className="page"><div className="banner banner-err">{err}</div></div>;
  if (!draft) return <div className="page"><div className="empty">Loading…</div></div>;

  const models = catalog[String(draft.base)]?.models?.map((m) => m.id) || [];
  const dirty = JSON.stringify(draft) !== JSON.stringify(h);
  const set = (patch: Partial<Harness>) => setDraft({ ...draft, ...patch });

  const save = async () => {
    setSaving(true); setErr(''); setMsg('');
    try {
      const saved = await updateHarness(id, {
        name: draft.name,
        defaultModel: draft.defaultModel,
        systemPrompt: draft.systemPrompt,
        maxStep: draft.maxStep,
        timeoutSeconds: draft.timeoutSeconds,
      });
      setH(saved); setDraft(saved); setMsg('Saved.');
    } catch (e) {
      setErr(String((e as Error).message || e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete "${draft.name}"? Its tasks are kept but it can no longer run.`)) return;
    try {
      await deleteHarness(id);
      router.push('/harnesses');
    } catch (e) {
      setErr(String((e as Error).message || e));
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <h1>{h?.name || draft.name}</h1>
        <div className="spacer" />
        <button className="btn" onClick={() => router.push(`/tasks?h=${encodeURIComponent(id)}`)}>
          Run a task
        </button>
        <button className="btn btn-danger" onClick={remove}>Delete</button>
        <button className="btn btn-primary" disabled={!dirty || saving} onClick={save}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>

      {err ? <div className="banner banner-err">{err}</div> : null}
      {msg ? <div className="banner banner-ok">{msg}</div> : null}

      <div className="card">
        <div className="field">
          <label htmlFor="n">Name</label>
          <input id="n" className="input" value={String(draft.name || '')}
                 onChange={(e) => set({ name: e.target.value })} />
        </div>

        <div className="field">
          <label htmlFor="b">Backend</label>
          <input id="b" className="input" value={String(draft.base || '')} disabled />
          <div className="muted" style={{ marginTop: 4 }}>
            The backend is fixed at creation — it determines which agent runtime executes a turn.
          </div>
        </div>

        <div className="field">
          <label htmlFor="m">Default model</label>
          {models.length ? (
            <select id="m" className="select" value={String(draft.defaultModel || '')}
                    onChange={(e) => set({ defaultModel: e.target.value })}>
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input id="m" className="input" value={String(draft.defaultModel || '')}
                   onChange={(e) => set({ defaultModel: e.target.value })} />
          )}
        </div>

        <div className="field">
          <label htmlFor="sp">Instructions</label>
          <textarea id="sp" className="textarea" value={String(draft.systemPrompt || '')}
                    placeholder="System prompt / AGENTS.md content for this harness"
                    onChange={(e) => set({ systemPrompt: e.target.value })} />
        </div>

        <div className="card-row">
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="ms">Max steps per turn</label>
            <input id="ms" className="input" type="number" min={1}
                   value={draft.maxStep ?? ''} placeholder="default"
                   onChange={(e) => set({ maxStep: e.target.value ? Number(e.target.value) : null })} />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="ts">Turn timeout (seconds)</label>
            <input id="ts" className="input" type="number" min={1}
                   value={draft.timeoutSeconds ?? ''} placeholder="default"
                   onChange={(e) => set({ timeoutSeconds: e.target.value ? Number(e.target.value) : null })} />
          </div>
        </div>
      </div>
    </div>
  );
}
