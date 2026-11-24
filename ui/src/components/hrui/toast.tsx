'use client';
// The design's toast: a line at the bottom centre, gone after a few seconds. A longer one (a refusal that says where
// the mistake is) wraps to the screen's width and stays long enough to be read: 2.6 s, plus 40 ms a character past
// the first 40, at most 8 s.
import { useEffect, useState } from 'react';

const EVENT = 'hrui:toast';

export function toast(msg: string): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(EVENT, { detail: msg }));
}

export function toastMs(msg: string): number {
  return Math.min(8000, 2600 + 40 * Math.max(0, msg.length - 40));
}

export function ToastHost() {
  const [msg, setMsg] = useState('');
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const on = (e: Event) => {
      const m = String((e as CustomEvent).detail || '');
      setMsg(m);
      if (t) clearTimeout(t);
      t = setTimeout(() => setMsg(''), toastMs(m));
    };
    window.addEventListener(EVENT, on);
    return () => { window.removeEventListener(EVENT, on); if (t) clearTimeout(t); };
  }, []);
  return <div className="toast" role="status" hidden={!msg}>{msg}</div>;
}
