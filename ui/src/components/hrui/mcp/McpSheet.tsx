'use client';
// Add or edit an MCP server: one sheet for every place a server is added (Add-ons › Tools and a
// setup's Settings › Capabilities). The design's mcpHtml (name, endpoint, optional bearer token)
// with what the console's earlier editor had and the design left out:
// - Test connection: the server is asked to start a session and list its tools (the gateway's
//   mcp-test, with the typed token or, when editing, the stored one). It answers which server it is
//   and its tools, or why it could not connect, in plain words. Saving never needs a test; a test
//   that failed is said beside Save.
// - a token can be a per-request header reference (`$headers.Name`): shown as text, never stored,
//   and the setup's declared headers are offered as one-click references.
// - a stored token is never shown: the field says it is stored and an empty field keeps it.
// - Remove, asked in the sheet itself.
// - From Add-ons, adding is two steps (Richard, 2026-10-18): this sheet makes it (its button says
//   Next, `next`), then Add to setups (ext/AddToSheet) chooses the setups that get it, each keeping
//   its own copy. Back there returns here with what was typed (`draft`). Editing there, the list of
//   setups (`targets`) is who uses it.
//
// The sheet only collects and tests. Its callers store: the token first (storeMcpSecret, only a
// reference kept on the setup), then the setup's record (Add-ons) or its Settings draft.
import { useMemo, useRef, useState } from 'react';
import { testMcp, storeMcpSecret, type McpServer } from '@/lib/harness';
import { harnessLogoSrc } from '@/components/HarnessLogo';
import { Sheet, SheetTop } from '../Sheet';
import { Skel, SkLine } from '../Skel';
import './mcp.css';

export const HEADER_REF = '$headers.';
export const isHeaderRef = (t: string | undefined | null) => !!t && String(t).startsWith(HEADER_REF);
/** An endpoint the service will call: https with a host. */
export const okEndpoint = (u: string) => /^https:\/\/[^\s/]+\.[^\s/]+/.test(u.trim());
/** The same server at another spelling of its address (trailing slashes and case ignored). */
export const addrKey = (u: string) => u.trim().replace(/\/+$/, '').toLowerCase();
export const newMcpId = () => 'mcp.' + crypto.randomUUID().replace(/-/g, '').slice(0, 8);

/** The auth a copy keeps: a typed header reference as it is, a typed token stored securely under
 *  this copy's id (only the reference is kept), nothing typed keeps `keep`. */
export async function authFor(id: string, typed: string, keep: string | undefined): Promise<string | undefined> {
  const t = typed.trim();
  if (!t) return keep;
  return isHeaderRef(t) ? t : storeMcpSecret(id, t);
}

/** A setup the server can be added to, and its copy of the server when it has one. */
export interface McpTarget { id: string; name: string; base: string; headers: string[]; has: boolean }

export interface McpSaveInput { name: string; url: string; token: string; to: string[] }

type Test = { busy: true; key: string } | { busy: false; key: string; ok: true; server: string; tools: { name: string; description?: string }[] }
  | { busy: false; key: string; ok: false; error: string };

/** What a failed test means, in the person's words (the gateway answers short technical reasons). */
function sayTestError(e: string | undefined): string {
  const s = String(e || '');
  const http = /HTTP (\d{3})/.exec(s)?.[1];
  if (/only https|must be http/i.test(s)) return 'Use the server’s https:// endpoint.';
  if (/internal|private|loopback|link-local|reserved/i.test(s)) return 'That address is on a private network. Use the server’s public https:// endpoint.';
  if (/no host|invalid url/i.test(s)) return 'That endpoint is not a full address. It looks like https://mcp.your-api.com/mcp.';
  if (http === '401' || http === '403') return `The server refused the connection (HTTP ${http}). Check the token.`;
  if (http === '404') return 'Nothing answered at that path (HTTP 404). An MCP endpoint often ends in /mcp.';
  if (http === '405') return 'That address does not take MCP requests (HTTP 405). Check the path.';
  if (http) return `The server answered HTTP ${http} instead of starting a session.`;
  if (/name or service not known|nodename|getaddrinfo|resolve/i.test(s)) return 'That host name does not exist. Check the endpoint.';
  if (/timed? ?out|timeout/i.test(s)) return 'The server did not answer in time.';
  if (/unreachable|connect|refused|ssl|certificate/i.test(s)) return 'The server could not be reached. Check the endpoint, and that it is reachable from the internet.';
  if (/tools\/list/i.test(s)) return 'It connected, but the server did not list its tools.';
  if (/^test failed: \d+/.test(s)) return 'The connection could not be tested just now. Try again in a moment.';
  return 'The server did not start a session.';
}

const CHECK = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} aria-hidden="true"><path d="M5 12l5 5L20 7" /></svg>;

export function McpSheet({ server, draft, next, keptAuth, headers, targets, initialTo, nameTaken, onSave, onRemove, onClose }: {
  /** the server being edited, or null to add one */
  server: McpServer | null;
  /** adding: what was typed before, coming back from the step after this one */
  draft?: { name: string; url: string; token: string };
  /** adding, where the setups are chosen in a step after this one: the main button's word (Next) */
  next?: string;
  /** when editing: the auth a test uses when no token is typed (a stored token's reference) */
  keptAuth?: string;
  /** header names the setup accepts per request (Settings); from Add-ons, read off the chosen setups */
  headers?: string[];
  /** Add-ons: every setup it can go to. Absent in a setup's Settings (it goes to that setup). */
  targets?: McpTarget[];
  initialTo?: string[];
  /** a name another server already has where it goes: the message to say, or '' */
  nameTaken: (name: string, to: string[]) => string;
  /** store it; resolves to an error to show, or '' once saved */
  onSave: (v: McpSaveInput) => Promise<string>;
  /** remove it (editing only); resolves to an error to show, or '' once removed */
  onRemove?: () => Promise<string>;
  onClose: () => void;
}) {
  const hdr0 = isHeaderRef(server?.auth);
  const stored = !!server?.auth && !hdr0;
  const [name, setName] = useState(server?.name || draft?.name || '');
  const [url, setUrl] = useState(server?.url || draft?.url || '');
  const [tok, setTok] = useState(hdr0 ? String(server!.auth) : draft?.token || '');
  const [to, setTo] = useState<string[]>(initialTo || []);
  const [bad, setBad] = useState<'' | 'name' | 'url' | 'to'>('');
  const [say, setSay] = useState('');          // why Save or Remove did not go through
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false); // Remove, asked in place
  const [test, setTest] = useState<Test | null>(null);
  const nameRef = useRef<HTMLInputElement | null>(null);
  const urlRef = useRef<HTMLInputElement | null>(null);

  const typedHdr = isHeaderRef(tok.trim());
  // a test answers for the endpoint and token it was run with; typing either makes it old
  const key = `${url.trim()}\n${tok.trim()}`;
  const cur = test && test.key === key ? test : null;
  const wide = !!targets;
  // the headers a reference may name: the setup's own, or every chosen setup's
  const offered = useMemo(() => {
    if (!targets) return headers || [];
    const set = new Set<string>();
    targets.filter((t) => to.includes(t.id)).forEach((t) => t.headers.forEach((h) => set.add(h)));
    return Array.from(set);
  }, [targets, headers, to]);
  const hdrName = typedHdr ? tok.trim().slice(HEADER_REF.length) : '';
  // a reference to a header the setup does not take reaches the server empty: say which ones
  // (with a step after this one, its setups are not chosen yet: that step says it of each)
  const lacking = typedHdr && hdrName && !next
    ? (targets ? targets.filter((t) => to.includes(t.id) && !t.headers.includes(hdrName)).map((t) => t.name) : (headers || []).includes(hdrName) ? [] : ['This setup'])
    : [];

  const fail = (f: 'name' | 'url' | 'to', msg: string) => { setBad(f); setSay(msg); if (f === 'name') nameRef.current?.focus(); else if (f === 'url') urlRef.current?.focus(); };

  async function runTest() {
    if (!okEndpoint(url)) { fail('url', 'Use the server’s https:// endpoint.'); return; }
    const k = key;
    setTest({ busy: true, key: k });
    // a header reference has no value here (it comes with each request), so the test goes without one
    const auth = typedHdr ? '' : tok.trim() || (stored ? keptAuth || server?.auth || '' : '');
    const r = await testMcp(url.trim(), auth).catch(() => ({ ok: false, error: 'unreachable' } as Awaited<ReturnType<typeof testMcp>>));
    setTest(r.ok
      ? { busy: false, key: k, ok: true, server: r.server || '', tools: (r.tools || []).filter((t) => t && t.name) }
      : { busy: false, key: k, ok: false, error: sayTestError(r.error) });
  }

  async function save() {
    if (busy) return;
    const n = name.trim(), u = url.trim();
    setSay('');
    if (!n) { fail('name', 'Give it a name.'); return; }
    if (!okEndpoint(u)) { fail('url', 'Use the server’s https:// endpoint.'); return; }
    if (wide && !to.length) { fail('to', server ? 'Choose at least one setup, or remove it.' : 'Choose the setup that gets it.'); return; }
    const taken = nameTaken(n, to);
    if (taken) { fail('name', taken); return; }
    setBusy(true);
    const err = await onSave({ name: n, url: u, token: tok, to }).catch(() => 'It could not be saved. Try again.');
    if (err) { setBusy(false); setSay(err); }
  }
  async function remove() {
    if (!onRemove || busy) return;
    setBusy(true); setSay('');
    const err = await onRemove().catch(() => 'It could not be removed. Try again.');
    if (err) { setBusy(false); setAsking(false); setSay(err); }
  }

  const enter = (e: React.KeyboardEvent) => { if (e.key === 'Enter') { e.preventDefault(); void save(); } };
  const users = targets ? targets.filter((t) => t.has) : [];
  const dropping = server && targets ? users.filter((t) => !to.includes(t.id)).map((t) => t.name) : [];
  const removeWhere = targets ? (users.length === 1 ? users[0].name : `${users.length} setups`) : 'this setup';

  return (
    <Sheet onClose={onClose} labelledBy="mch" className="small-sheet mcp-sheet mcp-x" busy={busy} initialFocus={nameRef}>
      <SheetTop id="mch" title={server ? 'Edit MCP server' : 'Add MCP server'} onClose={onClose} />
      <div className="set-f"><label htmlFor="mcName">Name</label>
        <input id="mcName" ref={nameRef} className={`set-in${bad === 'name' ? ' bad' : ''}`} placeholder="Order lookup" value={name} aria-invalid={bad === 'name' || undefined}
          onChange={(e) => { setName(e.target.value); if (bad === 'name') { setBad(''); setSay(''); } }} onKeyDown={enter} /></div>
      <div className="set-f"><label htmlFor="mcUrl">Endpoint</label>
        <input id="mcUrl" ref={urlRef} className={`set-in mono${bad === 'url' ? ' bad' : ''}`} inputMode="url" spellCheck={false} autoComplete="off"
          placeholder="https://mcp.your-api.com/mcp" value={url} aria-invalid={bad === 'url' || undefined}
          onChange={(e) => { setUrl(e.target.value); if (bad === 'url') { setBad(''); setSay(''); } }} onKeyDown={enter} /></div>
      <div className="set-f"><label htmlFor="mcTok">Bearer token {typedHdr ? <span className="mcp-kind">per-request header</span> : <span className="muted">optional</span>}</label>
        <input id="mcTok" className="set-in mono" type={typedHdr ? 'text' : 'password'} autoComplete="off" spellCheck={false}
          placeholder={stored ? 'Stored. Leave empty to keep it.' : 'Paste a token, or $headers.Name'} value={tok}
          aria-describedby={typedHdr ? 'mcTokHelp' : undefined} onChange={(e) => setTok(e.target.value)} onKeyDown={enter} />
        {/* said only once a header reference is typed: what it does differs from a token */}
        {typedHdr ? (
          <p className="set-help" id="mcTokHelp">Not stored. The value of the <code>{hdrName || 'Name'}</code> header your app sends with each task is passed to this server on every call.</p>
        ) : null}
        {lacking.length ? (
          <p className="set-help mcp-warn">{lacking.join(', ')} {lacking.length === 1 ? 'does' : 'do'} not take a <code>{hdrName}</code> header yet. Add it in Environment &amp; limits under Headers, or the server gets no token.</p>
        ) : null}
        {!typedHdr && offered.length ? (
          <div className="mcp-hdrs" role="group" aria-label="Use a header your app sends">
            {offered.map((h) => (
              <button key={h} type="button" className="mcp-hdr" onClick={() => setTok(HEADER_REF + h)}>Use the <code>{h}</code> header</button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="mcp-test">
        <button type="button" className="btn small line" disabled={!url.trim() || !!cur?.busy || busy} onClick={() => void runTest()}>Test connection</button>
        <span className={`set-help mcp-st${cur && !cur.busy ? (cur.ok ? ' ok' : ' bad') : ''}`} role="status">
          {cur && !cur.busy ? (cur.ok
            ? <>Connected{cur.server ? <> to <b>{cur.server}</b></> : null} · {cur.tools.length === 1 ? '1 tool' : `${cur.tools.length} tools`}</>
            : cur.error) : null}
          {typedHdr && cur && !cur.busy ? <span className="mcp-st-note"> Tested without a token: the header’s value only comes with each task.</span> : null}
        </span>
      </div>
      {cur?.busy ? (
        <Skel label="Testing the connection" className="mcp-tools">
          {[58, 72, 50].map((w, i) => <div key={i} className="mcp-tool"><SkLine w={`${w * 0.5}%`} h={12} /><SkLine w={`${w}%`} h={10} style={{ marginTop: 6 }} /></div>)}
        </Skel>
      ) : cur && cur.ok && cur.tools.length ? (
        <ul className="mcp-tools" aria-label={`Tools ${cur.server || 'the server'} offers`}>
          {cur.tools.map((t) => (
            <li key={t.name} className="mcp-tool"><b className="mono">{t.name}</b>{t.description ? <small title={t.description}>{t.description}</small> : null}</li>
          ))}
        </ul>
      ) : null}

      {/* editing a server never lists its setups here (Richard, 2026-10-21: "delete Used by"): which setups use it is
          changed from its row on Add-ons; saving keeps them as they are (`to` starts as initialTo and is not touched) */}
      {targets && !server ? (
        <div className="set-f mcp-to">
          <span className="mcp-to-l" id="mcToL">{server ? 'Used by' : 'Add to'}</span>
          {targets.length ? (
            <div className={`pick-list${bad === 'to' ? ' bad' : ''}`} role="group" aria-labelledby="mcToL">
              {targets.map((t) => {
                const on = to.includes(t.id), logo = harnessLogoSrc(t.base);
                return (
                  <button key={t.id} type="button" role="checkbox" aria-checked={on} className={`opt mcp-opt${on ? ' on' : ''}`}
                    onClick={() => { setTo((x) => (on ? x.filter((y) => y !== t.id) : [...x, t.id])); if (bad === 'to') { setBad(''); setSay(''); } }}>
                    <span className="mcp-box" aria-hidden="true">{on ? CHECK : null}</span>
                    {/* eslint-disable-next-line @next/next/no-img-element -- a static brand mark */}
                    {logo ? <img className="h-logo" src={logo} alt="" /> : <span className="h-logo" />}
                    <span className="grow">{t.name}</span>
                  </button>
                );
              })}
            </div>
          ) : <p className="set-help">No setups yet. Make one in Harness Studio first.</p>}
          {dropping.length ? <p className="set-help mcp-warn">Saving removes it from {dropping.join(', ')}.</p> : null}
        </div>
      ) : null}

      {asking ? (
        <div className="mcp-ask" role="alertdialog" aria-labelledby="mcAskT">
          <span id="mcAskT">Remove <b>{name.trim() || server?.name}</b> from {removeWhere}?{targets ? '' : ' It comes off when you save Settings.'}</span>
          <span className="mcp-ask-b">
            <button type="button" className="btn small" disabled={busy} onClick={() => setAsking(false)}>Keep</button>
            <button type="button" className="btn small del-go" disabled={busy} onClick={() => void remove()} autoFocus>Remove</button>
          </span>
        </div>
      ) : null}

      <div className="sheet-actions mcp-act">
        {server && onRemove && !asking ? <button type="button" className="link-q danger mcp-rm" disabled={busy} onClick={() => { setSay(''); setAsking(true); }}>Remove</button> : null}
        <span className={`set-help mcp-say${say ? ' bad' : ''}`} role="status">
          {say}
        </span>
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={busy || asking} onClick={() => void save()}>{server ? 'Save' : next || 'Add MCP server'}</button>
      </div>
    </Sheet>
  );
}
