'use client';
// API Keys (docs/uxuidesign/console-79, view `keys`: keysView, keyCreate('page'), revokeHtml).
// The workspace's keys as the gateway lists them (GET /v1/orgs/{org}/keys): name, last four,
// when it was made, when it last authenticated a call (stamped by the gateway; none reads
// "Never"). Revoked keys are left out: nothing can be done with one. A key with no workspace, or one
// made in the Default Workspace, reaches every workspace, and its row and its revoke say so.
// Create is the key step's own (start/KeyStep): the same create call and name rule (start/keys), a
// name that cannot be used said under the field, and the secret shown once until Copy key turns to
// Copied; then it folds away and the key is a row like any other. Outside the Default Workspace the
// create asks what the key reaches: this workspace only, or every workspace.
// Each row's Manage opens the key: rename it (PATCH /v1/orgs/{org}/keys/{kid}, the secret and its
// reach stay), rotate its secret (a new key with the same name and reach, then the old one revoked,
// so there is never a moment with no working key; the new secret shows once, as a new key's does),
// or revoke it (DELETE, after asking). A refusal from the gateway is said in its own words.
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { useWorkspace } from '@/lib/workspace';
import { ago } from './setups';
import { toast } from './toast';
import { PagePic } from './bricks';
import { ConfirmSheet, Sheet, SheetTop } from './Sheet';
import { Skel, SkRows } from './Skel';
import { keyMask, keyRefusal, reachesAll, useWsKeys, type WsKey } from './start/keys';
import { useCopyConfirm } from './start/copy';

type Key = WsKey & { member?: string };

const DAY_MS = 86400_000;
/** How long "Copied" shows before the secret folds away (the key step's own pause). */
const FOLD_MS = 600;
/** The gateway stamps seconds; tolerate milliseconds. 0 when absent. */
const toMs = (s?: string | number): number => { const n = Number(s); return n ? n * (n < 1e12 ? 1000 : 1) : 0; };

export function KeysPage() {
  const s = getSession();
  const org = s?.orgId || '';
  const member = s?.member?.email || s?.member?.id || '';
  const base = `/api/harness/v1/orgs/${encodeURIComponent(org)}/keys`;
  const { current, defaultId } = useWorkspace();
  const isDefaultWs = !current.id || current.id === defaultId;
  const k = useWsKeys();
  const id = useId();

  const [keys, setKeys] = useState<Key[] | null>(null);
  const [err, setErr] = useState(false);
  const [name, setName] = useState('');
  const [why, setWhy] = useState('');
  // what a new key reaches: asked only outside the Default Workspace (a key made there reaches every one)
  const [everywhere, setEverywhere] = useState(false);
  const [busy, setBusy] = useState(false);
  // the secret of the key just made (or rotated): on screen until it is copied
  const [fresh, setFresh] = useState<{ id: string; secret: string; name?: string } | null>(null);
  const [copied, setCopied] = useState(false);
  // the key open in its Manage sheet, the name typed there and why it cannot be used
  const [managing, setManaging] = useState<Key | null>(null);
  const [rename, setRename] = useState('');
  const [renameWhy, setRenameWhy] = useState('');
  const [revoking, setRevoking] = useState<Key | null>(null);
  // the gateway's refusal of a revoke (who can revoke this key, by role), said in its sheet
  const [refused, setRefused] = useState('');
  const nameRef = useRef<HTMLInputElement | null>(null);
  const renameRef = useRef<HTMLInputElement | null>(null);
  const secretRef = useRef<HTMLElement | null>(null);
  const fold = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(fold.current), []);
  useEffect(() => { setEverywhere(false); }, [current.id]);
  const { copy } = useCopyConfirm();

  const reload = useCallback(async () => {
    if (!org) return;
    try {
      const r = await harnessFetch(base);
      if (!r.ok) throw new Error(String(r.status));
      const d = await r.json();
      // a key belongs to a workspace; a key with no workspace reaches every one
      setKeys(((d.keys || []) as Key[]).filter((x) => !current.id || !x.workspace || x.workspace === current.id));
      setErr(false);
    } catch {
      setErr(true);
      setKeys((x) => x || []);
    }
  }, [base, org, current.id]);
  useEffect(() => { void reload(); }, [reload]);

  // newest first: the key just made is the first row; a revoked key is not listed
  const rows = useMemo(() => (keys || []).filter((x) => !x.revoked)
    .map((x) => ({ k: x, created: toMs(x.created_at), used: toMs(x.last_used), sub: [keyMask(x.tail), reachesAll(x, defaultId) ? 'every workspace' : ''].filter(Boolean).join(' · ') }))
    .sort((a, b) => b.created - a.created), [keys, defaultId]);
  const live = rows.map((r) => r.k);
  /** why a new name for `self` cannot be used, as the create's rule says it */
  const renameProblem = (nm: string, self: Key) => {
    if (!nm.trim()) return 'Name the key first, e.g. production.';
    if (live.some((x) => x.id !== self.id && (x.name || '').toLowerCase() === nm.trim().toLowerCase())) return `A key named ${nm.trim()} already exists. Use another name.`;
    return '';
  };

  async function create() {
    if (k.busy || !org) return;
    const problem = k.nameProblem(name);
    if (problem) { setWhy(problem); nameRef.current?.focus(); return; }
    // a refusal (who can make this key, by role) is said under the name, as a name that cannot be used is
    const onRefused = (no: string) => { setWhy(no); nameRef.current?.focus(); };
    const r = !isDefaultWs && everywhere ? await k.create(name, 'keys', onRefused, { everywhere: true }) : await k.create(name, 'keys', onRefused);
    if (!r) return;
    clearTimeout(fold.current);
    setFresh(r); setCopied(false); setName(''); setWhy('');
    await reload();
  }

  const copyKey = () => {
    if (!fresh) return;
    copy(fresh.secret, secretRef, 'Key copied', () => {
      setCopied(true);
      clearTimeout(fold.current);
      fold.current = setTimeout(() => { setFresh(null); setCopied(false); }, FOLD_MS);
    });
  };

  const openManage = (x: Key) => { setManaging(x); setRename(x.name || ''); setRenameWhy(''); };
  const closeManage = () => { if (!busy) setManaging(null); };

  async function saveName(x: Key) {
    if (busy) return;
    const nm = rename.trim();
    if (nm === (x.name || '')) { setManaging(null); return; }
    const problem = renameProblem(nm, x);
    if (problem) { setRenameWhy(problem); renameRef.current?.focus(); return; }
    setBusy(true);
    try {
      const r = await harnessFetch(`${base}/${encodeURIComponent(x.id)}`, {
        method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: nm }),
      });
      if (!r.ok) {
        const no = keyRefusal(r.status, await r.json().catch(() => null));
        if (no) { setRenameWhy(no); return; }
        throw new Error(String(r.status));
      }
      setManaging(null);
      toast(`Renamed to ${nm}.`);
      await reload();
    } catch {
      toast('The key could not be renamed. Try again.');
    } finally { setBusy(false); }
  }

  async function rotate(x: Key) {
    if (busy) return;
    setBusy(true);
    try {
      // the new key first, with the same name and reach: the old one stops only once the new one works
      const ws = x.workspace || '';
      const r = await harnessFetch(base, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name: x.name || 'default', member_id: member, workspace: ws,
          workspace_name: ws && ws === current.id ? current.name || '' : '', workspace_default: !!ws && ws === defaultId }),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok || !d?.key) {
        const no = keyRefusal(r.status, d);
        toast(no || 'The secret could not be rotated. Try again.');
        return;
      }
      const old = await harnessFetch(`${base}/${encodeURIComponent(x.id)}`, { method: 'DELETE' }).catch(() => null);
      setManaging(null);
      clearTimeout(fold.current);
      setFresh({ id: String(d.id || ''), secret: String(d.key), name: x.name || 'default' }); setCopied(false);
      if (!old?.ok) toast(`${x.name || 'The key'} has a new secret, but the old one could not be stopped. Revoke it from Manage.`);
      await reload();
    } catch {
      toast('The secret could not be rotated. Try again.');
    } finally { setBusy(false); }
  }

  async function revoke(x: Key) {
    setBusy(true);
    try {
      const r = await harnessFetch(`${base}/${encodeURIComponent(x.id)}`, { method: 'DELETE' });
      if (!r.ok) {
        const no = keyRefusal(r.status, await r.json().catch(() => null));
        if (no) { setRefused(no); return; }
        throw new Error(String(r.status));
      }
      if (fresh && fresh.id === x.id) setFresh(null);
      setRevoking(null);
      toast(`${x.name || 'The key'} revoked.`);
      await reload();
    } catch {
      toast('The key could not be revoked. Try again.');
    } finally { setBusy(false); }
  }

  const rv = revoking ? { used: toMs(revoking.last_used), all: reachesAll(revoking, defaultId) } : null;
  const mg = managing ? { all: reachesAll(managing, defaultId), created: toMs(managing.created_at), used: toMs(managing.last_used) } : null;

  return (
    <div className="scroll">
      <div className="list-wrap lw-n">
        <div className="list-top ph">
          <div>
            <h1>API Keys</h1>
          </div>
          <PagePic kind="keys" />
        </div>

        <div className="keybox">
          <h4>Create an API key</h4>
          {fresh ? (
            <div className="reveal">
              <b>{fresh.name ? `${fresh.name} has a new secret. ` : ''}Shown once. Paste it only into your coding agent’s secure prompt, never into chat or code.</b>
              {/* ph-no-capture: the secret stays out of session replay */}
              <code id="keySrc" className="ph-no-capture" ref={secretRef}>{fresh.secret}</code>
              <button type="button" className={`btn small ${copied ? 'kb-done' : 'primary'}`} onClick={copyKey}>{copied ? 'Copied' : 'Copy key'}</button>
            </div>
          ) : (
            <>
              <div className="keyrow">
                <label className="sr" htmlFor={`${id}-name`}>Key name</label>
                <input id={`${id}-name`} ref={nameRef} className={`keyname${why ? ' bad' : ''}`} placeholder="Key name, e.g. production"
                  autoComplete="off" spellCheck={false} aria-invalid={why ? true : undefined} aria-describedby={why ? `${id}-why` : undefined} value={name}
                  onChange={(e) => { setName(e.target.value); setWhy(''); }}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void create(); } }} />
                {isDefaultWs ? null : (
                  <div className="seg" role="radiogroup" aria-label="What the key reaches" id="keyReach">
                    <button type="button" role="radio" aria-checked={!everywhere} className={everywhere ? '' : 'on'} onClick={() => setEverywhere(false)}>This workspace only</button>
                    <button type="button" role="radio" aria-checked={everywhere} className={everywhere ? 'on' : ''} onClick={() => setEverywhere(true)}>Every workspace</button>
                  </div>
                )}
                <button type="button" className="btn primary" disabled={k.busy || !org} onClick={() => void create()}>{k.busy ? 'Creating' : 'Create'}</button>
              </div>
              {why ? <p className="kb-why" id={`${id}-why`} role="alert">{why}</p> : null}
            </>
          )}
        </div>

        <div className="rows-head keys-g" style={{ marginTop: 26 }}><span>Name</span><span className="r">Created</span><span className="r">Last used</span><span /></div>
        <div className="rows">
          {/* the key step's own read (its name check runs on it) failing is said here too */}
          {err || k.error ? (
            <div className="empty-list ld-fail" role="alert">Your keys could not be read just now.{' '}
              <button type="button" className="link-q inl" onClick={() => { if (err) void reload(); if (k.error) k.retry(); }}>Try again</button></div>
          ) : null}
          {keys === null ? <Skel label="Loading your keys"><SkRows n={3} cols={2} lead={false} /></Skel> : null}
          {keys !== null && !err && !rows.length ? <div className="empty-list">No keys yet.</div> : null}
          {rows.map(({ k: x, created, used, sub }) => (
            <div key={x.id} className="row keys-g">
              <span className="t"><b>{x.name || 'default'}</b>{sub ? <small className="sub2 mono">{sub}</small> : null}</span>
              <span className="r" title={created ? new Date(created).toLocaleString() : undefined}>{created ? ago(created) : ''}</span>
              <span className="r" title={used ? new Date(used).toLocaleString() : undefined}>{used ? ago(used) : 'Never'}</span>
              <span className="r"><button type="button" className="link-q" aria-label={`Manage ${x.name || 'default'}`} onClick={() => openManage(x)}>Manage</button></span>
            </div>
          ))}
        </div>
      </div>

      {managing && mg ? (
        <Sheet onClose={closeManage} labelledBy="kmh" className="small-sheet ship-sheet key-sheet" busy={busy} initialFocus={renameRef}>
          <SheetTop id="kmh" title={managing.name || 'default'} onClose={closeManage}
            sub={<>{[keyMask(managing.tail), mg.all ? 'Reaches every workspace' : `Reaches ${current.name || 'this workspace'} only`].filter(Boolean).join(' · ')}</>} />
          <div className="set-f">
            <label htmlFor="kmName">Name</label>
            <div className="keyrow">
              <input id="kmName" ref={renameRef} className={`keyname${renameWhy ? ' bad' : ''}`} autoComplete="off" spellCheck={false} value={rename}
                aria-invalid={renameWhy ? true : undefined} aria-describedby={renameWhy ? 'kmWhy' : undefined}
                onChange={(e) => { setRename(e.target.value); setRenameWhy(''); }}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void saveName(managing); } }} />
              <button type="button" className="btn" disabled={busy || rename.trim() === (managing.name || '')} onClick={() => void saveName(managing)}>Save name</button>
            </div>
            {renameWhy ? <p className="kb-why" id="kmWhy" role="alert">{renameWhy}</p> : null}
            <p className="set-help">Only the name changes. The secret and what it reaches stay as they are.</p>
          </div>
          <div className="set-f">
            <label id="kmRot">Secret</label>
            <p className="set-help">Rotating makes a new secret, shown once, and stops this one at once. Anything still using it stops working.</p>
            <div className="sheet-actions"><button type="button" className="btn" aria-describedby="kmRot" disabled={busy} onClick={() => void rotate(managing)}>Rotate secret</button></div>
          </div>
          <p className="set-help">Created {mg.created ? ago(mg.created) : 'at an unknown time'} · {mg.used ? `last used ${ago(mg.used)}` : 'never used'}</p>
          <div className="del-act">
            <button type="button" className="btn del-go" disabled={busy} onClick={() => { const x = managing; setManaging(null); setRefused(''); setRevoking(x); }}>Revoke key</button>
          </div>
        </Sheet>
      ) : null}

      {revoking && rv ? (
        <ConfirmSheet id="rv" title="Revoke key" confirmLabel="Revoke key" busy={busy} focusConfirm refused={refused}
          onClose={() => { setRevoking(null); setRefused(''); }} onConfirm={() => void revoke(revoking)}
          body={<><b>{revoking.name || 'default'}</b>{keyMask(revoking.tail) ? <> <span className="mono">{keyMask(revoking.tail)}</span></> : null} stops working right away{rv.all ? ' in every workspace' : ''}.{rv.used && Date.now() - rv.used < DAY_MS ? <> <b>It was used {ago(rv.used)}.</b></> : null} This can’t be undone.</>} />
      ) : null}
    </div>
  );
}
