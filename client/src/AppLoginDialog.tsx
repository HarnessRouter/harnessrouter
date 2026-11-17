import { useEffect, useState } from 'react';
import { Button, Modal } from 'antd';
import { AppApiError, appLogin } from './app-api';

export function AppLoginDialog({ open, onSuccess, onClose }: { open: boolean; onSuccess: (username: string) => void; onClose?: () => void }) {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { if (open) { setPassword(''); setError(''); } }, [open]);
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      const session = await appLogin(username.trim(), password);
      onSuccess(session.username);
    } catch (cause) {
      setError(cause instanceof AppApiError ? cause.message : '登录失败，请稍后重试。');
    } finally { setBusy(false); }
  };
  return <Modal open={open} title="登录 Hexa" onCancel={onClose} footer={null} centered destroyOnHidden width={420}>
    <form className="app-login-form" onSubmit={event => void submit(event)}>
      <p className="gateway-settings-note">使用 Hexa 管理员账户登录工作空间。</p>
      <label htmlFor="hexa-username">用户名<input id="hexa-username" autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} /></label>
      <label htmlFor="hexa-password">密码<input id="hexa-password" type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} /></label>
      {error && <p className="error-banner" role="alert">{error}</p>}
      <div className="gateway-settings-actions"><span />{onClose && <Button onClick={onClose}>取消</Button>}<Button aria-label="登录" type="primary" htmlType="submit" loading={busy} disabled={!username.trim() || !password}>登录</Button></div>
    </form>
  </Modal>;
}
