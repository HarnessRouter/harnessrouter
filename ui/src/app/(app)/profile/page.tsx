'use client';
// Profile: the sign-in for this instance, in the redesign's page (list-wrap, the operator's avatar,
// set-f fields). This edition has one operator, so a profile is exactly two things: who you sign in as,
// and the password you sign in with. There is no email, no picture and no team here.
//
// Server: GET/PUT /api/selfhost/profile. The current password is required to change either field. The
// console restarts to pick up new credentials (the sign-in gate reads them only at start-up), which
// signs every other browser out; the page says so, then waits for the console to answer again rather
// than reporting a failure for something that worked.
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { MyPic, refreshOperator } from '@/components/hrui/Avatar';
import { Skel, SkLine } from '@/components/hrui/Skel';

interface Profile { user: string; gated: boolean; usingDefaultPassword: boolean }

/** How long the page waits for the restarted console, in tries 500 ms apart. */
const RESTART_TRIES = 40;

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadErr, setLoadErr] = useState(false);
  const [username, setUsername] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  /** Poll until the restarted console answers. It is back in about a second; the ceiling exists so a
   *  console that fails to restart is said, instead of a wait that never ends. */
  const waitForRestart = useCallback(async (): Promise<boolean> => {
    for (let i = 0; i < RESTART_TRIES; i++) {
      await new Promise((r) => setTimeout(r, 500));
      try {
        const r = await fetch('/api/selfhost/profile', { cache: 'no-store' });
        if (r.ok) return true;
      } catch { /* still down: that is what is being waited out */ }
    }
    return false;
  }, []);

  const load = useCallback(async () => {
    setLoadErr(false);
    try {
      const r = await fetch('/api/selfhost/profile', { cache: 'no-store' });
      if (!r.ok) throw new Error(String(r.status));
      const doc = (await r.json()) as Profile;
      setProfile(doc);
      setUsername(doc.user);
    } catch {
      setLoadErr(true);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const changingPassword = newPassword.length > 0;
  const mismatch = changingPassword && confirmPassword.length > 0 && newPassword !== confirmPassword;
  const nothingToChange = username.trim() === (profile?.user || '') && !changingPassword;
  const canSave = !busy && !!profile && !!currentPassword && !!username.trim() && !nothingToChange
    && !mismatch && (!changingPassword || newPassword === confirmPassword);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!canSave) return;
    setBusy(true); setErr(''); setNotice('');
    try {
      const r = await fetch('/api/selfhost/profile', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ currentPassword, username: username.trim(), newPassword: newPassword || undefined }),
      });
      const doc = await r.json().catch(() => null);
      if (!r.ok) { setErr(typeof doc?.detail === 'string' && doc.detail ? doc.detail : 'Your changes could not be saved.'); return; }
      const changedPassword = changingPassword;
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('');
      setNotice('Saved. Signing every other browser out.');
      if (!(await waitForRestart())) { setNotice(''); setErr('Your changes were saved, but the console has not come back. Restart the container.'); return; }
      setNotice(changedPassword ? 'Saved. Every other signed-in browser has been signed out.' : 'Saved.');
      await load();
      void refreshOperator();
    } catch {
      setErr('Could not reach this instance.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="scroll">
      <div className="list-wrap lw-n" id="view-profile">
        <div className="list-top">
          <div>
            <h1>Profile</h1>
          </div>
        </div>

        {loadErr ? (
          <p className="empty-list ld-fail" role="alert">Your profile could not be read just now.{' '}
            <button type="button" className="link-q inl" onClick={() => void load()}>Try again</button></p>
        ) : !profile ? (
          <Skel label="Loading your profile">
            <div className="org-me"><SkLine w={64} h={64} r={32} /><div className="org-me-x"><SkLine w="40%" h={16} /><SkLine w="60%" h={12} style={{ marginTop: 10 }} /></div></div>
          </Skel>
        ) : (
          <>
            <div className="org-me">
              <MyPic size={64} />
              <div className="org-me-x">
                <b className="pf-name">{profile.user}</b>
                <p className="fine">The username and password you sign in to this instance with.</p>
              </div>
            </div>

            {profile.usingDefaultPassword ? (
              <div className="keywarn" role="alert"><b>You are using the default password.</b> It is published in the documentation, so anyone who can reach this address can sign in. Set your own below.</div>
            ) : null}

            <form onSubmit={save} noValidate style={{ maxWidth: 520, marginTop: 22, display: 'grid', gap: 16 }}>
              <div className="set-f">
                <label htmlFor="pf-user">Username</label>
                <input id="pf-user" className="set-in" value={username} autoComplete="username" spellCheck={false}
                  onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div className="set-f">
                <label htmlFor="pf-new">New password</label>
                <input id="pf-new" className="set-in" type="password" value={newPassword} autoComplete="new-password"
                  placeholder="Leave blank to keep your current password" onChange={(e) => setNewPassword(e.target.value)} />
              </div>
              {changingPassword ? (
                <div className="set-f">
                  <label htmlFor="pf-confirm">Confirm new password</label>
                  <input id="pf-confirm" className="set-in" type="password" value={confirmPassword} autoComplete="new-password"
                    aria-invalid={mismatch || undefined} aria-describedby={mismatch ? 'pfMismatch' : undefined}
                    onChange={(e) => setConfirmPassword(e.target.value)} />
                  {mismatch ? <p className="kb-why" id="pfMismatch" role="alert">Both passwords must match.</p> : null}
                </div>
              ) : null}
              <div className="set-f">
                <label htmlFor="pf-current">Current password</label>
                <input id="pf-current" className="set-in" type="password" value={currentPassword} autoComplete="current-password"
                  onChange={(e) => setCurrentPassword(e.target.value)} />
                <p className="set-help">Needed to change either one, so a tab left open cannot be used to take over this instance.</p>
              </div>
              {err ? <p className="kb-why" role="alert">{err}</p> : null}
              {notice ? <p className="set-help" role="status">{notice}</p> : null}
              <div className="sheet-actions">
                <button type="submit" className="btn primary" id="pfSave" disabled={!canSave} aria-busy={busy || undefined}>{busy ? 'Saving' : 'Save changes'}</button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
