'use client';
// API keys, per the v2 design: header with the one primary action, a search box, the shown-once
// reminder; then one card of keys (name, masked key, last used, created) with a row menu for
// rename, rotate and revoke, and the create sheet whose second stage reveals the secret once.
//
// Keys are workspace-scoped. "Last used" is what the gateway stamps when a key authenticates a
// call; a key with no stamp reads "never", never a guess.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { useWorkspace } from '@/lib/workspace';
import { useEscape } from '@/lib/useEscape';
import { track } from '@/lib/analytics';
import { timeAgo } from '@/lib/revamp-data';
import { Popover } from 'reifyui';

interface Key {
  id: string; name?: string; created_at?: string; revoked?: boolean; member?: string; tail?: string;
  workspace?: string; last_used?: string; last_harness?: string;
}

// The gateway began stamping key use on this date. A key made before it that carries no stamp
// may well have been used earlier, so "never" on it gets a tooltip saying so.
const USE_TRACKED_SINCE = Date.UTC(2026, 6, 23);

const toMs = (s?: string): number => { const n = Number(s); return n ? n * (n < 1e12 ? 1000 : 1) : 0; };
function createdLabel(ms: number): string {
  if (!ms) return '—';
  const d = new Date(ms);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString('en-US', sameYear ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' });
}

type Sheet =
  | { kind: 'create' }
  | { kind: 'reveal'; name: string; secret: string; rotated: boolean }
  | { kind: 'rename'; key: Key }
  | { kind: 'revoke'; key: Key }
  | null;

export default function KeysPage() {
  const [keys, setKeys] = useState<Key[] | null>(null);
  const [err, setErr] = useState('');
  const [search, setSearch] = useState('');
  const [sheet, setSheet] = useState<Sheet>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const menuAnchor = useRef<HTMLElement | null>(null);

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

  useEscape(!!sheet, () => { if (!busy) setSheet(null); });

  const rows = useMemo(() => (keys || [])
    .map((k) => {
      const created = toMs(k.created_at);
      const lastUsed = toMs(k.last_used);
      return { k, created, lastUsed, tracked: created >= USE_TRACKED_SINCE };
    })
    .sort((a, b) => b.created - a.created), [keys]);   // newest first: the key you just made is the first row
  const shown = rows.filter(({ k }) => {
    const q = search.trim().toLowerCase();
    return !q || (k.name || '').toLowerCase().includes(q) || (k.id || '').slice(-4).toLowerCase().includes(q);
  });

  async function mint(keyName: string, rotateFrom?: Key) {
    if (busy) return;
    setBusy(true); setErr('');
    try {
      const r = await harnessFetch(base, { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name: keyName, member_id: member, workspace: current.id || '',
                              workspace_name: current.name || '', workspace_default: isDefaultWs }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || JSON.stringify(d));
      if (rotateFrom) {
        // Rotation: the old secret is dead the moment the new one exists. Revoking first would
        // leave a window with no working key at all.
        await harnessFetch(`${base}/${encodeURIComponent(rotateFrom.id)}`, { method: 'DELETE' });
      } else {
        track('api_key_created', { surface: 'keys', is_first_key: (keys || []).length === 0,
                                   workspace_is_default: isDefaultWs, workspace_id: current.id || null });
      }
      setCopied(false);
      setSheet({ kind: 'reveal', name: keyName, secret: d.key, rotated: !!rotateFrom });
      reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function rename(key: Key, next: string) {
    const clean = next.trim();
    if (!clean || busy) return;
    setBusy(true); setErr('');
    try {
      const r = await harnessFetch(`${base}/${encodeURIComponent(key.id)}`, { method: 'PATCH',
        headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: clean }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || `${r.status}`);
      setSheet(null); reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function revoke(key: Key) {
    setBusy(true);
    try { await harnessFetch(`${base}/${encodeURIComponent(key.id)}`, { method: 'DELETE' }); }
    finally { setBusy(false); setSheet(null); reload(); }
  }

  const openMenu = (el: HTMLElement, id: string) => {
    if (menuFor === id) { setMenuFor(null); return; }
    menuAnchor.current = el; setMenuFor(id);
  };
  const menuKey = rows.find((r) => r.k.id === menuFor)?.k || null;

  const openCreate = () => { setName(''); setErr(''); setCopied(false); setSheet({ kind: 'create' }); };

  return (
    <section className="ak-root" id="view-api-keys">
      <header className="ak-head">
        <div className="ak-head-row">
          <div>
            <h1>API keys</h1>
            <p className="ak-sub">Create and revoke credentials scoped to {current.name}.</p>
          </div>
          <button className="ak-primary" type="button" disabled={!org} onClick={openCreate}>Create API key</button>
        </div>
        <div className="ak-tools">
          <input className="ak-search" type="search" placeholder="Search keys" aria-label="Search keys"
            autoComplete="off" value={search} onChange={(e) => setSearch(e.target.value)} />
          <span className="ak-once"><iconify-icon icon="tabler:shield-lock"></iconify-icon>New secrets are shown once</span>
        </div>
      </header>

      <div className="ak-body">
        {err && !sheet && <div className="ak-err" role="alert">Could not load keys. {err}</div>}
        <div className="ak-card">
          <div className="ak-thead" aria-hidden="true">
            <span>Name</span><span>Key</span>
            <span className="ak-th-last">Last used</span><span className="ak-th-created">Created</span><span />
          </div>
          {keys === null ? (
            <><div className="ak-skel" /><div className="ak-skel" style={{ width: '70%' }} /><div className="ak-skel" style={{ width: '85%' }} /></>
          ) : shown.length === 0 ? (
            <div className="ak-empty">
              {rows.length === 0 ? <>No API keys yet. Create one to call the API from your own code.</> : <>No keys match that search.</>}
            </div>
          ) : shown.map(({ k, created, lastUsed, tracked }) => (
            <div key={k.id} className="ak-row">
              <div className="ak-name">
                <b>{k.name || 'Untitled key'}</b>
              </div>
              {/* The key's own last four, kept at creation. A key from before that is shown masked only. */}
              <span className="ak-key">sk-hr-••••{k.tail || ''}</span>
              <span className={'ak-last' + (lastUsed ? '' : ' none')}
                title={lastUsed ? new Date(lastUsed).toLocaleString() : tracked ? undefined : 'Use has been recorded since Jul 23, 2026'}>
                {lastUsed ? timeAgo(lastUsed) : 'never'}
              </span>
              <span className="ak-created" title={created ? new Date(created).toLocaleDateString() : undefined}>{createdLabel(created)}</span>
              <button className="ak-dots" type="button" aria-label={`Actions for ${k.name || 'key'}`}
                aria-haspopup="menu" aria-expanded={menuFor === k.id}
                onClick={(e) => openMenu(e.currentTarget, k.id)}>
                <iconify-icon icon="tabler:dots"></iconify-icon>
              </button>
            </div>
          ))}
        </div>
      </div>

      <Popover open={!!menuKey} anchorRef={menuAnchor} onClose={() => setMenuFor(null)} width={180} minHeight={120}
        className="ak-menu" label={menuKey ? `Actions for ${menuKey.name || 'key'}` : 'Actions'}>
        {menuKey && (
          <div className="uic-pop-list" role="menu">
            <button type="button" role="menuitem" className="uic-pop-item"
              onClick={() => { setMenuFor(null); setName(menuKey.name || ''); setErr(''); setSheet({ kind: 'rename', key: menuKey }); }}>Rename</button>
            <button type="button" role="menuitem" className="uic-pop-item"
              onClick={() => { setMenuFor(null); void mint(menuKey.name || 'Untitled key', menuKey); }}>Rotate secret</button>
            <button type="button" role="menuitem" className="uic-pop-item danger"
              onClick={() => { setMenuFor(null); setSheet({ kind: 'revoke', key: menuKey }); }}>Revoke</button>
          </div>
        )}
      </Popover>

      {sheet && (
        <div className="ak-scrim" onMouseDown={() => { if (!busy && sheet.kind !== 'reveal') setSheet(null); }}>
          <section className="ak-modal" role="dialog" aria-modal="true" aria-labelledby="akTitle" onMouseDown={(e) => e.stopPropagation()}>
            {sheet.kind === 'create' && (
              <>
                <div className="ak-modal-body">
                  <h2 id="akTitle">Create API key</h2>
                  <p className="ak-modal-sub">Scoped to {current.name}. Name it after where it will live, so an unused key is easy to trace later.</p>
                  <div className="ak-field">
                    <div className="ak-field-k">Name</div>
                    <input value={name} placeholder="e.g. video-service · staging" autoFocus aria-label="Key name"
                      onChange={(e) => setName(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') void mint(name.trim() || 'Untitled key'); }} />
                  </div>
                  <div className="ak-warn"><i>!</i><span>The secret is shown once, on the next screen. Paste it into your server environment or the secure modal your coding agent opens, never into chat, source files, or logs.</span></div>
                  {err && <div className="ak-err" style={{ marginTop: 14 }} role="alert">Could not create the key. {err}</div>}
                </div>
                <div className="ak-modal-foot">
                  <button className="ak-secondary" type="button" onClick={() => setSheet(null)} disabled={busy}>Cancel</button>
                  <button className="ak-primary" type="button" onClick={() => void mint(name.trim() || 'Untitled key')} disabled={busy}>{busy ? 'Creating…' : 'Create key'}</button>
                </div>
              </>
            )}
            {sheet.kind === 'reveal' && (
              <>
                <div className="ak-modal-body">
                  <h2 id="akTitle">{sheet.rotated ? `“${sheet.name}” has a new secret` : `“${sheet.name}” is ready`}</h2>
                  <p className="ak-modal-sub">Copy it now. This is the only time it will be shown.</p>
                  {/* ph-no-capture: the plaintext secret stays out of session replay. */}
                  <div className="ak-secret ph-no-capture">
                    <code>{sheet.secret}</code>
                    <button className={'ak-copy' + (copied ? ' is-copied' : '')} type="button"
                      onClick={async () => { try { await navigator.clipboard.writeText(sheet.secret); setCopied(true); } catch { /* blocked */ } }}>
                      {copied ? 'Copied' : 'Copy'}
                    </button>
                  </div>
                  <p className="ak-modal-note">Store it as HR_API_KEY on your server. Rotate it from this page if it ever leaks.</p>
                </div>
                <div className="ak-modal-foot">
                  <button className="ak-primary" type="button" onClick={() => setSheet(null)}>{copied ? 'Done' : 'I have copied it'}</button>
                </div>
              </>
            )}
            {sheet.kind === 'rename' && (
              <>
                <div className="ak-modal-body">
                  <h2 id="akTitle">Rename key</h2>
                  <p className="ak-modal-sub">Only the name changes. The secret and its scope stay as they are.</p>
                  <div className="ak-field">
                    <div className="ak-field-k">Name</div>
                    <input value={name} autoFocus aria-label="Key name" onChange={(e) => setName(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') void rename(sheet.key, name); }} />
                  </div>
                  {err && <div className="ak-err" style={{ marginTop: 14 }} role="alert">Could not rename the key. {err}</div>}
                </div>
                <div className="ak-modal-foot">
                  <button className="ak-secondary" type="button" onClick={() => setSheet(null)} disabled={busy}>Cancel</button>
                  <button className="ak-primary" type="button" onClick={() => void rename(sheet.key, name)} disabled={busy || !name.trim()}>Save name</button>
                </div>
              </>
            )}
            {sheet.kind === 'revoke' && (
              <>
                <div className="ak-modal-body">
                  <h2 id="akTitle">Revoke “{sheet.key.name || 'Untitled key'}”?</h2>
                  <p className="ak-modal-sub">Anything using this key stops working right away. This cannot be undone.</p>
                </div>
                <div className="ak-modal-foot">
                  <button className="ak-secondary" type="button" onClick={() => setSheet(null)} disabled={busy}>Cancel</button>
                  <button className="ak-danger" type="button" onClick={() => void revoke(sheet.key)} disabled={busy}>Revoke key</button>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
