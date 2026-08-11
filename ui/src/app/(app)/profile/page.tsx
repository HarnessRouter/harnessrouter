'use client';
// Profile — the sign-in credentials for this instance.
//
// Self-hosted has one operator, so "profile" is exactly two things: who you sign in as, and the
// password you sign in with. There is no email, no avatar, no team — inventing those would be
// chrome over an account system this edition deliberately does not have.
//
// Server: GET/PUT /api/selfhost/profile. The current password is required to change either field,
// and the change signs out every other session.
import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { SkelRows } from '@/components/Skel';
import { SELF_HOSTED } from '@/lib/edition';

interface Profile { user: string; gated: boolean; usingDefaultPassword: boolean }

export default function ProfilePage() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [username, setUsername] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  /** Poll until the restarted console answers. It is back in about a second; the ceiling exists
   *  so a console that fails to restart surfaces as an error instead of a spinner forever. */
  const waitForRestart = useCallback(async () => {
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 500));
      try {
        const r = await fetch('/api/selfhost/profile', { cache: 'no-store' });
        if (r.ok) return;
      } catch { /* still down — that is what we are waiting out */ }
    }
    setErr('Your credentials were saved, but the console has not come back. Restart the container.');
  }, []);

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/selfhost/profile');
      if (!r.ok) throw new Error('unavailable');
      const doc = (await r.json()) as Profile;
      setProfile(doc);
      setUsername(doc.user);
    } catch {
      setErr('Could not load your profile.');
    }
  }, []);

  useEffect(() => { if (SELF_HOSTED) void load(); }, [load]);

  if (!SELF_HOSTED) {
    return (
      <section className="view is-active"><div className="page">
        <div className="session-empty">This page is not available on this instance.</div>
      </div></section>
    );
  }

  const changingPassword = newPassword.length > 0;
  const mismatch = changingPassword && confirmPassword.length > 0 && newPassword !== confirmPassword;
  const nothingToChange = username.trim() === (profile?.user || '') && !changingPassword;
  const canSave = !busy && !!profile && !!currentPassword && !nothingToChange
    && !mismatch && (!changingPassword || newPassword === confirmPassword);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(''); setNotice('');
    try {
      const r = await fetch('/api/selfhost/profile', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          currentPassword,
          username: username.trim(),
          newPassword: newPassword || undefined,
        }),
      });
      const doc = await r.json().catch(() => null);
      if (!r.ok) { setErr(doc?.detail || 'Could not save your changes.'); return; }
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('');
      // The console restarts to pick up the new credentials — the sign-in gate reads them only
      // at start-up. Say so, then wait for it rather than firing a request into a closed port
      // and reporting a failure for something that worked.
      setNotice('Saved. Signing every other browser out\u2026');
      await waitForRestart();
      setNotice(changingPassword
        ? 'Saved. Every other signed-in browser has been signed out.'
        : 'Saved.');
      await load();
    } catch {
      setErr('Could not reach this instance.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="view is-active" id="view-profile">
      <div className="page">
        <div className="page-header">
          <div>
            <button className="back-link" type="button" onClick={() => router.push('/harnesses')}>
              <iconify-icon icon="tabler:arrow-left"></iconify-icon><span>Harnesses</span></button>
            <h1>Profile</h1>
            <p>The username and password you sign in to this instance with.</p>
          </div>
        </div>

        {err && (
          <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon>
            <div><strong>Something went wrong</strong>{err}</div></div>
        )}
        {notice && <div className="itg-saved"><iconify-icon icon="tabler:check"></iconify-icon>{notice}</div>}

        {!profile ? <SkelRows rows={3} /> : (
          <>
            {profile.usingDefaultPassword && (
              <div className="notice"><iconify-icon icon="tabler:shield-exclamation"></iconify-icon>
                <div><strong>You are using the default password</strong>
                  It is published in the documentation, so anyone who can reach this address can
                  sign in. Set your own below.</div></div>
            )}

            <form className="field-stack" onSubmit={save} style={{ maxWidth: '32rem' }}>
              <div className="field">
                <label htmlFor="pf-user">Username</label>
                <input id="pf-user" value={username} autoComplete="username"
                  onChange={(e) => setUsername(e.target.value)} />
              </div>

              <div className="field">
                <label htmlFor="pf-new">New password</label>
                <input id="pf-new" type="password" value={newPassword} autoComplete="new-password"
                  placeholder="Leave blank to keep your current password"
                  onChange={(e) => setNewPassword(e.target.value)} />
              </div>

              {changingPassword && (
                <div className="field">
                  <label htmlFor="pf-confirm">Confirm new password</label>
                  <input id="pf-confirm" type="password" value={confirmPassword}
                    autoComplete="new-password"
                    onChange={(e) => setConfirmPassword(e.target.value)} />
                  {mismatch && <p className="field-help">Both passwords must match.</p>}
                </div>
              )}

              <div className="field">
                <label htmlFor="pf-current">Current password</label>
                <input id="pf-current" type="password" value={currentPassword}
                  autoComplete="current-password"
                  onChange={(e) => setCurrentPassword(e.target.value)} />
                <p className="field-help">
                  Required to change either field, so an unattended tab can&rsquo;t be used to take
                  over this instance.
                </p>
              </div>

              <button className="button primary" type="submit" disabled={!canSave}>
                {busy ? 'Saving…' : 'Save changes'}
              </button>
            </form>
          </>
        )}
      </div>
    </section>
  );
}
