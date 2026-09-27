// The task's browser, live, in the right pane. It slides in when the agent opens a browser, streams
// the vendor's live view of that browser, and glows the brand blue while the agent is driving it. A
// click on the screen takes the browser over: the view becomes interactive for the person and the
// agent's browser calls are held (each told so) until they hand it back. Closing the pane leaves
// the browser running; the chip in the conversation bar brings the pane back, and the next browser
// the agent opens brings it back on its own.
//
// The live URL is a credential (whoever holds it controls the browser): it is read here through the
// session's own route, kept in component state, and never written anywhere else.
'use client';
import React, { useEffect, useRef, useState } from 'react';
import { harnessFetch } from '@/lib/hfetch';
import { authHeaders } from '@/lib/chat';
import type { BrowserState } from '@/lib/conversation';

export interface BrowserInfo { open: boolean; live_url?: string; control?: string; opened_at?: number | null;
  last_call_at?: number | null; last_tool?: string; calls?: number; session_minutes?: number }

export async function fetchBrowser(sid: string): Promise<BrowserInfo | null> {
  try {
    const r = await harnessFetch(`/api/harness/v1/sessions/${encodeURIComponent(sid)}/browser`, { headers: authHeaders() });
    return r.ok ? (await r.json()) as BrowserInfo : null;
  } catch { return null; }
}
async function setControl(sid: string, control: 'user' | 'agent'): Promise<boolean> {
  try {
    const r = await harnessFetch(`/api/harness/v1/sessions/${encodeURIComponent(sid)}/browser/control`,
      { method: 'POST', headers: { ...authHeaders(), 'content-type': 'application/json' }, body: JSON.stringify({ control }) });
    return r.ok;
  } catch { return false; }
}

/** The vendor's viewer without its own tabs and toolbar: the pane is the chrome. */
function viewerUrl(liveUrl: string): string {
  if (!liveUrl) return '';
  try { const u = new URL(liveUrl); u.searchParams.set('ui', 'false'); return u.toString(); } catch { return liveUrl; }
}

const ACTING_MS = 6000;   // how long after a call the frame counts as "the agent is acting"

export function BrowserPane({ sessionId, live, busy, onClose }: {
  sessionId: string; live: BrowserState | undefined; busy: boolean; onClose: () => void;
}) {
  const [info, setInfo] = useState<BrowserInfo | null>(null);
  const [pending, setPending] = useState(false);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const epoch = live?.epoch ?? 0;
  // The live URL is read once per browser (a new epoch is a new browser with a new URL).
  useEffect(() => {
    let alive = true;
    setInfo(null);
    fetchBrowser(sessionId).then((i) => { if (alive) setInfo(i); });
    return () => { alive = false; };
  }, [sessionId, epoch]);
  // "acting" fades a few seconds after the agent's last call, so the glow follows the work.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live?.open) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [live?.open]);

  const open = live ? live.open : !!info?.open;
  const control: 'agent' | 'user' = live?.control ?? (info?.control === 'user' ? 'user' : 'agent');
  const lastCallAt = live?.lastCallAt ?? ((Number(info?.last_call_at) || 0) * 1000);
  const acting = control === 'agent' && open && (busy || now - lastCallAt < ACTING_MS);
  const held = !!live?.held && control === 'user';
  const src = viewerUrl(info?.live_url || '');

  const takeOver = async () => {
    if (pending || control === 'user') return;
    setPending(true);
    const ok = await setControl(sessionId, 'user');
    setPending(false);
    if (ok) window.setTimeout(() => frameRef.current?.focus(), 50);
  };
  const handBack = async () => {
    if (pending) return;
    setPending(true);
    await setControl(sessionId, 'agent');
    setPending(false);
  };

  const status = !open ? 'Closed'
    : control === 'user' ? (held ? 'You have the browser. The agent is waiting for it.' : 'You have the browser.')
    : acting ? (live?.lastTool ? `The agent is browsing (${live.lastTool})` : 'The agent is browsing')
    : 'The agent has the browser';

  return (
    <div className="fp-panel wbx-browser" role="region" aria-label="Browser">
      <div className="wbx-browser-head">
        <span className={'wbx-live-dot' + (acting ? ' is-on' : control === 'user' ? ' is-user' : open ? ' is-idle' : '')} aria-hidden="true" />
        <div className="wbx-browser-title">
          <b>Browser</b>
          <span className="wbx-browser-status">{status}</span>
        </div>
        {open && control === 'user' && (
          <button type="button" className="wbx-browser-btn is-primary" onClick={handBack} disabled={pending}>Hand back to the agent</button>
        )}
        {open && control === 'agent' && (
          <button type="button" className="wbx-browser-btn" onClick={takeOver} disabled={pending}>Take over</button>
        )}
        <button type="button" className="wbx-browser-close" onClick={onClose} aria-label="Close the browser view" title="Close">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </div>
      {!open ? (
        <div className="wbx-browser-empty">
          <p><b>The browser for this task is closed.</b></p>
          <p>It opens here again the next time the agent uses a browser.</p>
        </div>
      ) : (
        <div className={'wbx-browser-frame' + (control === 'user' ? ' is-user' : ' is-agent') + (acting ? ' is-acting' : '')}>
          {/* View-only while the agent drives: inert blocks focus and keys, the overlay blocks the
              pointer and is the one control, "take over". Both go the moment the person has it. */}
          <div className="wbx-browser-view" inert={control === 'agent' ? true : undefined}>
            {src ? (
              <iframe ref={frameRef} src={src} title="Live browser" allow="autoplay" tabIndex={control === 'agent' ? -1 : 0} />
            ) : (
              <div className="wbx-browser-loading">{info === null ? 'Connecting to the live view' : 'The live view is not available for this browser.'}</div>
            )}
          </div>
          {control === 'agent' && (
            <button type="button" className="wbx-browser-takeover" onClick={takeOver} disabled={pending}
              aria-label="Take over the browser">
              <span className="wbx-browser-pill">
                <span className="wbx-live-dot is-on" aria-hidden="true" />
                {acting ? 'The agent is browsing' : 'The agent has the browser'}
                <em>Click to take over</em>
              </span>
            </button>
          )}
          {control === 'user' && (
            <div className="wbx-browser-pill is-user" aria-live="polite">
              <span className="wbx-live-dot is-user" aria-hidden="true" />
              {held ? 'The agent is waiting for the browser' : 'You have the browser'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
