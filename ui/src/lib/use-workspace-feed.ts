'use client';
// The workspace's task activity (lib/workspace-feed) as a page holds it: listened to while the page is
// visible and `on`, stopped while it is hidden. Each frame goes to `onFrame`; each time the watch comes
// up, `onUp` runs once: the page's one catch-up read, for what started or ended while it was not up
// (no frame says it). `away`: how long the page was hidden before this (0 when it was not), so a page
// can read more after a long absence. Not up for PAUSED_AFTER_MS, `paused` is true until it is up
// again, and the page says its view may be out of date, with Try again (`reconnect`).
import { useEffect, useRef, useState } from 'react';
import { reconnectWorkspaceFeed, subscribeWorkspaceFeed, type FeedFrame, type FeedState } from '@/lib/workspace-feed';

/** The watch not up for this long (a gateway restart comes back well within it): `paused`. */
export const PAUSED_AFTER_MS = 5_000;

export function useWorkspaceFeed(opts: {
  on: boolean;
  /** the current workspace's id: a switch listens to the new workspace's feed */
  scope?: string;
  onFrame: (f: FeedFrame) => void;
  onUp: (away: number) => void;
}): { paused: boolean; reconnect: () => void } {
  const { on, scope = '' } = opts;
  const [paused, setPaused] = useState(false);
  const cb = useRef(opts);
  cb.current = opts;
  useEffect(() => {
    if (!on) return;
    let up = false;
    let hiddenAt = 0;
    let away = 0;
    let unsub: (() => void) | null = null;
    let pauseT: ReturnType<typeof setTimeout> | null = null;
    const unpause = () => { if (pauseT) { clearTimeout(pauseT); pauseT = null; } };
    const onState = (s: FeedState) => {
      if (s !== 'up') {
        up = false;
        if (!pauseT) pauseT = setTimeout(() => { pauseT = null; setPaused(true); }, PAUSED_AFTER_MS);
        return;
      }
      if (up) return;
      up = true;
      unpause();
      setPaused(false);
      const a = away;
      away = 0;
      cb.current.onUp(a);
    };
    const onFrame = (f: FeedFrame) => cb.current.onFrame(f);
    const listen = () => { if (!unsub) unsub = subscribeWorkspaceFeed(onFrame, onState); };
    const deafen = () => { unsub?.(); unsub = null; up = false; unpause(); };
    const onVis = () => {
      if (document.visibilityState === 'hidden') { if (!hiddenAt) hiddenAt = Date.now(); deafen(); return; }
      if (hiddenAt) away = Date.now() - hiddenAt;
      hiddenAt = 0;
      listen();
    };
    if (document.visibilityState === 'hidden') hiddenAt = Date.now(); else listen();
    document.addEventListener('visibilitychange', onVis);
    return () => { deafen(); setPaused(false); document.removeEventListener('visibilitychange', onVis); };
  }, [on, scope]);
  return { paused, reconnect: reconnectWorkspaceFeed };
}
