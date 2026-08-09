'use client';
// Integrations, token-provider routing console (platform org only for now; the config is
// GLOBAL: it decides which provider serves each model for every harness). Two sections per
// the 2026-07-22 wireframe: (1) named provider integrations, each with credentials and its
// supported-model list (canonical name -> the provider's real model id); (2) the
// Model - Integration Mapping (canonical model -> which integration serves it).
// Server: GET/PUT /v1/admin/integrations (secrets sentinel'd, never round-tripped).
// Later: customer BYOK writes the same schema to the org tenant.
import { harnessFetch } from '@/lib/hfetch';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { SkelRows } from '@/components/Skel';
import { getSession } from '@/lib/auth';
import { authHeaders } from '@/lib/chat';
import { PLATFORM_ADMIN_ORGS } from '@/lib/edition';

interface ModelRow { canonical: string; provider_id: string }
interface Integration { name: string; provider: string; config: Record<string, string>; models: ModelRow[] }
interface Doc { integrations: Integration[]; model_map: Record<string, string>; providers: string[] }

const SECRET = '__secret__';
// Per-provider config fields (which of them is the secret). Shown in the Add/Edit panel.
const PROVIDER_FIELDS: Record<string, { key: string; label: string; secret?: boolean; placeholder?: string }[]> = {
  'azure-foundry': [
    { key: 'base_url', label: 'Endpoint URL', placeholder: 'https://<resource>.openai.azure.com/openai/v1' },
    { key: 'api_key', label: 'API Key', secret: true },
  ],
  bedrock: [
    { key: 'aws_region', label: 'AWS Region', placeholder: 'us-east-1' },
    { key: 'aws_bearer_token', label: 'API Key (bearer token)', secret: true },
  ],
  openrouter: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://openrouter.ai/api/v1' },
    { key: 'api_key', label: 'API Key', secret: true },
  ],
  tokenrouter: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://api.tokenrouter.com/v1' },
    { key: 'api_key', label: 'API Key', secret: true },
  ],
  openai: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://api.openai.com/v1' },
    { key: 'api_key', label: 'API Key', secret: true },
  ],
  anthropic: [
    { key: 'base_url', label: 'Base URL (optional)', placeholder: 'https://api.anthropic.com' },
    { key: 'api_key', label: 'API Key', secret: true },
  ],
};
const PROVIDER_LABEL: Record<string, string> = {
  'azure-foundry': 'Azure OpenAI', bedrock: 'AWS Bedrock', openrouter: 'OpenRouter',
  tokenrouter: 'TokenRouter', openai: 'OpenAI', anthropic: 'Anthropic',
};

export default function IntegrationsPage() {
  const router = useRouter();
  const org = getSession()?.orgId || '';
  const allowed = PLATFORM_ADMIN_ORGS.includes(org);
  const [doc, setDoc] = useState<Doc | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [editing, setEditing] = useState<Integration | null>(null);   // panel draft
  const [editingOriginal, setEditingOriginal] = useState<string | null>(null); // name being edited, null = new
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const reload = useCallback(() => {
    harnessFetch('/api/harness/v1/admin/integrations', { headers: authHeaders() })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `${r.status}`);
        setDoc(await r.json());
      })
      .catch((e) => setErr(e instanceof Error ? e.message : 'load failed'));
  }, []);
  useEffect(() => { if (allowed) reload(); }, [allowed, reload]);

  async function persist(next: { integrations: Integration[]; model_map: Record<string, string> }) {
    setBusy(true); setErr('');
    try {
      const r = await harnessFetch('/api/harness/v1/admin/integrations', {
        method: 'PUT', headers: authHeaders(), body: JSON.stringify(next),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `${r.status}`);
      setDoc({ ...(doc as Doc), ...(await r.json()) });
      setNotice('Saved.');
      setTimeout(() => setNotice(''), 2500);
      return true;
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'save failed');
      return false;
    } finally { setBusy(false); }
  }

  // All canonical model names across integrations, the option set for the mapping rows.
  const allCanonicals = useMemo(() => {
    const s = new Set<string>();
    (doc?.integrations || []).forEach((i) => i.models.forEach((m) => s.add(m.canonical)));
    return [...s].sort();
  }, [doc]);

  if (!allowed) {
    return (
      <section className="view is-active"><div className="page">
        <div className="session-empty">This page is not available for your organization.</div>
      </div></section>
    );
  }

  return (
    <section className="view is-active" id="view-integrations">
      <div className="page">
        <div className="page-header">
          <div>
            <button className="back-link" type="button" onClick={() => router.push('/keys')}>
              <iconify-icon icon="tabler:arrow-left"></iconify-icon><span>API Keys</span></button>
            <h1>Integrations</h1>
            <p>Connect model providers and choose which one serves each model, applies to every Harness.</p>
          </div>
          <button className="button primary" type="button"
            onClick={() => { setEditing({ name: '', provider: 'openrouter', config: {}, models: [] }); setEditingOriginal(null); }}>
            <iconify-icon icon="tabler:plus"></iconify-icon>Add Integration</button>
        </div>

        {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Something went wrong</strong>{err}</div></div>}
        {notice && <div className="itg-saved"><iconify-icon icon="tabler:check"></iconify-icon>{notice}</div>}

        {!doc ? <SkelRows rows={4} /> : (
          <>
            <div className="table-wrap">
              <table className="itg-table">
                <thead><tr><th>Name</th><th>Provider</th><th className="itg-desktop-col">Supported models</th><th aria-label="Actions"></th></tr></thead>
                <tbody>
                  {doc.integrations.length === 0 && (
                    <tr><td colSpan={4}><div className="session-empty">No integrations yet, add your first provider.</div></td></tr>
                  )}
                  {doc.integrations.map((i) => (
                    <tr key={i.name} className="object-row" style={{ cursor: 'pointer' }}
                      onClick={() => { setEditing(JSON.parse(JSON.stringify(i))); setEditingOriginal(i.name); }}>
                      <td><strong>{i.name}</strong></td>
                      <td>{PROVIDER_LABEL[i.provider] || i.provider}</td>
                      <td className="itg-desktop-col"><span className="itg-models">{i.models.map((m) => m.canonical).join(', ') || '—'}</span></td>
                      <td className="itg-row-actions">
                        <button className="button danger-ghost" type="button" disabled={busy}
                          onClick={(e) => { e.stopPropagation(); setConfirmDelete(i.name); }}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="itg-section-head">
              <div><h2>Model, Integration Mapping</h2>
                <p>When a Harness runs a model, this decides which integration serves it. Unmapped models use the built-in provider routing.</p></div>
            </div>
            <div className="table-wrap">
              <table className="itg-table itg-map-table">
                <thead><tr><th>Model</th><th>Integration</th><th aria-label="Actions"></th></tr></thead>
                <tbody>
                  {Object.entries(doc.model_map).map(([model, iname]) => (
                    <tr key={model}>
                      <td>
                        <select className="select" value={model} disabled={busy}
                          onChange={(e) => {
                            const next = { ...doc.model_map };
                            delete next[model];
                            next[e.target.value] = iname;
                            void persist({ integrations: doc.integrations, model_map: next });
                          }}>
                          {[model, ...allCanonicals.filter((c) => c !== model && !(c in doc.model_map))].map((c) => (
                            <option key={c} value={c}>{c}</option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <select className="select" value={iname} disabled={busy}
                          onChange={(e) => void persist({
                            integrations: doc.integrations,
                            model_map: { ...doc.model_map, [model]: e.target.value },
                          })}>
                          {doc.integrations.filter((i) => i.models.some((m) => m.canonical === model)).map((i) => (
                            <option key={i.name} value={i.name}>{i.name}</option>
                          ))}
                          {!doc.integrations.some((i) => i.name === iname) && <option value={iname}>{iname}</option>}
                        </select>
                      </td>
                      <td className="itg-row-actions">
                        <button className="button danger-ghost" type="button" disabled={busy}
                          onClick={() => {
                            const next = { ...doc.model_map };
                            delete next[model];
                            void persist({ integrations: doc.integrations, model_map: next });
                          }}>Delete</button>
                      </td>
                    </tr>
                  ))}
                  <tr><td colSpan={3}>
                    <AddMappingRow doc={doc} allCanonicals={allCanonicals} busy={busy}
                      onAdd={(model, iname) => void persist({
                        integrations: doc.integrations,
                        model_map: { ...doc.model_map, [model]: iname },
                      })} />
                  </td></tr>
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {editing && doc && (
        <div className="modal-backdrop">
          <section className="modal itg-panel" role="dialog" aria-modal="true" aria-labelledby="itgTitle" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div><h2 id="itgTitle">{editingOriginal ? 'Edit Integration' : 'Add Integration'}</h2>
                <p>A provider connection plus the models it serves.</p></div>
              <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={() => setEditing(null)}><iconify-icon icon="tabler:x"></iconify-icon></button>
            </div>
            <div className="modal-body">
              <div className="field-stack">
                <div className="field"><label htmlFor="itgName">Name</label>
                  <input id="itgName" value={editing.name} placeholder="OpenRouter production"
                    onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></div>
                <div className="field"><label>Provider</label>
                  <div className="itg-provider-list">
                    {(doc.providers.length ? doc.providers : Object.keys(PROVIDER_FIELDS)).map((p) => (
                      <button key={p} type="button"
                        className={'itg-provider' + (editing.provider === p ? ' on' : '')}
                        disabled={Boolean(editingOriginal)}
                        onClick={() => setEditing({ ...editing, provider: p, config: {} })}>
                        {PROVIDER_LABEL[p] || p}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="field"><label>Configs</label>
                  <div className="field-stack">
                    {(PROVIDER_FIELDS[editing.provider] || []).map((f) => (
                      <div className="field" key={f.key}>
                        <label htmlFor={`itg-${f.key}`} className="itg-sublabel">{f.label}</label>
                        <input id={`itg-${f.key}`} type={f.secret ? 'password' : 'text'}
                          value={editing.config[f.key] || ''} placeholder={f.secret && editing.config[f.key] === SECRET ? '•••••••• (saved)' : f.placeholder || ''}
                          onChange={(e) => setEditing({ ...editing, config: { ...editing.config, [f.key]: e.target.value } })} />
                      </div>
                    ))}
                  </div>
                </div>
                <div className="field"><label>Supported models</label>
                  <p className="field-help">Canonical name (what users pick) → this provider&rsquo;s model id (what the API call uses).</p>
                  <div className="itg-modelgrid">
                    {editing.models.map((m, idx) => (
                      <div className="itg-modelrow" key={idx}>
                        <input value={m.canonical} placeholder="claude-opus-4.8" aria-label="Canonical model name"
                          onChange={(e) => setEditing({ ...editing, models: editing.models.map((x, k) => k === idx ? { ...x, canonical: e.target.value } : x) })} />
                        <span className="itg-arrow">→</span>
                        <input value={m.provider_id} placeholder="anthropic/claude-opus-4.8" aria-label="Provider model id"
                          onChange={(e) => setEditing({ ...editing, models: editing.models.map((x, k) => k === idx ? { ...x, provider_id: e.target.value } : x) })} />
                        <button className="icon-button" type="button" aria-label="Remove model"
                          onClick={() => setEditing({ ...editing, models: editing.models.filter((_, k) => k !== idx) })}>
                          <iconify-icon icon="tabler:x"></iconify-icon></button>
                      </div>
                    ))}
                    <button className="button" type="button"
                      onClick={() => setEditing({ ...editing, models: [...editing.models, { canonical: '', provider_id: '' }] })}>
                      <iconify-icon icon="tabler:plus"></iconify-icon>Add model</button>
                  </div>
                </div>
              </div>
              <div className="modal-actions">
                <button className="button" type="button" onClick={() => setEditing(null)} disabled={busy}>Cancel</button>
                <button className="button primary" type="button" disabled={busy || !editing.name.trim()}
                  onClick={async () => {
                    const rest = doc.integrations.filter((i) => i.name !== (editingOriginal ?? editing.name));
                    // renames retarget the mapping rows that pointed at the old name
                    const mm = Object.fromEntries(Object.entries(doc.model_map).map(([k, v]) =>
                      [k, v === editingOriginal ? editing.name.trim() : v]));
                    if (await persist({ integrations: [...rest, { ...editing, name: editing.name.trim() }], model_map: mm })) setEditing(null);
                  }}>{busy ? 'Saving…' : editingOriginal ? 'Save' : 'Create'}</button>
              </div>
            </div>
          </section>
        </div>
      )}

      {confirmDelete && doc && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header"><div><h2>Delete integration</h2>
              <p>&ldquo;{confirmDelete}&rdquo; and any model mappings pointing at it will be removed. Models fall back to the built-in provider routing.</p></div></div>
            <div className="modal-actions" style={{ padding: '0 22px 20px' }}>
              <button className="button" type="button" onClick={() => setConfirmDelete(null)} disabled={busy}>Cancel</button>
              <button className="button danger" type="button" disabled={busy}
                onClick={async () => {
                  const mm = Object.fromEntries(Object.entries(doc.model_map).filter(([, v]) => v !== confirmDelete));
                  if (await persist({ integrations: doc.integrations.filter((i) => i.name !== confirmDelete), model_map: mm })) setConfirmDelete(null);
                }}>{busy ? 'Deleting…' : 'Delete'}</button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

function AddMappingRow({ doc, allCanonicals, busy, onAdd }: {
  doc: Doc; allCanonicals: string[]; busy: boolean; onAdd: (model: string, iname: string) => void;
}) {
  const unmapped = allCanonicals.filter((c) => !(c in doc.model_map));
  const [model, setModel] = useState('');
  const [iname, setIname] = useState('');
  const eligible = doc.integrations.filter((i) => i.models.some((m) => m.canonical === model));
  return (
    <div className="itg-addmap">
      <select className="select" value={model} disabled={busy} aria-label="Model to map"
        onChange={(e) => { setModel(e.target.value); setIname(''); }}>
        <option value="">Choose a model…</option>
        {unmapped.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <select className="select" value={iname} disabled={busy || !model} aria-label="Integration to serve it"
        onChange={(e) => setIname(e.target.value)}>
        <option value="">Choose an integration…</option>
        {eligible.map((i) => <option key={i.name} value={i.name}>{i.name}</option>)}
      </select>
      <button className="button" type="button" disabled={busy || !model || !iname}
        onClick={() => { onAdd(model, iname); setModel(''); setIname(''); }}>
        <iconify-icon icon="tabler:plus"></iconify-icon>Add Mapping</button>
    </div>
  );
}
