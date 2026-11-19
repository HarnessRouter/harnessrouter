import { useEffect, useRef, useState } from 'react';
import { Button, Modal, Tag } from 'antd';
import { AppstoreOutlined, CopyOutlined, DatabaseOutlined, PlusOutlined, ReloadOutlined, RobotOutlined, SearchOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { AppApiError, appCreateAgent, appDeleteAgent, appDeleteAgentTemplate, appListAgentTemplates, appListGatewayAgentTemplates, appSaveAgentTemplate, type AppAgent, type AppAgentInput, type AppAgentTemplate, type AppAgentTemplateInput } from './app-api';
import { AgentDetailPanel } from './AgentDetailPanel';

const emptyInput: AppAgentTemplateInput = { name: '', description: '', base: '', default_model: '', system_prompt: '' };
const describe = (cause: unknown) => cause instanceof AppApiError ? cause.message : '应用服务暂时不可用，请重试。';
type Editor = { kind: 'agent' | 'template'; id?: number };
type Removal = { kind: 'agent'; row: AppAgent } | { kind: 'template'; row: AppAgentTemplate };
type Source = 'gateway' | 'custom';

function readView(): 'cards' | 'list' {
  try { return localStorage.getItem('hexa.agents.view') === 'list' ? 'list' : 'cards'; } catch { return 'cards'; }
}

export function AppAgentsPanel({ agents, selectedAgentId, onSelectAgent, reload, onChat, onSessionExpired }: {
  agents: AppAgent[];
  selectedAgentId: string | null;
  onSelectAgent: (id: string | null) => void;
  reload: () => Promise<void>;
  onChat: (id: string) => void;
  onSessionExpired?: () => void;
}) {
  const [section, setSection] = useState<'agents' | 'templates'>('agents');
  const [view, setView] = useState(readView);
  const [query, setQuery] = useState('');
  const [source, setSource] = useState<'all' | Source>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editor, setEditor] = useState<Editor | null>(null);
  const [input, setInput] = useState(emptyInput);
  const [target, setTarget] = useState<Removal | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const [catalogs, setCatalogs] = useState<Record<Source, AppAgentTemplate[]>>({ gateway: [], custom: [] });
  const [catalogLoading, setCatalogLoading] = useState<Record<Source, boolean>>({ gateway: false, custom: false });
  const [catalogErrors, setCatalogErrors] = useState<Record<Source, string>>({ gateway: '', custom: '' });
  const alive = useRef(true);
  const locked = useRef(false);
  const loaded = useRef(false);
  const serials = useRef({ gateway: 0, custom: 0 });
  const handleError = (cause: unknown) => {
    if (cause instanceof AppApiError && cause.status === 401) onSessionExpired?.();
    return describe(cause);
  };
  const refresh = async () => {
    setLoading(true); setError('');
    try { await reload(); }
    catch (cause) { if (alive.current) setError(handleError(cause)); }
    finally { if (alive.current) setLoading(false); }
  };
  const readCatalog = async (key: Source) => {
    const serial = ++serials.current[key];
    setCatalogLoading(current => ({ ...current, [key]: true }));
    setCatalogErrors(current => ({ ...current, [key]: '' }));
    try {
      const rows = await (key === 'gateway' ? appListGatewayAgentTemplates() : appListAgentTemplates());
      if (alive.current && serial === serials.current[key]) setCatalogs(current => ({ ...current, [key]: rows }));
    } catch (cause) {
      if (alive.current && serial === serials.current[key]) setCatalogErrors(current => ({ ...current, [key]: handleError(cause) }));
    } finally {
      if (alive.current && serial === serials.current[key]) setCatalogLoading(current => ({ ...current, [key]: false }));
    }
  };
  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => { alive.current = false; serials.current.gateway++; serials.current.custom++; };
  }, []);
  useEffect(() => {
    if (section !== 'templates' || loaded.current) return;
    loaded.current = true;
    void readCatalog('gateway'); void readCatalog('custom');
  }, [section]);
  useEffect(() => {
    if (!selectedAgentId) return;
    setSection('agents');
    setQuery('');
  }, [selectedAgentId]);
  const switchView = (value: 'cards' | 'list') => {
    setView(value);
    try { localStorage.setItem('hexa.agents.view', value); } catch { /* Browsers may disallow storage. */ }
  };
  const chooseSection = (next: 'agents' | 'templates') => {
    setSection(next);
    setQuery('');
    if (next === 'templates') onSelectAgent(null);
  };
  const open = (kind: Editor['kind'], row?: AppAgentTemplate, edit = false) => {
    setInput(row ? { name: row.name, description: row.description, base: row.base, default_model: row.default_model, system_prompt: row.system_prompt } : emptyInput);
    setEditor({ kind, ...(edit && row ? { id: Number(row.id) } : {}) }); setFormError('');
  };
  const save = async () => {
    if (locked.current || !editor) return;
    if (!input.name.trim() || !input.base.trim() || !input.default_model.trim()) { setFormError('请填写名称、后端和默认模型。'); return; }
    locked.current = true; setSaving(true); setFormError(''); setNotice('');
    try {
      const body: AppAgentInput = { name: input.name.trim(), base: input.base.trim(), default_model: input.default_model.trim(), system_prompt: input.system_prompt };
      if (editor.kind === 'agent') await appCreateAgent(body);
      else await appSaveAgentTemplate({ ...body, description: input.description.trim() }, editor.id);
      if (!alive.current) return;
      setEditor(null); setInput(emptyInput);
      setNotice(editor.kind === 'agent' ? 'Agent 已创建。' : '自定义模板已保存。');
      if (editor.kind === 'agent') { setSection('agents'); setQuery(''); await refresh(); }
      else await readCatalog('custom');
    } catch (cause) { if (alive.current) setFormError(handleError(cause)); }
    finally { locked.current = false; if (alive.current) setSaving(false); }
  };
  const remove = async () => {
    if (locked.current || !target) return;
    locked.current = true; setSaving(true); setFormError(''); setNotice('');
    try {
      if (target.kind === 'agent') await appDeleteAgent(target.row.id);
      else await appDeleteAgentTemplate(Number(target.row.id));
      if (!alive.current) return;
      setTarget(null); setNotice(target.kind === 'agent' ? 'Agent 已删除。' : '自定义模板已删除。');
      if (target.kind === 'agent') await refresh(); else await readCatalog('custom');
    } catch (cause) { if (alive.current) setFormError(handleError(cause)); }
    finally { locked.current = false; if (alive.current) setSaving(false); }
  };
  const close = () => { if (!locked.current) { setEditor(null); setTarget(null); setFormError(''); } };
  const matches = (values: Array<string | undefined>) => values.join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  const visibleAgents = agents.filter(row => matches([row.name, row.base, row.defaultModel, row.default_model]));
  const selectedAgent = selectedAgentId ? agents.find(row => row.id === selectedAgentId) : undefined;
  const templates = [...catalogs.custom, ...catalogs.gateway].filter(row => (source === 'all' || row.source === source) && matches([row.name, row.description, row.base, row.default_model]));
  const editorTitle = editor?.kind === 'agent' ? '创建 Agent' : editor?.id === undefined ? '新建自定义模板' : '编辑自定义模板';
  const removeTitle = target?.kind === 'agent' ? '删除 Agent' : '删除自定义模板';
  return <section className="page app-agents-page">
    <header><div><small>工作团队</small><h1>Agent 列表</h1></div><div className="app-agent-actions"><Button aria-label="刷新列表" icon={<ReloadOutlined aria-hidden="true" />} loading={loading} disabled={saving} onClick={() => { void refresh(); if (section === 'templates') void readCatalog('custom'); }}>刷新列表</Button><Button aria-label="创建 Agent" type="primary" icon={<PlusOutlined aria-hidden="true" />} disabled={saving} onClick={() => open('agent')}>创建 Agent</Button></div></header>
    <div className="agent-management-tabs" role="tablist" aria-label="Agent 管理" onKeyDown={event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 'agents' : event.key === 'End' ? 'templates' : section === 'agents' ? 'templates' : 'agents';
      chooseSection(next); document.getElementById(`${next}-tab`)?.focus();
    }}>
      <button role="tab" tabIndex={section === 'agents' ? 0 : -1} aria-selected={section === 'agents'} aria-controls="agent-catalog-panel" id="agents-tab" onClick={() => chooseSection('agents')}>我的 Agent <span>{agents.length}</span></button>
      <button role="tab" tabIndex={section === 'templates' ? 0 : -1} aria-selected={section === 'templates'} aria-controls="agent-catalog-panel" id="templates-tab" onClick={() => chooseSection('templates')}>模板库</button>
    </div>
    <div className="agent-management-content" role="tabpanel" id="agent-catalog-panel" aria-labelledby={section === 'agents' ? 'agents-tab' : 'templates-tab'}>
      {notice && <p className="agent-catalog-status" role="status">{notice}</p>}
      {section === 'agents' && selectedAgent ? <div className="agent-detail-shell">
        <AgentDetailPanel agent={selectedAgent} deleting={saving} onBack={() => onSelectAgent(null)} onChat={onChat} onDelete={() => { setTarget({ kind: 'agent', row: selectedAgent }); setFormError(''); }} />
      </div> : <>
        <div className="agent-catalog-intro"><div><h2>{section === 'agents' ? '你的 Agent 团队' : '从模板开始，构建你的 Agent'}</h2><p>{section === 'agents' ? '管理已创建的 Agent，随时开始一次新的对话。' : '使用 Gateway 基础模板，或保存适合客户业务的自定义配置。'}</p></div>{section === 'templates' && <div className="app-agent-actions"><Button aria-label="拉取 Gateway 模板" icon={<ReloadOutlined aria-hidden="true" />} loading={catalogLoading.gateway} disabled={saving} onClick={() => void readCatalog('gateway')}>拉取 Gateway 模板</Button><Button icon={<PlusOutlined aria-hidden="true" />} disabled={saving} onClick={() => open('template')}>新建自定义模板</Button></div>}</div>
        <div className="agent-catalog-toolbar">
          <label className="agent-catalog-search"><SearchOutlined aria-hidden="true" /><input aria-label="搜索 Agent 或模板" placeholder={section === 'agents' ? '搜索 Agent、运行时或模型' : '搜索模板、说明或运行时'} value={query} onChange={event => setQuery(event.target.value)} /></label>
          {section === 'templates' && <select aria-label="模板来源" value={source} onChange={event => setSource(event.target.value as typeof source)}><option value="all">全部来源</option><option value="gateway">Gateway 模板</option><option value="custom">客户自定义</option></select>}
          <div className="agent-view-switch" role="group" aria-label="展示方式"><Button aria-label="卡片视图" aria-pressed={view === 'cards'} icon={<AppstoreOutlined aria-hidden="true" />} onClick={() => switchView('cards')} /><Button aria-label="列表视图" aria-pressed={view === 'list'} icon={<UnorderedListOutlined aria-hidden="true" />} onClick={() => switchView('list')} /></div>
        </div>
        {section === 'agents' ? <>
          {error && <p className="error-banner" role="alert">{error} 已保留上次列表，请刷新重试。</p>}
          {loading && <p className="agent-catalog-status" role="status">正在读取 Agent…</p>}
          {!visibleAgents.length && !loading && !error && <p className="agent-catalog-empty">{agents.length ? '没有匹配的 Agent。' : '暂无可用 Agent。'}</p>}
          <div className={`agent-grid agent-catalog ${view === 'list' ? 'agent-catalog-list' : ''}`} data-view={view} role="region" aria-label="我的 Agent">{visibleAgents.map(row => <article key={row.id} tabIndex={0} className={selectedAgentId === row.id ? 'selected' : ''} onClick={() => onSelectAgent(row.id)} onKeyDown={event => { if (event.target !== event.currentTarget || !['Enter', ' '].includes(event.key)) return; event.preventDefault(); onSelectAgent(row.id); }}><div className="agent-catalog-icon"><RobotOutlined aria-hidden="true" /></div><div className="agent-catalog-copy"><h2>{row.name}</h2><p>已创建的 Agent</p><div className="agent-catalog-meta"><span>运行时 <b>{row.base || '后端未提供'}</b></span><span>模型 <b>{row.defaultModel || row.default_model || '默认模型'}</b></span></div></div><div className="app-agent-actions"><Button onClick={event => { event.stopPropagation(); onChat(row.id); }}>开始对话</Button><Button danger aria-label={`删除 ${row.name}`} disabled={saving} onClick={event => { event.stopPropagation(); setTarget({ kind: 'agent', row }); setFormError(''); }}>删除</Button></div></article>)}</div>
        </> : <>
          {(['gateway', 'custom'] as const).map(key => <div key={key}>{catalogLoading[key] && <p className="agent-catalog-status" role="status">正在读取{key === 'gateway' ? ' Gateway ' : '自定义'}模板…</p>}{catalogErrors[key] && <div className="agent-catalog-error" role="alert"><span>{catalogErrors[key]} 已保留上次模板列表。</span><Button size="small" onClick={() => void readCatalog(key)}>重试{key === 'gateway' ? ' Gateway ' : '自定义'}模板</Button></div>}</div>)}
          {!templates.length && !catalogLoading.gateway && !catalogLoading.custom && <p className="agent-catalog-empty">{query || source !== 'all' ? '没有匹配的模板。' : '暂无 Agent 模板，可新建自定义模板或拉取 Gateway 模板。'}</p>}
          <div className={`agent-catalog agent-template-catalog ${view === 'list' ? 'agent-catalog-list' : ''}`} data-view={view} role="region" aria-label="Agent 模板">{templates.map(row => <article key={`${row.source}-${row.id}`}><div className="agent-catalog-icon">{row.source === 'gateway' ? <DatabaseOutlined aria-hidden="true" /> : <RobotOutlined aria-hidden="true" />}</div><div className="agent-catalog-copy"><div className="agent-catalog-heading"><h2>{row.name}</h2><Tag>{row.source === 'gateway' ? 'Gateway' : '自定义'}</Tag></div><p>{row.description || (row.source === 'gateway' ? 'Gateway 提供的基础 Agent 配置' : '客户自定义 Agent 配置')}</p><div className="agent-catalog-meta"><span>运行时 <b>{row.base}</b></span><span>模型 <b>{row.default_model || '暂无可用模型'}</b></span></div>{!row.available && <small className="agent-template-unavailable">运行时未就绪或暂无可用模型</small>}</div><div className="app-agent-actions"><Button disabled={!row.available || saving} onClick={() => open('agent', row)}>使用模板</Button>{row.source === 'gateway' ? <Button icon={<CopyOutlined aria-hidden="true" />} disabled={saving} onClick={() => open('template', row)}>另存为自定义</Button> : <><Button disabled={saving} onClick={() => open('template', row, true)}>编辑模板</Button><Button danger disabled={saving} onClick={() => { setTarget({ kind: 'template', row }); setFormError(''); }}>删除模板</Button></>}</div></article>)}</div>
        </>}
      </>}
    </div>
    <Modal open={Boolean(editor)} title={editorTitle} onCancel={close} footer={null} closable={!saving} maskClosable={!saving} keyboard={!saving}>
      <form key={`${editor?.kind}-${editor?.id ?? 'new'}`} className="app-agent-form" onSubmit={event => { event.preventDefault(); void save(); }}>
        <label htmlFor="agent-editor-name">{editor?.kind === 'agent' ? 'Agent 名称' : '模板名称'}<input id="agent-editor-name" autoFocus required maxLength={255} value={input.name} onChange={event => setInput(current => ({ ...current, name: event.target.value }))} disabled={saving} /></label>
        {editor?.kind === 'template' && <label htmlFor="agent-editor-description">说明<textarea id="agent-editor-description" rows={2} maxLength={2000} value={input.description} onChange={event => setInput(current => ({ ...current, description: event.target.value }))} disabled={saving} /></label>}
        <label htmlFor="agent-editor-base">后端<input id="agent-editor-base" aria-label="后端" aria-describedby="app-agent-base-help" required maxLength={255} value={input.base} onChange={event => setInput(current => ({ ...current, base: event.target.value }))} disabled={saving} /><small id="app-agent-base-help">填写 Gateway 已配置的 Agent 运行时标识，例如 codex。</small></label>
        <label htmlFor="agent-editor-model">默认模型<input id="agent-editor-model" required maxLength={255} value={input.default_model} onChange={event => setInput(current => ({ ...current, default_model: event.target.value }))} disabled={saving} /></label>
        <label htmlFor="agent-editor-prompt">系统提示词<textarea id="agent-editor-prompt" rows={4} maxLength={20000} value={input.system_prompt} onChange={event => setInput(current => ({ ...current, system_prompt: event.target.value }))} disabled={saving} /></label>
        {formError && <p role="alert">{formError}</p>}
        <div className="app-agent-form-actions"><Button aria-label="取消" disabled={saving} onClick={close}>取消</Button><Button aria-label={editor?.kind === 'agent' ? '创建' : '保存模板'} type="primary" htmlType="submit" loading={saving}>{editor?.kind === 'agent' ? '创建' : '保存模板'}</Button></div>
      </form>
    </Modal>
    <Modal open={Boolean(target)} title={removeTitle} onCancel={close} footer={null} closable={!saving} maskClosable={!saving} keyboard={!saving}>
      <p>确认删除“{target?.row.name}”？{target?.kind === 'agent' ? '删除后无法再选择该 Agent 创建新对话。' : '已使用此模板创建的 Agent 将继续保留。'}</p>
      {formError && <p role="alert">{formError}</p>}
      <div className="app-agent-form-actions"><Button aria-label="取消" disabled={saving} onClick={close}>取消</Button><Button aria-label="删除" danger type="primary" loading={saving} onClick={() => void remove()}>删除</Button></div>
    </Modal>
  </section>;
}
