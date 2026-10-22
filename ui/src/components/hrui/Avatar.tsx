'use client';
// The signed-in operator's avatar as the design draws it (`.av`): their initials on their colour, on the
// rail's account button (the More tab on a phone) and on Profile. A self-hosted instance has one sign-in,
// so the name is the instance's username, asked of the server once per tab (it is set when the container
// runs, so it can't be built in).
import { useEffect, useState } from 'react';
import { initials, wsColor } from './ws';

export interface Operator { user: string; gated: boolean }

let cached: Operator | null = null;
let inflight: Promise<Operator | null> | null = null;
const listeners = new Set<(o: Operator | null) => void>();

/** Read again (after Profile changes the username), and redraw every avatar. */
export function refreshOperator(): Promise<Operator | null> {
  inflight = fetch('/api/selfhost/session', { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => (d && typeof d.user === 'string' ? { user: d.user, gated: d.gated !== false } : null))
    .catch(() => null)
    .then((o) => { if (o) cached = o; listeners.forEach((f) => f(cached)); inflight = null; return cached; });
  return inflight;
}

/** Who is signed in to this instance: null until the server has said. */
export function useOperator(): Operator | null {
  const [o, setO] = useState<Operator | null>(cached);
  useEffect(() => {
    listeners.add(setO);
    if (!cached && !inflight) void refreshOperator();
    else if (cached) setO(cached);
    return () => { listeners.delete(setO); };
  }, []);
  return o;
}

/** The operator's own avatar: their initials on their colour wherever it is drawn. */
export function MyPic({ size, className = '' }: { size?: number; className?: string }) {
  const o = useOperator();
  const name = o?.user || '';
  const box = size ? { width: size, height: size, fontSize: Math.round(size * 0.4) } : null;
  return (
    <span className={`av${className ? ` ${className}` : ''}`} style={{ background: name ? wsColor(name) : undefined, ...box }}
      title={name || undefined} aria-hidden="true">
      {name ? initials(name) : ''}
    </span>
  );
}
