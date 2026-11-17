import type { ReactNode } from 'react';
import { AppstoreOutlined, CarryOutOutlined, MessageOutlined, MoonOutlined, RobotOutlined, SettingOutlined, SunOutlined } from '@ant-design/icons';

export type ClientModule = 'chat' | 'tasks' | 'agents';
export const CLIENT_MODULES = [
  { id: 'chat', label: '对话', Icon: MessageOutlined },
  { id: 'tasks', label: '任务', Icon: CarryOutOutlined },
  { id: 'agents', label: '智能体', Icon: RobotOutlined },
] as const;

export function NavigationRail({ active, onSelect, labels, dark, onTheme, onSettings, workspace, user }: {
  active: ClientModule;
  onSelect: (module: ClientModule) => void;
  labels: boolean;
  dark: boolean;
  onTheme: () => void;
  onSettings: () => void;
  workspace: ReactNode;
  user: ReactNode;
}) {
  return <aside className="rail">
    <button className="logo" aria-label="Hexa"><AppstoreOutlined /></button>
    {workspace}
    <nav aria-label="主导航">{CLIENT_MODULES.map(({ id, label, Icon }) => <button key={id} className={active === id ? 'active' : ''} aria-label={label} aria-current={active === id ? 'page' : undefined} title={label} onClick={() => onSelect(id)}><Icon />{labels && <span className="rail-label">{label}</span>}</button>)}</nav>
    <div className="rail-bottom"><button aria-label="设置" onClick={onSettings}><SettingOutlined /></button><button aria-label="切换深色模式" onClick={onTheme}>{dark ? <SunOutlined /> : <MoonOutlined />}</button>{user}</div>
  </aside>;
}
