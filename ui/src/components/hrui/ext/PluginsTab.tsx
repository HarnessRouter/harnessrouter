'use client';
// Add-ons › Plugins (docs/uxuidesign/console-91: libraryView's plugins tab). One search at the top; then
// what the workspace has connected, a row each with the setups that include it; then every plugin that
// can still be connected as a grid. A plugin is connected once for the workspace and each setup includes
// the ones it needs (its Settings, or Add plugin there). Everything listed is the server's (lib/plugs.ts).
//
// Disconnect turns a plugin off for the workspace and keeps its settings and credential: its tile's
// Connect turns it back on as it was. Remove, on its sheet, deletes it and its stored credential.
// Microsoft 365 run as each person signs them in with Microsoft: Microsoft sends the person back to
// the address the workspace's Entra application lists (/plugins, which opens here with the code and
// state it carries), and this tab finishes the sign-in.
import { useEffect, useMemo, useRef, useState } from 'react';
import { microsoftComplete, setPlug } from '@/lib/plugs';
import { toast } from '../toast';
import { ConfirmSheet } from '../Sheet';
import { usedText, ReadFailed } from './shared';
import { Skel, SkRows } from '../Skel';
import {
  plugRows, accountOf, isOn, needsAuth, matches, tileDesc, usedBy, sayRefusal, Logo, SEARCH, Tile, usePlugConnect, type PluginsData, type Row,
} from './pluginParts';

export { usePlugins, type PluginsData } from './pluginParts';

/** Microsoft's answer in the address, when the person comes back from signing in: the code and our
 *  state, or why Microsoft did not finish. Null when the address carries none. */
export function signInReturn(search: string): { code: string; state: string } | { denied: string } | null {
  const q = new URLSearchParams(search);
  const code = q.get('code'), state = q.get('state');
  const denied = q.get('error_description') || q.get('error');
  if (denied && state) return { denied };
  return code && state ? { code, state } : null;
}

/** The address without Microsoft's answer in it, so a reload never sends the same code again. */
function forgetReturn() {
  const q = new URLSearchParams(window.location.search);
  for (const k of ['code', 'state', 'error', 'error_description', 'session_state', 'error_uri']) q.delete(k);
  const qs = q.toString();
  window.history.replaceState(window.history.state, '', window.location.pathname + (qs ? `?${qs}` : ''));
}

export function PluginsTab({ data, workspace }: { data: PluginsData; workspace: string }) {
  const { plugs, uses, reload } = data;
  const [q, setQ] = useState('');
  const [off, setOff] = useState<Row | null>(null);
  const [finishing, setFinishing] = useState(false);
  const { busy, setBusy, connect, manage, sheet } = usePlugConnect(reload);

  // back from Microsoft's sign-in: finished once, whatever the page draws meanwhile
  const returned = useRef(false);
  useEffect(() => {
    if (returned.current) return;
    const r = signInReturn(window.location.search);
    if (!r) return;
    returned.current = true;
    forgetReturn();
    if ('denied' in r) { toast(`Microsoft did not complete the sign-in: ${r.denied}`); return; }
    setFinishing(true);
    microsoftComplete(r.code, r.state)
      .then(async () => { await reload(); toast('Signed in with Microsoft.'); })
      .catch((e: unknown) => toast(sayRefusal(e, 'The sign-in did not finish.')))
      .finally(() => setFinishing(false));
  }, [reload]);

  const rows = useMemo(() => plugRows(plugs), [plugs]);
  const connected = rows.filter((r) => isOn(r.p) || needsAuth(r.p));
  const shownConnected = connected.filter((r) => matches(q, r.name, r.p.type, r.desc));
  const tiles = rows.filter((r) => !(isOn(r.p) || needsAuth(r.p))).filter((r) => matches(q, r.name, r.p.type, r.desc));

  async function disconnect(r: Row) {
    setBusy(r.key);
    try {
      await setPlug(r.p.type, { enabled: false });
      setOff(null); await reload();
      toast(`${r.name} disconnected.`);
    } catch (e) { toast(sayRefusal(e, `${r.name} could not be disconnected.`)); }
    finally { setBusy(''); }
  }

  // a list read before stays on screen when a later read fails; the line above it says so
  const read = plugs !== null;
  const loading = !read && !data.failed;
  const searching = !!q.trim();
  const offUsers = off ? usedBy(uses[off.p.type]) : null;

  return (
    <>
      <div className="pl-q" role="search">
        {SEARCH}
        <input className="dd-q" type="search" value={q} autoComplete="off" spellCheck={false} placeholder="Search plugins" aria-label="Search plugins"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Escape' && q) { e.preventDefault(); setQ(''); } }} />
      </div>

      {data.failed ? <ReadFailed what="plugins" retry={data.retry} /> : null}
      {finishing ? <p className="pl-note" role="status">Finishing your sign-in with Microsoft…</p> : null}
      {loading ? <Skel label="Loading the plugins"><SkRows n={4} /></Skel> : null}

      {read && (!searching || shownConnected.length) ? (
        <section className="pl-sec" aria-labelledby="pl-con-h">
          {/* the count is of the rows under it: all of them, or the ones the search finds */}
          <h2 className="pl-h" id="pl-con-h">Connected <span className="count">{searching ? shownConnected.length : connected.length}</span></h2>
          {shownConnected.length ? (
            <div className="rows">
              {shownConnected.map((r) => {
                const acct = accountOf(r); const used = usedBy(uses[r.p.type]); const lapsed = needsAuth(r.p);
                return (
                  <div key={r.key} className="row lib-g" data-plug={r.p.type}>
                    <span className="t lib-t">
                      <Logo mark={r.mark} name={r.name} size="row" />
                      <span>
                        <b>{r.name}</b>
                        {acct.text ? <small className={`sub2${acct.mono ? ' mono' : ''}${lapsed ? ' pl-warn' : ''}`}>{acct.text}</small> : null}
                        {used !== null ? <small className="lib-used">{usedText(used)}</small> : null}
                      </span>
                    </span>
                    <span className="lib-act">
                      {lapsed
                        ? <button type="button" className="btn small" disabled={busy === r.key || !workspace} onClick={() => manage(r)}>Reconnect</button>
                        : <button type="button" className="btn small line" disabled={busy === r.key || !workspace} onClick={() => manage(r)}>Manage</button>}
                      <button type="button" className="link-q danger" disabled={busy === r.key} onClick={() => setOff(r)}>Disconnect</button>
                    </span>
                  </div>
                );
              })}
            </div>
          ) : <div className="empty-list pl-empty">Nothing connected yet. Connect a plugin below.</div>}
        </section>
      ) : null}

      {read ? (
        <section className="pl-sec" aria-labelledby="pl-all-h">
          <h2 className="pl-h" id="pl-all-h">Available</h2>
          {tiles.length ? (
            <ul className="pl-grid" aria-label="Plugins you can connect">
              {tiles.map((r) => (
                <Tile key={r.key} logo={<Logo mark={r.mark} name={r.name} on={false} size="tile" />} name={r.name} desc={tileDesc(r)}>
                  <button type="button" className="btn small line" aria-label={`Connect ${r.name}`} disabled={busy === r.key || !workspace} onClick={() => connect(r)}>
                    {busy === r.key ? 'Connecting…' : 'Connect'}</button>
                </Tile>
              ))}
            </ul>
          ) : (
            <div className="empty-list pl-empty">{searching && !shownConnected.length ? `Nothing matches “${q.trim()}”.`
              : searching ? `Nothing else to connect matches “${q.trim()}”.` : 'Everything here is connected.'}</div>
          )}
        </section>
      ) : null}

      {sheet}

      {off ? (
        <ConfirmSheet id="ld" title={`Disconnect ${off.name}`} confirmLabel="Disconnect" busy={busy === off.key}
          onClose={() => setOff(null)} onConfirm={() => void disconnect(off)}
          body={offUsers && offUsers.length
            ? <><b>{offUsers.slice(0, 3).join(', ')}{offUsers.length > 3 ? ` and ${offUsers.length - 3} more` : ''}</b> {offUsers.length === 1 ? 'uses' : 'use'} it. Their tasks lose access to {off.name} until you connect it again.</>
            : offUsers ? `No setup uses it. Its settings are kept, so connecting it again is one click.`
              : `Tasks lose access to ${off.name} until you connect it again.`} />
      ) : null}
    </>
  );
}
