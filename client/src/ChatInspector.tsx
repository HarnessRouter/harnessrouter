import type { ReactNode } from 'react';
import { CheckCircleOutlined, FileTextOutlined, MessageOutlined, ToolOutlined } from '@ant-design/icons';

export type InspectorTab = 'session' | 'artifacts' | 'approvals' | 'tools';

export function InspectorHeader({ tab, onTab, onClose, closeLabel = '关闭上下文' }: {
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  onClose: () => void;
  closeLabel?: string;
}) {
  const tabs = [
    { id: 'session', label: '会话', icon: <MessageOutlined /> },
    { id: 'artifacts', label: '产物', icon: <FileTextOutlined /> },
    { id: 'approvals', label: '审批', icon: <CheckCircleOutlined /> },
    { id: 'tools', label: '工具', icon: <ToolOutlined /> },
  ] as const;
  return <div className="inspector-head">
    <div className="inspector-tabs" role="tablist" aria-label="上下文标签">{tabs.map(item => <button key={item.id} role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'active' : ''} onClick={() => onTab(item.id)}><span className="inspector-tab-icon" aria-hidden="true">{item.icon}</span><span>{item.label}</span></button>)}</div>
    <button className="inspector-collapse" aria-label={closeLabel} title="收起上下文" onClick={onClose}><span className="panel-toggle-icon" aria-hidden="true" /></button>
  </div>;
}

export function InspectorSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="inspector-section"><h3>{title}</h3>{children}</section>;
}

export function InspectorKV({ label, value }: { label: string; value: string }) {
  return <div className="inspector-kv"><span>{label}</span><strong title={value}>{value}</strong></div>;
}
