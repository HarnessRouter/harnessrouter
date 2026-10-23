'use client';
// A setup's Plugins tab (Settings › Capabilities › Plugins): every plugin this setup can use is a row,
// one tap to include it or leave it out. The workspace's connected plugins (one that waits for a new
// credential or sign-in says so, with Reconnect), and the packages installed on this setup. A switch on
// the right says whether the setup includes it; flipping it writes at once (the setup's plugins binding,
// or the package on the record), the switch waiting while it saves and back where it was when the write
// fails (the caller's toast says why). What the setup includes that the workspace no longer has
// connected (turned off or removed in Add-ons since) is listed too, so it can be left out.
//
// Included first, then the rest, each alphabetical, in the order the tab opened with: a row never moves
// under the finger that flipped it, and one listed only because the setup included it stays, off, so
// it can be switched back. Connect another plugin opens Add plugin at what can still be connected; what
// is connected there shows up here with its switch, marked as just connected.
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import type { Plug } from '@/lib/harness';
import { Skel, SkRows } from '../Skel';
import { toast } from '../toast';
import { accountOf, isOn, Logo, needsAuth, plugRef, plugRows, usePlugConnect, type Row } from '../ext/pluginParts';
import { UNREAD_NAME } from './setupParts';
import { plural } from './settingsModel';

/** What flipping a row writes. */
export type Act = { t: 'plug'; ref: string } | { t: 'package'; name: string };

/** What a row offers besides its switch: reconnect a lapsed credential here, connect it in Add-ons, or
 *  its package to manage. */
export type Fix = { k: 'reconnect'; r: Row } | { k: 'addons' } | { k: 'package'; name: string };

export interface Line {
  key: string;
  act: Act;
  name: string;
  /** the one line under the name: what it is, the account it is on, or what is wrong with it */
  small: string;
  warn: boolean;
  mark?: { src: string; app?: boolean };
  on: boolean;
  /** the workspace cannot serve it now (waiting for a credential, turned off, removed): its mark steps back */
  dim: boolean;
  /** listed only because the setup includes it: once left out it stays listed, off, until the tab closes */
  onlyIncluded: boolean;
  fix: Fix | null;
}

export interface PluginsIn {
  /** the workspace's plugins as the server lists them (lib/plugs listPlugs), null until read */
  plugs: Plug[] | null;
  /** the plugins the setup includes, by type; undefined while it is not read (or could not be) */
  binding: string[] | undefined;
  packages: { name: string; on: boolean; desc: string; left: number }[];
}

const JUST = 'Just connected. Include it in this setup?';
const without = (list: string[], x: string) => list.filter((y) => y !== x);

/** Every row of the tab (unordered): the rule at the top. Workspace plugins only once both they and the
 *  binding are read: a list that is not known is never drawn as nothing included, or disconnected. */
export function pluginLines(p: PluginsIn): Line[] {
  const out: Line[] = [];
  const b = p.binding;
  if (p.plugs && b) {
    const rows = plugRows(p.plugs);
    const listed = new Set<string>();
    for (const r of rows) {
      if (!(isOn(r.p) || needsAuth(r.p))) continue;
      const ref = plugRef(r.p);
      const lapsed = needsAuth(r.p);
      listed.add(ref);
      out.push({
        key: `plug:${ref}`, act: { t: 'plug', ref }, name: r.name, small: accountOf(r).text, warn: lapsed,
        mark: r.mark, on: b.includes(ref), dim: lapsed, onlyIncluded: false, fix: lapsed ? { k: 'reconnect', r } : null,
      });
    }
    // included, but not connected in the workspace now (turned off, or removed)
    for (const ref of b) {
      if (listed.has(ref)) continue;
      const r = rows.find((x) => x.p.type === ref);
      out.push({
        key: `plug:${ref}`, act: { t: 'plug', ref }, name: r?.name || ref,
        small: r?.p.status === 'disabled' ? 'Turned off in this workspace' : 'Not connected in this workspace', warn: true,
        mark: r?.mark, on: true, dim: true, onlyIncluded: true, fix: { k: 'addons' },
      });
    }
  }
  for (const k of p.packages) {
    out.push({
      key: `pkg:${k.name}`, act: { t: 'package', name: k.name }, name: k.name, small: k.left ? `${plural(k.left, 'part')} not loaded` : k.desc, warn: k.left > 0,
      on: k.on, dim: false, onlyIncluded: false, fix: { k: 'package', name: k.name },
    });
  }
  return out;
}

/** Whether the workspace has no plugin connected. Not known (null) while it is not read. */
export function nothingConnected(p: PluginsIn): boolean | null {
  if (!p.plugs) return null;
  return !p.plugs.some((w) => isOn(w) || needsAuth(w));
}

export function PluginSwitches({ input, setup, q, busy, failed, lost, onSet, onPackage, onManagePackage, onConnect, reload }: {
  input: PluginsIn;
  /** the setup's name, for each switch's label */
  setup: string;
  /** the tab's search */
  q: string;
  /** a change is being written: the switches wait for it */
  busy: boolean;
  /** the workspace's plugins could not be read: said in their place, with Try again */
  failed?: { retry: () => void } | null;
  /** the binding could not be read: said on its own row, with Try again */
  lost?: { retry: () => void } | null;
  /** write the plugins the setup includes (none left detaches them); each says its own failure and answers false */
  onSet: (plugs: string[]) => Promise<boolean>;
  onPackage: (name: string, on: boolean) => Promise<boolean>;
  onManagePackage: (name: string) => void;
  /** opens Add plugin at what can still be connected */
  onConnect: () => void;
  /** read the workspace's plugins again (a credential renewed here) */
  reload: () => Promise<void>;
}) {
  const [pending, setPending] = useState<{ key: string; want: boolean } | null>(null);
  const group = useRef(new Map<string, number>());     // 0 included, 1 the rest: as each row first showed
  const seen = useRef(new Map<string, Line>());         // every row shown since the tab opened
  const before = useRef<Set<string> | null>(null);      // the rows there when Connect another plugin was pressed
  const plug = usePlugConnect(reload);

  const b = input.binding;
  const ready = !!(input.plugs && b);
  const lines = pluginLines(input);
  const keys = new Set(lines.map((x) => x.key));
  // a row that went with its switch stays, off, so the flip can be undone (only while the binding is known)
  const kept = ready ? [...seen.current.values()].filter((x) => x.onlyIncluded && !keys.has(x.key)).map((x) => ({ ...x, on: false, fix: null })) : [];
  const all = [...lines, ...kept];
  useEffect(() => {
    for (const x of lines) {
      if (!group.current.has(x.key)) group.current.set(x.key, x.on ? 0 : 1);
      seen.current.set(x.key, x);
    }
  });
  const g = (x: Line) => group.current.get(x.key) ?? (x.on ? 0 : 1);
  const ql = q.trim().toLowerCase();
  const shown = all.filter((x) => !ql || x.name.toLowerCase().includes(ql) || x.small.toLowerCase().includes(ql))
    .sort((x, y) => g(x) - g(y) || x.name.localeCompare(y.name, undefined, { sensitivity: 'base' }));

  async function write(x: Line, want: boolean): Promise<boolean> {
    const a = x.act;
    if (a.t === 'package') return onPackage(a.name, want);
    if (!b) return false;
    return onSet(want ? [...without(b, a.ref), a.ref] : without(b, a.ref));
  }
  async function flip(x: Line) {
    if (pending || busy) return;
    const want = !x.on;
    setPending({ key: x.key, want });
    try { await write(x, want); }
    catch { toast(`${x.name} was not changed. Try again.`); }      // the calls say their own failures; anything else is said here
    finally { setPending(null); }
  }
  const connect = () => { before.current = ready ? new Set(all.map((x) => x.key)) : null; onConnect(); };

  const fixOf = (x: Line) => {
    const f = x.fix;
    if (!f) return null;
    if (f.k === 'reconnect') return <button type="button" className="link-q inl" disabled={plug.busy === f.r.key} onClick={() => plug.connect(f.r)}>Reconnect</button>;
    if (f.k === 'addons') return <Link className="link-q inl" href="/extensions">Open Add-ons</Link>;
    return <button type="button" className="link-q inl" onClick={() => onManagePackage(f.name)}>Manage</button>;
  };

  const row = (x: Line) => {
    const wait = pending?.key === x.key;
    const on = wait ? pending.want : x.on;
    const fresh = !on && !!before.current && !before.current.has(x.key);
    const small = fresh && !x.warn ? JUST : x.small;
    const fix = fixOf(x);
    return (
      <div key={x.key} className={`cap-row${on ? '' : ' off'}${fresh ? ' pl-fresh' : ''}`}>
        <Logo mark={x.mark} name={x.name} on={!x.dim} size="cap" />
        <span className="grow">
          <b>{x.name}</b>
          {small ? <small className={x.warn ? 'warn' : undefined}>{small}</small> : null}
          {fix ? <span className="pl-sw-fix">{fix}</span> : null}
        </span>
        <button type="button" role="switch" aria-checked={on} aria-busy={wait || undefined} aria-label={`Include ${x.name} in ${setup}`}
          className={`tog${on ? ' on' : ''}${wait ? ' wait' : ''}`} disabled={busy || !!pending} onClick={() => void flip(x)}>
          <i />{on ? 'On' : 'Off'}</button>
      </div>
    );
  };

  const empty = nothingConnected(input);
  const canConnect = ready && !failed;
  const loading = !failed && !lost && !ready;
  return (
    <>
      {failed ? (
        <div className="empty-list ld-fail" role="alert">
          Your plugins could not be loaded just now.{' '}
          <button type="button" className="link-q inl" onClick={failed.retry}>Try again</button>
        </div>
      ) : null}
      {shown.length || lost ? (
        <div className={`cap-list pl-sw${pending ? ' pl-sw-saving' : ''}`}>
          {shown.map(row)}
          {lost && !ql ? (
            <div className="cap-row off">
              <Logo name={UNREAD_NAME} on={false} size="cap" />
              <span className="grow"><b>{UNREAD_NAME}</b><small className="warn">They could not be read just now.</small>
                <span className="pl-sw-fix"><button type="button" className="link-q inl" onClick={lost.retry}>Try again</button></span></span>
            </div>
          ) : null}
        </div>
      ) : null}
      {loading ? <Skel label="Loading your plugins"><SkRows n={3} /></Skel> : null}
      {ql && !shown.length ? <p className="set-help cap-none">Nothing matches.</p> : null}
      {empty && !ql ? (
        <p className="pl-sw-foot">No plugins are connected in this workspace yet.{canConnect ? <> <button type="button" className="link-q inl" onClick={connect}>Connect a plugin</button></> : null}</p>
      ) : canConnect && !ql ? (
        <p className="pl-sw-foot"><button type="button" className="link-q inl" onClick={connect}>Connect another plugin</button></p>
      ) : null}
      {plug.sheet}
    </>
  );
}
