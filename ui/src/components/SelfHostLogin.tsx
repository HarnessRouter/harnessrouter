'use client';
// Sign-in for a self-hosted instance: one operator, one password.
//
// Deliberately not the hosted sign-in form. That one registers accounts, picks an organisation,
// resets passwords by email and offers Google — every one of those needs a service this box does
// not have. Reusing it would mean disabling four flows and explaining the remnants.
import { useState } from 'react';

export function SelfHostLogin({ next }: { next: string }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const r = await fetch('/api/selfhost/login', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!r.ok) {
        setErr((await r.json().catch(() => null))?.detail || 'Incorrect username or password.');
        return;
      }
      // A full navigation, not a client route change: the middleware has to see the new cookie,
      // and every page under it was rendered as unauthenticated.
      window.location.assign(next || '/harnesses');
    } catch {
      setErr('Could not reach this instance.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sh-login">
      <form className="sh-login-card" onSubmit={submit}>
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset, no layout shift */}
        <img className="sh-login-mark" src="/harnessrouter-wordmark.svg" alt="HarnessRouter" />
        <p className="sh-login-sub">Sign in to this instance.</p>

        {err ? <div className="notice error" role="alert">{err}</div> : null}

        <div className="field">
          <label htmlFor="sh-user">Username</label>
          <input id="sh-user" value={username} autoFocus autoComplete="username"
                 onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sh-pass">Password</label>
          <input id="sh-pass" type="password" value={password} autoComplete="current-password"
                 onChange={(e) => setPassword(e.target.value)} />
        </div>

        <button className="button primary sh-login-go" type="submit"
                disabled={busy || !username || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="sh-login-hint">
          First sign-in uses <code>HR_AUTH_USER</code> and <code>HR_AUTH_PASSWORD</code> from the
          container. You can change them from your profile once you are in.
        </p>
      </form>
    </div>
  );
}
