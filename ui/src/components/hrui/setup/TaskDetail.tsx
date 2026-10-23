'use client';
// The task open on a setup's Tasks tab (docs/uxuidesign/console-91: taskPane, newPane, delTaskHtml,
// shareTaskHtml, stopTask): the one bar over the reading column (its title, Stop task or Share). A
// self-hosted console shows a task as its conversation; the trace view is the hosted product's. Delete task is on the task's row in the list (Richard 10-18),
// asking here (DeleteTask). Everything shown is read from the task itself: its card and its trace.
import { useEffect, useRef, useState } from 'react';
import { harnessFetch } from '@/lib/hfetch';
import { authHeaders, cancelSession } from '@/lib/chat';
import { deleteSession } from '@/lib/harness';
import type { TraceCard } from '@/lib/revamp-data';
import { feedTurnOf, useFeedTurns } from '@/lib/conversation';
import { ConfirmSheet, Sheet, SheetTop } from '../Sheet';
import { toast } from '../toast';
import { cutWords, liveStateOf, preview } from './fmt';
import { BACK_IC } from './parts';


const LINK = <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1" /><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1" /></svg>;
const CHECK = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} aria-hidden="true"><path d="M5 12l5 5L20 7" /></svg>;
const PRIVATE = <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>;
const PUBLIC = <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></svg>;

/** A task's title, as the list and the bar show it. */
export function titleOf(c: TraceCard): string {
  const t = String(c.title || '').trim();
  if (t) return t;
  const p = preview(String(c.user_prompt || '')).slice(0, 90);
  return p || 'Untitled task';
}

async function copyText(text: string, ok = 'Copied'): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); toast(ok); return true; }
  catch { toast('Couldn’t copy automatically. Press Cmd or Ctrl + C.'); return false; }
}

interface ShareState { enabled: boolean; token: string }

function ShareSheet({ sid, state, onState, onClose }: {
  sid: string; state: ShareState | null; onState: (s: ShareState) => void; onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const inRef = useRef<HTMLInputElement | null>(null);
  const on = !!state?.enabled;
  const set = async (want: boolean) => {
    if (busy || (state && want === on)) return;
    setBusy(true);
    try {
      const r = await harnessFetch(`/api/harness/v1/sessions/${encodeURIComponent(sid)}/share`, {
        method: 'POST', headers: authHeaders(), body: JSON.stringify({ enabled: want }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(String(r.status));
      onState({ enabled: Boolean(d.enabled), token: String(d.token || '') });
      if (!want) toast('Link turned off');
    } catch { toast('Sharing could not be changed. Try again.'); }
    setBusy(false);
  };
  const link = on && state?.token ? `${window.location.origin}/share/${state.token}` : '';
  const copyLink = async () => {
    if (await copyText(link, 'Link copied')) return;
    inRef.current?.focus(); inRef.current?.select();
  };
  const ch = (v: boolean, ic: React.ReactNode, title: string, sub: string) => {
    const sel = !!state && v === on;
    return (
      <button type="button" className={'share-ch' + (sel ? ' on' : '')} aria-pressed={sel} disabled={busy} onClick={() => void set(v)}>
        <span className="share-ic">{ic}</span><span><b>{title}</b><small>{sub}</small></span><span className="share-ok">{sel ? CHECK : null}</span>
      </button>
    );
  };
  return (
    <Sheet onClose={onClose} labelledBy="shth" className="small-sheet share-sheet">
      <SheetTop id="shth" title="Share task" onClose={onClose} />
      <div className="share-list">
        {ch(false, PRIVATE, 'Keep private', 'Only those who can sign in here can see it')}
        {ch(true, PUBLIC, 'Create public link', 'Anyone with the link can read the conversation and download its files')}
      </div>
      {link ? (
        <div className="share-link">
          <label className="sr" htmlFor="shareUrl">Public link</label>
          <input ref={inRef} id="shareUrl" className="set-in mono" readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
          <button type="button" className="btn" onClick={() => void copyLink()}>Copy</button>
        </div>
      ) : null}
      <div className="sheet-actions share-done"><button type="button" className="btn primary" onClick={onClose}>Done</button></div>
    </Sheet>
  );
}

/** Delete task (delTaskHtml), from the task's row: it goes with its conversation, files and trace,
 *  after one confirm. Whether its public link would stop working is read as the sheet opens; a read
 *  that fails is said (never read as "not shared"). */
export function DeleteTask({ card, onClose, onGone }: { card: TraceCard; onClose: () => void; onGone: (sid: string) => void }) {
  const sid = card.session_id;
  const [shared, setShared] = useState<boolean | 'unknown' | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    harnessFetch(`/api/harness/v1/sessions/${encodeURIComponent(sid)}/share`, { headers: authHeaders() })
      .then((x) => { if (!x.ok) throw new Error(String(x.status)); return x.json(); })
      .then((d) => { if (alive) setShared(Boolean(d?.enabled)); })
      .catch(() => { if (alive) setShared('unknown'); });
    return () => { alive = false; };
  }, [sid]);
  const del = async () => {
    setBusy(true);
    try {
      await deleteSession(sid);
      toast('Task deleted');
      onClose();
      onGone(sid);
    } catch {
      toast('The task could not be deleted. Try again.');
      setBusy(false);
    }
  };
  return (
    <ConfirmSheet id="dt" title="Delete task" confirmLabel="Delete task" focusConfirm busy={busy}
      body={<><b>{cutWords(titleOf(card), 60)}</b> is removed with its conversation and files.{shared === true ? ' Its public link stops working.' : shared === 'unknown' ? ' Whether it has a public link could not be checked.' : ''} This can’t be undone.</>}
      onConfirm={() => void del()} onClose={onClose} />
  );
}

/** The New task pane's bar (newPane): back to the list on a phone, and its name. */
export function NewTaskHead({ onBack }: { onBack: () => void }) {
  return (
    <div className="task-head tp-head tp-new">
      <div className="th-row">
        <button type="button" className="tk-back" aria-label="All tasks" onClick={onBack}>{BACK_IC}</button>
        <h2 className="tp-t">New task</h2>
      </div>
    </div>
  );
}

/** The open task's one bar over the reading column (taskPane): back to the list on a phone, its
 *  title, the Browser control when the setup includes the browser plugin
 *  (setup/BrowserSlot), and Stop task while it runs (the feed's word first, as its row's dot), else
 *  Share. Who sent it is on its message and what it took follows each reply. A test sent a
 *  moment ago that has no task yet (no session id) shows its title alone: its actions come
 *  once it has one (never drawn disabled before). */
export function TaskHead({ card, onStopped, onBack, browser }: {
  card: TraceCard;
  onStopped: (sid: string) => void; onBack: () => void;
  /** the Browser control, when the setup includes the browser plugin */
  browser?: React.ReactNode;
}) {
  const sid = card.session_id;
  useFeedTurns();
  const running = liveStateOf(card, feedTurnOf(sid)) === 'running';
  const [share, setShare] = useState<ShareState | null>(null);
  useEffect(() => {
    let alive = true;
    setShare(null);
    if (!sid) return undefined;
    harnessFetch(`/api/harness/v1/sessions/${encodeURIComponent(sid)}/share`, { headers: authHeaders() })
      .then((x) => (x.ok ? x.json() : null))
      .then((d) => { if (alive && d) setShare({ enabled: Boolean(d.enabled), token: String(d.token || '') }); })
      .catch(() => { /* the button reads Share */ });
    return () => { alive = false; };
  }, [sid]);
  const [sharing, setSharing] = useState(false);
  const [stopping, setStopping] = useState(false);
  useEffect(() => { if (!running) setStopping(false); }, [running]);

  const title = titleOf(card);

  const stop = async () => {
    if (stopping) return;
    setStopping(true);
    const v = await cancelSession(sid).catch(() => ({ cancelled: false, status: '' }));
    if (v.cancelled) toast('Task stopped');
    else if (!v.status) { toast('The task could not be stopped. Try again.'); setStopping(false); return; }
    onStopped(sid);
  };
  return (
    <div className="task-head tp-head">
      <div className="th-row">
        <button type="button" className="tk-back" aria-label="All tasks" onClick={onBack}>{BACK_IC}</button>
        <h2 className="tp-t" title={title}>{title}</h2>
        <div className="tk-acts">
          {sid ? browser : null}
          {!sid ? null : running ? (
            <button type="button" className="btn small tk-stop" disabled={stopping} onClick={() => void stop()}>Stop task</button>
          ) : (
            <button type="button" className={'icon-btn tk-ib tk-share' + (share?.enabled ? ' on' : '')} aria-label={share?.enabled ? 'Shared publicly. Manage the link' : 'Share task'}
              title={share?.enabled ? 'Shared publicly' : 'Share task'} onClick={() => setSharing(true)}>{LINK}</button>
          )}
        </div>
      </div>
      {sharing ? <ShareSheet sid={sid} state={share} onState={setShare} onClose={() => setSharing(false)} /> : null}
    </div>
  );
}

