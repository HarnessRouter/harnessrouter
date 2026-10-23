'use client';
// The design's toast: one short line at the bottom centre, gone after a few seconds.
import { useEffect, useState } from 'react';

const EVENT = 'hrui:toast';

export function toast(msg: string): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(EVENT, { detail: msg }));
}

export function ToastHost() {
  const [msg, setMsg] = useState('');
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const on = (e: Event) => {
      setMsg(String((e as CustomEvent).detail || ''));
      if (t) clearTimeout(t);
      t = setTimeout(() => setMsg(''), 2600);
    };
    window.addEventListener(EVENT, on);
    return () => { window.removeEventListener(EVENT, on); if (t) clearTimeout(t); };
  }, []);
  return <div className="toast" role="status" hidden={!msg}>{msg}</div>;
}
