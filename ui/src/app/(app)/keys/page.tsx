'use client';
// API Keys, per the finalized 2026-07-19 design revision (prototype view-api-keys):
// page header + Create button, search toolbar with the shown-once security note, table
// (Name / Key / Last used / Created) with a per-row dots menu for Revoke, and the
// create modal with one-time reveal. Keys are workspace-scoped (CT-249). "Last used"
// is not tracked by the gateway yet, it renders "—" rather than a guess.
import { harnessFetch } from '@/lib/hfetch';
import { useCallback, useEffect, useRef, useState } from 'react';
import { SkelRows } from '@/components/Skel';
import { getSession } from '@/lib/auth';
import { useWorkspace } from '@/lib/workspace';

interface Key { id: string; name?: string; created_at?: string; revoked?: boolean; member?: string; workspace?: string; last_used?: string }

function fmtDate(s?: string): string {
  const n = Number(s); if (!n) return '—';
  try { return new Date(n * (n < 1e12 ? 1000 : 1)).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); } catch { return '—'; }
}

export default function KeysPage() {
  const [keys, setKeys] = useState<Key[] | null>(null);
  const [err, setErr] = useState('');
  const [search, setSearch] = useState('');
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [minted, setMinted] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<Key | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const org = getSession()?.orgId || '';
  const member = getSession()?.member?.email || getSession()?.member?.id || '';
  const base = `/api/harness/v1/orgs/${encodeURIComponent(org)}/keys`;
  const { current, defaultId } = useWorkspace();
  const isDefaultWs = !current.id || current.id === defaultId;

  const reload = useCallback(() => {
    if (!org) { setErr('No org in session.'); return; }
    harnessFetch(base)
      .then((r) => r.json())
      .then((d) => setKeys((d.keys || []).filter((k: Key) => !k.revoked)
        // Keys belong to a workspace; unstamped legacy keys belong to the Default Workspace.
        .filter((k: Key) => !current.id || (k.workspace || '') === current.id || (isDefaultWs && !k.workspace))))
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [base, org, current.id, isDefaultWs]);
  useEffect(reload, [reload]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuFor(null);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  async function mint() {
    if (busy) return;               // name is OPTIONAL, never gate the action on it
    setBusy(true); setErr('');
    try {
      const finalName = name.trim() || 'Untitled key';
      const r = await harnessFetch(base, { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name: finalName, member_id: member,
                              workspace: current.id || '', workspace_default: isDefaultWs }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || JSON.stringify(d));
      setMinted(d.key); setCopied(false); setName(''); reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function revoke(id: string) {
    await harnessFetch(`${base}/${encodeURIComponent(id)}`, { method: 'DELETE' });
    setRevoking(null); setMenuFor(null); reload();
  }

  const shown = (keys || []).filter((k) =>
    !search.trim() || (k.name || '').toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <section className="view is-active" id="view-api-keys">
      <div className="page">
        <div className="page-header">
          <div><h1>API Keys</h1><p>Create and revoke credentials scoped to <span className="workspace-name">{current.name}</span>.</p></div>
          <button className="button primary" type="button" disabled={!org}
            onClick={() => { setName(''); setErr(''); setMinted(null); setCreating(true); }}>
            <iconify-icon icon="tabler:plus"></iconify-icon>Create API Key
          </button>
        </div>
        <div className="api-key-toolbar">
          <label className="api-key-search">
            <span className="sr-only">Search API keys</span>
            <iconify-icon icon="tabler:search"></iconify-icon>
            <input className="search-input" type="search" placeholder="Search keys" autoComplete="off"
              value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          <div className="api-key-toolbar-meta">
            <span className="api-key-security"><iconify-icon icon="tabler:shield-lock"></iconify-icon>New secrets are shown once</span>
          </div>
        </div>
        {err && !creating && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Could not load keys</strong>{err}</div></div>}
        <div className="table-wrap">
          <table><thead><tr><th>Name</th><th>Key</th><th>Last used</th><th>Created</th><th aria-label="Actions"></th></tr></thead><tbody>
            {shown.map((k) => (
              <tr key={k.id}>
                <td><strong>{k.name || 'Untitled key'}</strong></td>
                <td><code>sk-hr-••••{(k.id || '').slice(-4)}</code></td>
                <td>{fmtDate(k.last_used)}</td>
                <td>{fmtDate(k.created_at)}</td>
                <td>
                  <div className="api-key-menu-wrap" ref={menuFor === k.id ? menuRef : undefined}>
                    <button className="row-action" type="button" aria-label={`Manage ${k.name || 'key'}`}
                      aria-expanded={menuFor === k.id}
                      onClick={() => setMenuFor(menuFor === k.id ? null : k.id)}>
                      <iconify-icon icon="tabler:dots"></iconify-icon>
                    </button>
                    {menuFor === k.id && (
                      <div className="api-key-menu">
                        <button className="danger" type="button" onClick={() => { setMenuFor(null); setRevoking(k); }}>Revoke key</button>
                      </div>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody></table>
          {keys === null && <table><tbody><SkelRows rows={3} cols={5} first={140} /></tbody></table>}
          {keys != null && keys.length === 0 && (
            <div className="api-key-empty">No API keys yet. Use <b>Create API Key</b> to make one and call the API.</div>
          )}
          {keys != null && keys.length > 0 && shown.length === 0 && (
            <div className="api-key-empty">No keys match this search.</div>
          )}
        </div>
      </div>

      {creating && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="newKeyTitle" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div><h2 id="newKeyTitle">Create API Key</h2><p>A secret key for the public API, scoped to <span className="workspace-name">{current.name}</span>. The secret is shown once, right after creation.</p></div>
              <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={() => setCreating(false)}><iconify-icon icon="tabler:x"></iconify-icon></button>
            </div>
            {!minted ? (
              <div className="modal-body">
                <div className="field-stack">
                  <div className="field"><label htmlFor="newKeyName">Key name <span className="optional-label">Optional</span></label>
                    <input id="newKeyName" value={name} placeholder="e.g. production" autoFocus
                      onChange={(e) => setName(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') void mint(); }} /></div>
                  {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Could not create</strong>{err}</div></div>}
                </div>
                <div className="modal-actions">
                  <button className="button" type="button" onClick={() => setCreating(false)} disabled={busy}>Cancel</button>
                  <button className="button primary" type="button" onClick={() => void mint()} disabled={busy}>{busy ? 'Creating…' : 'Create API Key'}</button>
                </div>
              </div>
            ) : (
              <div className="modal-body">
                <div className="key-reveal"><code>{minted}</code><span>This key is shown once. Copy it now, for security it is never shown again.</span></div>
                <div className="security-note"><iconify-icon icon="tabler:shield-lock"></iconify-icon><span>Never paste this key into normal chat, source files, browser code, logs, or screenshots.</span></div>
                <div className="modal-actions">
                  <span className="copy-state" role="status" aria-live="polite">{copied ? 'Copied' : ''}</span>
                  <button className="button" type="button" onClick={async () => { try { await navigator.clipboard.writeText(minted); setCopied(true); } catch { /* blocked */ } }}>
                    <iconify-icon icon={copied ? 'tabler:check' : 'tabler:copy'}></iconify-icon>{copied ? 'Copied' : 'Copy API Key'}</button>
                  <button className="button primary" type="button" onClick={() => { setCreating(false); setMinted(null); }}>Done</button>
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {revoking && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="revokeTitle" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div><h2 id="revokeTitle">Revoke &ldquo;{revoking.name || 'Untitled key'}&rdquo;?</h2><p>Any integration using this key will immediately stop working. This cannot be undone.</p></div>
              <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={() => setRevoking(null)}><iconify-icon icon="tabler:x"></iconify-icon></button>
            </div>
            <div className="modal-body">
              <div className="modal-actions">
                <button className="button" type="button" onClick={() => setRevoking(null)}>Cancel</button>
                <button className="button danger" type="button" onClick={() => void revoke(revoking.id)}>Revoke key</button>
              </div>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
