'use client';
// Email-verification landing: consumes the emailed token, which flips the account verified AND
// signs the user in (the link doubles as first login). Mirrors /reset's structure.
import { Suspense, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { switchOrg, verifyEmail, type Org, type Session } from '@/lib/auth';

function hrSubscribed(orgs: Org[]): Org[] {
  return (orgs || []).filter((o) => (o as { hr_subscribed?: unknown }).hr_subscribed === '1');
}

function VerifyInner() {
  const token = useSearchParams().get('token') || '';
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(true);
  const [choices, setChoices] = useState<Org[] | null>(null);
  const ran = useRef(false);

  async function enter(orgId: string) {
    await switchOrg(orgId);
    window.location.assign('/quickstart');   // fresh account -> start at Quickstart
  }
  async function afterAuth(s: Session) {
    const orgs = hrSubscribed(s.orgs);
    if (orgs.length === 1) await enter(orgs[0].id);
    else if (orgs.length > 1) { setChoices(orgs); setBusy(false); }
    else window.location.assign('/login');
  }
  useEffect(() => {
    if (!token || ran.current) { setBusy(false); return; }
    ran.current = true;                       // strict-mode double-invoke guard
    verifyEmail(token).then(afterAuth).catch((ex) => {
      setErr(ex instanceof Error ? ex.message : 'Verification failed');
      setBusy(false);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

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
                        onClick={() => { enter(o.id).catch(() => undefined); }}>
                  {(o.name as string) || o.id}
                </button>
              ))}
            </div>
          </>
        ) : !token ? (
          <>
            <h1 style={{ marginTop: 14, marginBottom: 4 }}>Verify email</h1>
            <div className="hr-err">This verification link is missing its token. Use the link from your email, or request a new one from the sign-in page.</div>
            <a className="hr-btn primary" style={{ width: '100%', marginTop: 14, textAlign: 'center' }} href="/login">Back to sign in</a>
          </>
        ) : busy ? (
          <>
            <h1 style={{ marginTop: 14, marginBottom: 4 }}>Verifying…</h1>
            <p className="sub">Confirming your email address.</p>
          </>
        ) : err ? (
          <>
            <h1 style={{ marginTop: 14, marginBottom: 4 }}>Verify email</h1>
            <div className="hr-err">{err}</div>
            <p className="sub" style={{ marginTop: 10 }}>The link may have expired (valid for 24 hours). Sign in to request a fresh one.</p>
            <a className="hr-btn primary" style={{ width: '100%', marginTop: 14, textAlign: 'center' }} href="/login">Back to sign in</a>
          </>
        ) : null}
      </div>
    </div>
  );
}

export default function VerifyPage() {
  return <Suspense fallback={null}><VerifyInner /></Suspense>;
}
