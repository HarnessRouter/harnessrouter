'use client';
// The workspace menu's two sheets, opened from its "New workspace" and "Workspace settings".
//
// New workspace: a name field and "Create workspace". Whatever the server refuses is said under the
// name, in its own words. A created workspace is switched to and the page reloads on Start; its
// "is ready." toast survives the reload.
//
// Workspace settings, one sheet: the workspace's name and description, and its Cloud upload, inline as
// compact rows (WsSettings.tsx), with no page of its own (/settings opens this sheet).
import { useCallback, useEffect, useRef, useState } from 'react';
import { useWorkspace } from '@/lib/workspace';
import { Sheet, SheetTop } from './Sheet';
import { WsBadge } from './ws';
import { toast } from './toast';
import { CloudUploadRow, WsProfile } from './WsSettings';

export type WsSheet = 'people' | 'newws' | null;

/** Opens "Workspace settings" from anywhere in the console. An address with ?sheet=people opens it too
 *  (the /settings page sends people there). */
export const PEOPLE_EVENT = 'hrui:people';
export function openPeopleSheet(): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(PEOPLE_EVENT));
}

/** Opens the workspace menu (the workspaces, Workspace settings, New workspace) under the element
 *  that asks for it: the rail's workspace button, or Studio's workspace name, as the design does. */
export const WS_MENU_EVENT = 'hrui:wsmenu';
export function openWorkspaceMenu(anchor: HTMLElement): void {
  window.dispatchEvent(new CustomEvent<{ anchor: HTMLElement }>(WS_MENU_EVENT, { detail: { anchor } }));
}

const NOTE_KEY = 'hrui.toast.next';      // a toast for the page a reload lands on
const LAND = '/start';                   // where a new workspace lands (the design: go('start'))

const ssGet = (k: string) => { try { return sessionStorage.getItem(k) || ''; } catch { return ''; } };
const ssSet = (k: string, v: string) => { try { if (v) sessionStorage.setItem(k, v); else sessionStorage.removeItem(k); } catch { /* private mode */ } };

/** The shell's sheet state: which sheet is open, opened by the menu or by PEOPLE_EVENT; also shows
 *  the toast a create left for the page it reloaded onto. */
export function useWorkspaceSheets(): [WsSheet, (s: WsSheet) => void] {
  const [sheet, setSheet] = useState<WsSheet>(null);
  useEffect(() => {
    const on = () => setSheet('people');
    window.addEventListener(PEOPLE_EVENT, on);
    // ?sheet=people: open it here, and take the word out of the address so a reload does not reopen it
    const u = new URL(window.location.href);
    if (u.searchParams.get('sheet') === 'people') {
      setSheet('people');
      u.searchParams.delete('sheet');
      window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash);
    }
    // a frame later, so the toast host is listening; read and cleared only when shown
    const raf = requestAnimationFrame(() => { const note = ssGet(NOTE_KEY); if (note) { ssSet(NOTE_KEY, ''); toast(note); } });
    return () => { window.removeEventListener(PEOPLE_EVENT, on); cancelAnimationFrame(raf); };
  }, []);
  return [sheet, setSheet];
}

const X = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
);

/** The design's badField: the toast says what is wrong, and the field is marked and focused. */
function useBad(): [string, (id: string, el: HTMLInputElement | null, msg: string) => void, () => void] {
  const [bad, setBad] = useState('');
  const mark = useCallback((id: string, el: HTMLInputElement | null, msg: string) => { toast(msg); setBad(id); el?.focus(); }, []);
  const clear = useCallback(() => setBad(''), []);
  return [bad, mark, clear];
}

const sameName = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

// ── New workspace ────────────────────────────────────────────────────────────────────────────

export function NewWorkspaceSheet({ onClose }: { onClose: () => void }) {
  const { workspaces, create } = useWorkspace();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [bad, markBad, clearBad] = useBad();
  // the server's refusal, said under the name
  const [refused, setRefused] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement | null>(null);

  async function go() {
    if (busy) return;
    const nm = name.trim();
    if (!nm) { markBad('nwName', nameRef.current, 'Give the workspace a name.'); return; }
    if (workspaces.some((w) => w.id && sameName(w.name, nm))) { markBad('nwName', nameRef.current, `You already have a workspace named ${nm}.`); return; }
    setBusy(true); setRefused(null);
    try {
      await create(nm);       // the new workspace becomes the current one
      ssSet(NOTE_KEY, `${nm} is ready.`);
      // a full load, so every surface reads the new workspace (the menu's switch does the same)
      window.location.assign(LAND);
    } catch (e) {
      // the server's own words, never a limit of ours
      setBusy(false);
      setRefused(e instanceof Error && e.message ? e.message : 'The workspace could not be created. Try again in a moment.');
      nameRef.current?.focus();
    }
  }

  return (
    <Sheet onClose={onClose} labelledBy="nwh" className="small-sheet" busy={busy} initialFocus={nameRef}>
      <SheetTop id="nwh" title="New workspace" onClose={onClose} />
      <div className="keyrow">
        <label className="sr" htmlFor="nwName">Workspace name</label>
        <input id="nwName" ref={nameRef} className={`keyname plain${bad === 'nwName' ? ' bad' : ''}`} aria-invalid={bad === 'nwName' || undefined}
          aria-describedby={refused ? 'nwWhy' : undefined} placeholder="Workspace name" autoComplete="off" maxLength={80} value={name}
          onChange={(e) => { setName(e.target.value); clearBad(); }}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void go(); } }} />
      </div>
      {refused ? (
        <p className="kb-why" id="nwWhy" role="alert">{refused}</p>
      ) : null}
      <div className="sheet-actions">
        <button type="button" className="btn primary" disabled={busy} onClick={() => void go()}>Create workspace</button>
      </div>
    </Sheet>
  );
}

// ── Workspace settings ───────────────────────────────────────────────────────────────────────

export function PeopleSheet({ onClose }: { onClose: () => void }) {
  const { current } = useWorkspace();
  const [saving, setSaving] = useState(false);

  return (
    <Sheet onClose={onClose} labelledBy="wsh" className="small-sheet ws-sheet" busy={saving} initialFocus="dialog">
      <div className="sheet-top">
        <div className="ws-sheet-h">
          <WsBadge name={current.name} size={36} />
          <h3 id="wsh">{current.name}</h3>
        </div>
        <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>{X}</button>
      </div>
      <div className="ins-h ws-set-h">Settings</div>
      <WsProfile onSaving={setSaving} />
      <CloudUploadRow />
    </Sheet>
  );
}
