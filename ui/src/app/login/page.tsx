'use client';
import { useEffect, useState } from 'react';
import { login, register, googleSignIn, requestPasswordReset, resendVerification, switchOrg, getSession, type Org, type Session } from '@/lib/auth';
import { GoogleButton, GOOGLE_ENABLED } from '@/components/GoogleButton';
import { stashInvite, takePendingInvite } from '@/app/(app)/billing/lib';
import { SELF_HOSTED } from '@/lib/edition';
import { SelfHostLogin } from '@/components/SelfHostLogin';

// HarnessRouter is a subscribable product over AgentStudio orgs. The sign-in org picker lists ONLY
// orgs that subscribed to HR (hr_subscribed flag). The account itself is the shared AgentStudio user.
function hrSubscribed(orgs: Org[]): Org[] {
  return (orgs || []).filter((o) => (o as { hr_subscribed?: unknown }).hr_subscribed === '1');
}

export default function LoginPage() {
  // One route, two sign-ins. The hosted form registers accounts, picks an org, resets by email
  // and offers Google — all of which need services a single box doesn't have.
  if (SELF_HOSTED) {
    const next = typeof window !== 'undefined'
      ? new URLSearchParams(window.location.search).get('next') || ''
      : '';
    return <SelfHostLogin next={next} />;
  }
  return <HostedLoginPage />;
}

function HostedLoginPage() {
  const [mode, setMode] = useState<'signin' | 'register' | 'forgot'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [choices, setChoices] = useState<Org[] | null>(null);
  const [resetSent, setResetSent] = useState(false);
  // Email-verification hand-off: set after a sign-up (or an unverified sign-in), shows the
  // check-your-email screen with a resend action.
  const [verifyEmailAddr, setVerifyEmailAddr] = useState('');
  const [resent, setResent] = useState(false);
  // Terms clickwrap, gates account CREATION (email register + Google, which auto-creates on
  // first sign-in). Returning sign-in is not re-gated.
  const [agreed, setAgreed] = useState(false);

  // Capture an invite code from the link (/login?invite=CODE) so it survives the sign-up flow
  // (register -> verify email -> land in app); the app layout redeems it once a session exists.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    stashInvite(q.get('invite'));
    // Landed here from handleAuthExpired (dead/expired session): say why, in the existing notice slot.
    if (q.get('expired') === '1') setErr('Your session has expired. Please sign in again.');
  }, []);

  // Already signed in with an active org → straight to the dashboard (visiting /login while
  // authenticated should never show the sign-in form again). An authenticated but ORG-LESS
  // session (a multi-org member whose login didn't auto-select) gets the org picker straight
  // away instead, so they can pick without re-entering credentials.
  useEffect(() => {
    const s = getSession();
    if (!s?.token) return;
    if (s.orgId) { window.location.replace('/dashboard'); return; }
    const subscribed = hrSubscribed(s.orgs || []);
    if (subscribed.length > 0) setChoices(subscribed);
  }, []);

  async function enter(orgId: string, dest = '/dashboard') {
    await switchOrg(orgId);
    window.location.assign(dest);  // hard nav so (app) remounts
  }

  // Route a freshly-authenticated session: into the single HR org, or to the org picker, or a notice.
  // A brand-new account (dest '/quickstart') lands on Quickstart to set up its first harness; returning
  // sign-ins land on the Dashboard. Matches the verify-email landing, which also opens Quickstart.
  async function afterAuth(session: Session, dest = '/dashboard') {
    const orgs = hrSubscribed(session.orgs);
    if (orgs.length === 0) setErr('This account has no HarnessRouter workspace yet. Ask an admin to add you, or subscribe an org.');
    else if (orgs.length === 1) await enter(orgs[0].id, dest);
    else setChoices(orgs);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(''); setBusy(true);
    try {
      if (mode === 'forgot') {
        await requestPasswordReset(email.trim());
        setResetSent(true);
      } else if (mode === 'register') {
        // Carry the referral code into the sign-up request, the engine redeems it against the
        // new org, so the credit lands at account creation regardless of the verification device.
        const r = await register(email.trim(), password, name.trim(), takePendingInvite());
        if ('verifyRequired' in r) setVerifyEmailAddr(r.email);   // check-your-email screen
        else await afterAuth(r, '/quickstart');                   // fail-open immediate session
      } else {
        await afterAuth(await login(email.trim(), password));
      }
    } catch (ex) {
      const msg = ex instanceof Error ? ex.message : `${mode === 'register' ? 'Sign up' : 'Sign in'} failed`;
      if (msg === 'email_not_verified') { setVerifyEmailAddr(email.trim()); }
      else setErr(msg);
    } finally { setBusy(false); }
  }

  async function onGoogle(credential: string) {
    setErr(''); setBusy(true);
    // Google auto-creates an account on first sign-in, on the register form, require the same
    // terms consent as the email path before running the credential.
    if (mode === 'register' && !agreed) {
      setErr('Please agree to the Terms of Service and Privacy Policy first.');
      setBusy(false);
      return;
    }
    try {
      const { session, newAccount } = await googleSignIn(credential, takePendingInvite());
      await afterAuth(session, newAccount ? '/quickstart' : '/dashboard');
    }
    catch (ex) { setErr(ex instanceof Error ? ex.message : 'Google sign-in failed'); }
    finally { setBusy(false); }
  }

  return (
    <div className="hr-auth">
      <div className="hr-auth-card">
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <a className="hr-brand" href="https://harnessrouter.ai"><img className="hr-brand-logo" src="/harnessrouter-wordmark.png" alt="HarnessRouter" /></a>
        {verifyEmailAddr ? (
          <>
            <h1 style={{ marginTop: 14 }}>Check your email</h1>
            <p className="sub">
              We sent a verification link to <strong>{verifyEmailAddr}</strong>. Click it to
              activate your account, the link signs you in.
            </p>
            <button type="button" className="hr-btn" style={{ width: '100%', marginTop: 14 }}
                    disabled={resent}
                    onClick={() => { resendVerification(verifyEmailAddr); setResent(true); setTimeout(() => setResent(false), 30000); }}>
              {resent ? 'Sent, check your inbox' : 'Resend email'}
            </button>
            <p className="hr-auth-switch">
              Wrong address?{' '}
              <button type="button" onClick={() => { setVerifyEmailAddr(''); setErr(''); setMode('register'); }}>Sign up again</button>
            </p>
          </>
        ) : !choices ? (
          <form onSubmit={submit}>
            <h1 style={{ marginTop: 14, marginBottom: 4 }}>{mode === 'register' ? 'Create your account' : mode === 'forgot' ? 'Reset password' : 'Sign in'}</h1>
            <p className="sub" style={{ marginBottom: 18 }}>{mode === 'register' ? 'Get started in seconds.' : mode === 'forgot' ? 'We’ll email you a reset link.' : 'Welcome back.'}</p>

            {mode === 'forgot' ? (
              resetSent ? (
                <>
                  <div className="hr-note">If an account exists for <b>{email.trim()}</b>, a password-reset link is on its way. It’s valid for 1 hour.</div>
                  <button type="button" className="hr-btn primary" style={{ width: '100%', marginTop: 14 }}
                          onClick={() => { setErr(''); setResetSent(false); setMode('signin'); }}>Back to sign in</button>
                </>
              ) : (
                <>
                  <div className="hr-field">
                    <label>Email</label>
                    <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus required autoComplete="email" />
                  </div>
                  {err && <div className="hr-err">{err}</div>}
                  <button type="submit" className="hr-btn primary" style={{ width: '100%', marginTop: 8 }} disabled={busy}>
                    {busy ? 'Please wait…' : 'Send reset link'}
                  </button>
                  <p className="hr-auth-switch">
                    <button type="button" onClick={() => { setErr(''); setMode('signin'); }}>Back to sign in</button>
                  </p>
                </>
              )
            ) : (
              <>
                {GOOGLE_ENABLED && (
                  <>
                    <div className="hr-gwrap"><GoogleButton onCredential={onGoogle} onError={setErr} /></div>
                    <div className="hr-or"><span>or</span></div>
                  </>
                )}

                {mode === 'register' && (
                  <div className="hr-field">
                    <label>Name</label>
                    <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" placeholder="Jane Doe" />
                  </div>
                )}
                <div className="hr-field">
                  <label>Email</label>
                  <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus required autoComplete="email" />
                </div>
                <div className="hr-field">
                  <div className="hr-field-row">
                    <label>Password</label>
                    {mode === 'signin' && (
                      <button type="button" className="hr-link-sm" onClick={() => { setErr(''); setResetSent(false); setMode('forgot'); }}>Forgot password?</button>
                    )}
                  </div>
                  <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                    autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                    placeholder={mode === 'register' ? 'At least 8 characters' : ''} />
                </div>
                {mode === 'register' && (
                  <label className="hr-consent">
                    <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
                    <span>I agree to the <a href="https://harnessrouter.ai/tos" target="_blank" rel="noreferrer">Terms of Service</a> and <a href="https://harnessrouter.ai/privacy" target="_blank" rel="noreferrer">Privacy Policy</a>.</span>
                  </label>
                )}
                {err && <div className="hr-err">{err}</div>}
                <button type="submit" className="hr-btn primary" style={{ width: '100%', marginTop: 8 }}
                  disabled={busy || (mode === 'register' && !agreed)}>
                  {busy ? 'Please wait…' : mode === 'register' ? 'Create account' : 'Sign in'}
                </button>
                <p className="hr-auth-switch">
                  {mode === 'register' ? 'Already have an account?' : 'New to HarnessRouter?'}{' '}
                  <button type="button" onClick={() => { setErr(''); setMode(mode === 'register' ? 'signin' : 'register'); }}>
                    {mode === 'register' ? 'Sign in' : 'Create one'}
                  </button>
                </p>
              </>
            )}
          </form>
        ) : (
          <>
            <h1 style={{ marginTop: 14 }}>Choose workspace</h1>
            <p className="sub">These workspaces have HarnessRouter.</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
              {choices.map((o) => (
                <button key={o.id} type="button" className="hr-btn" style={{ width: '100%', justifyContent: 'flex-start' }}
                        disabled={busy} onClick={() => { setBusy(true); enter(o.id).catch(() => setBusy(false)); }}>
                  {(o.name as string) || o.id}
                </button>
              ))}
            </div>
            {err && <div className="hr-err">{err}</div>}
          </>
        )}
      </div>
    </div>
  );
}
