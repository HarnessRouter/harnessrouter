'use client';

// Account, security settings: change password, delete account.
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { getSession, changePassword, deleteAccount, logout } from '@/lib/auth';

export default function AccountPage() {
  const router = useRouter();
  const s = getSession();
  const [curPw, setCurPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [pwMsg, setPwMsg] = useState('');
  const [pwBusy, setPwBusy] = useState(false);
  const [delOpen, setDelOpen] = useState(false);
  const [delPw, setDelPw] = useState('');
  const [delErr, setDelErr] = useState('');
  const [delBusy, setDelBusy] = useState(false);

  async function onChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwMsg('');
    setPwBusy(true);
    try {
      await changePassword(curPw, newPw);
      setPwMsg('Password updated.');
      setCurPw(''); setNewPw('');
    } catch (err) {
      setPwMsg(err instanceof Error ? err.message : 'Could not change password.');
    } finally {
      setPwBusy(false);
    }
  }

  async function onDelete() {
    setDelErr('');
    setDelBusy(true);
    try {
      await deleteAccount(delPw, delPw ? '' : 'DELETE');
      logout();
      router.replace('/login');
    } catch (err) {
      setDelErr(err instanceof Error ? err.message : 'Could not delete account.');
      setDelBusy(false);
    }
  }

  return (
    <div className="hr-wrap hrb-content" style={{ maxWidth: 640 }}>
      <div className="hr-card" style={{ padding: 20 }}>
        <h2 className="hr-h2" style={{ marginBottom: 4 }}>Account</h2>
        <div className="hr-meta" style={{ marginBottom: 16 }}>{s?.member?.email}</div>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>Change password</div>
        <form onSubmit={onChangePassword} style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 360 }}>
          <input className="hr-input" type="password" placeholder="Current password" autoComplete="current-password"
            value={curPw} onChange={(e) => setCurPw(e.target.value)} required />
          <input className="hr-input" type="password" placeholder="New password (at least 8 characters)" autoComplete="new-password"
            value={newPw} onChange={(e) => setNewPw(e.target.value)} required minLength={8} />
          {pwMsg ? <div style={{ fontSize: 12.5, color: pwMsg === 'Password updated.' ? '#1F7A3D' : '#B42318' }}>{pwMsg}</div> : null}
          <button className="hr-btn primary" type="submit" disabled={pwBusy} style={{ alignSelf: 'flex-start' }}>
            {pwBusy ? 'Saving...' : 'Change password'}
          </button>
        </form>
        <div style={{ fontSize: 12.5, color: 'var(--mute, #5B5D66)', marginTop: 8 }}>
          Signed up with Google and have no password yet? Use the reset link on the sign-in page to set one.
        </div>
      </div>

      <div className="hr-card" style={{ padding: 20, borderColor: '#FECACA' }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#991B1B', marginBottom: 6 }}>Delete account</div>
        <div style={{ fontSize: 13, color: 'var(--mute, #5B5D66)', lineHeight: 1.6, marginBottom: 12 }}>
          Deleting your account signs you out everywhere immediately. Your data is kept for 30 days,
          then permanently removed. To restore within 30 days, email contact@harnessrouter.ai from this address.
        </div>
        {delOpen ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 360 }}>
            <input className="hr-input" type="password" placeholder="Your password (Google-only accounts: leave blank)"
              autoComplete="current-password" value={delPw} onChange={(e) => setDelPw(e.target.value)} />
            {delErr ? <div style={{ fontSize: 12.5, color: '#B42318' }}>{delErr}</div> : null}
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="hr-btn ghost" onClick={() => setDelOpen(false)} disabled={delBusy}>Cancel</button>
              <button className="hr-btn" style={{ background: '#B42318', borderColor: '#B42318', color: '#fff' }}
                onClick={onDelete} disabled={delBusy}>
                {delBusy ? 'Deleting...' : 'Delete account'}
              </button>
            </div>
          </div>
        ) : (
          <button className="hr-btn ghost" style={{ color: '#991B1B', borderColor: '#FECACA' }} onClick={() => setDelOpen(true)}>
            Delete my account
          </button>
        )}
      </div>
    </div>
  );
}
