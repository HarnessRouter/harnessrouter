import { useEffect, useRef, useState } from 'react';
import { appUploadFile, appDeleteFile, appConversationFiles, appCancelConversation, appWatchConversation, appFileBlob, type AppFile } from './app-api';
import { Button, Checkbox, ConfigProvider, Modal, Tag, theme } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { UserMenu } from './UserMenu';
import { InspectorHeader, InspectorSection, InspectorKV, type InspectorTab } from './ChatInspector';
import { SettingsDialog } from './SettingsDialog';
import { NavigationRail, CLIENT_MODULES, type ClientModule } from './NavigationRail';
import { AppAgentsPanel } from './AppAgentsPanel';
import { appModelSelection, onAppSessionExpired } from './app-api';
import { AppLoginDialog } from './AppLoginDialog';
import { AppTasks } from './AppTasks';
import { sampleRuns } from './AppTasks';
import { AppApiError, appSession, appLogout, appListAgents, appListAgentModels, appListConversations, appCreateConversation, appGetConversation, appConversationStatus, appSendMessage, appListWorkspaces, appCreateWorkspace, appSelectWorkspace, type AppAgent, type AppConversation, type AppMessage } from './app-api';

const errorText = (cause: unknown) => cause instanceof AppApiError ? cause.message : '应用服务暂时不可用，请重试。';
type Workspace = { id: number; name: string; description: string };
type GatewayState = 'checking' | 'connected' | 'unavailable' | 'unauthorized';
export function AppBackendClient() {
  const [username, setUsername] = useState('');
  const [checking, setChecking] = useState(true);
  const [loginOpen, setLoginOpen] = useState(false);
  const [agents, setAgents] = useState<AppAgent[]>([]);
  const [agentId, setAgentId] = useState('');
  const [models, setModels] = useState<Array<{ id: string; label: string }>>([]);
  const [model, setModel] = useState('');
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState('');
  const [modelsRevision, setModelsRevision] = useState(0);
  const catalogGeneration = useRef(0);
  const [conversations, setConversations] = useState<AppConversation[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const historyGeneration = useRef(0);
  const [selected, setSelected] = useState<number | null>(() => Number(sessionStorage.getItem('hexa.app.recent')) || null);
  const [messages, setMessages] = useState<AppMessage[]>([]);
  const [draft, setDraft] = useState(() => sessionStorage.getItem('hexa.app.draft') || '');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [gatewayState, setGatewayState] = useState<GatewayState>('checking');
  const [status, setStatus] = useState('idle');
  const [responseId, setResponseId] = useState<string | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(() => !matchMedia('(max-width: 640px)').matches);
  const [tab, setTab] = useState<InspectorTab>('session');
  const [dark, setDark] = useState(false);
  const [active, setActive] = useState<ClientModule>('chat');
  const [taskSection, setTaskSection] = useState<'mine' | 'templates' | 'runs'>('mine');
  const [runListCollapsed, setRunListCollapsed] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState('run-18');
  const [railLabels, setRailLabels] = useState(() => localStorage.getItem('hexa.client.rail-labels') !== 'false');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [labelsDraft, setLabelsDraft] = useState(railLabels);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [workspaceName, setWorkspaceName] = useState('');
  const [files, setFiles] = useState<AppFile[]>([]);
  const [attachments, setAttachments] = useState<AppFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [liveText, setLiveText] = useState('');
  const [executingId, setExecutingId] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ name: string; text?: string; image?: string } | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const pending = useRef<{ text: string; key: string; id: number } | null>(null);
  const locked = busy || messages.length > 0 || Boolean(responseId);
  const agent = agents.find(row => row.id === agentId);

  const loadAgents = async () => {
    const serial = ++catalogGeneration.current;
    try {
      const rows = await appListAgents();
      if (serial === catalogGeneration.current) { setAgents(rows); setGatewayState('connected'); }
    } catch (cause) {
      if (serial === catalogGeneration.current) setGatewayState(cause instanceof AppApiError && [401, 403].includes(cause.status) ? 'unauthorized' : 'unavailable');
      throw cause;
    }
  };
  const loadHistory = async () => {
    const serial = ++historyGeneration.current;
    setHistoryLoading(true); setHistoryError('');
    try {
      const list = await appListConversations();
      if (serial === historyGeneration.current) setConversations(list.conversations);
    } catch (cause) {
      if (serial === historyGeneration.current) setHistoryError(errorText(cause));
    } finally { if (serial === historyGeneration.current) setHistoryLoading(false); }
  };
  const loadCatalog = async () => {
    await Promise.all([loadAgents(), loadHistory(), appListWorkspaces().then(spaces => {
      setWorkspaces(spaces.workspaces); setWorkspaceId(spaces.selected_id);
    })]);
  };
  useEffect(() => {
    let alive = true;
    void appSession().then(session => { if (alive) setUsername(session.username); }).catch(() => { if (alive) setLoginOpen(true); }).finally(() => { if (alive) setChecking(false); });
    return () => { alive = false; generation.current++; };
  }, []);
  useEffect(() => { if (username) { setGatewayState('checking'); void loadCatalog().catch(cause => setError(errorText(cause))); } }, [username]);
  useEffect(() => {
    if (!username) return;
    return onAppSessionExpired(() => {
      generation.current++; catalogGeneration.current++; historyGeneration.current++;
      pending.current = null;
      setUsername(''); setAgents([]); setConversations([]); setWorkspaces([]); setWorkspaceId(null);
      setMessages([]); setFiles([]); setAttachments([]); setAgentId(''); setModel(''); setModels([]);
      setBusy(false); setExecutingId(null); setResponseId(null); setLiveText(''); setLoading(false);
      setHistoryLoading(false); setHistoryError(''); setStatus('idle'); setActive('chat'); setLoginOpen(true);
    });
  }, [username]);
  useEffect(() => { sessionStorage.setItem('hexa.app.draft', draft); }, [draft]);
  useEffect(() => {
    if (!selected || busy || !['running', 'unknown'].includes(status)) return;
    const serial = generation.current;
    const timer = setInterval(() => { void restoreConversation(selected, serial).catch(() => {}); }, 2500);
    return () => clearInterval(timer);
  }, [selected, busy, status]);
  useEffect(() => {
    if (!busy || !executingId) return;
    const serial = generation.current;
    return appWatchConversation(executingId, snapshot => {
      if (serial !== generation.current) return;
      setLiveText(snapshot.text || ''); if (snapshot.response_id) setResponseId(snapshot.response_id);
    });
  }, [busy, executingId]);
  useEffect(() => () => { if (preview?.image) URL.revokeObjectURL(preview.image); }, [preview]);
  useEffect(() => {
    const media = matchMedia('(max-width: 640px)');
    const sync = () => setInspectorOpen(!media.matches);
    media.addEventListener('change', sync); return () => media.removeEventListener('change', sync);
  }, []);
  useEffect(() => {
    setModels([]); setModelsError('');
    if (!username || !agentId) { setModelsLoading(false); return; }
    let alive = true;
    setModelsLoading(true);
    void appListAgentModels(agentId).then(value => {
      if (!alive) return;
      const selection = appModelSelection(value);
      setModels(selection.models);
      setModel(current => appModelSelection(value, locked ? current : '').model);
      if (!selection.models.length && !locked) setModelsError('该 Agent 暂无可用模型。');
    }).catch(cause => { if (alive) setModelsError(errorText(cause)); })
      .finally(() => { if (alive) setModelsLoading(false); });
    return () => { alive = false; };
  }, [username, agentId, modelsRevision]);
  const restoreConversation = async (id: number, serial: number) => {
    await appConversationStatus(id);
    const snapshot = await appGetConversation(id);
    if (serial !== generation.current) return;
    setMessages(snapshot.messages); setResponseId(snapshot.previous_response_id); setAgentId(snapshot.agent_id || ''); setModel(snapshot.model || ''); setStatus(snapshot.status || 'idle');
    const listed = await appConversationFiles(id);
    if (serial === generation.current) setFiles(listed);
  };
  useEffect(() => {
    const serial = ++generation.current;
    setMessages([]); setResponseId(null); setError(''); setBusy(false);
    if (!username || selected === null) { setLoading(false); return; }
    sessionStorage.setItem('hexa.app.recent', String(selected));
    setLoading(true);
    void restoreConversation(selected, serial).catch(cause => { if (serial === generation.current) setError(errorText(cause)); }).finally(() => { if (serial === generation.current) setLoading(false); });
  }, [username, selected]);

  const newChat = (id = '') => {
    for (const file of attachments) void appDeleteFile(file.id).catch(() => setError('临时文件清理失败，请稍后重试。'));
    setAttachments([]);
    generation.current++; pending.current = null;
    setSelected(null); setMessages([]); setFiles([]); setAgentId(id); setModel(''); setResponseId(null); setStatus('idle'); setError(''); setBusy(false); setActive('chat');
    setModels([]); setModelsError(''); setModelsLoading(Boolean(id)); setModelsRevision(value => value + 1);
    sessionStorage.removeItem('hexa.app.recent');
  };
  const send = async () => {
    const text = draft.trim(); if ((!text && !attachments.length) || busy || !agent || !username || loading || modelsLoading || Boolean(modelsError) || !model || status === 'unknown') return;
    const serial = generation.current;
    setBusy(true); setError(''); setStatus('running'); setLiveText('');
    try {
      let id = selected;
      if (id === null) {
        const made = await appCreateConversation(text.slice(0, 60), workspaceId ?? undefined, agentId, model);
        if (serial !== generation.current) return;
        id = made.id;
        // Do not change the selected state until the request completes: its recovery
        // effect would otherwise invalidate this request's generation.
        sessionStorage.setItem('hexa.app.recent', String(id));
      }
      const request = pending.current?.id === id && pending.current.text === text ? pending.current : { id, text, key: crypto.randomUUID() };
      pending.current = request;
      setExecutingId(id);
      const answer = await appSendMessage(id, text, null, request.key, attachments.map(row => row.id));
      if (serial !== generation.current) return;
      pending.current = null; setDraft(''); setAttachments([]); setStatus(answer.status); setResponseId(answer.response_id);
      await restoreConversation(id, serial);
      if (serial !== generation.current) return;
      setSelected(id); await loadCatalog();
    } catch (cause) {
      if (serial !== generation.current) return;
      setStatus('unknown'); setError(errorText(cause));
      const id = pending.current?.id;
      if (id) { setSelected(id); await restoreConversation(id, serial).catch(() => {}); }
    } finally { if (serial === generation.current) setBusy(false); }
  };
  const logout = async () => {
    try { await appLogout(); generation.current++; catalogGeneration.current++; historyGeneration.current++; setUsername(''); setMessages([]); setFiles([]); setAttachments([]); setSelected(null); setAgents([]); setConversations([]); setHistoryError(''); setHistoryLoading(false); setDraft(''); setLoginOpen(true); sessionStorage.removeItem('hexa.app.recent'); }
    catch (cause) { setError(errorText(cause)); }
  };
  const chooseFiles = async (list: FileList | null) => {
    const serial = generation.current;
    setUploading(true);
    try {
      for (const file of Array.from(list || [])) {
        const result = await appUploadFile(file);
        if (serial === generation.current) setAttachments(current => [...current, result]);
        else await appDeleteFile(result.id).catch(() => {});
      }
    } catch (cause) { if (serial === generation.current) setError(errorText(cause)); }
    finally { setUploading(false); if (uploadInput.current) uploadInput.current.value = ''; }
  };
  const openFile = async (file: AppFile, download: boolean) => {
    try {
      const blob = await appFileBlob(file.id);
      if (!download && file.media_type.startsWith('text/') && file.media_type !== 'text/html') { setPreview({ name: file.filename, text: (await blob.text()).slice(0, 200000) }); return; }
      const image = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.media_type);
      const url = URL.createObjectURL(new Blob([blob], { type: image ? file.media_type : 'application/octet-stream' }));
      if (!download && image) { setPreview({ name: file.filename, image: url }); return; }
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = file.filename; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { setError(errorText(cause)); }
  };
  const statusLabel = ({ idle: '就绪', running: '生成中', completed: '已完成', unknown: '等待恢复', failed: '失败', incomplete: '未完成', cancelled: '已取消' } as Record<string, string>)[status] || status;
  const gatewayLabel = ({ checking: '正在连接 Gateway', connected: 'Gateway 已连接', unavailable: 'Gateway 不可用', unauthorized: 'Gateway 鉴权失败' } as Record<GatewayState, string>)[gatewayState];
  return <ConfigProvider theme={{ algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm, token: { colorPrimary: '#2563eb', borderRadius: 9 } }}><div className={`app hexa-backend-app${dark ? ' dark' : ''}`}>
    <NavigationRail active={active} onSelect={setActive} labels={railLabels} dark={dark} onTheme={() => setDark(value => !value)} onSettings={() => { setLabelsDraft(railLabels); setSettingsOpen(true); }} workspace={<button className="workspace" aria-label="切换工作区" onClick={() => setWorkspaceOpen(true)}>W</button>} user={<UserMenu user={username ? { username, displayName: username, signedInAt: 0 } : null} workspaceName={workspaces.find(row => row.id === workspaceId)?.name || 'Hexa 工作空间'} dark={dark} onRequestLogin={() => setLoginOpen(true)} onUserChange={user => { if (!user) void logout(); }} />} />
    <aside className="sidebar"><header><b>{CLIENT_MODULES.find(item => item.id === active)?.label}</b><small>{workspaces.find(row => row.id === workspaceId)?.name || 'Hexa 工作空间'}</small></header>{active === 'chat' && <Button block icon={<PlusOutlined />} disabled={busy} onClick={() => newChat()}>新建对话</Button>}{active === 'tasks' && <Button block icon={<PlusOutlined />} onClick={() => setTaskSection('mine')}>新建任务</Button>}<div className="side-list"><small>{active === 'chat' ? '对话历史' : active === 'tasks' ? '任务工作区' : '全部智能体'}</small>{active === 'chat' && <>{historyLoading && <p role="status">正在加载历史…</p>}{historyError && <div role="alert">{historyError}<button onClick={() => void loadHistory()}>重试</button></div>}{!historyLoading && !historyError && !conversations.length && <p>暂无历史对话</p>}</>}{active === 'chat' && conversations.map(row => <button key={row.id} aria-label={row.title} disabled={busy} className={selected === row.id ? 'selected' : ''} onClick={() => setSelected(row.id)}>{row.title}{row.status === 'unknown' && <small> · 待恢复</small>}</button>)}{active === 'tasks' && <><button className={taskSection === 'mine' ? 'selected' : ''} onClick={() => setTaskSection('mine')}><span>我的任务</span><small>3</small></button><button className={taskSection === 'templates' ? 'selected' : ''} onClick={() => setTaskSection('templates')}><span>模板管理</span><small>3</small></button><span className="side-list-divider" aria-hidden="true" /><button className={taskSection === 'runs' ? 'selected' : ''} onClick={() => setTaskSection('runs')}><span>运行记录</span><small>12</small></button>{taskSection === 'runs' && <><button className="sidebar-run-toggle" aria-label={runListCollapsed ? '展开运行记录' : '收起运行记录'} onClick={() => setRunListCollapsed(value => !value)}>{runListCollapsed ? '展开运行记录' : '收起运行记录'}</button>{!runListCollapsed && <div className="sidebar-run-list" aria-label="运行记录列表">{sampleRuns.map(run => <button key={run.id} className={run.id === selectedRunId ? 'selected' : ''} aria-label={`${run.title} ${run.status}`} onClick={() => setSelectedRunId(run.id)}><span>{run.title}</span><small>{run.time} · {run.detail}</small></button>)}</div>}</>}</>}{active === 'agents' && agents.map(row => <button key={row.id} disabled={busy} onClick={() => newChat(row.id)}>{row.name}</button>)}</div><small className="app-user">{checking ? '检查登录状态…' : ''}</small></aside>
    <main className="main">{active === 'tasks' && <AppTasks section={taskSection} selectedRunId={selectedRunId} onSectionChange={setTaskSection} onRunChange={setSelectedRunId} onCreate={() => setTaskSection('mine')} />}{active === 'agents' ? <AppAgentsPanel agents={agents} reload={loadAgents} onChat={newChat} /> : active === 'chat' && <section className={`page chat-page${inspectorOpen ? ' inspector-open' : ''}`}>
      <header><small>当前对话</small><h1>{conversations.find(row => row.id === selected)?.title || '新对话'}</h1><Tag color={gatewayState === 'connected' ? 'green' : gatewayState === 'unavailable' || gatewayState === 'unauthorized' ? 'red' : 'blue'}>{username ? gatewayLabel : '未登录'}</Tag></header>
      {error && <p className="error-banner" role="alert">{error}<button onClick={() => { setError(''); void (selected ? restoreConversation(selected, generation.current) : loadCatalog()).catch(cause => setError(errorText(cause))); }}>刷新状态</button></p>}
      <div className={`chat-stage${inspectorOpen ? ' inspector-open' : ''}`}><div className="chat-column"><div className="chat">{loading ? <p role="status">正在恢复会话…</p> : messages.length ? messages.map((message, index) => message.role === 'user' ? <div className="bubble user" key={index}>{message.text}</div> : <article className="reply" key={index}><div><b>{agent?.name || 'Agent'}</b><small>{model}</small></div><p>{message.text}</p></article>) : <div className="empty-state"><h2>开始一次对话</h2><p>从右侧选择 Agent 和模型，发送你的任务。</p></div>}{busy && status === 'running' && <article className="reply" role="status"><p>{liveText || 'Agent 正在生成…'}</p></article>}</div><div className="composer"><textarea aria-label="消息输入" value={draft} onChange={event => setDraft(event.target.value)} disabled={!username} placeholder="发送消息…" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} /><div className="composer-actions"><input ref={uploadInput} type="file" multiple hidden onChange={event => void chooseFiles(event.target.files)} /><button disabled={busy || uploading} onClick={() => uploadInput.current?.click()}>{uploading ? '正在上传…' : '附件'}</button><span>{statusLabel}</span>{busy && executingId && <button onClick={() => { void appCancelConversation(executingId).then(result => setStatus(result.status)).catch(cause => setError(errorText(cause))); }}>取消生成</button>}<Button type="primary" shape="circle" aria-label="发送消息" disabled={(!draft.trim() && !attachments.length) || !agent || !username || loading || busy || uploading || modelsLoading || Boolean(modelsError) || !model || status === 'unknown'} onClick={() => void send()}>↑</Button></div>{attachments.map(file => <div className="attachment-card" key={file.id}><span>{file.media_type.startsWith('image/') ? '图片' : '文件'} · {file.filename} · {file.bytes} B</span><button aria-label={`移除 ${file.filename}`} onClick={() => { void appDeleteFile(file.id).then(() => setAttachments(current => current.filter(row => row.id !== file.id))).catch(cause => setError(errorText(cause))); }}>移除</button></div>)}</div></div>
      {inspectorOpen ? <>
        <button className="app-inspector-scrim" aria-label="关闭上下文遮罩" onClick={() => setInspectorOpen(false)} />
        <aside className="inspector-panel app-inspector" aria-label="会话检查器">
          <InspectorHeader tab={tab} onTab={setTab} onClose={() => setInspectorOpen(false)} closeLabel="收起上下文" />
          <div className="inspector-body">
            {tab === 'session' ? <>
              <InspectorSection title="参与 Agent">
                <div className="runtime-picker">
                  <label htmlFor="chat-agent">Agent</label><select id="chat-agent" aria-label="会话 Agent" disabled={locked} value={agentId} onChange={event => { setAgentId(event.target.value); setModel(''); setModels([]); setModelsError(''); setModelsLoading(Boolean(event.target.value)); }}><option value="">请选择 Agent</option>{agents.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
                  <label htmlFor="chat-model">模型</label><select id="chat-model" aria-label="会话模型" value={model} disabled={locked || modelsLoading || Boolean(modelsError)} onChange={event => setModel(event.target.value)}>{model && !models.some(row => row.id === model) && <option value={model}>{model}</option>}{models.map(row => <option key={row.id} value={row.id}>{row.label}</option>)}</select>
                  {modelsLoading && <small role="status">正在读取模型…</small>}
                  {modelsError && <div className="app-model-error"><p role="alert">{modelsError}</p><Button size="small" onClick={() => setModelsRevision(value => value + 1)}>重试模型</Button></div>}
                  {locked && <small>当前会话已锁定 Agent 和模型。</small>}
                </div>
              </InspectorSection>
              <InspectorSection title="连接"><InspectorKV label="Gateway" value="由应用后端管理" /><InspectorKV label="连接状态" value={username ? gatewayLabel : '未登录'} /><InspectorKV label="后端" value={agent?.base || '未选择'} /></InspectorSection>
              <InspectorSection title="上下文"><InspectorKV label="模板" value="未使用模板" /><InspectorKV label="会话轮数" value={String(messages.filter(row => row.role === 'user').length)} /><InspectorKV label="响应" value={responseId ? `${responseId.slice(0, 8)}…` : '尚无响应'} /><InspectorKV label="请求状态" value={statusLabel} /></InspectorSection>
            </> : tab === 'artifacts' && files.length ? <div className="app-file-list">{files.map(file => <div className="inspector-file" key={file.id}><strong>{file.filename}</strong><small>{file.direction === 'input' ? '输入' : '输出'} · {file.media_type} · {file.bytes} B</small>{file.direction === 'output' && <div><button onClick={() => void openFile(file, false)}>安全预览</button><button onClick={() => void openFile(file, true)}>下载</button></div>}</div>)}</div> : <p className="inspector-empty">{tab === 'approvals' ? '暂无待审批。' : tab === 'tools' ? '暂无工具状态。' : '暂无会话产物。'}</p>}
          </div>
        </aside>
      </> : <button className="inspector-reveal" aria-label="展开上下文" onClick={() => setInspectorOpen(true)}>上下文</button>}</div>
    </section>}</main>
    <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} sections={[{ id: 'interface', label: '界面与导航', content: <><Checkbox checked={labelsDraft} onChange={event => setLabelsDraft(event.target.checked)}>一级导航显示文字</Checkbox><p className="gateway-settings-note">Gateway 连接由应用后端管理。</p></> }]} onSubmit={event => { event.preventDefault(); setRailLabels(labelsDraft); localStorage.setItem('hexa.client.rail-labels', JSON.stringify(labelsDraft)); setSettingsOpen(false); }} footer={<><Button onClick={() => setSettingsOpen(false)}>取消</Button><Button htmlType="submit" type="primary">保存设置</Button></>} />
    <Modal open={Boolean(preview)} title={preview?.name} onCancel={() => setPreview(null)} footer={null}>{preview?.image ? <img alt={preview.name} src={preview.image} style={{ maxWidth: '100%' }} /> : <pre style={{ whiteSpace: 'pre-wrap', maxHeight: '60vh', overflow: 'auto' }}>{preview?.text}</pre>}</Modal>
    <AppLoginDialog open={loginOpen} onSuccess={name => { setUsername(name); setLoginOpen(false); }} onClose={() => setLoginOpen(false)} />
    <Modal open={workspaceOpen} title="工作空间" onCancel={() => setWorkspaceOpen(false)} footer={null}><div className="app-workspaces">{workspaces.map(row => <button key={row.id} onClick={() => { void appSelectWorkspace(row.id).then(() => { setWorkspaceId(row.id); newChat(); setWorkspaceOpen(false); }).catch(cause => setError(errorText(cause))); }}>{row.name}{workspaceId === row.id ? ' · 当前' : ''}</button>)}<label>新工作空间<input value={workspaceName} onChange={event => setWorkspaceName(event.target.value)} /></label><Button disabled={!workspaceName.trim()} onClick={() => { void appCreateWorkspace(workspaceName.trim(), '').then(() => { setWorkspaceName(''); return loadCatalog(); }).catch(cause => setError(errorText(cause))); }}>创建工作空间</Button></div></Modal>
  </div></ConfigProvider>;
}
