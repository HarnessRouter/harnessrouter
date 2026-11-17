import { useEffect, useRef, useState } from 'react';
import { Button, Modal } from 'antd';
import { PlusOutlined, ReloadOutlined, RobotOutlined } from '@ant-design/icons';
import { AppApiError, appCreateAgent, appDeleteAgent, type AppAgent, type AppAgentInput } from './app-api';

const emptyInput: AppAgentInput = { name: '', base: '', default_model: '', system_prompt: '' };
const describe = (cause: unknown) => cause instanceof AppApiError ? cause.message : '应用服务暂时不可用，请重试。';

export function AppAgentsPanel({ agents, reload, onChat, onSessionExpired }: { agents: AppAgent[]; reload: () => Promise<void>; onChat: (id: string) => void; onSessionExpired?: () => void }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [creating, setCreating] = useState(false);
  const [input, setInput] = useState(emptyInput);
  const [target, setTarget] = useState<AppAgent | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const alive = useRef(true);
  const refresh = async () => {
    setLoading(true); setError('');
    try { await reload(); }
    catch (cause) { if (cause instanceof AppApiError && cause.status === 401) { onSessionExpired?.(); return; } if (alive.current) setError(describe(cause)); }
    finally { if (alive.current) setLoading(false); }
  };
  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => { alive.current = false; };
  }, []);
  const mutate = async (kind: 'create' | 'delete') => {
    if (saving) return;
    if (kind === 'create' && (!input.name.trim() || !input.base.trim() || !input.default_model.trim())) {
      setFormError('请填写名称、后端和默认模型。'); return;
    }
    setSaving(true); setFormError(''); setNotice('');
    try {
      if (kind === 'create') await appCreateAgent({ name: input.name.trim(), base: input.base.trim(), default_model: input.default_model.trim(), system_prompt: input.system_prompt });
      else if (target) await appDeleteAgent(target.id);
      if (!alive.current) return;
      setCreating(false); setTarget(null); setInput(emptyInput);
      setNotice(kind === 'create' ? 'Agent 已创建。' : 'Agent 已删除。');
      await refresh();
    } catch (cause) { if (alive.current) setFormError(describe(cause)); }
    finally { if (alive.current) setSaving(false); }
  };
  const close = () => { if (!saving) { setCreating(false); setTarget(null); setFormError(''); } };
  return <section className="page app-agents-page">
    <header><div><small>工作团队</small><h1>Agent 列表</h1></div><div className="app-agent-actions"><Button aria-label="刷新列表" icon={<ReloadOutlined aria-hidden="true" />} loading={loading} disabled={saving} onClick={() => void refresh()}>刷新列表</Button><Button aria-label="创建 Agent" type="primary" icon={<PlusOutlined aria-hidden="true" />} disabled={saving} onClick={() => { setInput(emptyInput); setFormError(''); setCreating(true); }}>创建 Agent</Button></div></header>
    {error && <p className="error-banner" role="alert">{error} 已保留上次列表，请刷新重试。</p>}
    {notice && <p className="app-agent-notice" role="status">{notice}</p>}
    {loading && <p className="app-agent-notice" role="status">正在读取 Agent…</p>}
    {!agents.length && !loading && !error && <p className="empty-state">暂无可用 Agent。</p>}
    <div className="agent-grid">{agents.map(row => <article key={row.id}><RobotOutlined aria-hidden="true" /><h2>{row.name}</h2><p>{row.base || '后端未提供'}</p><p>{row.defaultModel || row.default_model || '默认模型'}</p><div className="app-agent-actions"><Button onClick={() => onChat(row.id)}>开始对话</Button><Button danger aria-label={`删除 ${row.name}`} disabled={saving} onClick={() => { setTarget(row); setFormError(''); }}>删除</Button></div></article>)}</div>
    <Modal open={creating} title="创建 Agent" onCancel={close} footer={null} closable={!saving} maskClosable={!saving} keyboard={!saving}>
      <form className="app-agent-form" onSubmit={event => { event.preventDefault(); void mutate('create'); }}>
        <label>Agent 名称<input autoFocus required maxLength={255} value={input.name} onChange={event => setInput(current => ({ ...current, name: event.target.value }))} disabled={saving} /></label>
        <label>后端<input aria-label="后端" aria-describedby="app-agent-base-help" required maxLength={255} value={input.base} onChange={event => setInput(current => ({ ...current, base: event.target.value }))} disabled={saving} /><small id="app-agent-base-help">填写 Gateway 已配置的普通 BYOK 后端。</small></label>
        <label>默认模型<input required maxLength={255} value={input.default_model} onChange={event => setInput(current => ({ ...current, default_model: event.target.value }))} disabled={saving} /></label>
        <label>系统提示词<textarea rows={4} maxLength={20000} value={input.system_prompt} onChange={event => setInput(current => ({ ...current, system_prompt: event.target.value }))} disabled={saving} /></label>
        {formError && <p role="alert">{formError}</p>}
        <div className="app-agent-form-actions"><Button aria-label="取消" disabled={saving} onClick={close}>取消</Button><Button aria-label="创建" type="primary" htmlType="submit" loading={saving}>创建</Button></div>
      </form>
    </Modal>
    <Modal open={Boolean(target)} title="删除 Agent" onCancel={close} footer={null} closable={!saving} maskClosable={!saving} keyboard={!saving}>
      <p>确认删除“{target?.name}”？删除后无法再选择该 Agent 创建新对话。</p>
      {formError && <p role="alert">{formError}</p>}
      <div className="app-agent-form-actions"><Button aria-label="取消" disabled={saving} onClick={close}>取消</Button><Button aria-label="删除" danger type="primary" loading={saving} onClick={() => void mutate('delete')}>删除</Button></div>
    </Modal>
  </section>;
}
