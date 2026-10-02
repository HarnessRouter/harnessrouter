'use client';
// Plugins, per the console design (Plugins.dc.html), the same page as the hosted console's:
// connect a service once for the workspace, any Harness can then use it, and each Harness
// decides which ones it needs. Two tabs: Browse (the catalog, by category, with a search box and
// a detail sheet per plugin) and Installed (a table: plugin, source, how many Harnesses include
// it, status; the status is a switch and a plugin can be removed). A plugin is the workspace's
// own account: the sheet asks for the credential the organization created at the service and
// the names beside it, the gateway tries it there and keeps it in this instance's secret store,
// never shown again. Every figure on the page is the gateway's: the catalog with each plugin's
// state and price, the tool lists, the counts of Harnesses that include it.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { SkelRows } from '@/components/Skel';
import {
  listPlugs, setPlug, deletePlug, plugTools, plugAttachments, microsoftStart, microsoftComplete, microsoftSignout,
  type Plug, type PlugTool,
} from '@/lib/harness';

const CATEGORY_OF: Record<string, string> = { github: 'code', browser: 'tools', vercel: 'hosting', insforge: 'backend', microsoft365: 'productivity' };
const CATEGORY: Record<string, string> = { code: 'Developer', tools: 'Developer', hosting: 'Hosting', backend: 'Data and infrastructure', productivity: 'Productivity', agents: 'Agents', other: 'Other' };
/** Each service by its own mark (public/plugs): the GitHub and Vercel glyphs, Microsoft 365's logo,
 *  InsForge's app icon (drawn full-bleed, it carries its own ground), our browser glyph. A type
 *  without one shows its initial. */
const MARK: Record<string, { src: string; app?: boolean }> = {
  github: { src: '/plugs/github.svg' }, vercel: { src: '/plugs/vercel.svg' }, microsoft365: { src: '/plugs/microsoft365.svg' },
  insforge: { src: '/plugs/insforge.png', app: true }, browser: { src: '/plugs/browser.svg' },
};
function Tile({ type, name, large }: { type: string; name: string; large?: boolean }) {
  const m = MARK[type];
  const cls = 'pl-tile' + (large ? ' pl-tile-lg' : '') + (m?.app ? ' is-app' : '');
  // eslint-disable-next-line @next/next/no-img-element -- a static brand mark
  return <span className={cls} aria-hidden="true">{m ? <img src={m.src} alt="" /> : name.charAt(0)}</span>;
}
const BLURB: Record<string, string> = {
  browser: 'A real web browser: open pages, read them, click, type, and take screenshots',
  github: 'Your own repository: files, branches, pull requests',
  vercel: 'Your own Vercel project: deployments and domains',
  insforge: 'Your own InsForge backend: tables and records',
  microsoft365: 'Your own SharePoint, OneDrive, Outlook and directory, as each signed-in person',
};
const ABOUT: Record<string, string> = {
  browser: 'Connect the browser so an agent can open a public page, read what is on it, fill in forms, click through, wait for things to appear and take screenshots that are kept with the task. Each task gets its own browser, opened when the agent first needs it and closed when the task ends. Private and local addresses are never reached.',
  github: 'Connect a repository of your own GitHub account or organization with a token you create there. An agent can then read files, make commits on a branch, open pull requests and merge them in that repository and nowhere else. The token is tried against the repository before it is kept, stored securely, and never handed to the agent.',
  vercel: 'Connect a project of your own Vercel account or team with a token you create there. An agent can then read the project, trigger deployments from a branch and watch them go live. The token is tried against the project before it is kept, stored securely, and never handed to the agent.',
  insforge: 'Connect a backend project of your own InsForge account with its API key and address. An agent can then read and write its tables and check its health. The key is tried against the backend before it is kept, stored securely, and never handed to the agent.',
  microsoft365: 'Connect your organization’s own Microsoft Entra application. Each person then signs in with Microsoft once, and an agent working for them reads their SharePoint sites, OneDrive, mail and calendar exactly as they may; or run it as the application itself for unattended work. The application’s secret is checked at Entra before it is kept, stored securely, and never handed to the agent.',
};
const STATUS_LABEL: Record<string, string> = { connected: 'Connected', disabled: 'Disabled', needs_auth: 'Needs auth' };
const SOURCE_LABEL: Record<string, string> = { platform: 'Official', local: 'Your account' };
/** The fields the gateway names per plugin (secrets_needed, config_fields), with the label beside
 *  each, the hint under it, and which may stay empty. The browser's site lists have their own
 *  section, and a record's own bookkeeping never shows as a field. */
const FIELD: Record<string, { label: string; hint?: string; kind?: 'text' | 'select' }> = {
  token: { label: 'Access token', hint: 'Created in the service’s settings; tried there before it is kept.' },
  api_key: { label: 'API key' },
  client_secret: { label: 'Client secret', hint: 'From the Entra application’s certificates and secrets.' },
  repo: { label: 'Repository (owner/name)', hint: 'Agents can reach this repository and nothing else.' },
  owner: { label: 'Owner', hint: 'Left empty, the owner in the repository name.' },
  default_branch: { label: 'Default branch', hint: 'Left empty, main.' },
  project: { label: 'Project', hint: 'The project’s name or id at the service.' },
  project_id: { label: 'Project id' },
  team_id: { label: 'Team id', hint: 'For a project that belongs to a team.' },
  url: { label: 'Address', hint: 'The backend’s https address.' },
  region: { label: 'Region' },
  tenant_id: { label: 'Directory (tenant) id' },
  client_id: { label: 'Application (client) id' },
  mode: { label: 'Identity', kind: 'select' },
};
const REQUIRED: Record<string, string[]> = {
  github: ['token', 'repo'], vercel: ['token', 'project'], insforge: ['api_key', 'url'], microsoft365: ['client_secret', 'tenant_id', 'client_id'],
};
const HIDDEN_FIELDS = new Set(['allow_domains', 'deny_domains', 'proxy', 'accounts', 'directory']);
// The non-secret names a connected plugin shows back, in the order they read best.
const SHOWN: Record<string, [string, string][]> = {
  github: [['repo', 'Repository'], ['owner', 'Owner'], ['default_branch', 'Default branch']],
  vercel: [['project', 'Project'], ['project_id', 'Project id'], ['team_id', 'Team']],
  insforge: [['url', 'Address'], ['project', 'Project'], ['region', 'Region']],
  microsoft365: [['directory', 'Directory'], ['tenant_id', 'Directory id'], ['client_id', 'Application id'], ['mode', 'Identity']],
};
type Field = { name: string; label: string; hint?: string; required: boolean; secret: boolean; kind: 'text' | 'select' };
const listOf = (v: unknown) => (Array.isArray(v) ? v.map(String).join(', ') : '');
const domainsOf = (text: string) => text.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean);
const shownValue = (v: unknown) => (Array.isArray(v) ? v.map(String).join(', ') : v == null ? '' : String(v));
const installedOf = (p: Plug) => p.status !== 'missing';
const takesCredential = (p: Plug) => p.secrets_needed.length > 0;
const delegated = (p: Plug) => p.type === 'microsoft365' && String(p.config.mode || 'delegated') === 'delegated';
const accountsOf = (p: Plug) => (p.config.accounts || {}) as Record<string, { upn?: string; name?: string; signed_in_at?: string }>;
function fieldsOf(p: Plug): Field[] {
  const req = REQUIRED[p.type] || [];
  const one = (name: string, secret: boolean): Field => ({ name, secret, label: FIELD[name]?.label || name, hint: FIELD[name]?.hint, required: req.includes(name), kind: FIELD[name]?.kind || 'text' });
  return [...p.secrets_needed.map((n) => one(n, true)), ...p.config_fields.filter((n) => !HIDDEN_FIELDS.has(n)).map((n) => one(n, false))];
}

export default function PluginsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [plugs, setPlugs] = useState<Plug[] | null>(null);
  const [counts, setCounts] = useState<Record<string, { attached: number; harnesses: number }>>({});
  const [tools, setTools] = useState<Record<string, PlugTool[]>>({});
  const [tab, setTab] = useState<'browse' | 'installed'>('browse');
  const [q, setQ] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [detail, setDetail] = useState<Plug | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [formErr, setFormErr] = useState('');
  const [replacing, setReplacing] = useState(false);
  const [removing, setRemoving] = useState<Plug | null>(null);
  const [allow, setAllow] = useState('');
  const [deny, setDeny] = useState('');

  const reload = useCallback(async () => {
    try {
      const d = await listPlugs();
      setPlugs(d.plugs);
      const c: Record<string, { attached: number; harnesses: number }> = {};
      await Promise.all(d.plugs.filter(installedOf).map(async (p) => {
        try { const a = await plugAttachments(p.type); c[p.type] = { attached: a.attached, harnesses: a.harnesses }; } catch { /* the column stays empty */ }
      }));
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
      try { await microsoftComplete(code, state); setTab('installed'); await reload(); }
      catch (e) { setErr(e instanceof Error ? e.message : 'The sign-in did not finish. Try again.'); }
      finally { setBusy(''); router.replace('/plugins'); }
    })();
  }, [params, reload, router]);

  const byType = useMemo(() => Object.fromEntries((plugs || []).map((p) => [p.type, p])), [plugs]);
  const installed = useMemo(() => (plugs || []).filter(installedOf), [plugs]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (plugs || []).filter((p) => !needle || p.label.toLowerCase().includes(needle) || (BLURB[p.type] || '').toLowerCase().includes(needle));
  }, [plugs, q]);
  const sections = useMemo(() => {
    const out: { title: string; items: Plug[] }[] = [];
    for (const p of shown) {
      const title = CATEGORY[CATEGORY_OF[p.type] || 'other'];
      let s = out.find((x) => x.title === title);
      if (!s) { s = { title, items: [] }; out.push(s); }
      s.items.push(p);
    }
    return out;
  }, [shown]);

  const openDetail = (p: Plug, replace = false) => {
    setAllow(listOf(p.config.allow_domains)); setDeny(listOf(p.config.deny_domains));
    const f: Record<string, string> = {};
    for (const x of fieldsOf(p)) f[x.name] = x.secret ? '' : (x.name === 'mode' ? String(p.config.mode || 'delegated') : shownValue(p.config[x.name]));
    setForm(f); setFormErr('');
    // Needs auth means a new credential, except on a Microsoft 365 plug run as each person: there it means a sign-in
    setReplacing(replace || (installedOf(p) && p.status === 'needs_auth' && !delegated(p)));
    setDetail(p);
    if (!tools[p.type]) plugTools(p.type).then((t) => setTools((cur) => ({ ...cur, [p.type]: t.tools }))).catch(() => { /* the chips stay off */ });
  };
  const bodyOf = (p: Plug) => {
    const secrets: Record<string, string> = {}; const config: Record<string, unknown> = {};
    for (const x of fieldsOf(p)) {
      const v = (form[x.name] || '').trim();
      if (x.secret) { if (v) secrets[x.name] = v; }
      else config[x.name] = v;
    }
    return { secrets, config };
  };
  const connect = async (p: Plug) => {
    setBusy(p.type); setErr(''); setFormErr('');
    try {
      const { secrets, config } = bodyOf(p);
      await setPlug(p.type, { enabled: true, config, ...(Object.keys(secrets).length ? { secrets } : {}) });
      setDetail(null); setTab('installed'); await reload();
    } catch (e) { setFormErr(e instanceof Error ? e.message : 'The plugin was not connected. Try again.'); }
    finally { setBusy(''); }
  };
  const signIn = async () => {
    setBusy('microsoft365'); setErr('');
    try { const { auth_url } = await microsoftStart(`${window.location.origin}/plugins`); window.location.assign(auth_url); }
    catch (e) { setErr(e instanceof Error ? e.message : 'Microsoft could not be reached. Try again.'); setBusy(''); }
  };
  const signOut = async () => {
    setBusy('microsoft365'); setErr('');
    try { await microsoftSignout(); setDetail(null); await reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : 'The sign-out did not finish. Try again.'); }
    finally { setBusy(''); }
  };
  const toggle = async (p: Plug) => {
    if (p.status === 'needs_auth') { openDetail(p); return; }   // a new credential, or a person's sign-in
    setBusy(p.type); setErr('');
    try { await setPlug(p.type, { enabled: p.status === 'disabled' }); await reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : 'The status was not changed. Try again.'); }
    finally { setBusy(''); }
  };
  const remove = async (p: Plug) => {
    setBusy(p.type); setErr('');
    try { await deletePlug(p.type); setRemoving(null); setDetail(null); await reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : 'The plugin was not removed. Try again.'); }
    finally { setBusy(''); }
  };
  const saveSites = async (p: Plug) => {
    setBusy(p.type); setErr('');
    try { await setPlug(p.type, { enabled: p.status !== 'disabled', config: { allow_domains: domainsOf(allow), deny_domains: domainsOf(deny) } }); await reload(); setDetail(null); }
    catch (e) { setErr(e instanceof Error ? e.message : 'The sites were not saved. Try again.'); }
    finally { setBusy(''); }
  };
  const saveNames = async (p: Plug) => {
    setBusy(p.type); setErr(''); setFormErr('');
    try { await setPlug(p.type, { enabled: p.status !== 'disabled', config: bodyOf(p).config }); await reload(); setDetail(null); }
    catch (e) { setFormErr(e instanceof Error ? e.message : 'The change was not saved. Try again.'); }
    finally { setBusy(''); }
  };

  const ready = plugs !== null;
  const detailRow = detail && installedOf(detail) ? byType[detail.type] : undefined;
  const sitesChanged = Boolean(detailRow && detail?.type === 'browser'
    && (domainsOf(allow).join(',') !== listOf(detailRow.config.allow_domains).split(', ').filter(Boolean).join(',')
      || domainsOf(deny).join(',') !== listOf(detailRow.config.deny_domains).split(', ').filter(Boolean).join(',')));
  const namesChanged = Boolean(detail && detailRow && !replacing && takesCredential(detail)
    && fieldsOf(detail).filter((x) => !x.secret).some((x) => (form[x.name] || '').trim() !== (x.name === 'mode' ? String(detailRow.config.mode || 'delegated') : shownValue(detailRow.config[x.name]).trim())));
  const formComplete = (p: Plug, withSecrets: boolean) => fieldsOf(p).every((x) => !x.required || (x.secret && !withSecrets) || (form[x.name] || '').trim());

  const renderField = (x: Field) => (
    <div className="field pl-field" key={x.name}>
      <label htmlFor={`pl-f-${x.name}`}>{x.label}{x.required ? '' : ' (optional)'}</label>
      {x.kind === 'select' ? (
        <select id={`pl-f-${x.name}`} value={form[x.name] || 'delegated'} onChange={(e) => setForm({ ...form, [x.name]: e.target.value })}>
          <option value="delegated">Each person signs in with Microsoft (recommended)</option>
          <option value="application">The application itself (unattended)</option>
        </select>
      ) : (
        <input id={`pl-f-${x.name}`} type={x.secret ? 'password' : 'text'} autoComplete="off" spellCheck={false}
          value={form[x.name] || ''} onChange={(e) => setForm({ ...form, [x.name]: e.target.value })} />
      )}
      {x.hint && <span className="pl-hint">{x.hint}</span>}
    </div>
  );

  return (
    <section className="view is-active pl" id="view-plugins">
      <div className="pl-head">
        <div className="pl-head-row">
          <div>
            <h1>Plugins</h1>
            <p>Connect a service once for the workspace. Any harness can then use it, and each harness decides which ones it needs.</p>
          </div>
        </div>
        <div className="pl-tabs" role="tablist">
          <button type="button" role="tab" className={'pl-tab' + (tab === 'browse' ? ' is-on' : '')} aria-selected={tab === 'browse'} onClick={() => setTab('browse')}>
            <span>Browse</span>{plugs && <span className="pl-count">{plugs.length}</span>}</button>
          <button type="button" role="tab" className={'pl-tab' + (tab === 'installed' ? ' is-on' : '')} aria-selected={tab === 'installed'} onClick={() => setTab('installed')}>
            <span>Installed</span>{plugs && <span className="pl-count">{installed.length}</span>}</button>
        </div>
      </div>
      <div className="pl-body">
        {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Something went wrong</strong>{err}</div></div>}
        {!ready ? <SkelRows rows={4} /> : tab === 'installed' ? (
          <>
            <div className="pl-table">
              <div className="pl-table-head"><span>Plugin</span><span>Source</span><span>Harnesses</span><span className="pl-right">Status</span></div>
              {installed.length === 0 && <div className="pl-empty">Nothing installed yet. Browse the catalog and connect a plugin for this workspace.</div>}
              {installed.map((row) => {
                const c = counts[row.type]; const st = row.status;
                return (
                  <div key={row.type} className="pl-row">
                    <span className="pl-cell-name">
                      <Tile type={row.type} name={row.label} />
                      <span className="pl-copy"><span className="pl-name">{row.label}</span>
                        <span className="pl-blurb">{st === 'needs_auth' && row.attention ? row.attention : (BLURB[row.type] || '')}</span></span>
                    </span>
                    <span className="pl-source">{SOURCE_LABEL[row.source] || row.source}</span>
                    <span className="pl-mono">{c ? `${c.attached} of ${c.harnesses}` : ''}</span>
                    <span className="pl-cell-status">
                      <button type="button" className={'pl-pill is-' + st} disabled={busy === row.type} onClick={() => void toggle(row)}
                        title={st === 'needs_auth' ? 'Connect your account again to restore access' : st === 'disabled' ? 'Turn back on' : 'Turn off without disconnecting'}>
                        {STATUS_LABEL[st] || st}</button>
                      <button type="button" className="pl-x" aria-label={`Remove ${row.label}`} disabled={busy === row.type} onClick={() => setRemoving(row)}>
                        <iconify-icon icon="tabler:x"></iconify-icon></button>
                    </span>
                  </div>
                );
              })}
            </div>
            <div className="pl-foot">A harness includes a plugin under its settings. <button type="button" className="pl-link" onClick={() => router.push('/harnesses')}>Open Agent Harnesses</button></div>
          </>
        ) : (
          <>
            <div className="pl-search"><iconify-icon icon="tabler:search"></iconify-icon>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search plugins" aria-label="Search plugins" /></div>
            {sections.map((sec) => (
              <div key={sec.title} className="pl-section">
                <div className="pl-section-title">{sec.title}</div>
                <div className="pl-hr" />
                <div className="pl-grid">
                  {sec.items.map((p) => {
                    const has = installedOf(p);
                    return (
                      <div key={p.type} className={'pl-card' + (has ? ' has' : '')} role="button" tabIndex={0} onClick={() => openDetail(p)} onKeyDown={(e) => { if (e.key === 'Enter') openDetail(p); }}>
                        <Tile type={p.type} name={p.label} />
                        <span className="pl-copy"><span className="pl-name">{p.label}</span><span className="pl-blurb">{BLURB[p.type] || ''}</span>
                          <span className="pl-meta">Official{p.tools ? ` · ${p.tools} tools` : ''}{p.pricing && p.pricing.usd_per_unit > 0 ? ` · $${p.pricing.usd_per_unit.toFixed(2)} per ${p.pricing.unit}` : ''}</span></span>
                        <span className="pl-plus" aria-hidden="true">{has ? '✓' : '+'}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
            {sections.length === 0 && <div className="pl-empty">No plugin matches that.</div>}
          </>
        )}
      </div>

      {detail && (
        <div className="modal-backdrop" onClick={() => busy || setDetail(null)}>
          <section className="modal pl-sheet" role="dialog" aria-modal="true" aria-labelledby="pl-detail-title" onClick={(e) => e.stopPropagation()}>
            <div className="pl-sheet-head">
              <Tile type={detail.type} name={detail.label} large />
              <span className="pl-copy"><span id="pl-detail-title" className="pl-sheet-name">{detail.label}</span>
                <span className="pl-sheet-meta">{CATEGORY[CATEGORY_OF[detail.type] || 'other'] + ' · Official'}</span></span>
              {detailRow
                ? <span className={'pl-btn is-installed' + (detailRow.status === 'needs_auth' ? ' is-attention' : '')}>{detailRow.status === 'needs_auth' ? 'Needs auth' : 'Installed'}</span>
                : !takesCredential(detail) && <button type="button" className="pl-btn" disabled={Boolean(busy)} onClick={() => void connect(detail)}>{busy === detail.type ? 'Connecting…' : 'Connect'}</button>}
              <button type="button" className="pl-x pl-x-lg" aria-label="Close" onClick={() => setDetail(null)}><iconify-icon icon="tabler:x"></iconify-icon></button>
            </div>
            <div className="pl-sheet-body">
              <div className="pl-about">{ABOUT[detail.type] || BLURB[detail.type] || ''}</div>
              {(tools[detail.type] || []).length > 0 && (<>
                <div className="pl-label">Tools</div>
                <div className="pl-chips">{tools[detail.type].map((x) => <span key={x.name} className="pl-chip" title={x.description}>{x.name}</span>)}</div>
              </>)}
              {detail.pricing && detail.pricing.usd_per_unit > 0 && (
                <div className="pl-note">{`$${detail.pricing.usd_per_unit.toFixed(2)} per ${detail.pricing.unit}, the service's own price with no markup, rounded ${detail.pricing.rounding || 'up to the minute'}.`}
                  {detail.pricing.session_cap_minutes ? ` Up to ${detail.pricing.session_cap_minutes} minutes per task, at most $${(detail.pricing.session_estimate_usd || 0).toFixed(4)} a task, counted against the task's cost limit.` : ''}</div>
              )}

              {takesCredential(detail) && !detailRow && (<>
                <div className="pl-label">Connect your account</div>
                <div className="pl-form">{fieldsOf(detail).map(renderField)}</div>
                <div className="pl-hint pl-hint-form">The credential is tried against {detail.label} before it is kept. It is stored securely, never shown again, and never handed to an agent.</div>
                {formErr && <div className="pl-form-err">{formErr}</div>}
                <div className="pl-actions"><button type="button" className="pl-btn" disabled={Boolean(busy) || !formComplete(detail, true)} onClick={() => void connect(detail)}>{busy === detail.type ? 'Connecting…' : 'Connect'}</button></div>
              </>)}

              {takesCredential(detail) && detailRow && (<>
                <div className="pl-label">Your account</div>
                {detailRow.status === 'needs_auth' && !(detail.type === 'microsoft365' && replacing === false) && <div className="pl-note">{detailRow.attention || 'Connect your account again to restore access.'}</div>}
                {detail.type === 'microsoft365' && !replacing && delegated(detailRow) && (() => {
                  const accounts = Object.values(accountsOf(detailRow));
                  return (
                    <div className="pl-signin">
                      {accounts.length
                        ? <div className="pl-signin-row"><span>Signed in as <strong>{accounts.map((a) => a.upn || a.name).join(', ')}</strong>. Agents working for a signed-in person read what that person may read.</span>
                            <button type="button" className="pl-link" disabled={Boolean(busy)} onClick={() => void signOut()}>Sign out</button></div>
                        : <div className="pl-signin-row"><span>{detailRow.attention || 'Sign in with Microsoft so the agent can act as you.'}</span>
                            <button type="button" className="pl-btn" disabled={Boolean(busy)} onClick={() => void signIn()}>{busy === 'microsoft365' ? 'Opening Microsoft…' : 'Sign in with Microsoft'}</button></div>}
                    </div>
                  );
                })()}
                {!replacing && (<>
                  <dl className="pl-facts">
                    {(SHOWN[detail.type] || []).filter(([k]) => shownValue(detailRow.config[k])).map(([k, label]) => (
                      <div key={k}><dt>{label}</dt><dd>{shownValue(detailRow.config[k])}</dd></div>
                    ))}
                  </dl>
                  <div className="pl-form">{fieldsOf(detail).filter((x) => !x.secret).map(renderField)}</div>
                  {formErr && <div className="pl-form-err">{formErr}</div>}
                  <div className="pl-actions pl-actions-split">
                    <button type="button" className="pl-link" disabled={Boolean(busy)} onClick={() => { setReplacing(true); setFormErr(''); }}>Use a different credential</button>
                    {namesChanged && <button type="button" className="pl-btn" disabled={Boolean(busy) || !formComplete(detail, false)} onClick={() => void saveNames(detailRow)}>{busy ? 'Saving…' : 'Save'}</button>}
                  </div>
                </>)}
                {replacing && (<>
                  <div className="pl-form">{fieldsOf(detail).map(renderField)}</div>
                  <div className="pl-hint pl-hint-form">The new credential is tried against {detail.label} before it replaces the stored one. It is stored securely, never shown again, and never handed to an agent.</div>
                  {formErr && <div className="pl-form-err">{formErr}</div>}
                  <div className="pl-actions pl-actions-split">
                    {detailRow.status !== 'needs_auth' && <button type="button" className="pl-link" disabled={Boolean(busy)} onClick={() => { setReplacing(false); setFormErr(''); }}>Keep the current one</button>}
                    <button type="button" className="pl-btn" disabled={Boolean(busy) || !formComplete(detail, true)} onClick={() => void connect(detail)}>{busy === detail.type ? 'Connecting…' : 'Connect'}</button>
                  </div>
                </>)}
              </>)}

              {detailRow && detail.type === 'browser' && (<>
                <div className="pl-label">Sites</div>
                <div className="field pl-field"><label htmlFor="pl-allow">Only these sites</label>
                  <input id="pl-allow" value={allow} onChange={(e) => setAllow(e.target.value)} placeholder="example.com, docs.example.org (empty means any public site)" /></div>
                <div className="field pl-field"><label htmlFor="pl-deny">Never these sites</label>
                  <input id="pl-deny" value={deny} onChange={(e) => setDeny(e.target.value)} placeholder="ads.example.com" /></div>
                {sitesChanged && <div className="pl-actions"><button type="button" className="pl-btn" disabled={Boolean(busy)} onClick={() => void saveSites(detailRow)}>{busy ? 'Saving…' : 'Save sites'}</button></div>}
              </>)}
            </div>
          </section>
        </div>
      )}

      {removing && (
        <div className="modal-backdrop" onClick={() => busy || setRemoving(null)}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="pl-remove-title" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header"><div><h2 id="pl-remove-title">Remove {removing.label}?</h2>
              <p>The workspace disconnects it and the stored credential is deleted; every harness that includes it loses its tools on the next task. Nothing at {removing.label} changes. You can connect it again any time.</p></div></div>
            <div className="modal-body">
              <div className="modal-actions">
                <button className="button" type="button" onClick={() => setRemoving(null)} disabled={Boolean(busy)}>Cancel</button>
                <button className="button danger" type="button" disabled={Boolean(busy)} onClick={() => void remove(removing)}>{busy ? 'Removing…' : 'Remove'}</button>
              </div>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
