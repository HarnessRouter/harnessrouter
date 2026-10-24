'use client';
// What Add-ons › Plugins and a setup's Add plugin share: the workspace's plugins as the server lists
// them (lib/plugs.ts: the catalog with each plugin's state here), a row per plugin, each service's mark,
// and the one sheet that connects or manages a plugin. A plugin with nothing to ask (the browser)
// connects in one click; any other gets the fields the server names for it (secrets_needed,
// config_fields), its credential tried at the service before it is kept. A connected plugin's sheet
// changes the names beside the credential or replaces it, signs each person in with Microsoft where
// Microsoft 365 runs as each person, keeps the browser's site lists, lists the tools an agent gets,
// and removes the plugin from the workspace.
import { useCallback, useEffect, useState } from 'react';
import { getSession } from '@/lib/auth';
import {
  listPlugs, plugAttachments, setPlug, deletePlug, plugTools, microsoftStart, microsoftSignout,
  type Plug, type PlugTool, type PlugUse,
} from '@/lib/plugs';
import { READ_MS, readSettled, withDeadline } from '@/lib/settle';
import { partIcon } from '../bricks';
import { toast } from '../toast';
import { Sheet, SheetTop } from '../Sheet';
import { Skel, SkLine } from '../Skel';
import { ABOUT, BLURB, FIELD, HIDDEN_FIELDS, M365_MODES, MARK, REQUIRED, SHOWN } from './plugCopy';
import '../mcp/mcp.css';
import './plugins.css';

// ── the workspace's plugins ───────────────────────────────────────────────────────────────────────
export interface PluginsData {
  /** every plugin this instance serves, with its state in the workspace; null until read */
  plugs: Plug[] | null;
  /** which setups include each added plugin, by type (a plugin whose count could not be read has none) */
  uses: Record<string, PlugUse>;
  /** the last read failed after its quiet second try (lib/settle.ts): the list says so, with Try again */
  failed: boolean;
  reload: () => Promise<void>;
  /** Try again: read again (a list read before stays on screen meanwhile) */
  retry: () => void;
  /** how many plugins Connected lists (connected, or waiting for a credential or a sign-in); null until read */
  connectedCount: number | null;
}

/** The workspace's plugins, read again when the workspace changes ('' while it is not known yet).
 *  `counts`: also read which setups include each one (Add-ons says so on each row; a setup's sheet does not). */
export function usePlugins(workspace: string, { counts: withCounts = true }: { counts?: boolean } = {}): PluginsData {
  const [plugs, setPlugs] = useState<Plug[] | null>(null);
  const [uses, setUses] = useState<Record<string, PlugUse>>({});
  const [failed, setFailed] = useState(false);
  // every read here ends (readSettled): a server that stops answering is a failed read the list says,
  // not a skeleton forever. A list read before stays on screen under it.
  const reload = useCallback(async () => {
    if (!workspace) return;
    try {
      const d = await readSettled((signal) => listPlugs(signal));
      setPlugs(d.plugs); setFailed(false);
      if (!withCounts) return;
      const c: Record<string, PlugUse> = {};
      await Promise.all(d.plugs.filter(isAdded).map(async (p) => {
        try { c[p.type] = await withDeadline((signal) => plugAttachments(p.type, signal), READ_MS); } catch { /* no used line for it */ }
      }));
      setUses(c);
    } catch {
      setFailed(true);
    }
  }, [workspace, withCounts]);
  useEffect(() => { void reload(); }, [reload]);
  const retry = useCallback(() => { setFailed(false); void reload(); }, [reload]);
  const connectedCount = plugs === null ? null : plugs.filter((p) => isOn(p) || needsAuth(p)).length;
  return { plugs, uses, failed, reload, retry, connectedCount };
}

// ── plugins as rows ───────────────────────────────────────────────────────────────────────────────
export const isOn = (p?: Plug | null) => p?.status === 'connected';
/** waiting for a credential, or (Microsoft 365 run as each person) for a person's sign-in */
export const needsAuth = (p?: Plug | null) => p?.status === 'needs_auth';
/** the workspace has a record of it: connected, turned off, or waiting */
export const isAdded = (p?: Plug | null) => !!p && p.status !== 'missing';
/** how a setup names a plugin it includes */
export const plugRef = (p: Plug) => p.type;
/** the names of the setups that include it (the server's list, at read time); null when not read */
export const usedBy = (u?: PlugUse) => (u ? (u.harness_list || []).map((h) => h.name || h.id) : null);

export interface Row { key: string; p: Plug; name: string; desc: string; mark?: { src: string; app?: boolean } }

/** Every plugin the server serves, a row each, in the server's order. */
export function plugRows(plugs: Plug[] | null): Row[] {
  return (plugs || []).map((p) => ({ key: p.type, p, name: p.label || p.type, desc: BLURB[p.type] || '', mark: MARK[p.type] }));
}

const shownValue = (v: unknown) => (Array.isArray(v) ? v.map(String).join(', ') : v == null ? '' : String(v));
const domainsOf = (text: string) => text.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean);
const listOf = (v: unknown) => (Array.isArray(v) ? v.map(String).join(', ') : '');
const m365Delegated = (p: Plug) => p.type === 'microsoft365' && String(p.config.mode || 'delegated') === 'delegated';
type Account = { upn?: string; name?: string };
const accountsOf = (p: Plug) => (p.config.accounts && typeof p.config.accounts === 'object' ? p.config.accounts : {}) as Record<string, Account>;
const accountName = (a: Account) => a.upn || a.name || '';

/** The account a connected plugin is on, in its own terms: the repository, the project, the address,
 *  the directory, the sites the browser keeps to. The names beside a credential are never secret. */
export function accountOf(r: Row): { text: string; mono: boolean } {
  const p = r.p;
  if (needsAuth(p)) return { text: p.attention || 'Connect your account again to restore access.', mono: false };
  if (p.type === 'browser') {
    const only = listOf(p.config.allow_domains);
    return only ? { text: `Only ${only}`, mono: false } : { text: r.desc, mono: false };
  }
  // Microsoft 365: how people use it, and its directory by name when known; its ids are in Manage, labelled
  // (two bare ids side by side on a row said nothing a person could read)
  if (p.type === 'microsoft365') {
    const dir = shownValue(p.config.directory);
    const how = String(p.config.mode || 'delegated') === 'delegated' ? 'Each person signs in with Microsoft' : 'Runs as the application';
    return { text: dir ? `${dir} · ${how}` : how, mono: false };
  }
  const vals = (SHOWN[p.type] || []).filter(([k]) => k !== 'mode').map(([k]) => shownValue(p.config[k])).filter(Boolean).slice(0, 2);
  return vals.length ? { text: vals.join(' · '), mono: true } : { text: r.desc, mono: false };
}

// ── marks and tiles ───────────────────────────────────────────────────────────────────────────────
/** A service's own mark; a plugin without one is a plugin brick. */
export function Logo({ mark, on = true, size }: { mark?: { src: string; app?: boolean }; name?: string; on?: boolean; size: 'row' | 'tile' | 'cap' }) {
  const wrap = size === 'row' ? `lib-ic${on ? '' : ' off'}` : size === 'cap' ? `cap-ic pl-capic${on ? '' : ' off'}` : 'pl-ic';
  if (!mark) return <span className={wrap} aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon(on ? 'built' : 'empty', 'plugin') }} />;
  return (
    <span className={wrap} aria-hidden="true">
      <span className={`brand-ic${mark.app ? ' pl-cover' : ' pl-b'}`}>
        {/* eslint-disable-next-line @next/next/no-img-element -- a static brand mark */}
        <img src={mark.src} alt="" />
      </span>
    </span>
  );
}

export const SEARCH = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>;

/** One tile of the grid: the mark, the name, a two-line description, and its action. */
export function Tile({ logo, name, desc, children }: { logo: React.ReactNode; name: string; desc: string; children: React.ReactNode }) {
  return (
    <li className="pl-tile">
      <span className="pl-top">{logo}<b>{name}</b></span>
      <p className="pl-d">{desc}</p>
      <span className="pl-act">{children}</span>
    </li>
  );
}

/** A plugin that is not connected, as its tile says it: turned off here (its settings kept), or what it is. */
export const tileDesc = (r: Row) => (r.p.status === 'disabled' ? 'Turned off here. Connect turns it back on as it was.' : r.desc);

/** Whether a word typed in the search finds this plugin (its name, its type or its line). */
export const matches = (q: string, ...text: string[]) => {
  const n = q.trim().toLowerCase();
  return !n || text.some((t) => (t || '').toLowerCase().includes(n));
};

// ── the form a plugin asks for ────────────────────────────────────────────────────────────────────
export interface Field { name: string; label: string; hint?: string; required: boolean; secret: boolean; kind: 'text' | 'mode' }

/** The fields the server names for a plugin, in the order a person fills them: what it is and where,
 *  then the secret. The browser's site lists and a record's own bookkeeping are not fields. */
export function fieldsOf(p: Plug): Field[] {
  const req = REQUIRED[p.type] || [];
  const one = (name: string, secret: boolean): Field => ({
    name, secret, label: FIELD[name]?.label || name, hint: FIELD[name]?.hint, required: req.includes(name), kind: FIELD[name]?.kind || 'text',
  });
  return [...(p.config_fields || []).filter((n) => !HIDDEN_FIELDS.has(n)).map((n) => one(n, false)), ...(p.secrets_needed || []).map((n) => one(n, true))];
}
/** Nothing to ask: Connect turns it on at once. */
export const oneClick = (p: Plug) => fieldsOf(p).length === 0;

// ── connecting one ────────────────────────────────────────────────────────────────────────────────
/** Connect, turn back on, reconnect or manage a plugin. `sheet` is its sheet when one is open;
 *  `onConnected` hears the plugin's type once it is connected. */
export function usePlugConnect(reload: () => Promise<void>, onConnected?: (type: string) => void) {
  const [busy, setBusy] = useState('');
  const [open, setOpen] = useState<Plug | null>(null);
  const done = async (type: string, said: string, connected: boolean) => { await reload(); toast(said); if (connected) onConnected?.(type); };
  async function turnOn(r: Row) {
    setBusy(r.key);
    try {
      const p = await setPlug(r.p.type, { enabled: true });
      if (isOn(p)) await done(p.type, `${r.name} connected.`, true);
      else { await reload(); setOpen(p); }          // it waits for a credential or a sign-in: its sheet says which
    } catch (e) { toast(sayRefusal(e, `${r.name} could not be connected.`)); }
    finally { setBusy(''); }
  }
  function connect(r: Row) {
    if (r.p.status === 'disabled' || (r.p.status === 'missing' && oneClick(r.p))) { void turnOn(r); return; }
    setOpen(r.p);
  }
  const manage = (r: Row) => setOpen(r.p);
  const sheet = open ? (
    <PlugSheet p={open} onClose={() => setOpen(null)} onChanged={() => void reload()}
      onDone={async (said, connected) => { const t = open.type; setOpen(null); await done(t, said, connected); }} />
  ) : null;
  return { busy, setBusy, connect, manage, sheet };
}

/** The server's sentence for a refusal (lib/harness gw throws it), else `fallback` and to try again. */
export function sayRefusal(e: unknown, fallback: string): string {
  const s = e instanceof Error ? e.message.trim() : '';
  if (!s || /^\d{3}$/.test(s)) return `${fallback} Try again.`;
  return /[.!?]$/.test(s) ? s : `${s}.`;
}

/** One plugin's sheet. Not added yet: the fields it asks for, then Connect. Added: the names beside its
 *  credential (Save), a new credential in place of the stored one, Microsoft's sign-in for each person,
 *  the browser's sites, its tools, and Remove. */
export function PlugSheet({ p, onClose, onChanged, onDone }: {
  p: Plug; onClose: () => void;
  /** the plugin changed here and the sheet stays open (a person signed in or out, or it waits for a sign-in) */
  onChanged: () => void;
  /** the work is done and the sheet closes: what to say, and whether the plugin is connected now */
  onDone: (said: string, connected: boolean) => void;
}) {
  const [cur, setCur] = useState<Plug>(p);
  const label = cur.label || cur.type;
  const added = isAdded(cur);
  const fields = fieldsOf(cur);
  const takesCredential = (cur.secrets_needed || []).length > 0;
  const delegated = m365Delegated(cur);
  const signIn = added && delegated && (cur.secrets_set || []).includes('client_secret');
  const initForm = (x: Plug) => Object.fromEntries(fieldsOf(x).map((f) => [f.name,
    f.secret ? '' : f.kind === 'mode' ? String(x.config.mode || 'delegated') : shownValue(x.config[f.name])]));
  const [form, setForm] = useState<Record<string, string>>(() => initForm(p));
  // a new credential in place of the stored one: from the start when there is none to keep
  const [replacing, setReplacing] = useState(() => !isAdded(p) || (needsAuth(p) && takesCredential && !(m365Delegated(p) && (p.secrets_set || []).includes('client_secret'))));
  const [allow, setAllow] = useState(listOf(p.config.allow_domains));
  const [deny, setDeny] = useState(listOf(p.config.deny_domains));
  const [tools, setTools] = useState<PlugTool[] | null>(null);
  const [busy, setBusy] = useState<'' | 'save' | 'signin' | 'signout' | 'remove'>('');
  const [say, setSay] = useState('');
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    let live = true;
    plugTools(p.type).then((t) => { if (live) setTools(t.tools || []); }).catch(() => { if (live) setTools([]); });
    return () => { live = false; };
  }, [p.type]);

  const me = getSession()?.member;
  const mine = String(me?.email || me?.id || '');
  const accounts = accountsOf(cur);
  const myAccount = mine ? accounts[mine] : undefined;
  const others = Object.entries(accounts).filter(([k]) => k !== mine).map(([, a]) => accountName(a)).filter(Boolean);

  const shown = fields.filter((f) => replacing || !f.secret);
  const complete = shown.every((f) => !f.required || (form[f.name] || '').trim());
  const namesChanged = added && !replacing && fields.some((f) => !f.secret && (form[f.name] || '').trim() !== (f.kind === 'mode' ? String(cur.config.mode || 'delegated') : shownValue(cur.config[f.name]).trim()));
  const sitesChanged = added && cur.type === 'browser'
    && (domainsOf(allow).join(',') !== domainsOf(listOf(cur.config.allow_domains)).join(',') || domainsOf(deny).join(',') !== domainsOf(listOf(cur.config.deny_domains)).join(','));
  const changed = !added || replacing || namesChanged || sitesChanged;

  async function submit() {
    if (busy || !complete || !changed) return;
    setBusy('save'); setSay('');
    const secrets: Record<string, string> = {}; const config: Record<string, unknown> = {};
    for (const f of shown) {
      const v = (form[f.name] || '').trim();
      if (f.secret) { if (v) secrets[f.name] = v; } else config[f.name] = v;
    }
    if (cur.type === 'browser' && added) { config.allow_domains = domainsOf(allow); config.deny_domains = domainsOf(deny); }
    try {
      const next = await setPlug(cur.type, { enabled: true, config, ...(Object.keys(secrets).length ? { secrets } : {}) });
      if (isOn(next)) { onDone(`${label} ${!isOn(cur) ? 'connected' : replacing ? 'updated' : 'saved'}.`, !isOn(cur)); return; }
      // kept, and waiting: Microsoft 365 run as each person waits for a sign-in, said here
      setCur(next); setReplacing(false); setForm(initForm(next)); onChanged();
      setSay(m365Delegated(next) ? '' : next.attention || 'It still needs a credential.');
    } catch (e) {
      setSay(sayRefusal(e, `${label} could not be connected.`));
    } finally { setBusy(''); }
  }
  async function microsoft() {
    setBusy('signin'); setSay('');
    try {
      // Microsoft comes back to the address the workspace's Entra application lists, the Plugins page's,
      // which finishes the sign-in (PluginsTab)
      const { auth_url } = await microsoftStart(`${window.location.origin}/plugins`);
      window.location.assign(auth_url);
    } catch (e) { setSay(sayRefusal(e, 'Microsoft could not be reached.')); setBusy(''); }
  }
  async function signOut() {
    setBusy('signout'); setSay('');
    try { setCur(await microsoftSignout()); onChanged(); toast('Signed out of Microsoft.'); }
    catch (e) { setSay(sayRefusal(e, 'The sign-out did not finish.')); }
    finally { setBusy(''); }
  }
  async function remove() {
    setBusy('remove'); setSay('');
    try { await deletePlug(cur.type); onDone(`${label} removed.`, false); }
    catch (e) { setSay(sayRefusal(e, `${label} could not be removed.`)); setAsking(false); setBusy(''); }
  }

  const enter = (e: React.KeyboardEvent) => { if (e.key === 'Enter') { e.preventDefault(); void submit(); } };
  const field = (f: Field) => (
    <div key={f.name} className="set-f">
      <label htmlFor={`pc-${f.name}`}>{f.label}{f.required ? null : <span className="muted">optional</span>}</label>
      {f.kind === 'mode' ? (
        <select id={`pc-${f.name}`} className="set-in" value={form[f.name] || 'delegated'} disabled={!!busy}
          onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}>
          {M365_MODES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
      ) : (
        <input id={`pc-${f.name}`} className={`set-in${f.secret ? ' mono' : ''}`} type={f.secret ? 'password' : 'text'} autoComplete="off" spellCheck={false}
          value={form[f.name] || ''} disabled={!!busy} onChange={(e) => setForm({ ...form, [f.name]: e.target.value })} onKeyDown={enter} />
      )}
      {f.hint ? <p className="set-help">{f.hint}</p> : null}
    </div>
  );
  const facts = (SHOWN[cur.type] || []).filter(([k]) => k === 'directory' && shownValue(cur.config[k]));

  return (
    <Sheet onClose={onClose} labelledBy="pch" className="small-sheet mcp-sheet mcp-x pl-sheet" busy={!!busy}>
      <SheetTop id="pch" title={`${added ? 'Manage' : 'Connect'} ${label}`} sub={ABOUT[cur.type] || BLURB[cur.type] || undefined} onClose={onClose} />

      {/* Microsoft 365 as each person: who is signed in here, and this person's own sign-in */}
      {signIn && !replacing ? (
        <div className="set-f pl-signin">
          <span className="mcp-to-l">Microsoft sign-in</span>
          {facts.map(([k, l]) => <p key={k} className="set-help">{l}: <b>{shownValue(cur.config[k])}</b></p>)}
          {myAccount ? (
            <div className="set-row">
              <span>Signed in as <b>{accountName(myAccount) || 'you'}</b>. Agents working for you read what you may read.</span>
              <button type="button" className="link-q" disabled={!!busy} onClick={() => void signOut()}>{busy === 'signout' ? 'Signing out…' : 'Sign out'}</button>
            </div>
          ) : (
            <div className="set-row">
              <span>{cur.attention || 'Sign in with Microsoft so the agent can act as you.'}</span>
              <button type="button" className="btn small primary" disabled={!!busy} onClick={() => void microsoft()}>{busy === 'signin' ? 'Opening Microsoft…' : 'Sign in with Microsoft'}</button>
            </div>
          )}
          {others.length ? <p className="set-help">Also signed in here: {others.join(', ')}.</p> : null}
        </div>
      ) : null}
      {needsAuth(cur) && !signIn && !replacing && cur.attention ? <p className="set-help pl-warn">{cur.attention}</p> : null}

      {shown.map(field)}
      {takesCredential && (replacing || !added) ? (
        <p className="set-help pl-keep">{added
          ? `The new credential is tried against ${label} before it replaces the stored one. It is stored securely, never shown again, and never handed to an agent.`
          : `The credential is tried against ${label} before it is kept. It is stored securely, never shown again, and never handed to an agent.`}</p>
      ) : null}
      {/* a stored credential is kept unless a new one is asked for; one that is missing has none to keep */}
      {added && takesCredential && !replacing ? (
        <p className="set-help"><button type="button" className="link-q inl" disabled={!!busy} onClick={() => { setReplacing(true); setSay(''); }}>Use a different credential</button></p>
      ) : added && takesCredential && (isOn(cur) || signIn) ? (
        <p className="set-help"><button type="button" className="link-q inl" disabled={!!busy} onClick={() => { setReplacing(false); setForm(initForm(cur)); setSay(''); }}>Keep the current credential</button></p>
      ) : null}

      {/* the browser's sites: where an agent may go, and where never */}
      {added && cur.type === 'browser' ? (
        <>
          <div className="set-f"><label htmlFor="pc-allow">Only these sites <span className="muted">optional</span></label>
            <input id="pc-allow" className="set-in mono" value={allow} spellCheck={false} placeholder="example.com, docs.example.org" disabled={!!busy}
              onChange={(e) => setAllow(e.target.value)} onKeyDown={enter} />
            <p className="set-help">Left empty, any public site.</p></div>
          <div className="set-f"><label htmlFor="pc-deny">Never these sites <span className="muted">optional</span></label>
            <input id="pc-deny" className="set-in mono" value={deny} spellCheck={false} placeholder="ads.example.com" disabled={!!busy}
              onChange={(e) => setDeny(e.target.value)} onKeyDown={enter} /></div>
        </>
      ) : null}

      {cur.pricing && cur.pricing.usd_per_unit > 0 ? (
        <p className="set-help pl-price">{`$${cur.pricing.usd_per_unit.toFixed(2)} per ${cur.pricing.unit}, the service’s own price with no markup, rounded ${cur.pricing.rounding || 'up to the minute'}.`}
          {cur.pricing.session_cap_minutes ? ` Up to ${cur.pricing.session_cap_minutes} minutes per task, at most $${(cur.pricing.session_estimate_usd || 0).toFixed(4)} a task, counted against the task’s cost limit.` : ''}</p>
      ) : null}

      {tools === null ? (
        <Skel label="Reading its tools" className="mcp-tools">
          {[58, 72, 50].map((w, i) => <div key={i} className="mcp-tool"><SkLine w={`${w * 0.5}%`} h={12} /><SkLine w={`${w}%`} h={10} style={{ marginTop: 6 }} /></div>)}
        </Skel>
      ) : tools.length ? (
        <div className="set-f">
          <span className="mcp-to-l" id="pcToolsL">{tools.length === 1 ? '1 tool' : `${tools.length} tools`} an agent gets</span>
          <ul className="mcp-tools" aria-labelledby="pcToolsL">
            {tools.map((t) => <li key={t.name} className="mcp-tool"><b className="mono">{t.name}</b>{t.description ? <small title={t.description}>{t.description}</small> : null}</li>)}
          </ul>
        </div>
      ) : null}

      {asking ? (
        <div className="mcp-ask" role="alertdialog" aria-labelledby="pcAskT">
          <span id="pcAskT">Remove <b>{label}</b> from this workspace? Its stored credential is deleted, and setups that include it lose its tools from their next task. Nothing at {label} changes.</span>
          <span className="mcp-ask-b">
            <button type="button" className="btn small" disabled={!!busy} onClick={() => setAsking(false)}>Keep</button>
            <button type="button" className="btn small del-go" disabled={!!busy} onClick={() => void remove()} autoFocus>{busy === 'remove' ? 'Removing…' : 'Remove'}</button>
          </span>
        </div>
      ) : null}

      <div className="sheet-actions mcp-act">
        {added && !asking ? <button type="button" className="link-q danger mcp-rm" disabled={!!busy} onClick={() => { setSay(''); setAsking(true); }}>Remove</button> : null}
        <span className={`set-help mcp-say${say ? ' bad' : ''}`} role="status">{say}</span>
        {changed ? (
          <>
            <button type="button" className="btn" disabled={!!busy} onClick={onClose}>Cancel</button>
            <button type="button" className="btn primary" disabled={!!busy || !complete || asking} onClick={() => void submit()}>
              {busy === 'save' ? (added && !replacing ? 'Saving…' : 'Connecting…') : added && !replacing ? 'Save' : 'Connect'}</button>
          </>
        ) : <button type="button" className="btn primary" disabled={!!busy} onClick={onClose}>Done</button>}
      </div>
    </Sheet>
  );
}
