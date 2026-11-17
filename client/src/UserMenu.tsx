import { useState } from 'react';
import { Button, Modal, Popover } from 'antd';
import { IdcardOutlined, LoginOutlined, LogoutOutlined, UserOutlined } from '@ant-design/icons';

export interface ClientUser {
  username: string;
  displayName: string;
  signedInAt: number;
}

function initialOf(value: string): string {
  return Array.from(value.trim())[0]?.toUpperCase() || 'U';
}

function loginTime(value: number): string {
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function UserMenu({ user, workspaceName, dark = false, onUserChange, onRequestLogin }: {
  user: ClientUser | null;
  workspaceName: string;
  dark?: boolean;
  onUserChange: (user: ClientUser | null) => void;
  onRequestLogin: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const label = user?.displayName || '未登录';

  const openLogin = () => {
    setOpen(false);
    onRequestLogin();
  };
  const logout = () => {
    setOpen(false);
    onUserChange(null);
  };
  const content = user ? <div className="rail-user-panel" role="dialog" aria-label="用户菜单">
    <div className="rail-user-summary">
      <span className="rail-user-summary-avatar" aria-hidden="true">{initialOf(user.displayName)}</span>
      <span className="rail-user-summary-copy"><strong>{user.displayName}</strong><small>@{user.username}</small></span>
      <span className="rail-user-status">在线</span>
    </div>
    <p className="rail-user-note">当前登录态由应用服务端会话管理，退出后需要重新登录。</p>
    <div className="rail-user-actions">
      <button className="rail-user-action" aria-label="个人信息" onClick={() => { setOpen(false); setProfileOpen(true); }}><IdcardOutlined />个人信息</button>
      <button className="rail-user-action danger" aria-label="退出登录" onClick={logout}><LogoutOutlined />退出登录</button>
    </div>
  </div> : <div className="rail-user-panel" role="dialog" aria-label="用户菜单">
    <div className="rail-user-summary">
      <span className="rail-user-summary-avatar muted" aria-hidden="true"><UserOutlined /></span>
      <span className="rail-user-summary-copy"><strong>未登录</strong><small>Hexa 应用账户</small></span>
    </div>
    <p className="rail-user-note">登录后可在此查看个人信息和当前工作空间。</p>
    <Button className="rail-user-login" type="primary" block icon={<LoginOutlined />} aria-label="登录" onClick={openLogin}>登录</Button>
  </div>;

  return <>
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="rightBottom"
      arrow={false}
      content={content}
      rootClassName={`rail-user-popover${dark ? ' is-dark' : ''}`}
    >
      <button
        className="rail-user"
        aria-label={`用户菜单：${label}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={`用户菜单：${label}`}
      >
        {user ? <span className="rail-user-initial">{initialOf(user.displayName)}</span> : <UserOutlined />}
      </button>
    </Popover>

    <Modal
      open={profileOpen}
      title="个人信息"
      onCancel={() => setProfileOpen(false)}
      centered
      width={480}
      footer={<Button aria-label="关闭" onClick={() => setProfileOpen(false)}>关闭</Button>}
    >
      {user && <div className="user-profile">
        <div className="user-profile-head">
          <span className="rail-user-summary-avatar" aria-hidden="true">{initialOf(user.displayName)}</span>
          <span><strong>{user.displayName}</strong><small>@{user.username}</small></span>
        </div>
        <dl className="user-profile-details">
          <div><dt>用户名</dt><dd>@{user.username}</dd></div>
          <div><dt>登录状态</dt><dd>应用会话账户</dd></div>
          <div><dt>当前工作空间</dt><dd>{workspaceName || '未选择工作空间'}</dd></div>
          <div><dt>登录时间</dt><dd>{user.signedInAt > 0 ? loginTime(user.signedInAt) : '当前会话'}</dd></div>
          <div><dt>资料存储</dt><dd>由应用服务端会话管理</dd></div>
        </dl>
      </div>}
    </Modal>
  </>;
}
