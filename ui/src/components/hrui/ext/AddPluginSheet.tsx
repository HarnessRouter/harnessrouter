'use client';
// A setup's Add plugin (Settings › Capabilities › Plugins): the same search, Connected and grid as Add-ons
// › Plugins. What the workspace has connected is listed with an Include switch for this setup; then
// every plugin that can still be connected, whose Connect runs the same flow as Add-ons and then offers
// Include. Including writes the setup's binding at once (the caller's onSet: the plugins it includes,
// by type, POST /v1/harnesses/{id}/servers/plugs; none left detaches them).
import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { Sheet, SheetTop } from '../Sheet';
import { Skel, SkRows } from '../Skel';
import {
  usePlugins, plugRows, plugRef, accountOf, isOn, needsAuth, matches, tileDesc, Logo, SEARCH, Tile, usePlugConnect, type Row,
} from './pluginParts';
import { ReadFailed } from './shared';

/** What a setup includes: its plugins, each by its type. */
export interface Binding { plugs: string[] }

export function AddPluginSheet({ workspace, setup, binding, busy, focus, onSet, onInstall, onChanged, onClose }: {
  workspace: string;
  /** the setup's name, for each switch's label */
  setup: string;
  binding: Binding;
  /** a change to the setup is being written: the switches wait for it */
  busy: boolean;
  /** 'available': it opens at what can still be connected (a setup's Plugins tab lists the connected ones
   *  with their switches, so its Connect another plugin opens here at the rest) */
  focus?: 'available';
  /** write the plugins the setup includes; resolves false when it did not take (the caller says why) */
  onSet: (plugs: string[]) => Promise<boolean>;
  /** a package of tools and skills in the Agent Plugins format, from a folder on this computer */
  onInstall?: () => void;
  /** the workspace's plugins changed here (one connected): the setup reads them again */
  onChanged?: () => void;
  onClose: () => void;
}) {
  const data = usePlugins(workspace, { counts: false });
  const { plugs } = data;
  const reload = async () => { await data.reload(); onChanged?.(); };
  const [q, setQ] = useState('');
  const [fresh, setFresh] = useState<string[]>([]);          // just connected here: offered to include
  const plugConnect = usePlugConnect(reload, (type) => setFresh((f) => (f.includes(type) ? f : [...f, type])));

  const rows = useMemo(() => plugRows(plugs), [plugs]);
  const lines = rows.filter((r) => isOn(r.p) || needsAuth(r.p));
  const shown = lines.filter((r) => matches(q, r.name, r.p.type, r.desc));
  const items = rows.filter((r) => !(isOn(r.p) || needsAuth(r.p))).filter((r) => matches(q, r.name, r.p.type, r.desc));

  const toggle = (r: Row) => {
    const ref = plugRef(r.p);
    const on = binding.plugs.includes(ref);
    void onSet(on ? binding.plugs.filter((x) => x !== ref) : [...binding.plugs, ref]);
  };

  const read = plugs !== null;
  const loading = !read && !data.failed;
  const searching = !!q.trim();
  // opened at Available: once the Connected rows above it are drawn, scrolled to it (once)
  const availRef = useRef<HTMLElement | null>(null);
  const atAvail = useRef(false);
  useEffect(() => {
    if (focus !== 'available' || atAvail.current || !read) return;
    atAvail.current = true;
    availRef.current?.scrollIntoView?.({ block: 'start' });
  }, [focus, read]);

  const lineView = (r: Row) => {
    const on = binding.plugs.includes(plugRef(r.p));
    const lapsed = needsAuth(r.p);
    const just = fresh.includes(r.p.type);
    const small = lapsed ? accountOf(r).text : just ? 'Just connected. Include it in this setup?' : accountOf(r).text;
    return (
      <div key={r.key} className={`cap-row${just ? ' pl-fresh' : ''}`} data-plug={r.p.type}>
        <Logo mark={r.mark} name={r.name} size="cap" />
        <span className="grow"><b>{r.name}</b>{small ? <small className={lapsed ? 'warn' : undefined}>{small}</small> : null}</span>
        <button type="button" className={`tog${on ? ' on' : ''}`} aria-pressed={on} aria-label={`Include ${r.name} in ${setup}`} disabled={busy} onClick={() => toggle(r)}>
          <i />{on ? 'Included' : 'Include'}</button>
      </div>
    );
  };

  return (
    <Sheet onClose={onClose} labelledBy="aph" className="pl-add" busy={busy}>
      <SheetTop id="aph" title="Add plugin" onClose={onClose} />
      <div className="pl-q" role="search">
        {SEARCH}
        <input className="dd-q" type="search" value={q} autoComplete="off" spellCheck={false} placeholder="Search plugins" aria-label="Search plugins"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Escape' && q) { e.preventDefault(); e.stopPropagation(); setQ(''); } }} />
      </div>

      {data.failed ? <ReadFailed what="plugins" retry={data.retry} /> : null}
      {loading ? <Skel label="Loading your plugins"><SkRows n={3} /></Skel> : read && (!searching || shown.length) ? (
        <section className="pl-sec" aria-labelledby="ap-con-h">
          <h2 className="pl-h" id="ap-con-h">Connected <span className="count">{shown.length}</span></h2>
          {shown.length ? <div className="cap-list">{shown.map(lineView)}</div>
            : <div className="empty-list pl-empty">Nothing connected yet. Connect a plugin below.</div>}
        </section>
      ) : null}

      {read ? (
        <section className="pl-sec" aria-labelledby="ap-all-h" ref={availRef}>
          <h2 className="pl-h" id="ap-all-h">Available</h2>
          {items.length ? (
            <ul className="pl-grid pl-grid-sheet" aria-label="Plugins you can connect">
              {items.map((r) => (
                <Tile key={r.key} logo={<Logo mark={r.mark} name={r.name} on={false} size="tile" />} name={r.name} desc={tileDesc(r)}>
                  <button type="button" className="btn small line" aria-label={`Connect ${r.name}`} disabled={plugConnect.busy === r.key || !workspace} onClick={() => plugConnect.connect(r)}>
                    {plugConnect.busy === r.key ? 'Connecting…' : 'Connect'}</button>
                </Tile>
              ))}
            </ul>
          ) : (
            <div className="empty-list pl-empty">{searching && !shown.length ? `Nothing matches “${q.trim()}”.`
              : searching ? `Nothing else to connect matches “${q.trim()}”.` : 'Everything here is connected.'}</div>
          )}
        </section>
      ) : null}

      <div className="sheet-actions pl-add-foot">
        <Link className="btn" href="/extensions">Open Add-ons</Link>
        {onInstall ? <button type="button" className="btn" disabled={busy} onClick={onInstall}>Install from folder</button> : null}
      </div>
      {plugConnect.sheet}
    </Sheet>
  );
}
