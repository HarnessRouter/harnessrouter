'use client';
// Plugins: services a workspace connects once (a browser, a GitHub repository, a Vercel project,
// an InsForge backend); each Harness then includes the ones it needs under Harness Settings.
// One catalog, every plugin a row of it: its state here, what it costs, how many Harnesses
// include it. Nothing on this page is a copy: the catalog, the tool counts and the price come
// from the server that serves and charges them.
import { useCallback, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { SkelRows } from '@/components/Skel';
import { listPlugs, setPlug, plugAttachments, microsoftStart, microsoftComplete, microsoftSignout, type Plug } from '@/lib/harness';

/** Each service by its own mark (public/plugs): the GitHub and Vercel glyphs, Microsoft 365's logo,
 *  InsForge's app icon (drawn full-bleed, it carries its own ground), our browser glyph. A type
 *  without one shows a plug. */
const MARK: Record<string, { src: string; app?: boolean }> = {
  github: { src: '/plugs/github.svg' }, vercel: { src: '/plugs/vercel.svg' }, microsoft365: { src: '/plugs/microsoft365.svg' },
  insforge: { src: '/plugs/insforge.png', app: true }, browser: { src: '/plugs/browser.svg' },
};
const BLURB: Record<string, string> = {
  browser: 'A real web browser the agent can open, read, click through and screenshot.',
  github: 'The repository this workspace connects: files, branches and pull requests.',
  vercel: 'The project this workspace connects: deployments and domains.',
  insforge: 'The backend this workspace connects: its tables and records.',
  microsoft365: 'Your own SharePoint, OneDrive, Outlook and directory, read as each signed-in person through your organization\u2019s Microsoft Entra application, or as the application itself.',
};
const FIELD_LABEL: Record<string, string> = {
  allow_domains: 'Only these sites', deny_domains: 'Never these sites', token: 'Access token', api_key: 'API key',
  repo: 'Repository (owner/name)', owner: 'Owner', default_branch: 'Default branch', project: 'Project', project_id: 'Project id',
  team_id: 'Team id', url: 'Address', region: 'Region',
  tenant_id: 'Directory (tenant) id', client_id: 'Application (client) id', client_secret: 'Client secret', mode: 'Identity',
};
const PLACEHOLDER: Record<string, string> = { tenant_id: 'e89476d8-\u2026', client_id: 'the application (client) id from the app registration' };
/** A Microsoft 365 plug runs as each signed-in person unless it was connected as the application. */
const delegated = (p: Plug) => p.type === 'microsoft365' && String(p.config.mode || 'delegated') === 'delegated';
const accountsOf = (p: Plug) => (p.config.accounts || {}) as Record<string, { upn?: string; name?: string; signed_in_at?: string }>;
const STATUS_LABEL: Record<Plug['status'], string> = { connected: 'Connected', disabled: 'Disabled', needs_auth: 'Needs auth', missing: 'Not connected' };
const listOf = (v: unknown) => (Array.isArray(v) ? v.map(String).join(', ') : '');
const domainsOf = (text: string) => text.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean);

export default function PluginsPage() {
  const router = useRouter();
  const [plugs, setPlugs] = useState<Plug[] | null>(null);
  const [counts, setCounts] = useState<Record<string, { attached: number; harnesses: number }>>({});
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [editing, setEditing] = useState<Plug | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const params = useSearchParams();

  const reload = useCallback(async () => {
    try {
      const d = await listPlugs();
      setPlugs(d.plugs);
      const c: Record<string, { attached: number; harnesses: number }> = {};
      for (const p of d.plugs) {
        if (p.status === 'missing') continue;
        try { const a = await plugAttachments(p.type); c[p.type] = { attached: a.attached, harnesses: a.harnesses }; } catch { /* the line stays off */ }
      }
      setCounts(c);
    } catch (e) { setErr(e instanceof Error ? e.message : 'The plugins could not be read.'); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);
  // back from Microsoft's sign-in: the query carries the code and our state; the console finishes it
  useEffect(() => {
    const code = params.get('code'); const state = params.get('state');
    const denied = params.get('error_description') || params.get('error');
    if (denied && state) { setErr(`Microsoft did not complete the sign-in: ${denied}`); router.replace('/plugins'); return; }
    if (!code || !state) return;
    void (async () => {
      setBusy('microsoft365');
      try { await microsoftComplete(code, state); await reload(); }
      catch (e) { setErr(e instanceof Error ? e.message : 'The sign-in did not finish. Try again.'); }
      finally { setBusy(''); router.replace('/plugins'); }
    })();
  }, [params, reload, router]);
  const signIn = async () => {
    setBusy('microsoft365'); setErr('');
    try { const { auth_url } = await microsoftStart(`${window.location.origin}/plugins`); window.location.assign(auth_url); }
    catch (e) { setErr(e instanceof Error ? e.message : 'Microsoft could not be reached. Try again.'); setBusy(''); }
  };
  const signOut = async () => {
    setBusy('microsoft365'); setErr('');
    try { await microsoftSignout(); setEditing(null); await reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : 'The sign-out did not finish. Try again.'); }
    finally { setBusy(''); }
  };

  const open = (p: Plug) => {
    const f: Record<string, string> = {};
    for (const k of p.config_fields) f[k] = p.type === 'browser' ? listOf(p.config[k]) : String(p.config[k] ?? '');
    for (const k of p.secrets_needed) f[k] = '';
    setForm(f); setEditing(p);
  };
  const save = async (p: Plug, enabled: boolean, withForm: boolean) => {
    setBusy(p.type); setErr('');
    try {
      const body: { enabled: boolean; config?: Record<string, unknown>; secrets?: Record<string, string> } = { enabled };
      if (withForm) {
        body.config = Object.fromEntries(p.config_fields.map((k) => [k, p.type === 'browser' ? domainsOf(form[k] || '') : (form[k] || '')]));
        const secrets = Object.fromEntries(p.secrets_needed.filter((k) => (form[k] || '').trim()).map((k) => [k, form[k].trim()]));
        if (Object.keys(secrets).length) body.secrets = secrets;
      }
      await setPlug(p.type, body);
      setEditing(null);
      await reload();
    } catch (e) { setErr(e instanceof Error ? e.message : 'The plugin was not saved. Try again.'); }
    finally { setBusy(''); }
  };

  return (
    <section className="view is-active" id="view-plugins">
      <div className="page">
        <div className="page-header">
          <div>
            <h1>Plugins</h1>
            <p>Connect a service once for this workspace. Each Harness then chooses which plugins it includes, under its settings.</p>
          </div>
        </div>
        {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Something went wrong</strong>{err}</div></div>}
        {!plugs ? <SkelRows rows={4} /> : (
          <div className="capability-list">
            {plugs.map((p) => {
              const on = p.status === 'connected';
              const c = counts[p.type];
              const price = p.pricing ? `$${p.pricing.usd_per_unit.toFixed(2)} per ${p.pricing.unit}, billed at the service's own price` : 'No charge';
              return (
                <div key={p.type} className="capability-row">
                  <span className={'capability-icon' + (MARK[p.type]?.app ? ' is-app' : '')} aria-hidden="true">
                    {MARK[p.type]
                      // eslint-disable-next-line @next/next/no-img-element -- a static brand mark
                      ? <img src={MARK[p.type].src} alt="" />
                      : <iconify-icon icon="lucide:plug"></iconify-icon>}
                  </span>
                  <div className="capability-copy">
                    <strong>{p.label} {p.official && <span className="status neutral">Official</span>} <span className={'status ' + (on ? 'healthy' : p.status === 'needs_auth' ? 'warning' : 'neutral')}>{STATUS_LABEL[p.status]}</span></strong>
                    <span>{BLURB[p.type] || ''} {p.tools} tools · {price}{c ? ` · ${c.attached} of ${c.harnesses} Harnesses include it` : ''}</span>
                    {p.attention && <span className="field-help">{p.attention}</span>}
                  </div>
                  <div className="capability-actions">
                    {p.status === 'missing' && (p.secrets_needed.length === 0
                      ? <button className="button small" type="button" disabled={busy === p.type} onClick={() => void save(p, true, false)}>Turn on</button>
                      : <button className="button small" type="button" disabled={busy === p.type} onClick={() => open(p)}>Connect</button>)}
                    {p.status === 'needs_auth' && (delegated(p)
                      ? <button className="button small" type="button" disabled={busy === p.type} onClick={() => void signIn()}>{busy === p.type ? 'Opening Microsoft\u2026' : 'Sign in with Microsoft'}</button>
                      : <button className="button small" type="button" disabled={busy === p.type} onClick={() => open(p)}>Add credentials</button>)}
                    {p.status === 'disabled' && <button className="button small" type="button" disabled={busy === p.type} onClick={() => void save(p, true, false)}>Turn on</button>}
                    {p.status !== 'missing' && <button className="button quiet small" type="button" disabled={busy === p.type} onClick={() => open(p)}>Settings</button>}
                    {on && <button className="button quiet small" type="button" disabled={busy === p.type} onClick={() => void save(p, false, false)}>Turn off</button>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <p className="field-help" style={{ marginTop: 14 }}>
          A Harness includes a plugin under its settings. <button className="hr-link-sm" type="button" onClick={() => router.push('/harnesses')}>Open Agent Harnesses</button>
        </p>
      </div>

      {editing && (
        <div className="modal-backdrop" onClick={() => busy || setEditing(null)}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="plug-title" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header"><div><h2 id="plug-title">{editing.label}</h2><p>{BLURB[editing.type] || ''}</p></div>
              <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={() => setEditing(null)}><iconify-icon icon="tabler:x"></iconify-icon></button></div>
            <div className="modal-body">
              <div className="field-stack">
                {editing.secrets_needed.map((k) => (
                  <div className="field" key={k}><label htmlFor={`plug-${k}`}>{FIELD_LABEL[k] || k}</label>
                    <input id={`plug-${k}`} type="password" autoComplete="off" value={form[k] || ''}
                      placeholder={editing.secrets_set.includes(k) ? '•••••••• (saved, leave blank to keep)' : ''}
                      onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></div>
                ))}
                {editing.config_fields.map((k) => (
                  <div className="field" key={k}><label htmlFor={`plug-${k}`}>{FIELD_LABEL[k] || k}</label>
                    {k === 'mode' ? (
                      <select id={`plug-${k}`} value={form[k] || 'delegated'} onChange={(e) => setForm({ ...form, [k]: e.target.value })}>
                        <option value="delegated">Each person signs in with Microsoft (recommended)</option>
                        <option value="application">The application itself (unattended)</option>
                      </select>
                    ) : (
                      <input id={`plug-${k}`} type="text" value={form[k] || ''}
                        placeholder={editing.type === 'browser' ? (k === 'allow_domains' ? 'example.com, docs.example.org (empty means any public site)' : 'ads.example.com') : (PLACEHOLDER[k] || '')}
                        onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                    )}</div>
                ))}
                {delegated(editing) && editing.status !== 'missing' && (() => {
                  const accounts = Object.values(accountsOf(editing));
                  return accounts.length
                    ? <span className="field-help">Signed in as <strong>{accounts.map((a) => a.upn || a.name).join(', ')}</strong>. Agents working for a signed-in person read what that person may read.
                        {' '}<button className="hr-link-sm" type="button" disabled={Boolean(busy)} onClick={() => void signOut()}>Sign out</button></span>
                    : <span className="field-help">{editing.attention || 'Sign in with Microsoft so the agent can act as you.'}
                        {' '}<button className="hr-link-sm" type="button" disabled={Boolean(busy)} onClick={() => void signIn()}>Sign in with Microsoft</button></span>;
                })()}
                {editing.secrets_needed.length > 0 && <span className="field-help">This plugin runs on the credential you enter here, kept in this instance and never shown again. Every call an agent makes lands in the account that credential belongs to.</span>}
                {editing.pricing && <span className="field-help">{`Up to ${editing.pricing.session_cap_minutes} minutes of browsing per task, at most $${editing.pricing.session_estimate_usd.toFixed(4)} a task. Private and local addresses are never reachable.`}</span>}
              </div>
              <div className="modal-actions">
                <button className="button" type="button" onClick={() => setEditing(null)} disabled={Boolean(busy)}>Cancel</button>
                <button className="button primary" type="button" disabled={Boolean(busy)} onClick={() => void save(editing, true, true)}>{busy ? 'Saving…' : editing.status === 'missing' ? 'Connect' : 'Save'}</button>
              </div>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
