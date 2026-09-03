'use client';
// Integrations — bring your own provider keys.
//
// An integration is a provider connection plus the models it serves; the mapping below decides
// which integration serves each model when a harness runs it.
//
// The form is driven by the SERVER's provider catalog, not by a copy of it here. That catalog
// knows each vendor's endpoint and the models it can address, so adding an integration asks for
// a key and nothing else: a base URL we can look up is not a question worth asking, and a model
// id the user has to transcribe is a support ticket waiting to happen. Both would also rot here
// the moment the gateway learns a new model.
//
// Server: GET/PUT /v1/admin/integrations (secrets sentinel'd, never round-tripped).
import { harnessFetch } from '@/lib/hfetch';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { SkelRows } from '@/components/Skel';
import { getSession } from '@/lib/auth';
import { authHeaders } from '@/lib/chat';
import { PLATFORM_ADMIN_ORGS, SELF_HOSTED } from '@/lib/edition';

interface ModelRow { canonical: string; provider_id: string }
interface Integration {
  name: string; provider: string; config: Record<string, string>;
  models: ModelRow[];
  /** Image models this integration can serve. Separate from `models`: an image model offered in
   *  a chat picker is a choice that cannot work. */
  image_models?: ModelRow[];
}
interface ProviderField { key: string; label: string; placeholder?: string }
interface ProviderMeta {
  id: string;
  label: string;
  /** Known endpoint, applied server-side. null means it genuinely varies, so `fields` asks. */
  base_url: string | null;
  fields: ProviderField[];
  secret: string;
  secret_label: string;
  key_hint?: string;
  models: ModelRow[];
  backends: string[];
}
interface Doc {
  integrations: Integration[];
  model_map: Record<string, string>;
  /** Images route separately from chat: the integration serving your chat models is usually not
   *  the one serving images, and an image model in a chat picker is a broken choice. */
  image_model_map?: Record<string, string>;
  providers: string[];
  catalog: ProviderMeta[];
  /** Video, speech and music are NOT routed by a model map. They are routed by an ordered chain
   *  per capability, and the first candidate whose provider is connected wins. */
  media_chains?: MediaChain[];
  media_policy?: Record<string, { order?: string[]; disabled?: string[] }>;
}
interface MediaCandidate {
  model: string;
  provider: string;
  connected: boolean;
  off: boolean;
  resolution?: string;
  seconds?: number | null;
  duration_ignored?: boolean;
  accepts_input_image?: boolean | null;
  usd?: number | null;
  verification?: string;
  /** The clause the chain would use if this one were asked for right now. */
  unavailable?: string;
}
interface MediaChain { capability: string; unit: string; candidates: MediaCandidate[] }

const SECRET = '__secret__';

export default function IntegrationsPage() {
  const router = useRouter();
  const org = getSession()?.orgId || '';
  // Self-hosted is single-tenant: the operator owns the box and the keys, so there is nobody
  // to withhold this from. The gateway makes the same call server-side.
  const allowed = SELF_HOSTED || PLATFORM_ADMIN_ORGS.includes(org);
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

  async function persist(next: { integrations: Integration[]; model_map: Record<string, string>;
                                 image_model_map?: Record<string, string>;
                                 media_policy?: Record<string, { order?: string[]; disabled?: string[] }> }) {
    // Always send every map. The write replaces the whole document, so posting one of them alone
    // would silently clear the others.
    const body = { image_model_map: doc?.image_model_map || {},
                   media_policy: doc?.media_policy || {}, ...next };
    setBusy(true); setErr('');
    try {
      const r = await harnessFetch('/api/harness/v1/admin/integrations', {
        method: 'PUT', headers: authHeaders(), body: JSON.stringify(body),
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

  const catalog = useMemo(() => doc?.catalog || [], [doc]);
  const metaFor = useCallback(
    (id: string) => catalog.find((c) => c.id === id), [catalog]);
  const labelFor = useCallback(
    (id: string) => metaFor(id)?.label || id, [metaFor]);

  // All canonical model names across integrations, the option set for the mapping rows.
  const allCanonicals = useMemo(() => {
    const s = new Set<string>();
    (doc?.integrations || []).forEach((i) => i.models.forEach((m) => s.add(m.canonical)));
    return [...s].sort();
  }, [doc]);
  const allImageCanonicals = useMemo(() => {
    const s = new Set<string>();
    (doc?.integrations || []).forEach((i) => (i.image_models || []).forEach((m) => s.add(m.canonical)));
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
              <iconify-icon icon="tabler:arrow-left"></iconify-icon><span>API keys</span></button>
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
                      <td>{labelFor(i.provider)}</td>
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

            <MappingTable
              title="Model, Integration Mapping"
              blurb={<>When a Harness runs a model, this decides which integration serves it.{' '}
                {SELF_HOSTED
                  ? 'A model with no integration has no provider, so it can\u2019t be selected.'
                  : 'Unmapped models use the built-in provider routing.'}</>}
              map={doc.model_map}
              allCanonicals={allCanonicals}
              servedBy={(i, model) => i.models.some((m) => m.canonical === model)}
              busy={busy} integrations={doc.integrations}
              onChange={(next) => void persist({ integrations: doc.integrations, model_map: next })}
              emptyHint="" />

            <MappingTable
              title="Image Model, Integration Mapping"
              blurb={<>Which integration generates images. Routed separately from chat because it is
                usually a different provider, and an Anthropic connection has no image API at all.{' '}
                An image model with no integration means a Harness cannot generate images.</>}
              map={doc.image_model_map || {}}
              allCanonicals={allImageCanonicals}
              servedBy={(i, model) => (i.image_models || []).some((m) => m.canonical === model)}
              busy={busy} integrations={doc.integrations}
              onChange={(next) => void persist({ integrations: doc.integrations,
                                                 model_map: doc.model_map, image_model_map: next })}
              emptyHint="None of your integrations serve an image model." />

            {/* Video, speech and music. NOT a map: a chain, in order, with the measurements that
                justify the order. Flattening it to one row per model would throw away both the
                ranking and the facts, which are the two things that make a fallback safe. */}
            {(doc.media_chains || []).filter((c) => c.candidates.length > 0).map((chain) => (
              <MediaChainTable
                key={chain.capability}
                chain={chain}
                busy={busy}
                policy={doc.media_policy || {}}
                onChange={(next) => void persist({ integrations: doc.integrations,
                                                   model_map: doc.model_map,
                                                   image_model_map: doc.image_model_map || {},
                                                   media_policy: next })}
              />
            ))}

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
                    {catalog.map((c) => (
                      <button key={c.id} type="button"
                        className={'itg-provider' + (editing.provider === c.id ? ' on' : '')}
                        disabled={Boolean(editingOriginal)}
                        onClick={() => setEditing({ ...editing, provider: c.id, config: c.id === 'custom' ? { api_format: 'openai' } : {} })}>
                        {c.label}
                      </button>
                    ))}
                  </div>
                </div>
                {(() => {
                  const meta = metaFor(editing.provider);
                  if (!meta) return null;
                  const isCustom = editing.provider === 'custom';
                  // Only what varies by deployment. A provider with a known endpoint never
                  // shows a Base URL field — the server fills it in.
                  const fields = [...meta.fields,
                                  { key: meta.secret, label: meta.secret_label,
                                    placeholder: meta.key_hint }];
                  return (
                    <div className="field-stack">
                      {fields.map((f) => {
                        const secret = f.key === meta.secret;
                        const saved = secret && editing.config[f.key] === SECRET;
                        // Special rendering for custom provider fields
                        if (isCustom && f.key === 'api_format') {
                          return (
                            <div className="field" key={f.key}>
                              <label htmlFor={`itg-${f.key}`}>{f.label}</label>
                              <select id={`itg-${f.key}`} className="select"
                                value={editing.config[f.key] || ''}
                                onChange={(e) => setEditing({
                                  ...editing,
                                  config: { ...editing.config, [f.key]: e.target.value },
                                })}>
                                <option value="openai">OpenAI Chat Completions</option>
                                <option value="anthropic">Anthropic Messages</option>
                              </select>
                              <p className="field-help">
                                {editing.config['api_format'] === 'anthropic'
                                  ? 'Anthropic Messages format works with Claude Code, OpenCode, Pi, and DSH backends.'
                                  : editing.config['api_format'] === 'openai'
                                  ? 'OpenAI Chat Completions format works with Hermes, OpenCode, Pi, and DSH backends. Codex and Claude Code cannot drive a custom OpenAI endpoint.'
                                  : 'If you use Claude Code, choose Anthropic Messages format.'}
                              </p>
                            </div>
                          );
                        }
                        if (isCustom && f.key === 'full_url') {
                          const fullUrlOn = editing.config[f.key] === '1' || editing.config[f.key] === 'true';
                          return (
                            <div className="field" key={f.key}>
                              <label>{f.label}</label>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                <button type="button" role="switch" aria-checked={fullUrlOn}
                                  className="toggle-button"
                                  onClick={() => setEditing({
                                    ...editing,
                                    config: { ...editing.config, [f.key]: fullUrlOn ? '' : '1' },
                                  })}
                                  style={{ minWidth: 44, minHeight: 26, padding: 0, borderRadius: 999,
                                    border: fullUrlOn ? '1px solid var(--accent)' : '1px solid var(--line)',
                                    background: fullUrlOn ? 'var(--accent)' : 'var(--surface-subtle)',
                                    cursor: 'pointer', position: 'relative', transition: 'background .15s' }}>
                                  <span style={{ display: 'block', width: 18, height: 18, borderRadius: 999,
                                    background: fullUrlOn ? '#fff' : 'var(--line)',
                                    position: 'absolute', top: 3, left: fullUrlOn ? 21 : 3,
                                    transition: 'left .15s' }} />
                                </button>
                                <span style={{ fontSize: 13, color: fullUrlOn ? 'var(--ink)' : 'var(--muted)' }}>
                                  {fullUrlOn ? 'On — the URL is used as-is' : 'Off — /chat/completions is appended'}
                                </span>
                              </div>
                            </div>
                          );
                        }
                        // Dynamic placeholder for base_url based on full_url toggle
                        let placeholder = f.placeholder || '';
                        if (isCustom && f.key === 'base_url') {
                          const fullUrl = editing.config['full_url'] === '1' || editing.config['full_url'] === 'true';
                          placeholder = fullUrl
                            ? 'Enter the full request URL, including the path. The request will use this URL directly.'
                            : 'Enter an OpenAI-compatible API endpoint, without a trailing slash. /chat/completions will be appended to your endpoint.';
                        }
                        return (
                          <div className="field" key={f.key}>
                            <label htmlFor={`itg-${f.key}`}>{f.label}</label>
                            <input id={`itg-${f.key}`} type={secret ? 'password' : 'text'}
                              value={saved ? '' : (editing.config[f.key] || '')}
                              placeholder={saved ? '•••••••• (saved, leave blank to keep)' : placeholder}
                              autoComplete="off"
                              onChange={(e) => setEditing({
                                ...editing,
                                config: { ...editing.config, [f.key]: e.target.value },
                              })} />
                          </div>
                        );
                      })}
                      {meta.base_url ? (
                        <p className="field-help">Endpoint: <code>{meta.base_url}</code></p>
                      ) : null}
                    </div>
                  );
                })()}
                {(() => {
                  const meta = metaFor(editing.provider);
                  const isCustom = editing.provider === 'custom';
                  const models = meta?.models || [];
                  if (isCustom) {
                    return (
                      <div className="field">
                        <label>Model</label>
                        <p className="field-help">
                          This integration serves the model ID you entered above. Add it in the
                          mapping table below after saving.
                        </p>
                      </div>
                    );
                  }
                  return (
                    <div className="field">
                      <label>Supported models</label>
                      <p className="field-help">
                        Maintained here, not by you: this integration serves the{' '}
                        <strong>{models.length}</strong> model{models.length === 1 ? '' : 's'} below, and
                        picks up new ones as they are added.
                      </p>
                      <details className="itg-modellist">
                        <summary>{models.map((m) => m.canonical).slice(0, 4).join(', ')}
                          {models.length > 4 ? ` and ${models.length - 4} more` : ''}</summary>
                        <ul>
                          {models.map((m) => <li key={m.canonical}>{m.canonical}</li>)}
                        </ul>
                      </details>
                    </div>
                  );
                })()}
              </div>
              <div className="modal-actions">
                <button className="button" type="button" onClick={() => setEditing(null)} disabled={busy}>Cancel</button>
                <button className="button primary" type="button" disabled={busy || !editing.name.trim()}
                  onClick={async () => {
                    const rest = doc.integrations.filter((i) => i.name !== (editingOriginal ?? editing.name));
                    // renames retarget the mapping rows that pointed at the old name
                    const mm = Object.fromEntries(Object.entries(doc.model_map).map(([k, v]) =>
                      [k, v === editingOriginal ? editing.name.trim() : v]));
                    if (await persist({
                      integrations: [...rest, { ...editing, name: editing.name.trim(), models: [] }],
                      model_map: mm,
                    })) setEditing(null);
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
                  // EVERY map that can name an integration has to be pruned here, not just the
                  // chat one. The server rejects the whole write if any mapping still points at a
                  // name that is gone, so leaving image_model_map behind made Delete fail with
                  // "image model 'gpt-image-1' maps to unknown integration 'Vercel'" and no way
                  // forward from the dialog. The copy above already promises this.
                  const drop = (m: Record<string, string> | undefined) =>
                    Object.fromEntries(Object.entries(m || {}).filter(([, v]) => v !== confirmDelete));
                  const mm = drop(doc.model_map);
                  const imm = drop(doc.image_model_map);
                  // media_policy names integrations inside per-model order/disabled lists. The
                  // server does not validate it, but leaving a deleted name there would resurrect
                  // it in the UI's ordering controls.
                  const mp = Object.fromEntries(Object.entries(doc.media_policy || {}).map(([k, v]) => [k, {
                    ...v,
                    order: (v?.order || []).filter((n) => n !== confirmDelete),
                    disabled: (v?.disabled || []).filter((n) => n !== confirmDelete),
                  }]));
                  if (await persist({ integrations: doc.integrations.filter((i) => i.name !== confirmDelete),
                                      model_map: mm, image_model_map: imm, media_policy: mp })) setConfirmDelete(null);
                }}>{busy ? 'Deleting…' : 'Delete'}</button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

/** One mapping table. Chat models and image models route independently but the mechanics are
 *  identical, and two copies of this would drift the moment either changed. */
function MappingTable({ title, blurb, map, allCanonicals, servedBy, integrations, busy, onChange, emptyHint }: {
  title: string; blurb: React.ReactNode; map: Record<string, string>; allCanonicals: string[];
  servedBy: (i: Integration, model: string) => boolean; integrations: Integration[]; busy: boolean;
  onChange: (next: Record<string, string>) => void; emptyHint: string;
}) {
  return (
    <>
      <div className="itg-section-head"><div><h2>{title}</h2><p>{blurb}</p></div></div>
      <div className="table-wrap">
        <table className="itg-table itg-map-table">
          <thead><tr><th>Model</th><th>Integration</th><th aria-label="Actions"></th></tr></thead>
          <tbody>
            {Object.entries(map).filter(([, iname]) => iname).map(([model, iname]) => (
              <tr key={model}>
                <td>
                  <select className="select" value={model} disabled={busy}
                    onChange={(e) => {
                      const next = { ...map };
                      // Renaming a row is not a delete: clear the old key outright rather than
                      // leaving an "off" marker that would suppress the model it moved away from.
                      delete next[model];
                      next[e.target.value] = iname;
                      onChange(next);
                    }}>
                    {[model, ...allCanonicals.filter((c) => c !== model && !(c in map))].map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <select className="select" value={iname} disabled={busy}
                    onChange={(e) => onChange({ ...map, [model]: e.target.value })}>
                    {integrations.filter((i) => servedBy(i, model)).map((i) => (
                      <option key={i.name} value={i.name}>{i.name}</option>
                    ))}
                    {!integrations.some((i) => i.name === iname) && <option value={iname}>{iname}</option>}
                  </select>
                </td>
                <td className="itg-row-actions">
                  {/* Writes an explicit "off" marker rather than dropping the key. The server
                      claims every model an integration can serve, so simply removing the row let
                      the claim put it straight back: the save returned 200 and the row reappeared,
                      which read as Delete being broken. An empty value is how "no integration
                      serves this" is said. */}
                  <button className="button danger-ghost" type="button" disabled={busy}
                    onClick={() => onChange({ ...map, [model]: '' })}>Delete</button>
                </td>
              </tr>
            ))}
            {Object.keys(map).length === 0 && allCanonicals.length === 0 && emptyHint && (
              <tr><td colSpan={3}><span className="hr-meta">{emptyHint}</span></td></tr>
            )}
            <tr><td colSpan={3}>
              <AddMappingRow map={map} allCanonicals={allCanonicals} integrations={integrations}
                servedBy={servedBy} busy={busy}
                onAdd={(model, iname) => onChange({ ...map, [model]: iname })} />
            </td></tr>
          </tbody>
        </table>
      </div>
    </>
  );
}

function AddMappingRow({ map, allCanonicals, integrations, servedBy, busy, onAdd }: {
  map: Record<string, string>; allCanonicals: string[]; integrations: Integration[];
  servedBy: (i: Integration, model: string) => boolean; busy: boolean;
  onAdd: (model: string, iname: string) => void;
}) {
  const unmapped = allCanonicals.filter((c) => !(c in map));
  const [model, setModel] = useState('');
  const [iname, setIname] = useState('');
  const eligible = integrations.filter((i) => servedBy(i, model));
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

/* ── one media capability's chain ────────────────────────────────────────────────────────────
   Order is the routing rule: the first candidate whose provider is connected and that can serve
   the request is the one that runs. So the control is Move up / Move down, not a dropdown — the
   list IS the policy, and showing it any other way would be showing something that is not what
   happens.

   Every measured fact travels with its row because those facts are the reason to prefer one over
   another. "Ignores the duration you ask for" is the difference between a 5-second shot and a
   6-second one, and nobody can weigh that from a model name. */
const CAP_TITLE: Record<string, string> = {
  text_to_video: 'Video, from text',
  image_to_video: 'Video, from an image',
  text_to_image: 'Images',
  image_to_image: 'Images, from an image',
  text_to_speech: 'Speech',
  text_to_music: 'Music',
  export: 'Film assembly',
};

function MediaChainTable({ chain, policy, busy, onChange }: {
  chain: MediaChain;
  policy: Record<string, { order?: string[]; disabled?: string[] }>;
  busy: boolean;
  onChange: (next: Record<string, { order?: string[]; disabled?: string[] }>) => void;
}) {
  const models = chain.candidates.map((c) => c.model);
  const cur = policy[chain.capability] || {};
  const off = new Set(cur.disabled || []);

  /** The order as it stands, with one model moved. Written whole: a preference that lists only
   *  the models somebody touched leaves the rest to the catalog, and the two disagree the moment
   *  the catalog changes. */
  const move = (from: number, to: number) => {
    if (to < 0 || to >= models.length) return;
    const next = [...models];
    const [row] = next.splice(from, 1);
    next.splice(to, 0, row);
    onChange({ ...policy, [chain.capability]: { order: next, disabled: [...off] } });
  };
  const toggle = (model: string) => {
    const d = new Set(off);
    if (d.has(model)) d.delete(model); else d.add(model);
    onChange({ ...policy, [chain.capability]: { order: models, disabled: [...d] } });
  };

  const facts = (c: MediaCandidate) => {
    const out: string[] = [];
    if (c.resolution) out.push(c.resolution);
    if (typeof c.seconds === 'number') out.push(`${c.seconds}s measured`);
    if (c.duration_ignored) out.push('ignores the duration you ask for');
    if (c.accepts_input_image === false) out.push('text only');
    if (typeof c.usd === 'number') out.push(`$${c.usd.toFixed(2)} a ${chain.unit || 'run'}`);
    return out;
  };

  return (
    <div className="itg-section">
      <div className="itg-section-head">
        <div>
          <h2>{CAP_TITLE[chain.capability] || chain.capability}</h2>
          <p>Tried in this order. The first one whose provider is connected, and that can do what
            was asked, is the one that runs.</p>
        </div>
      </div>
      {/* Wide on purpose (order, model, provider, blurb): on a phone the table scrolls inside
          its own wrap instead of running past the page edge, like the other tables here. */}
      <div className="table-wrap">
      <table className="table">
        <thead><tr><th>Order</th><th>Model</th><th>Provider</th><th>What it does</th><th /></tr></thead>
        <tbody>
          {chain.candidates.map((c, i) => (
            <tr key={c.model} className={c.off || !c.connected ? 'is-dim' : undefined}>
              <td>{i + 1}</td>
              <td>
                <span className="mono">{c.model}</span>
                {/* Never colour alone: the state is a word. */}
                {c.off && <span className="chip"> switched off</span>}
                {!c.off && !c.connected && <span className="chip"> no key</span>}
                {!c.off && c.connected && c.unavailable && <span className="chip"> unavailable</span>}
              </td>
              <td>{c.provider}</td>
              <td className="muted">{facts(c).join(' · ') || '—'}</td>
              <td className="right">
                <button className="button ghost" type="button" disabled={busy || i === 0}
                  onClick={() => move(i, i - 1)} aria-label={`Move ${c.model} up`}>Up</button>
                <button className="button ghost" type="button" disabled={busy || i === chain.candidates.length - 1}
                  onClick={() => move(i, i + 1)} aria-label={`Move ${c.model} down`}>Down</button>
                <button className="button ghost" type="button" disabled={busy}
                  onClick={() => toggle(c.model)}>{c.off ? 'Switch on' : 'Switch off'}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
