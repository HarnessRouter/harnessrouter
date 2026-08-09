'use client';
import { Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { resetPassword, switchOrg, type Org, type Session } from '@/lib/auth';

function hrSubscribed(orgs: Org[]): Org[] {
  return (orgs || []).filter((o) => (o as { hr_subscribed?: unknown }).hr_subscribed === '1');
}

function ResetInner() {
  const token = useSearchParams().get('token') || '';
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [choices, setChoices] = useState<Org[] | null>(null);

  async function enter(orgId: string) {
    await switchOrg(orgId);
    window.location.assign('/workbench');
  }
  async function afterAuth(s: Session) {
    const orgs = hrSubscribed(s.orgs);
    if (orgs.length === 1) await enter(orgs[0].id);
    else if (orgs.length > 1) setChoices(orgs);
    else window.location.assign('/login');
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr('');
    if (password.length < 8) { setErr('Password must be at least 8 characters.'); return; }
    if (password !== confirm) { setErr('Passwords don’t match.'); return; }
    setBusy(true);
    try { await afterAuth(await resetPassword(token, password)); }
    catch (ex) { setErr(ex instanceof Error ? ex.message : 'Could not reset password'); }
    finally { setBusy(false); }
  }

  return (
    <div className="hr-auth">
      <div className="hr-auth-card">
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <a className="hr-brand" href="https://harnessrouter.ai"><img className="hr-brand-logo" src="/harnessrouter-wordmark.png" alt="HarnessRouter" /></a>
        {choices ? (
          <>
            <h1 style={{ marginTop: 14 }}>Choose workspace</h1>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
              {choices.map((o) => (
                <button key={o.id} type="button" className="hr-btn" style={{ width: '100%', justifyContent: 'flex-start' }}
                        disabled={busy} onClick={() => { setBusy(true); enter(o.id).catch(() => setBusy(false)); }}>
                  {(o.name as string) || o.id}
                </button>
              ))}
            </div>
          </>
        ) : !token ? (
          <>
            <h1 style={{ marginTop: 14, marginBottom: 4 }}>Reset password</h1>
            <div className="hr-err">This reset link is missing its token. Request a new one from the sign-in page.</div>
            <a className="hr-btn primary" style={{ width: '100%', marginTop: 14, textAlign: 'center' }} href="/login">Back to sign in</a>
          </>
        ) : (
          <form onSubmit={submit}>
            <h1 style={{ marginTop: 14, marginBottom: 4 }}>Set a new password</h1>
            <p className="sub" style={{ marginBottom: 18 }}>Choose a strong password for your account.</p>
            <div className="hr-field">
              <label>New password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus required
                autoComplete="new-password" placeholder="At least 8 characters" />
            </div>
            <div className="hr-field">
              <label>Confirm password</label>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required autoComplete="new-password" />
            </div>
            {err && <div className="hr-err">{err}</div>}
            <button type="submit" className="hr-btn primary" style={{ width: '100%', marginTop: 8 }} disabled={busy}>
              {busy ? 'Please wait…' : 'Reset password & sign in'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

export default function ResetPage() {
  return <Suspense fallback={<div className="hr-auth"><div className="hr-auth-card" /></div>}><ResetInner /></Suspense>;
}
