// The task's browser, live, as one floating card: an action row on top (who has it, take over or
// hand back, full screen, float, close) and the vendor's live view filling the rest. The card glows
// the brand blue while the agent has the browser, breathing while it acts; a click on the screen
// or the button takes it over, after which the view is the person's and the agent's next browser
// call waits for the hand-back. The card docks beside the conversation, fills the window, or
// floats over the page and can be dragged by its top row.
//
// The live URL is a credential (whoever holds it controls the browser): it is read through the
// session's own route, kept in component state, and never written anywhere else.
'use client';
import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { harnessFetch } from '@/lib/hfetch';
import { authHeaders } from '@/lib/chat';
import { getPaneState, setPaneState, type BrowserState, type PaneMode } from '@/lib/conversation';

export interface BrowserInfo { open: boolean; live_url?: string; control?: string; opened_at?: number | null;
  last_call_at?: number | null; last_tool?: string; calls?: number; session_minutes?: number }

export async function fetchBrowser(sid: string): Promise<BrowserInfo | null> {
  if (!sid) return null;
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

/** The vendor's viewer without its own tabs and toolbar: the card's row is the chrome. */
function viewerUrl(liveUrl: string): string {
  if (!liveUrl) return '';
  try { const u = new URL(liveUrl); u.searchParams.set('ui', 'false'); return u.toString(); } catch { return liveUrl; }
}

const ACTING_MS = 6000;   // how long after a call the card counts as "the agent is acting"

const Icon = ({ d }: { d: string }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
const ICONS = {
  close: 'M6 6l12 12M18 6L6 18',
  full: 'M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3',
  restore: 'M9 3H4v5M15 3h5v5M9 21H4v-5M15 21h5v-5',
  float: 'M4 8V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-2M4 12h8a2 2 0 0 1 2 2v6H4z',
  dock: 'M4 5h16v14H4zM14 5v14',
};

/** A cursor that stands where the agent last acted and glides there along a small arc when the
 *  point moves, with a ring on a click. Page coordinates map onto the stream assuming the vendor's
 *  viewer fits the page to the stream's width from the top, which is how it letterboxes. */
function GhostCursor({ point, viewport, tool, at, host }: {
  point: { x: number; y: number }; viewport: { w: number; h: number }; tool: string; at: number; host: React.RefObject<HTMLDivElement | null>;
}) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [ring, setRing] = useState(0);
  const from = useRef<{ x: number; y: number } | null>(null);
  const raf = useRef(0);
  useEffect(() => {
    const el = host.current; if (!el) return;
    const scale = el.clientWidth / Math.max(1, viewport.w);
    const target = { x: point.x * scale, y: point.y * scale };
    // the first point is reached from the middle of the screen, so the cursor is seen arriving
    const start = from.current || { x: el.clientWidth / 2, y: el.clientHeight / 2 };
    cancelAnimationFrame(raf.current);
    // a quadratic arc: the control point sits off the straight line, to the side, a quarter of the way
    const dx = target.x - start.x, dy = target.y - start.y, len = Math.hypot(dx, dy) || 1;
    const ctrl = { x: (start.x + target.x) / 2 - dy / len * Math.min(90, len * 0.25), y: (start.y + target.y) / 2 + dx / len * Math.min(90, len * 0.25) };
    const dur = Math.min(900, 350 + len * 0.8); const t0 = performance.now();
    const step = (now: number) => {
      const u = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - u, 3);   // ease-out
      const x = (1 - e) * (1 - e) * start.x + 2 * (1 - e) * e * ctrl.x + e * e * target.x;
      const y = (1 - e) * (1 - e) * start.y + 2 * (1 - e) * e * ctrl.y + e * e * target.y;
      setPos({ x, y });
      if (u < 1) raf.current = requestAnimationFrame(step); else { from.current = target; if (tool === 'click') setRing((n) => n + 1); }
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [point.x, point.y, viewport.w, at, tool, host]);
  if (!pos) return null;
  return (
    <div className="wbx-ghost" style={{ transform: `translate(${pos.x}px, ${pos.y}px)` }} aria-hidden="true">
      {ring > 0 && <span key={ring} className="wbx-ghost-ring" />}
      <svg width="24" height="24" viewBox="0 0 24 24"><path d="M5 3l14 8.5-6.2 1.3L16 20l-2.6 1.1-3.2-7.3L5 18.5z" fill="#fff" stroke="var(--brand)" strokeWidth="1.6" strokeLinejoin="round" /></svg>
    </div>
  );
}

export function BrowserPane({ harnessId, sessionId, live, busy, mode, onClose }: {
  harnessId: string; sessionId: string; live: BrowserState | undefined; busy: boolean; mode: PaneMode; onClose: () => void;
}) {
  const [info, setInfo] = useState<BrowserInfo | null>(null);
  const [pending, setPending] = useState(false);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const streamRef = useRef<HTMLDivElement>(null);
  const epoch = live?.epoch ?? 0;
  // The live URL is read once per browser (a new epoch is a new browser with a new URL).
  useEffect(() => {
    let alive = true;
    setInfo(null);
    fetchBrowser(sessionId).then((i) => { if (alive) setInfo(i); });
    return () => { alive = false; };
  }, [sessionId, epoch]);
  const open = live ? live.open : !!info?.open;
  // "acting" fades a few seconds after the agent's last call, so the glow follows the work.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live?.open) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [live?.open]);

  const control: 'agent' | 'user' = live?.control ?? (info?.control === 'user' ? 'user' : 'agent');
  const lastCallAt = live?.lastCallAt ?? ((Number(info?.last_call_at) || 0) * 1000);
  const acting = control === 'agent' && open && (busy || now - lastCallAt < ACTING_MS);
  const held = !!live?.held && control === 'user';
  const src = viewerUrl(info?.live_url || '');

  const takeOver = async () => {
    if (pending || control === 'user' || !open) return;
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
  const setMode = (m: PaneMode) => setPaneState(harnessId, { mode: m });

  // Floating: dragged by its top row, kept inside the window.
  const pane = getPaneState(harnessId);
  const [pos, setPos] = useState(() => pane.float);
  useEffect(() => {
    if (mode !== 'float') return;
    const p = getPaneState(harnessId).float;
    const w = Math.min(p.w, window.innerWidth - 24), h = Math.min(p.h, window.innerHeight - 24);
    const x = p.x < 0 ? window.innerWidth - w - 24 : Math.min(p.x, window.innerWidth - w), y = p.y < 0 ? window.innerHeight - h - 24 : Math.min(p.y, window.innerHeight - h);
    setPos({ x, y, w, h });
  }, [mode, harnessId]);
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  const onBarPointerDown = (e: React.PointerEvent) => {
    if (mode !== 'float' || (e.target as HTMLElement).closest('button')) return;
    drag.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onBarPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const x = Math.max(0, Math.min(e.clientX - drag.current.dx, window.innerWidth - pos.w));
    const y = Math.max(0, Math.min(e.clientY - drag.current.dy, window.innerHeight - 48));
    setPos((p) => ({ ...p, x, y }));
  };
  const onBarPointerUp = () => { if (drag.current) { drag.current = null; setPaneState(harnessId, { float: pos }); } };

  const status = !open ? 'Not open'
    : control === 'user' ? (held ? 'You have the browser. The agent is waiting.' : 'You have the browser.')
    : acting ? (live?.lastTool ? `The agent is browsing (${live.lastTool})` : 'The agent is browsing')
    : 'The agent has the browser';

  const card = (
    <div className={'wbx-browser-card is-' + mode + (open ? (control === 'user' ? ' is-user' : ' is-agent') : ' is-empty') + (acting ? ' is-acting' : '')}
         role="region" aria-label="Browser"
         style={mode === 'float' ? { left: pos.x, top: pos.y, width: pos.w, height: pos.h } : undefined}>
      <div className={'wbx-browser-bar' + (mode === 'float' ? ' is-draggable' : '')}
           onPointerDown={onBarPointerDown} onPointerMove={onBarPointerMove} onPointerUp={onBarPointerUp} onPointerCancel={onBarPointerUp}>
        <span className={'wbx-live-dot' + (acting ? ' is-on' : control === 'user' && open ? ' is-user' : open ? ' is-idle' : '')} aria-hidden="true" />
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
        <span className="wbx-browser-bar-gap" aria-hidden="true" />
        {mode !== 'full' && (
          <button type="button" className="wbx-browser-ic" onClick={() => setMode(mode === 'float' ? 'docked' : 'float')}
            title={mode === 'float' ? 'Dock beside the conversation' : 'Float over the page'} aria-label={mode === 'float' ? 'Dock beside the conversation' : 'Float over the page'}>
            <Icon d={mode === 'float' ? ICONS.dock : ICONS.float} />
          </button>
        )}
        <button type="button" className="wbx-browser-ic" onClick={() => setMode(mode === 'full' ? 'docked' : 'full')}
          title={mode === 'full' ? 'Exit full screen' : 'Full screen'} aria-label={mode === 'full' ? 'Exit full screen' : 'Full screen'}>
          <Icon d={mode === 'full' ? ICONS.restore : ICONS.full} />
        </button>
        <button type="button" className="wbx-browser-ic" onClick={onClose} aria-label="Close the browser view" title="Close">
          <Icon d={ICONS.close} />
        </button>
      </div>
      {!open ? (
        <div className="wbx-browser-empty">
          <div className="wbx-browser-empty-art" aria-hidden="true">
            <svg viewBox="0 0 220 150" width="220" height="150" fill="none">
              <rect x="10" y="12" width="200" height="126" rx="14" className="art-window" />
              <path d="M10 42h200" className="art-line" />
              <circle cx="27" cy="27" r="3.5" className="art-dot" /><circle cx="40" cy="27" r="3.5" className="art-dot" /><circle cx="53" cy="27" r="3.5" className="art-dot" />
              <rect x="70" y="20" width="110" height="14" rx="7" className="art-bar" />
              <rect x="30" y="60" width="96" height="10" rx="5" className="art-text" />
              <rect x="30" y="80" width="150" height="8" rx="4" className="art-text is-light" />
              <rect x="30" y="96" width="120" height="8" rx="4" className="art-text is-light" />
              <path d="M148 98l14 30 5-11 11-5z" className="art-cursor" />
            </svg>
          </div>
          <p className="wbx-browser-empty-title">Nothing to watch yet</p>
          <p>When the agent opens a page for this task it streams here, live. Watch it work, take it over from the row above or with a click on the screen, and hand it back when you are done.</p>
        </div>
      ) : (
        <div className="wbx-browser-stream" ref={streamRef}>
          {/* View-only while the agent drives: inert blocks focus and keys, the transparent button
              over the screen blocks the pointer and is "take over". Both go the moment the person has it. */}
          <div className="wbx-browser-view" inert={control === 'agent' ? true : undefined}>
            {src ? (
              <iframe ref={frameRef} src={src} title="Live browser" allow="autoplay" tabIndex={control === 'agent' ? -1 : 0} />
            ) : (
              <div className="wbx-browser-loading">{info === null ? 'Connecting to the live view' : 'The live view is not available for this browser.'}</div>
            )}
          </div>
          {control === 'agent' && (
            <>
              {/* the agent's presence: the edges of the screen tint blue and breathe, faster while it
                  acts; the middle stays clear */}
              <div className={'wbx-browser-veil' + (acting ? ' is-acting' : '')} aria-hidden="true" />
              {live?.point && live.viewport && (
                <GhostCursor point={live.point} viewport={live.viewport} tool={live.lastTool} at={live.lastCallAt} host={streamRef} />
              )}
              <button type="button" className="wbx-browser-takeover" onClick={takeOver} disabled={pending} title="Click to take over the browser"
                aria-label="Take over the browser" />
            </>
          )}
        </div>
      )}
    </div>
  );
  if (mode === 'docked') return card;
  return typeof document === 'undefined' ? null : createPortal(card, document.body);
}
