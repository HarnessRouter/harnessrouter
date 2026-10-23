'use client';
// The form that adds a connection to a provider, or edits one, inside the provider's row (the design's
// pv-form). What it asks is the server's catalog for that provider (byok/doc.ts CatalogEntry): its
// fields, its secret, and, where the provider offers it, signing in as an application in the
// operator's own Microsoft Entra directory. A provider whose endpoint the server knows asks nothing
// about it; the endpoint is shown. A stored secret never comes back: left blank, it is kept.
//
// A custom endpoint (OpenAI or Anthropic compatible) also asks its API format, whether its address
// is the full request URL, and, for the Responses format, which built-in tools it accepts; and it
// lists its own models: the id a harness asks for and the name the endpoint wants on the wire. Any
// other provider serves the models the catalog lists, and a model newer than this release is one row
// away (its id and its name on the wire).
import { useRef, useState } from 'react';
import { OOB } from '@/lib/harness';
import { toast } from '../toast';
import { HOSTED, SECRET, isEntra, nameFor, type CatalogEntry, type Doc, type Integration, type ModelRow, type ProviderField } from './doc';

const X = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>;
const FORMATS: [string, string][] = [['openai', 'OpenAI Chat Completions'], ['responses', 'OpenAI Responses'], ['anthropic', 'Anthropic Messages']];
const WIRE: Record<string, string> = { openai: '/chat/completions', responses: '/responses', anthropic: '/v1/messages' };
const on = (v?: string) => v === '1' || v === 'true';

/** The harnesses' names as the console shows them everywhere else ("Claude Code", not the server's
 *  `claude`); an id the console does not know is shown as it is. */
export function baseNames(backends: string[]): string[] {
  const names = new Map(OOB.filter((h) => h.backend).map((h) => [h.backend as string, h.name]));
  return [...new Set(backends.map((b) => names.get(b) || b))].sort((a, b) => a.localeCompare(b));
}

function Seg<T extends string>({ label, value, options, onChange, id }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void; id?: string }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label} id={id}>
      {options.map(([v, t]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} className={value === v ? 'on' : ''} onClick={() => onChange(v)}>{t}</button>
      ))}
    </div>
  );
}

export function KeyForm({ meta, name: provName, doc, editing, busy, onCancel, onSubmit }: {
  meta: CatalogEntry; name: string; doc: Doc; editing?: Integration; busy: boolean;
  onCancel: () => void;
  /** saves the connection; `detail` is the server's reason when it refused */
  onSubmit: (entry: Integration) => Promise<{ ok: true } | { ok: false; detail: string }>;
}) {
  const custom = meta.id === 'custom';
  const [cfg, setCfg] = useState<Record<string, string>>(() => {
    const c = { ...(editing?.config || {}) };
    if (custom && !c.api_format) c.api_format = 'openai';
    return c;
  });
  const table = new Map((meta.models || []).map((m) => [m.canonical, m.provider_id]));
  // a custom endpoint's rows are its whole list; any other provider's rows are what differs from its
  // catalog: a model beyond it, or a listed one sent under another name
  const [rows, setRows] = useState<ModelRow[]>(() => (editing?.models || []).filter((m) => custom || table.get(m.canonical) !== m.provider_id));
  const [label, setLabel] = useState('');
  const [how, setHow] = useState<'key' | 'entra'>(editing && isEntra(editing) ? 'entra' : 'key');
  const [refused, setRefused] = useState('');
  const first = useRef<HTMLInputElement | null>(null);
  const id = (f: string) => `pk-${meta.id}-${f}`;
  const name = editing ? editing.name : nameFor(doc, meta.id, label);
  const entra = !!meta.entra && how === 'entra';
  const secretKey = entra && meta.entra ? meta.entra.secret : meta.secret;
  const fields: ProviderField[] = entra && meta.entra
    ? [...meta.fields, ...meta.entra.fields, { key: meta.entra.secret, label: meta.entra.secret_label }]
    : [...meta.fields, { key: meta.secret, label: meta.secret_label, placeholder: meta.key_hint }];
  const saved = (k: string) => editing?.config?.[k] === SECRET;
  const set = (k: string, v: string) => { setCfg((c) => ({ ...c, [k]: v })); setRefused(''); };
  const fmt = cfg.api_format || 'openai';

  async function save() {
    if (busy) return;
    setRefused('');
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(cfg)) if (v != null && String(v).trim() !== '') out[k] = String(v).trim();
    if (entra) out.auth = 'entra'; else delete out.auth;
    // a stored secret left blank is kept: it goes back as the sentinel
    if (saved(secretKey) && !out[secretKey]) out[secretKey] = SECRET;
    if (!custom && !entra && !out[secretKey]) { toast(`Paste your ${provName} ${meta.secret_label}.`); first.current?.focus(); return; }
    if (entra && meta.entra && [...meta.entra.fields.map((f) => f.key), meta.entra.secret].some((k) => !out[k])) { toast('Fill in every Microsoft Entra field.'); return; }
    if (custom && !out.base_url) { toast('Add the endpoint’s base URL.'); return; }
    const own = rows.map((m) => ({ ...m, canonical: m.canonical.trim() || (custom ? m.provider_id.trim() : ''), provider_id: m.provider_id.trim() }))
      .filter((m) => m.canonical);
    if (custom && !own.length) { toast('Add the models this endpoint serves.'); return; }
    const models = custom ? own : [...(meta.models || []).filter((m) => !own.some((o) => o.canonical === m.canonical)), ...own];
    const res = await onSubmit({ name, provider: meta.id, config: out, models });
    if (!res.ok) {
      // the server's reason, without its own prefix ("integration 'name': "); never the secret
      if (res.detail) { const why = res.detail.replace(/^integration '[^']*':\s*/, ''); setRefused(why.charAt(0).toUpperCase() + why.slice(1)); }
      else toast(`Your ${provName} connection could not be saved. Check it and try again.`);
    }
  }
  const enter = (e: React.KeyboardEvent) => { if (e.key === 'Enter') { e.preventDefault(); void save(); } };

  const field = (f: ProviderField) => {
    const secret = f.key === secretKey;
    if (custom && f.key === 'api_format') {
      return (
        <div className="set-f" key={f.key}>
          <label htmlFor={id(f.key)}>{f.label}</label>
          <select id={id(f.key)} className="set-in" value={fmt} onChange={(e) => set(f.key, e.target.value)}>
            {FORMATS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select>
          <p className="set-help">The API your endpoint accepts. The harnesses it can drive are listed under its models.</p>
        </div>
      );
    }
    if (custom && f.key === 'full_url') {
      return (
        <div className="set-f" key={f.key}>
          <label id={id(f.key)}>{f.label}</label>
          <Seg label={f.label} value={on(cfg[f.key]) ? '1' : ''} onChange={(v) => set(f.key, v)} options={[['', `Append ${WIRE[fmt]}`], ['1', 'Use as it is']]} />
        </div>
      );
    }
    if (custom && (f.key === 'namespace_tools' || f.key === 'web_search')) {
      if (fmt !== 'responses') return null;
      const t = f.key === 'namespace_tools' ? 'Codex namespace tools' : 'Codex web search';
      return (
        <div className="set-f" key={f.key}>
          <label id={id(f.key)}>{t}</label>
          <Seg label={t} value={on(cfg[f.key]) ? '1' : ''} onChange={(v) => set(f.key, v)} options={[['', 'Off'], ['1', 'On']]} />
          <p className="set-help">{f.key === 'namespace_tools' ? 'Off unless your endpoint accepts more than function tools.' : 'Off unless your endpoint accepts Codex web search.'}</p>
        </div>
      );
    }
    let ph = f.placeholder || '';
    if (custom && f.key === 'base_url') ph = on(cfg.full_url) ? 'The full request URL, path included' : `The endpoint, without a trailing slash; ${WIRE[fmt]} is appended`;
    if (secret && saved(f.key)) ph = 'Saved. Leave blank to keep it.';
    return (
      <div className="set-f" key={f.key}>
        <label htmlFor={id(f.key)}>{f.label}</label>
        <input id={id(f.key)} ref={secret ? first : undefined} className={`set-in${secret || /url/i.test(f.key) ? ' mono' : ''}`}
          type={secret ? 'password' : 'text'} autoComplete="off" spellCheck={false} placeholder={ph}
          value={secret && saved(f.key) && cfg[f.key] === SECRET ? '' : cfg[f.key] || ''} onChange={(e) => set(f.key, e.target.value)} onKeyDown={enter} />
      </div>
    );
  };

  const rowsBox = (help: string) => (
    <>
      {custom ? (
        <datalist id="custom-model-ids">{(meta.canonicals || []).map((c) => <option key={c} value={c} />)}</datalist>
      ) : null}
      {rows.map((r, i) => (
        <div className="keyrow pv-mrow" key={i}>
          <input type="text" className="keyname mono" list={custom ? 'custom-model-ids' : undefined} aria-label="Model" placeholder="Model id" value={r.canonical}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, canonical: e.target.value } : x)))} />
          <input type="text" className="keyname mono" aria-label="Name on the wire" placeholder={r.canonical || 'Same as the model id'}
            value={r.provider_id === r.canonical ? '' : r.provider_id}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, provider_id: e.target.value } : x)))} />
          <button type="button" className="icon-btn" aria-label="Remove model" onClick={() => setRows(rows.filter((_, j) => j !== i))}>{X}</button>
        </div>
      ))}
      <p className="set-help">{help}</p>
      <div><button type="button" className="btn small line" onClick={() => setRows([...rows, { canonical: '', provider_id: '' }])}>Add model</button></div>
    </>
  );

  const list = meta.models || [];
  return (
    <div className="pv-form ship-sheet">
      {meta.entra ? (
        <div className="set-f pv-how">
          <label id={id('how')}>Signs in with</label>
          <Seg label="Signs in with" value={how} onChange={(v) => { setHow(v); setRefused(''); }} options={[['key', 'API key'], ['entra', 'Microsoft Entra']]} />
          {entra ? <p className="set-help">Tasks sign in to Microsoft Entra as this application. Give the application a role on your Azure resource.</p> : null}
        </div>
      ) : null}
      {editing ? null : (
        <div className="set-f">
          <label htmlFor={id('label')}>Name <span className="muted">optional</span></label>
          <input id={id('label')} className="set-in" autoComplete="off" placeholder={nameFor(doc, meta.id, '')} value={label} onChange={(e) => setLabel(e.target.value)} onKeyDown={enter} />
          <p className="set-help">How this connection is named in your list and in which key serves each model.</p>
        </div>
      )}
      {fields.map(field)}
      {meta.base_url ? <p className="set-help">Endpoint: <code>{cfg.base_url || meta.base_url}</code></p> : null}
      <div className="set-f">
        <label>{custom ? 'Models' : 'Models it serves'}</label>
        {custom ? rowsBox(`Each model a harness picks, and the name this endpoint wants for it (blank: the model id as it is). Compatible harnesses: ${meta.format_backends?.[fmt]?.length ? baseNames(meta.format_backends[fmt]).join(', ') + '.' : 'not known for this format.'}`)
          : list.length ? (
            <>
              <details className="hk-more">
                <summary>{list.length} model{list.length === 1 ? '' : 's'}: {list.slice(0, 4).map((m) => m.canonical).join(', ')}{list.length > 4 ? ` and ${list.length - 4} more` : ''}</summary>
                <p className="set-help mono">{list.map((m) => m.canonical).join(', ')}</p>
              </details>
              {rowsBox('A model newer than this release: add it with the id the provider uses on the wire, and it shows in every model list this provider serves.')}
            </>
          ) : <p className="set-help">{meta.id === HOSTED ? 'The list of models arrives with your key.' : 'No models are listed for this provider yet.'}</p>}
      </div>
      {refused ? <div className="keywarn" role="alert">{refused}</div> : null}
      <div className="sheet-actions">
        <button type="button" className="btn primary" disabled={busy} onClick={() => void save()}>{busy ? 'Saving' : editing ? 'Save' : 'Create'}</button>
        <button type="button" className="btn" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
