'use client';
// Sign-in for this instance: one operator, one username and password (POST /api/selfhost/login), on
// the redesign's sign-in card (hrui/auth/AuthFrame). No accounts, no sign-up, no reset by email and no
// third-party sign-in: each needs a service this box does not have. The username and password are
// changed from Profile once signed in.
import { useRef, useState, type FormEvent } from 'react';
import { safeNext } from '@/lib/safe-next';
import { AuthFrame, Field, LooseErr } from '@/components/hrui/auth/AuthFrame';

/** A full navigation, not a client route change: the middleware has to see the new cookie, and every
 *  page under it was rendered as unauthenticated. */
const assignTo = (href: string) => window.location.assign(href);

export function SelfHostLogin({ next, go = assignTo }: { next: string; go?: (href: string) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [fe, setFe] = useState<{ at: 'user' | 'pass'; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const userRef = useRef<HTMLInputElement>(null);
  const passRef = useRef<HTMLInputElement>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setErr(''); setFe(null);
    if (!username.trim()) { setFe({ at: 'user', msg: 'Enter your username.' }); userRef.current?.focus(); return; }
    if (!password) { setFe({ at: 'pass', msg: 'Enter your password.' }); passRef.current?.focus(); return; }
    setBusy(true);
    try {
      const r = await fetch('/api/selfhost/login', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        setErr(typeof d?.detail === 'string' && d.detail ? d.detail : 'Incorrect username or password.');
        setBusy(false);
        return;
      }
      // Only a path on this site: `next` is whatever the link said (GHSA-59mq-hx4p-fw48).
      go(safeNext(next));
    } catch {
      setErr('Could not reach this instance.');
      setBusy(false);
    }
  }

  return (
    <AuthFrame n={3}>
      <h1>Sign in</h1>
      <p className="au-sub">Sign in to this instance.</p>
      <form onSubmit={submit} noValidate>
        <Field id="sh-user" name="username" label="Username" ac="username" value={username} autoFocus inputRef={userRef}
          err={fe?.at === 'user' ? fe.msg : ''} onChange={(v) => { if (fe?.at === 'user') setFe(null); setUsername(v); }} />
        <Field id="sh-pass" name="password" label="Password" type="password" ac="current-password" value={password} inputRef={passRef}
          err={fe?.at === 'pass' ? fe.msg : ''} onChange={(v) => { if (fe?.at === 'pass') setFe(null); setPassword(v); }} />
        <LooseErr err={err} />
        <button type="submit" className="btn primary au-wide" id="auGo" disabled={busy} aria-busy={busy || undefined}>{busy ? 'Signing in' : 'Sign in'}</button>
      </form>
      <p className="au-hint">The first sign-in uses <code>HR_AUTH_USER</code> and <code>HR_AUTH_PASSWORD</code> from the container. Change them from Profile once you are in.</p>
    </AuthFrame>
  );
}
