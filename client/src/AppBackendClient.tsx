import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { appUploadFile, appDeleteFile, appConversationFiles, appCancelConversation, appWatchConversation, appFileBlob, type AppFile } from './app-api';
import { Button, Checkbox, ConfigProvider, Modal, Tag, theme } from 'antd';
import { antdTheme } from './theme';
import { PlusOutlined, RobotOutlined } from '@ant-design/icons';
import { UserMenu } from './UserMenu';
import { InspectorHeader, InspectorSection, InspectorKV, type InspectorTab } from './ChatInspector';
import { SettingsDialog } from './SettingsDialog';
import { NavigationRail, CLIENT_MODULES, type ClientModule } from './NavigationRail';
import { AppAgentsPanel } from './AppAgentsPanel';
import { appModelSelection, onAppSessionExpired } from './app-api';
import { AppLoginDialog } from './AppLoginDialog';
import { AppTasks } from './AppTasks';
import { SuperAgentCoordinator } from './SuperAgentCoordinator';
import { WorkspaceMenu } from './WorkspaceMenu';
import { CopyReplyButton, MarkdownMessage } from './MarkdownMessage';
import { formatElapsed } from './reply-details';
import { createWorkspaceRestorer, type WorkspaceRestoration } from './workspace-restoration';
import type { AppMessageExecution } from './app-api';
import { AppApiError, appSession, appLogout, appListAgents, appListAgentModels, appListConversations, appCreateConversation, appGetConversation, appConversationStatus, appSendMessage, appListWorkspaces, type AppAgent, type AppConversation, type AppMessage } from './app-api';

const errorText = (cause: unknown) => cause instanceof AppApiError ? cause.message : '应用服务暂时不可用，请重试。';
type Workspace = { id: number; name: string; description: string };
type GatewayState = 'checking' | 'connected' | 'unavailable' | 'unauthorized';
const CONTEXT_MIN = 280, CONTEXT_MAX = 560;
type ReplyExecution = AppMessageExecution;

const executionStatus = (value: string) => ({ completed: '已完成', in_progress: '执行中', failed: '失败', cancelled: '已取消', incomplete: '未完成', running: '执行中', unknown: '等待恢复' } as Record<string, string>)[value] || value;

function ReplyDetails({ execution, model, base, running }: { execution?: AppMessageExecution; model: string; base: string; running: boolean }) {
  const elapsed = formatElapsed(execution?.elapsed_ms);
  const steps = execution?.steps || [];
  return <details className="reply-details">
    <summary aria-label="回复详情"><span>{elapsed}</span><span className="reply-details-chevron" aria-hidden="true">›</span></summary>
    <div className="reply-details-content">
      <div><span>Harness</span><strong>{execution?.harness_id || base || '未提供'}</strong></div>
      <div><span>模型</span><strong>{execution?.model || model || '未提供'}</strong></div>
      {execution?.status && <div><span>状态</span><strong>{executionStatus(execution.status)}</strong></div>}
      <div className="reply-execution"><span>思考执行过程</span><strong>{execution?.reasoning || (running ? '正在接收 Gateway 流式输出' : 'Gateway 未返回思考摘要。')}</strong></div>
      {steps.length > 0 && <div className="reply-steps"><span>工具执行</span>{steps.map(step => <span key={step.id}><b>{step.name}</b><em>{executionStatus(step.status)}</em></span>)}</div>}
    </div>
  </details>;
}

function ContextResizer({ width, max, onChange }: { width: number; max: number; onChange: (width: number) => void }) {
  const drag = useRef<{ x: number; width: number } | null>(null);
  const stop = () => { drag.current = null; document.body.classList.remove('inspector-resizing'); };
  return <div className="inspector-resizer chat-context-resizer" role="separator" aria-label="调整上下文宽度" aria-orientation="vertical"
    aria-valuemin={CONTEXT_MIN} aria-valuemax={Math.round(max)} aria-valuenow={Math.round(width)} tabIndex={0}
    onPointerDown={event => {
      if (event.button !== 0) return;
      drag.current = { x: event.clientX, width };
      event.currentTarget.setPointerCapture(event.pointerId);
      document.body.classList.add('inspector-resizing');
      event.preventDefault();
    }}
    onPointerMove={event => { if (drag.current) onChange(drag.current.width + drag.current.x - event.clientX); }}
    onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={stop}
    onKeyDown={event => {
      const delta = event.key === 'ArrowLeft' ? 24 : event.key === 'ArrowRight' ? -24 : 0;
      if (!delta && !['Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      onChange(event.key === 'Home' ? CONTEXT_MIN : event.key === 'End' ? max : width + delta);
    }} />;
}

export function AppBackendClient() {
  const [username, setUsername] = useState('');
  const [checking, setChecking] = useState(true);
  const [loginOpen, setLoginOpen] = useState(false);
  const [agents, setAgents] = useState<AppAgent[]>([]);
  const [agentDetailId, setAgentDetailId] = useState<string | null>(null);
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
  const [responseStartedAt, setResponseStartedAt] = useState<number | null>(null);
  const [responseExecution, setResponseExecution] = useState<AppMessageExecution | undefined>();
  const [inspectorOpen, setInspectorOpen] = useState(() => !matchMedia('(max-width: 640px)').matches);
  const [contextWidth, setContextWidth] = useState(() => {
    const saved = Number(localStorage.getItem('hexa.chat.context-width'));
    return Number.isFinite(saved) && saved > 0 ? Math.min(CONTEXT_MAX, Math.max(CONTEXT_MIN, saved)) : 304;
  });
  const [contextMax, setContextMax] = useState(CONTEXT_MAX);
  const [tab, setTab] = useState<InspectorTab>('session');
  const [dark, setDark] = useState(false);
  const [active, setActive] = useState<ClientModule>(() => location.pathname.startsWith('/coordinator') ? 'coordinator' : /^\/(tasks|runs)\//.test(location.pathname) ? 'tasks' : 'chat');
  const [coordinatorVisited, setCoordinatorVisited] = useState(() => location.pathname.startsWith('/coordinator'));
  useEffect(() => { if (active === 'coordinator') setCoordinatorVisited(true); }, [active]);
  const [taskSection, setTaskSection] = useState<'mine' | 'templates' | 'runs'>(() => location.pathname.startsWith('/runs/') ? 'runs' : 'mine');
  const [selectedRunId, setSelectedRunId] = useState(() => location.pathname.match(/^\/runs\/(\d+)$/)?.[1] || '');
  const [taskCreateRequest, setTaskCreateRequest] = useState(0);
  const [taskCounts, setTaskCounts] = useState({ tasks: 0, runs: 0, templates: 0 });
  const [railLabels, setRailLabels] = useState(() => localStorage.getItem('hexa.client.rail-labels') !== 'false');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [labelsDraft, setLabelsDraft] = useState(railLabels);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [workspaceRestoration, setWorkspaceRestoration] = useState<WorkspaceRestoration>({ status: 'loading' });
  const workspaceRestorer = useRef<ReturnType<typeof createWorkspaceRestorer> | null>(null);
  if (!workspaceRestorer.current) workspaceRestorer.current = createWorkspaceRestorer(appListWorkspaces, state => {
    if (state.status === 'ready') {
      setWorkspaces(state.value.workspaces); setWorkspaceId(state.value.selected_id);
    }
    setWorkspaceRestoration(state);
  });
  const workspaceReady = Boolean(username) && workspaceRestoration.status === 'ready';
  const [files, setFiles] = useState<AppFile[]>([]);
  const [attachments, setAttachments] = useState<AppFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [liveText, setLiveText] = useState('');
  const [executingId, setExecutingId] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ name: string; text?: string; image?: string } | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const chatRef = useRef<HTMLDivElement>(null);
  const chatWorkspaceRef = useRef<HTMLDivElement>(null);
  const followOutput = useRef(true);
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
    const [, , restored] = await Promise.all([loadAgents(), loadHistory(), workspaceRestorer.current!.load()]);
    if (!restored) throw new AppApiError('工作空间读取失败。', 503);
  };
  useEffect(() => {
    let alive = true;
    void appSession().then(session => { if (alive) setUsername(session.username); }).catch(() => { if (alive) setLoginOpen(true); }).finally(() => { if (alive) setChecking(false); });
    return () => { alive = false; generation.current++; };
  }, []);
  useEffect(() => {
    if (username) { setGatewayState('checking'); void loadCatalog().catch(cause => setError(errorText(cause))); }
    return () => { workspaceRestorer.current!.invalidate(); };
  }, [username]);
  useEffect(() => {
    if (agentDetailId && !agents.some(row => row.id === agentDetailId)) setAgentDetailId(null);
  }, [agents, agentDetailId]);
  useEffect(() => {
    if (!username) return;
    return onAppSessionExpired(() => {
      generation.current++; catalogGeneration.current++; historyGeneration.current++;
      pending.current = null;
      workspaceRestorer.current!.invalidate(); setWorkspaceRestoration({ status: 'loading' });
      setUsername(''); setAgents([]); setAgentDetailId(null); setConversations([]); setWorkspaces([]); setWorkspaceId(null);
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
      if (snapshot.execution) setResponseExecution(current => ({ ...current, ...snapshot.execution }));
      if (snapshot.status !== 'running') {
        setStatus(snapshot.status);
        setBusy(false);
        setExecutingId(null);
        // A restored page has no pending send promise to project the final
        // persisted messages. Read them after the stream reaches its end.
        void restoreConversation(executingId, serial).catch(cause => {
          if (serial === generation.current) setError(errorText(cause));
        });
      }
    }, { waitForStart: true, startedAt: responseStartedAt || undefined });
  }, [busy, executingId]);
  useEffect(() => {
    if (!responseStartedAt || !busy) return;
    const timer = window.setInterval(() => setResponseExecution(current => ({ ...current, elapsed_ms: Date.now() - responseStartedAt })), 1000);
    return () => window.clearInterval(timer);
  }, [busy, responseStartedAt]);
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
    if (snapshot.status === 'running' && snapshot.progress) {
      setLiveText(snapshot.progress.text || '');
      setResponseId(snapshot.progress.response_id || snapshot.previous_response_id);
      const startedAt = snapshot.progress.execution?.started_at ? snapshot.progress.execution.started_at * 1000 : Date.now();
      setResponseStartedAt(startedAt);
      setResponseExecution(current => ({ ...current, ...(snapshot.progress?.execution || {}), started_at: snapshot.progress?.execution?.started_at, elapsed_ms: Date.now() - startedAt, status: 'running' }));
      setExecutingId(id);
      setBusy(true);
    } else {
      setBusy(false);
      setExecutingId(null);
    }
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
    const startedAt = Date.now();
    setBusy(true); setError(''); setStatus('running'); setLiveText(''); setResponseStartedAt(startedAt); setResponseExecution({ elapsed_ms: 0, harness_id: agentId, model, status: 'running' });
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
      pending.current = null; setDraft(''); setAttachments([]); setStatus(answer.status); setResponseId(answer.response_id); setResponseExecution(answer.assistant.execution);
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
    try { await appLogout(); generation.current++; catalogGeneration.current++; historyGeneration.current++; workspaceRestorer.current!.invalidate(); setWorkspaceRestoration({ status: 'loading' }); setWorkspaces([]); setWorkspaceId(null); setUsername(''); setMessages([]); setFiles([]); setAttachments([]); setSelected(null); setAgents([]); setAgentDetailId(null); setConversations([]); setHistoryError(''); setHistoryLoading(false); setDraft(''); setLoginOpen(true); sessionStorage.removeItem('hexa.app.recent'); }
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
  const trackLatest = () => {
    const element = chatRef.current;
    followOutput.current = !element || element.scrollHeight - element.scrollTop - element.clientHeight < 96;
  };
  useEffect(() => {
    if (!followOutput.current) return;
    const element = chatRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages, liveText, busy, status, loading]);
  useEffect(() => { localStorage.setItem('hexa.chat.context-width', String(Math.round(contextWidth))); }, [contextWidth]);
  useEffect(() => {
    const element = chatWorkspaceRef.current;
    if (!element || !inspectorOpen) return;
    const media = matchMedia('(max-width: 640px)');
    const measure = () => {
      if (!element.clientWidth || media.matches) return;
      const max = Math.max(CONTEXT_MIN, Math.min(CONTEXT_MAX, element.clientWidth - 420));
      setContextMax(max);
      setContextWidth(current => Math.min(current, max));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    media.addEventListener('change', measure);
    measure();
    return () => { observer.disconnect(); media.removeEventListener('change', measure); };
  }, [inspectorOpen]);
  const updateContextWidth = (value: number) => setContextWidth(Math.round(Math.max(CONTEXT_MIN, Math.min(contextMax, value))));
  return <ConfigProvider theme={{ algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm, ...antdTheme(dark) }}><div className={`app hexa-backend-app${dark ? ' dark' : ''}`}>
    <NavigationRail active={active} onSelect={setActive} labels={railLabels} dark={dark} onTheme={() => setDark(value => !value)} onSettings={() => { setLabelsDraft(railLabels); setSettingsOpen(true); }} workspace={<WorkspaceMenu workspaces={workspaces} currentId={workspaceId} onReload={loadCatalog} onSelected={id => { workspaceRestorer.current!.invalidate(); setWorkspaceId(id); setWorkspaceRestoration({ status: 'ready', value: { workspaces, selected_id: id } }); newChat(); }} />} user={<UserMenu user={username ? { username, displayName: username, signedInAt: 0 } : null} workspaceName={workspaces.find(row => row.id === workspaceId)?.name || 'Hexa 工作空间'} dark={dark} onRequestLogin={() => setLoginOpen(true)} onUserChange={user => { if (!user) void logout(); }} />} />
    <aside className="sidebar"><header><b>{CLIENT_MODULES.find(item => item.id === active)?.label}</b><small>{workspaces.find(row => row.id === workspaceId)?.name || 'Hexa 工作空间'}</small></header>{active === 'chat' && <Button block icon={<PlusOutlined />} disabled={busy} onClick={() => newChat()}>新建对话</Button>}{active === 'tasks' && <Button block disabled={!workspaceReady} icon={<PlusOutlined />} onClick={() => { setTaskSection('mine'); setTaskCreateRequest(value => value + 1); }}>新建任务</Button>}<div className="side-list"><small>{active === 'chat' ? '对话历史' : active === 'tasks' ? '任务工作区' : active === 'coordinator' ? '协调工作区' : '全部智能体'}</small>{active === 'chat' && <>{historyLoading && <p role="status">正在加载历史…</p>}{historyError && <div role="alert">{historyError}<button onClick={() => void loadHistory()}>重试</button></div>}{!historyLoading && !historyError && !conversations.length && <p>暂无历史对话</p>}</>}{active === 'chat' && conversations.map(row => <button key={row.id} aria-label={row.title} disabled={busy} className={selected === row.id ? 'selected' : ''} onClick={() => setSelected(row.id)}>{row.title}{row.status === 'unknown' && <small> · 待恢复</small>}</button>)}{active === 'tasks' && <nav aria-label="任务菜单"><button className={taskSection === 'mine' ? 'selected' : ''} onClick={() => setTaskSection('mine')}><span>我的任务</span><small>{taskCounts.tasks}</small></button><button className={taskSection === 'templates' ? 'selected' : ''} onClick={() => setTaskSection('templates')}><span>模板管理</span><small>{taskCounts.templates}</small></button><span className="side-list-divider" aria-hidden="true" /><button className={taskSection === 'runs' ? 'selected' : ''} onClick={() => setTaskSection('runs')}><span>运行记录</span><small>{taskCounts.runs}</small></button></nav>}{active === 'coordinator' && <p className="sidebar-note">协调 Agent 只负责分发与监控。</p>}{active === 'agents' && agents.map(row => <button key={row.id} disabled={busy} className={agentDetailId === row.id ? 'selected' : ''} aria-current={agentDetailId === row.id ? 'true' : undefined} onClick={() => setAgentDetailId(row.id)}>{row.name}</button>)}</div><small className="app-user">{checking ? '检查登录状态…' : ''}</small></aside>
    <main className="main">{(active === 'tasks' || active === 'coordinator') && !workspaceReady && <section className="page" aria-label="工作区恢复">{workspaceRestoration.status === 'error' ? <div role="alert" className="error-banner">{errorText(workspaceRestoration.cause)}<Button onClick={() => void workspaceRestorer.current!.load()}>重试工作区</Button></div> : <p role="status">{username ? '正在恢复工作区…' : '请先登录后恢复工作区。'}</p>}</section>}{workspaceReady && (coordinatorVisited || active === 'coordinator') && <SuperAgentCoordinator key={`coordinator-${username}-${workspaceId}`} visible={active === 'coordinator'} agents={agents} workspaceId={workspaceId} onOpenTasks={(mode = 'mine') => { setActive('tasks'); setTaskSection(mode); }} />}{active === 'tasks' && workspaceReady && <AppTasks section={taskSection} selectedRunId={selectedRunId} onSectionChange={setTaskSection} onRunChange={setSelectedRunId} key={`${username}-${workspaceId}`} workspaceId={workspaceId} agents={agents} createRequest={taskCreateRequest} onCountsChange={setTaskCounts} />}{active === 'agents' ? <AppAgentsPanel key={username} agents={agents} selectedAgentId={agentDetailId} onSelectAgent={setAgentDetailId} reload={loadAgents} onChat={newChat} /> : active === 'chat' && <section className={`page chat-page${inspectorOpen ? ' is-context-open' : ''}`} aria-label="对话工作台">
      <div ref={chatWorkspaceRef} className={`chat-workspace${inspectorOpen ? ' is-context-open' : ''}`} style={{ '--chat-context-width': `${contextWidth}px` } as CSSProperties}>
        <section className="chat-main" aria-label="会话内容">
          <header className="chat-main-head"><small>当前对话</small><h1>{conversations.find(row => row.id === selected)?.title || '新对话'}</h1><Tag color={gatewayState === 'connected' ? 'green' : gatewayState === 'unavailable' || gatewayState === 'unauthorized' ? 'red' : 'blue'}>{username ? gatewayLabel : '未登录'}</Tag><button className="chat-context-reveal" type="button" aria-label="展开上下文" onClick={() => setInspectorOpen(true)}>上下文</button></header>
          {error && <p className="error-banner" role="alert">{error}<button onClick={() => { setError(''); void (selected ? restoreConversation(selected, generation.current) : loadCatalog()).catch(cause => setError(errorText(cause))); }}>刷新状态</button></p>}
          <div className="chat-thread"><div className="chat-scroll" ref={chatRef} onScroll={trackLatest}><div className="chat">{loading ? <p role="status">正在恢复会话…</p> : messages.length ? messages.map((message, index) => message.role === 'user' ? <div className="bubble user" key={index}>{message.text}</div> : <article className="reply" key={index}><span className="agent-avatar reply-avatar" aria-hidden="true"><RobotOutlined /></span><div className="reply-main"><div className="reply-meta"><b>{agent?.name || 'Agent'}</b><ReplyDetails execution={message.execution as ReplyExecution | undefined} model={model} base={agent?.base || ''} running={false} /></div><div className="reply-body"><MarkdownMessage text={message.text} /></div><CopyReplyButton text={message.text} /></div></article>) : <div className="empty-state"><h2>开始一次对话</h2><p>从右侧选择 Agent 和模型，发送你的任务。</p></div>}{busy && status === 'running' && <article className="reply reply-live" role="status"><span className="agent-avatar reply-avatar" aria-hidden="true"><RobotOutlined /></span><div className="reply-main"><div className="reply-meta"><b>{agent?.name || 'Agent'}</b><ReplyDetails execution={responseExecution} model={model} base={agent?.base || ''} running /></div><div className="reply-body">{liveText ? <MarkdownMessage text={liveText} /> : <p className="reply-pending">Agent 正在生成…</p>}<span className="reply-caret" aria-hidden="true" /></div></div></article>}</div></div></div>
          <div className="composer"><textarea aria-label="消息输入" value={draft} onChange={event => setDraft(event.target.value)} disabled={!username} placeholder="发送消息…" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} /><div className="composer-actions"><input ref={uploadInput} type="file" multiple hidden onChange={event => void chooseFiles(event.target.files)} /><button disabled={busy || uploading} onClick={() => uploadInput.current?.click()}>{uploading ? '正在上传…' : '附件'}</button><span>{statusLabel}</span>{busy && executingId && <button onClick={() => { void appCancelConversation(executingId).then(result => setStatus(result.status)).catch(cause => setError(errorText(cause))); }}>取消生成</button>}<Button type="primary" shape="circle" aria-label="发送消息" disabled={(!draft.trim() && !attachments.length) || !agent || !username || loading || busy || uploading || modelsLoading || Boolean(modelsError) || !model || status === 'unknown'} onClick={() => void send()}>↑</Button></div>{attachments.map(file => <div className="attachment-card" key={file.id}><span>{file.media_type.startsWith('image/') ? '图片' : '文件'} · {file.filename} · {file.bytes} B</span><button aria-label={`移除 ${file.filename}`} onClick={() => { void appDeleteFile(file.id).then(() => setAttachments(current => current.filter(row => row.id !== file.id))).catch(cause => setError(errorText(cause))); }}>移除</button></div>)}</div>
        </section>
        {inspectorOpen ? <>
          <button className="app-inspector-scrim" aria-label="关闭上下文遮罩" onClick={() => setInspectorOpen(false)} />
          <aside className="chat-context app-inspector" aria-label="会话检查器" role="complementary">
            <ContextResizer width={contextWidth} max={contextMax} onChange={updateContextWidth} />
            <InspectorHeader tab={tab} onTab={setTab} onClose={() => setInspectorOpen(false)} closeLabel="收起上下文" />
            <div className="inspector-body">
              <p className="chat-context-eyebrow">会话上下文</p>
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
        </> : <button className="chat-context-handle" aria-label="展开上下文" onClick={() => setInspectorOpen(true)}><span>上下文</span></button>}
      </div>
    </section>}</main>
    <SettingsDialog
      open={settingsOpen}
      onClose={() => setSettingsOpen(false)}
      onSubmit={event => {
        event.preventDefault();
        setRailLabels(labelsDraft);
        localStorage.setItem('hexa.client.rail-labels', JSON.stringify(labelsDraft));
        setSettingsOpen(false);
      }}
      sections={[
        {
          id: 'connection',
          label: '连接',
          content: <div className="settings-section">
            <div className="settings-section-heading"><h2>应用服务连接</h2><p>Gateway 连接由应用后端管理。</p></div>
            <p className="gateway-settings-note">当前客户端通过已登录的应用服务访问 Gateway，无需在浏览器中保存连接地址或 API Key。</p>
          </div>,
        },
        {
          id: 'interface',
          label: '界面与导航',
          content: <div className="settings-section">
            <div className="settings-section-heading"><h2>界面与导航</h2><p>调整工作台入口的显示方式。</p></div>
            <div className="settings-option-row">
              <div><strong>一级导航显示文字</strong><small>在对话、任务和智能体图标下方显示名称。</small></div>
              <Checkbox aria-label="一级导航显示文字" checked={labelsDraft} onChange={event => setLabelsDraft(event.target.checked)} />
            </div>
          </div>,
        },
      ]}
      footer={<><span className="settings-footer-spacer" /><Button onClick={() => setSettingsOpen(false)}>取消</Button><Button htmlType="submit" type="primary">保存设置</Button></>}
    />
    <Modal open={Boolean(preview)} title={preview?.name} onCancel={() => setPreview(null)} footer={null}>{preview?.image ? <img alt={preview.name} src={preview.image} style={{ maxWidth: '100%' }} /> : <pre style={{ whiteSpace: 'pre-wrap', maxHeight: '60vh', overflow: 'auto' }}>{preview?.text}</pre>}</Modal>
    <AppLoginDialog open={loginOpen} onSuccess={name => { setUsername(name); setLoginOpen(false); }} onClose={() => setLoginOpen(false)} />
  </div></ConfigProvider>;
}
