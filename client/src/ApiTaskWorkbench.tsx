import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { Button, Drawer, Modal } from 'antd';
import { AppstoreOutlined, FileTextOutlined, PlusOutlined, UnorderedListOutlined } from '@ant-design/icons';
import {
  AppApiError, appCreateTask, appGetTask, appListTasksPage, appListRuns, appGetRun, appSaveTaskInput,
  appSaveTaskWorkflow, appStartTaskRun, appControlRun, appContinueRun, appWatchTaskRun,
  appListTemplates, appGetTemplate, appSaveTemplate, appSaveTaskAsTemplate, appTaskState,
  appDebugNode, appRetryNode, appSkipNode, appAdoptNode, appArtifactBlob, appListTaskArtifacts, appListRunArtifacts, appListNodeArtifacts,
  type AppAgent, type AppTask, type AppRun, type AppTemplate, type AppTaskNode, type AppArtifact,
} from './app-api';
import { Templates } from './AppModules';
import { activeRun, flowEdgeTone, nodeStatusLive, nodeStatusTone, statusLive, taskLabels, runLabels, nodeLabels, statusTone, taskProgress, workflowDraft, snapshotEvents, waitingGate, latestRunOutputs } from './task-workbench';
import { WorkflowCanvas } from './workflow-canvas';
import { layoutRunNodes, replayStates } from './run-history';
import { mergePage, nextOffset } from './pagination';
import type { ClientTemplate } from './app-types';
import { loadWorkbenchLists } from './workbench-loading';

export type TaskSection = 'mine' | 'templates' | 'runs';
type Counts = { tasks: number; runs: number; templates: number };
type PageState = { offset: number; limit: number; has_more: boolean };
const errorText = (cause: unknown) => cause instanceof AppApiError ? cause.message : '应用服务暂时不可用，请重试。';
const Pill = ({ status, label }: { status: string; label: string }) => <span className={`workbench-status ${statusTone(status)}${statusLive(status) ? ' is-live' : ''}`}><i aria-hidden="true" />{label}</span>;

const latestTemplateVersion = (template: AppTemplate) => template.latest_version || template.versions.at(-1);

function useMobile() {
  const [mobile, setMobile] = useState(() => matchMedia('(max-width: 900px)').matches);
  useEffect(() => { const media = matchMedia('(max-width: 900px)'); const sync = () => setMobile(media.matches); media.addEventListener('change', sync); return () => media.removeEventListener('change', sync); }, []);
  return mobile;
}

export function AppTasks({ section = 'mine', onSectionChange, selectedRunId = '', onRunChange, workspaceId = null, agents = [], createRequest = 0, onCountsChange }: {
  section?: TaskSection; onSectionChange?: (section: TaskSection) => void; selectedRunId?: string;
  onRunChange?: (id: string) => void; workspaceId?: number | null; agents?: AppAgent[]; createRequest?: number; onCountsChange?: (counts: Counts) => void;
}) {
  const mobile = useMobile();
  const [tasks, setTasks] = useState<AppTask[]>([]), [runs, setRuns] = useState<AppRun[]>([]), [templates, setTemplates] = useState<AppTemplate[]>([]);
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [busy, setBusy] = useState(false), [templateVersionsLoading, setTemplateVersionsLoading] = useState(false);
  const [taskId, setTaskId] = useState<number | null>(() => Number(location.pathname.match(/^\/tasks\/(\d+)$/)?.[1]) || null), [runId, setRunId] = useState<number | null>(Number(selectedRunId.replace('run-', '')) || null), [templateId, setTemplateId] = useState<number | null>(null);
  const [query, setQuery] = useState(''), [filter, setFilter] = useState('all'), [view, setView] = useState<'list' | 'cards'>('list'), [page, setPage] = useState(1);
  const [detailOpen, setDetailOpen] = useState(false), [collapsed, setCollapsed] = useState(false), [flowOpen, setFlowOpen] = useState(false), [taskFlowOpen, setTaskFlowOpen] = useState(false), [runConfirmOpen, setRunConfirmOpen] = useState(false);
  const [creating, setCreating] = useState(false), [title, setTitle] = useState(''), [description, setDescription] = useState(''), [input, setInput] = useState(''), [sourceVersion, setSourceVersion] = useState<number | null>(null);
  const [runInput, setRunInput] = useState(''), [runError, setRunError] = useState('');
  const [editor, setEditor] = useState<{ task?: AppTask; template?: AppTemplate; draft: ClientTemplate } | null>(null);
  const [streamRetry, setStreamRetry] = useState(0), [streamError, setStreamError] = useState('');
  const [detailLoading, setDetailLoading] = useState(false);
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false), [targetTemplate, setTargetTemplate] = useState<number | null>(null);
  const [gateRefs, setGateRefs] = useState<string[]>([]);
  const [taskResults, setTaskResults] = useState<Array<{ nodeId: string; output: Record<string, unknown> | null }>>([]), [resultError, setResultError] = useState('');
  const splitRef = useRef<HTMLDivElement>(null), [splitWidth, setSplitWidth] = useState(0);
  const [widths, setWidths] = useState<Partial<Record<TaskSection, number>>>({});
  const generation = useRef(0), detailGeneration = useRef(0);
  const commandKeys = useRef(new Map<string, string>());
  const previousCreateRequest = useRef(createRequest);
  const cursors = useRef<Record<TaskSection, number | null>>({ mine: null, runs: null, templates: null });
  const [moreLoading, setMoreLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [listIds, setListIds] = useState<Record<TaskSection, number[]>>({ mine: [], runs: [], templates: [] });
  const [retryPage, setRetryPage] = useState(false);

  const load = useCallback(async () => {
    const serial = ++generation.current;
    setLoading(true); setDetailLoading(false); setMoreLoading(false); setError(''); setRetryPage(false); setStreamError('');
    const linkedTaskId = Number(location.pathname.match(/^\/tasks\/(\d+)$/)?.[1]) || null;
    const linkedRunId = Number(location.pathname.match(/^\/runs\/(\d+)$/)?.[1]) || null;
    try {
      const options = { offset: 0, limit: 20, workspaceId };
      // A deep-linked run/task is the primary screen. Load it independently so a
      // secondary list endpoint (templates, global runs, or a stale deployment)
      // cannot turn a valid detail page into a misleading "Not Found" state.
      const linked = await Promise.allSettled([
        linkedRunId ? appGetRun(linkedRunId) : Promise.resolve(null),
        linkedTaskId ? appGetTask(linkedTaskId) : Promise.resolve(null),
      ]);
      if (serial !== generation.current) return;
      let linkedRun = linked[0].status === 'fulfilled' ? linked[0].value : null;
      const linkedTask = linked[1].status === 'fulfilled' ? linked[1].value : null;
      let parent: AppTask | null = linkedTask;
      let routeError = '';
      if (linkedRun) {
        try { parent = await appGetTask(linkedRun.task_id); }
        catch (cause) { routeError = errorText(cause); linkedRun = null; }
      }
      if (serial !== generation.current) return;
      if (parent && (parent.workspace_id ?? null) !== workspaceId) {
        routeError = '该记录不在当前工作区，请切换工作区。';
        linkedRun = null; parent = null;
      }
      if (linkedRun) setRuns(current => mergePage(current, [linkedRun!]));
      if (parent) setTasks(current => mergePage(current, [parent!]));
      const detailFailure = linkedRunId && linked[0].status === 'rejected' ? errorText(linked[0].reason) : linkedTaskId && linked[1].status === 'rejected' ? errorText(linked[1].reason) : '';

      const lists = await loadWorkbenchLists({
        tasks: appListTasksPage({ ...options, ...(section === 'mine' ? { q: query, status: filter } : {}) }),
        templates: appListTemplates({ ...options, ...(section === 'templates' ? { q: query } : {}) }),
        runs: appListRuns({ ...options, ...(section === 'runs' ? { q: query, status: filter } : {}) }),
      });
      if (serial !== generation.current) return;
      const taskPage = lists.tasks || { tasks: [], pagination: { offset: 0, limit: 20, has_more: false } };
      const templatePage = lists.templates || { templates: [], pagination: { offset: 0, limit: 20, has_more: false } };
      const runPage = lists.runs || { runs: [], pagination: { offset: 0, limit: 20, has_more: false } };
      const listFailure = lists.failures.find(failure => failure.section === (section === 'mine' ? 'tasks' : section)) || lists.failures[0];
      cursors.current = { mine: nextOffset(taskPage.pagination), templates: nextOffset(templatePage.pagination), runs: nextOffset(runPage.pagination) };
      setHasMore(cursors.current[section] !== null);
      const scoped = taskPage.tasks.filter(row => (row.workspace_id ?? null) === workspaceId);
      if (parent && !scoped.some(task => task.id === parent!.id)) scoped.unshift(parent);
      const snapshots = (await Promise.allSettled(scoped.filter(task => task.latest_run_id && !runPage.runs.some(run => run.id === task.latest_run_id)).map(task => appGetRun(task.latest_run_id!)))).flatMap(result => result.status === 'fulfilled' ? [result.value] : []);
      if (serial !== generation.current) return;
      setListIds({ mine: taskPage.tasks.map(t => t.id), runs: runPage.runs.map(r => r.id), templates: templatePage.templates.map(t => t.id) });
      setTasks(current => mergePage(current.filter(t => t.id === taskId && (t.workspace_id ?? null) === workspaceId), scoped));
      setTemplates(templatePage.templates.filter(t => (t.workspace_id ?? null) === workspaceId));
      setRuns(current => mergePage(mergePage(mergePage(current.filter(r => r.id === runId && scoped.some(t => t.id === r.task_id)), runPage.runs), snapshots), linkedRun ? [linkedRun] : []).sort((a, b) => b.id - a.id));
      if (serial !== generation.current) return;
      if (routeError || detailFailure) setError(routeError || detailFailure);
      else if (listFailure) setError(listFailure.message);
    } catch (cause) { if (serial === generation.current) setError(errorText(cause)); }
    finally { if (serial === generation.current) setLoading(false); }
  }, [workspaceId, section, query, filter]);

  useEffect(() => { void load(); return () => { generation.current++; detailGeneration.current++; }; }, [load]);
  useEffect(() => { onCountsChange?.({ tasks: tasks.length, runs: runs.length, templates: templates.length }); }, [tasks.length, runs.length, templates.length, onCountsChange]);
  useEffect(() => { setQuery(''); setFilter('all'); setPage(1); setDetailOpen(false); setFlowOpen(false); setTaskFlowOpen(false); }, [section]);
  useEffect(() => { setPage(1); }, [query, filter]);
  useEffect(() => { if (selectedRunId) setRunId(Number(selectedRunId.replace('run-', '')) || null); }, [selectedRunId]);
  useEffect(() => { if (previousCreateRequest.current !== createRequest) { previousCreateRequest.current = createRequest; setTitle(''); setDescription(''); setInput(''); setSourceVersion(null); setCreating(true); } }, [createRequest]);
  useEffect(() => {
    const element = splitRef.current;
    if (!element || mobile) return;
    const measure = () => setSplitWidth(element.clientWidth);
    const observer = new ResizeObserver(measure); observer.observe(element); measure();
    return () => observer.disconnect();
  }, [mobile, section, loading, editor, flowOpen]);

  const selectedTask = taskId !== null ? tasks.find(t => t.id === taskId) : tasks[0];
  const selectedRun = runId !== null ? runs.find(r => r.id === runId) : runs[0];
  const selectedTemplate = templates.find(t => t.id === templateId) || templates[0];
  const resultKey = JSON.stringify(selectedTask?.current_result || {});
  useEffect(() => {
    let alive = true;
    setTaskResults([]); setResultError('');
    if (!selectedTask) return;
    const entries = Object.entries(selectedTask.current_result || {});
    void Promise.all(entries.map(async ([nodeId, id]) => ({ nodeId, output: (await appDebugNode(id)).output })))
      .then(results => { if (alive) setTaskResults(results); })
      .catch(() => { if (alive) setResultError('结果加载失败，请刷新任务后重试。'); });
    return () => { alive = false; };
  }, [selectedTask?.id, resultKey]);
  const currentTaskRun = selectedTask ? runs.find(r => r.id === selectedTask.latest_run_id) : undefined;
  const adoptedNodeIds = new Set(Object.keys(selectedTask?.current_result || {}));
  const currentTaskOutputs = latestRunOutputs(currentTaskRun).filter(row => !adoptedNodeIds.has(row.nodeId));
  const gateRun = section === 'runs' ? selectedRun : currentTaskRun;
  const gate = waitingGate(gateRun);
  useEffect(() => { setGateRefs([]); }, [gateRun?.id, gate?.id]);

  // Observe every loaded active run, including runs restored after a browser reload.
  const activeIds = runs.filter(run => activeRun(run) && !run.paused && run.status !== 'waiting_human').map(run => run.id).join(',');
  useEffect(() => {
    let alive = true;
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const stops: Array<() => void> = [];
    const serial = generation.current;
    const update = (snapshot: AppRun) => {
      if (!alive || serial !== generation.current) return;
      setRuns(current => current.map(run => run.id === snapshot.id ? snapshot : run));
      if (!activeRun(snapshot) || snapshot.status === 'waiting_human' || snapshot.paused) {
        void appGetTask(snapshot.task_id).then(task => { if (serial === generation.current) setTasks(current => current.map(t => t.id === task.id ? task : t)); }).catch(() => { if (alive) setStreamError('任务状态刷新失败，请刷新状态。'); });
      }
    };
    const poll = (id: number) => {
      const timer = setTimeout(() => {
        timers.delete(timer);
        void appGetRun(id).then(snapshot => { update(snapshot); if (alive && activeRun(snapshot) && !snapshot.paused && snapshot.status !== 'waiting_human') poll(id); }).catch(() => { if (alive) poll(id); });
      }, 2000);
      timers.add(timer);
    };
    setStreamError('');
    for (const id of activeIds.split(',').filter(Boolean).map(Number)) stops.push(appWatchTaskRun(id, update, () => { if (alive) { setStreamError('实时连接中断，正在定时刷新运行状态。'); poll(id); } }));
    return () => { alive = false; stops.forEach(stop => stop()); timers.forEach(clearTimeout); };
  }, [activeIds, streamRetry, loading]);

  const execute = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); } catch (cause) { setError(errorText(cause)); } finally { setBusy(false); }
  };
  const keyed = async <T,>(identity: string, action: (key: string) => Promise<T>) => {
    const key = commandKeys.current.get(identity) || crypto.randomUUID(); commandKeys.current.set(identity, key);
    try { const result = await action(key); commandKeys.current.delete(identity); return result; }
    catch (cause) { if (cause instanceof AppApiError && cause.status !== 0 && cause.status < 500) commandKeys.current.delete(identity); throw cause; }
  };
  const updateRun = (run: AppRun) => setRuns(current => [run, ...current.filter(r => r.id !== run.id)].sort((a, b) => b.id - a.id));
  const applySnapshotAction = async (runId: number, action: () => Promise<unknown>) => {
    const result = await action();
    if (result && typeof result === 'object' && 'task_id' in result && 'nodes' in result) {
      const run = result as AppRun;
      updateRun(run); setRunId(run.id); onRunChange?.(`run-${run.id}`);
    } else updateRun(await appGetRun(runId));
  };
  const openTaskFlow = () => {
    if (!selectedTask?.workflow?.nodes.length) return;
    setTaskFlowOpen(true);
    if (mobile) setDetailOpen(false);
  };
  const chooseTask = async (id: number) => {
    history.replaceState(null, '', `/tasks/${id}`);
    setTaskId(id); setTaskFlowOpen(false); setDetailOpen(true); setCollapsed(false); setDetailLoading(true);
    const serial = ++detailGeneration.current;
    try { const task = await appGetTask(id); if (serial === detailGeneration.current) setTasks(current => mergePage(current, [task])); }
    catch (cause) { if (serial === detailGeneration.current) setError(errorText(cause)); }
    finally { if (serial === detailGeneration.current) setDetailLoading(false); }
  };
  const chooseRun = async (id: number) => {
    history.replaceState(null, '', `/runs/${id}`);
    setRunId(id); onRunChange?.(`run-${id}`); setDetailOpen(true); setCollapsed(false); setDetailLoading(true);
    const serial = ++detailGeneration.current;
    try { const run = await appGetRun(id); if (serial === detailGeneration.current) updateRun(run); }
    catch (cause) { if (serial === detailGeneration.current) setError(errorText(cause)); }
    finally { if (serial === detailGeneration.current) setDetailLoading(false); }
  };
  const openCreate = (template?: AppTemplate) => { setTitle(template?.title || ''); setDescription(''); setInput(''); setSourceVersion(template ? latestTemplateVersion(template)?.id || null : null); setCreating(true); };
  const editTask = () => selectedTask && void execute(async () => {
    const task = await appGetTask(selectedTask.id);
    setDetailOpen(false);
    setEditor({ task, draft: { id: String(task.id), title: task.title, description: task.description, version: task.current_revision, ...workflowDraft(task.workflow) } });
  });
  const readCurrentTemplate = (template: AppTemplate) => appGetTemplate(template.id, { versionsLimit: 20 });
  const editTemplate = () => selectedTemplate && void execute(async () => {
    const template = await readCurrentTemplate(selectedTemplate), latest = latestTemplateVersion(template);
    setEditor({ template, draft: { id: String(template.id), title: template.title, description: '', version: latest?.version || 0, ...workflowDraft(latest?.workflow) } });
  });
  const useTemplate = () => selectedTemplate && void execute(async () => {
    const template = await readCurrentTemplate(selectedTemplate);
    setTemplates(current => current.map(item => item.id === template.id ? template : item));
    openCreate(template);
  });
  const loadMoreTemplateVersions = () => selectedTemplate?.versions_pagination?.has_more && void (async () => {
    if (templateVersionsLoading) return;
    const serial = generation.current;
    setTemplateVersionsLoading(true); setError('');
    try {
      const offset = nextOffset(selectedTemplate.versions_pagination);
      if (offset === null) return;
      const page = await appGetTemplate(selectedTemplate.id, { versionsOffset: offset, versionsLimit: 20 });
      if (serial !== generation.current) return;
      setTemplates(current => current.map(template => {
        if (template.id !== selectedTemplate.id) return template;
        return { ...template, latest_version: page.latest_version || template.latest_version, versions: mergePage(template.versions, page.versions), versions_pagination: page.versions_pagination };
      }));
    } catch (cause) { setError(errorText(cause)); }
    finally { setTemplateVersionsLoading(false); }
  })();
  const start = async () => {
    if (!selectedTask || busy) return;
    setBusy(true); setRunError('');
    try {
      if (runInput !== (selectedTask.input || '')) {
        const saved = await appSaveTaskInput(selectedTask.id, runInput, selectedTask.input || '');
        setTasks(current => current.map(task => task.id === saved.id ? saved : task));
      }
      const run = await keyed(`start:${selectedTask.id}:${selectedTask.current_revision}`, key => appStartTaskRun(selectedTask.id, key));
      updateRun(run); setTaskId(selectedTask.id); setRunId(run.id); onRunChange?.(`run-${run.id}`);
      setRunConfirmOpen(false); onSectionChange?.('runs');
      const task = await appGetTask(selectedTask.id); setTasks(current => current.map(t => t.id === task.id ? task : t));
    } catch (cause) { setRunError(errorText(cause)); }
    finally { setBusy(false); }
  };
  const control = (run: AppRun, action: 'pause' | 'cancel' | 'continue', body: Record<string, unknown> = {}) => void execute(async () => {
    await keyed(`${run.id}:${action}:${JSON.stringify(body)}`, key => appControlRun(run.id, action, body, key));
    updateRun(await appGetRun(run.id));
    const task = await appGetTask(run.task_id); setTasks(current => current.map(t => t.id === task.id ? task : t));
  });
  const openRun = (id: number) => { onSectionChange?.('runs'); setRunId(id); onRunChange?.(`run-${id}`); void chooseRun(id); };
  const returnTask = (id: number) => { onSectionChange?.('mine'); setTaskId(id); void chooseTask(id); };
  const changeState = (action: 'reopen' | 'archive' | 'unarchive') => selectedTask && !loading && !detailLoading && void execute(async () => {
    const task = await appTaskState(selectedTask.id, action);
    setTasks(current => current.map(t => t.id === task.id ? task : t));
    setListIds(current => current.mine.includes(task.id) ? current : { ...current, mine: [task.id, ...current.mine] });
    setTaskId(task.id);
  });
  const maxWidth = Math.max(400, splitWidth - 280), detailWidth = Math.min(maxWidth, Math.max(400, widths[section] ?? Math.min(720, splitWidth * .64 || 720)));
  const updateWidth = (width: number) => setWidths(current => ({ ...current, [section]: Math.max(400, Math.min(maxWidth, width)) }));

  const gatePanel = gate && gateRun ? <section className="detail-section" aria-label="人工确认">
    <div className="detail-section-head"><strong>选择 {gate.name || gate.id} 的输入</strong><span>{gateRefs.length} 项</span></div>
    <p>只有勾选的结果会进入下游上下文。也可以在流程图中选择人工节点，在运行属性里完成确认。</p>
    {(gate.deps || []).map(id => { const attempt = gateRun.nodes.find(node => node.node_id === id); const name = gateRun.workflow?.nodes.find(node => node.id === id)?.name || id; return <div key={id} className="gate-candidate"><label className="dep"><input aria-label={name} type="checkbox" disabled={attempt?.status !== 'succeeded'} checked={gateRefs.includes(id)} onChange={event => setGateRefs(current => event.target.checked ? [...current, id] : current.filter(ref => ref !== id))} />{name} · {nodeLabels[attempt?.status || 'idle'] || attempt?.status}</label><ResultOutput title={`查看 ${name} 的结果`} output={attempt?.output || null} /></div>; })}
    <div className="gate-actions"><Button type="primary" disabled={busy || !gateRefs.length} onClick={() => void execute(async () => { await keyed(`gate:${gateRun.id}:${gate.id}:${gateRefs.join(',')}`, key => appContinueRun(gateRun.id, gate.id, gateRefs, key)); updateRun(await appGetRun(gateRun.id)); })}>确认并继续</Button><Button danger disabled={busy} onClick={() => control(gateRun, 'cancel')}>终止任务</Button></div>
  </section> : null;

  const taskContent = selectedTask && <div className="task-detail-content">
    <div className="detail-title-block"><div className="task-detail-title-row"><Pill status={selectedTask.status} label={taskLabels[selectedTask.status] || selectedTask.status} /><span className="task-detail-id">Task #{selectedTask.id}</span></div><h2>{selectedTask.title}</h2><p>{selectedTask.description || '暂无说明'}</p><p>来源模板：{selectedTask.source_template_id ? `#${selectedTask.source_template_id} · v${selectedTask.source_template_version}（版本 #${selectedTask.source_template_version_id}）` : '无来源模板'}</p></div>
    <section className="detail-progress-card task-detail-progress" aria-label="任务进度"><div className="detail-progress-head"><span><small>节点完成</small><b>{currentTaskRun ? taskProgress(currentTaskRun).done : 0} / {currentTaskRun ? taskProgress(currentTaskRun).total : selectedTask.workflow?.nodes.length || 0}</b></span><span><small>当前状态</small><strong><Pill status={selectedTask.status} label={taskLabels[selectedTask.status] || selectedTask.status} /></strong></span></div><div className="detail-progress-bar"><i style={{ width: `${currentTaskRun && taskProgress(currentTaskRun).total ? Math.round(taskProgress(currentTaskRun).done / taskProgress(currentTaskRun).total * 100) : 0}%` }} /></div><div className="detail-progress-meta"><span>{currentTaskRun ? `Run #${currentTaskRun.id} · Workflow v${currentTaskRun.workflow_revision}` : '尚未启动运行'}</span><span>{currentTaskRun ? '最近运行' : '等待配置'}</span></div></section>
    <section className="detail-section"><div className="detail-section-head"><strong>当前工作流 · v{selectedTask.current_revision}</strong><Button aria-label="查看流程图" disabled={!selectedTask.workflow?.nodes.length} onClick={openTaskFlow}>查看流程图</Button><Button aria-label="编辑流程" disabled={busy || activeRun(currentTaskRun) || ['completed', 'archived'].includes(selectedTask.status)} onClick={editTask}>编辑流程</Button></div>
      <p>{selectedTask.workflow?.nodes.length || 0} 个节点 · {currentTaskRun ? `${taskProgress(currentTaskRun).done} / ${taskProgress(currentTaskRun).total} 最近运行节点完成` : '尚未运行'}</p>
      <FlowThumb nodes={selectedTask.workflow?.nodes || []} run={currentTaskRun} />
      {activeRun(currentTaskRun) && <p>活动运行中，执行配置已锁定。</p>}
    </section>
    {gatePanel}
    <section className="detail-section"><strong>任务输入</strong><p className="task-input-copy">{selectedTask.input || '暂无输入'}</p></section>
    <section className="detail-section" aria-label="任务结果"><div className="detail-section-head"><strong>任务结果</strong><span>已采用 {Object.keys(selectedTask.current_result || {}).length} 项 · 最近运行 {latestRunOutputs(currentTaskRun).length} 项输出</span></div>{resultError && <p role="alert">{resultError}</p>}{!resultError && !Object.keys(selectedTask.current_result || {}).length && !currentTaskOutputs.length && <p>尚未产生结果。运行任务后会在这里显示各节点输出。</p>}{taskResults.map(result => <ResultOutput key={result.nodeId} title={selectedTask.workflow?.nodes.find(node => node.id === result.nodeId)?.name || result.nodeId} output={result.output} stale={selectedTask.stale_nodes?.includes(result.nodeId)} />)}{currentTaskOutputs.length > 0 && <div className="task-run-results" role="region" aria-label="最近运行节点输出"><div className="task-run-results-head"><span><strong>最近运行节点输出</strong><small>Run #{currentTaskRun?.id} · Workflow v{currentTaskRun?.workflow_revision}</small></span><small>只读快照</small></div>{currentTaskOutputs.map(result => <ResultOutput key={result.nodeId} title={`${selectedTask.workflow?.nodes.find(node => node.id === result.nodeId)?.name || result.nodeId} · ${nodeLabels[result.status] || result.status}`} output={result.output} />)}</div>}</section>
    <section className="detail-section task-detail-activity"><div className="detail-section-head"><strong>最近活动</strong><span>{currentTaskRun ? '当前运行' : '暂无运行'}</span></div><div className="task-activity-item"><i className={currentTaskRun ? statusTone(currentTaskRun.status) : 'gray'} /><span>{currentTaskRun ? `Run #${currentTaskRun.id} · ${runLabels[currentTaskRun.status] || currentTaskRun.status}` : '任务已创建，等待首次运行'}</span></div><div className="task-activity-item"><i className="blue" /><span>工作流 v{selectedTask.current_revision} 已保存</span></div></section>
    {selectedTask.stale_nodes?.length ? <p role="status">结果已过期：{selectedTask.stale_nodes.join('、')}</p> : null}
    <PagedArtifacts key={`task-${selectedTask.id}`} kind="task" id={selectedTask.id} refreshKey={`${selectedTask.status}:${currentTaskRun?.id}:${currentTaskRun?.nodes.map(n => `${n.id}:${n.status}`).join(',')}`} />
    <div className="detail-rule"><strong>任务流程和模板分别保存</strong><span>运行使用已保存的工作流版本，历史快照不会随编辑改变。</span></div>
    <div className="task-api-actions">
      <Button aria-label="运行" disabled={busy || activeRun(currentTaskRun) || ['completed', 'archived'].includes(selectedTask.status) || !selectedTask.workflow?.nodes.length} type="primary" onClick={() => { setRunInput(selectedTask.input || ''); setRunError(''); setRunConfirmOpen(true); }}>运行</Button>
      <Button disabled={!selectedTask.latest_run_id} onClick={() => openRun(selectedTask.latest_run_id!)}>查看运行记录</Button>
      <Button disabled={busy || !selectedTask.workflow?.nodes.length} onClick={() => { setTargetTemplate(null); setSaveTemplateOpen(true); }}>保存为模板</Button>
      {['completed', 'failed', 'waiting'].includes(selectedTask.status) && !activeRun(currentTaskRun) && <Button disabled={busy || loading || detailLoading} onClick={() => changeState('reopen')}>重新打开任务</Button>}
      {selectedTask.status === 'archived' ? <Button disabled={busy || loading || detailLoading} onClick={() => changeState('unarchive')}>取消归档</Button> : ['draft', 'completed', 'failed'].includes(selectedTask.status) && !activeRun(currentTaskRun) && <Button disabled={busy || loading || detailLoading} onClick={() => changeState('archive')}>归档任务</Button>}
    </div>
  </div>;
  const runContent = selectedRun && <>
    <div className="run-detail-head"><div><h2>{tasks.find(t => t.id === selectedRun.task_id)?.title || `任务 #${selectedRun.task_id}`}</h2><p>Run #{selectedRun.id} · Workflow v{selectedRun.workflow_revision}</p></div><Pill status={selectedRun.status} label={selectedRun.paused ? '已暂停' : runLabels[selectedRun.status] || selectedRun.status} /></div>
    <div className="task-api-actions"><Button onClick={() => returnTask(selectedRun.task_id)}>返回所属任务</Button><Button onClick={() => { setFlowOpen(true); setDetailOpen(false); }}>打开流程图</Button>
      {activeRun(selectedRun) && <><Button disabled={busy} onClick={() => control(selectedRun, 'cancel')}>取消运行</Button>{selectedRun.paused ? <Button disabled={busy} onClick={() => control(selectedRun, 'continue')}>继续运行</Button> : selectedRun.status !== 'waiting_human' && <Button disabled={busy} onClick={() => control(selectedRun, 'pause')}>暂停运行</Button>}</>}
    </div>
    <div className="run-metrics"><span><small>节点进度</small><strong>{taskProgress(selectedRun).done} / {taskProgress(selectedRun).total}</strong></span><span><small>人工决定</small><strong>{selectedRun.decisions?.length || 0} 项</strong></span><span><small>配置快照</small><strong>Workflow v{selectedRun.workflow_revision}</strong></span></div>
    {gatePanel}
    <section className="detail-section" aria-label="节点结果"><div className="detail-section-head"><strong>节点结果</strong><span>Run #{selectedRun.id} · Workflow v{selectedRun.workflow_revision}</span></div>{selectedRun.nodes.filter(node => node.output !== null).map(node => <ResultOutput key={node.id} title={selectedRun.workflow?.nodes.find(item => item.id === node.node_id)?.name || node.node_id} output={node.output} />)}{!selectedRun.nodes.some(node => node.output !== null) && <p>本次运行暂无节点输出。</p>}</section>
    <PagedArtifacts key={`run-${selectedRun.id}`} kind="run" id={selectedRun.id} refreshKey={`${selectedRun.status}:${selectedRun.nodes.map(n => `${n.id}:${n.status}`).join(',')}`} />
    <div className="run-detail-columns"><section className="run-column" aria-label="执行轨迹"><h3>执行轨迹</h3>{selectedRun.workflow?.nodes.map(node => { const attempt = selectedRun.nodes.find(n => n.node_id === node.id); return <div className="run-trace-item" key={node.id}><span><strong>{node.name || node.id}</strong><small>尝试 {attempt?.attempt || 0} · {nodeLabels[attempt?.status || 'idle'] || attempt?.status}</small>{attempt?.error_code && <small>{attempt.error_code}</small>}</span></div>; })}</section>
      <section className="run-column" aria-label="运行事件"><h3>运行事件</h3><p>根据本次运行的已记录节点时间回看。</p><ol className="run-event-list">{snapshotEvents(selectedRun).map((event, i) => <li key={i}><code>{event.nodeId}</code><span>{event.label}</span><time>{event.time || '未提供时间'}</time></li>)}</ol></section></div>
  </>;
  const nextListPage = async () => {
    if (moreLoading) return;
    if (page < Math.max(1, Math.ceil(rows.length / 20))) { setPage(value => value + 1); return; }
    const offset = cursors.current[section];
    if (offset === null) return;
    const serial = generation.current;
    setMoreLoading(true); setError(''); setRetryPage(false);
    try {
      const options = { offset, limit: 20, workspaceId, q: query, status: filter };
      let pagination;
      if (section === 'mine') {
        const result = await appListTasksPage(options); pagination = result.pagination;
        const snapshots = await Promise.all(result.tasks.filter(task => task.latest_run_id).map(task => appGetRun(task.latest_run_id!)));
        if (serial !== generation.current) return;
        setListIds(current => ({ ...current, mine: [...new Set([...current.mine, ...result.tasks.map(t => t.id)])] }));
        setTasks(current => mergePage(current, result.tasks)); setRuns(current => mergePage(current, snapshots));
      } else if (section === 'templates') {
        const result = await appListTemplates(options); pagination = result.pagination;
        if (serial !== generation.current) return;
        setListIds(current => ({ ...current, templates: [...new Set([...current.templates, ...result.templates.map(t => t.id)])] }));
        setTemplates(current => mergePage(current, result.templates));
      } else {
        const result = await appListRuns(options); pagination = result.pagination;
        if (serial !== generation.current) return;
        setListIds(current => ({ ...current, runs: [...new Set([...current.runs, ...result.runs.map(r => r.id)])] }));
        setRuns(current => mergePage(current, result.runs));
      }
      cursors.current[section] = nextOffset(pagination); setHasMore(cursors.current[section] !== null);
      setPage(value => value + 1);
    } catch (cause) { if (serial === generation.current) { setError(errorText(cause)); setRetryPage(true); } }
    finally { if (serial === generation.current) setMoreLoading(false); }
  };
  const templateContent = selectedTemplate && (() => {
    const latest = latestTemplateVersion(selectedTemplate);
    const nodes = latest?.workflow.nodes || [];
    return <>
      <div className="run-detail-head template-detail-title"><div><Pill status="blue" label="可复用模板" /><h2>{selectedTemplate.title}</h2><p>当前版本 v{latest?.version || 0} · {nodes.length} 个节点</p></div></div>
      <p className="template-description">保存稳定的工作流结构，供新任务复用。模板不包含运行记录、结果或凭据。</p>
      <section className="template-flow-card" aria-label="模板工作流"><FlowThumb nodes={nodes} /></section>
      <div className="task-api-actions template-detail-actions"><Button disabled={busy} onClick={editTemplate}>编辑模板</Button><Button type="primary" disabled={busy || !selectedTemplate.versions.length} onClick={useTemplate}>使用此模板</Button></div>
      <section className="detail-section"><div className="detail-section-head"><strong>版本历史</strong><span>{selectedTemplate.versions.length} 个版本</span></div><div className="template-version-list">{[...selectedTemplate.versions].reverse().map(version => <div key={version.id}><code>v{version.version}</code><span>版本 #{version.id}</span><small>{version.workflow.nodes.length} 个节点</small></div>)}</div>{selectedTemplate.versions_pagination?.has_more && <Button loading={templateVersionsLoading} disabled={busy} onClick={loadMoreTemplateVersions}>加载更多版本</Button>}</section>
      <div className="detail-rule"><strong>模板只保存可复用工作流定义</strong><span>新版本不会改变已经创建的任务。</span></div>
    </>;
  })();

  if (editor) return <section className="task-module task-module-template-editor" aria-label={editor.task ? '任务流程设计工作区' : '模板设计工作区'}>
    <Templates key={`${editor.task ? 'task' : 'template'}-${editor.draft.id}`} template={editor.draft} mode={editor.task ? 'task' : 'template'} persist={false} agents={agents}
      onBack={() => setEditor(null)} onUse={() => { if (editor.template) void execute(async () => { const template = await readCurrentTemplate(editor.template!); setEditor(null); setTemplates(current => current.map(item => item.id === template.id ? template : item)); openCreate(template); }); }}
      onSave={async draft => {
        if (editor.task) {
          const task = await appSaveTaskWorkflow(editor.task.id, editor.task.current_revision, { nodes: draft.nodes, ...(draft.max_concurrency !== undefined ? { max_concurrency: draft.max_concurrency } : {}) });
          setTasks(current => current.map(t => t.id === task.id ? task : t));
        } else {
          const template = await appSaveTemplate({ title: draft.title, workspace_id: workspaceId, workflow: { nodes: draft.nodes, ...(draft.max_concurrency !== undefined ? { max_concurrency: draft.max_concurrency } : {}) }, expected_revision: editor.draft.version }, editor.template?.id);
          setTemplates(current => [template, ...current.filter(t => t.id !== template.id)]); setListIds(current => ({ ...current, templates: [template.id, ...current.templates.filter(id => id !== template.id)] })); setTemplateId(template.id);
        }
        setEditor(null);
      }} />
  </section>;

  if (taskFlowOpen && selectedTask) return <section className="workbench-region run-flow-region task-flow-region" aria-label="任务流程图"><header className="run-flow-head"><div><strong>{selectedTask.title} · Workflow v{selectedTask.current_revision}</strong><small>{currentTaskRun ? `Run #${currentTaskRun.id} · ${runLabels[currentTaskRun.status] || currentTaskRun.status} · 与任务列表同步` : '尚未运行 · 只读工作流预览'}</small></div><div className="task-api-actions"><Button onClick={() => { setTaskFlowOpen(false); if (mobile) setDetailOpen(true); }}>返回任务详情</Button>{currentTaskRun && <Button onClick={() => openRun(currentTaskRun.id)}>查看运行记录</Button>}</div></header>{currentTaskRun ? <RunSnapshot key={currentTaskRun.id} run={currentTaskRun} onAction={action => applySnapshotAction(currentTaskRun.id, action)} /> : <div className="task-flow-preview" role="region" aria-label="工作流预览"><FlowThumb nodes={selectedTask.workflow?.nodes || []} /><p>尚未运行，当前展示已保存的工作流结构。启动任务后，这里会同步节点状态和结果。</p></div>}</section>;

  if (flowOpen && selectedRun) return <section className="workbench-region run-flow-region" aria-label="运行记录工作台"><header className="run-flow-head"><strong>Run #{selectedRun.id} · Workflow v{selectedRun.workflow_revision}</strong><Button onClick={() => setFlowOpen(false)}>返回运行详情</Button></header><RunSnapshot key={selectedRun.id} run={selectedRun} onAction={action => applySnapshotAction(selectedRun.id, action)} /></section>;

  const names = section === 'mine' ? ['我的任务工作台', '任务列表区域', '任务列表', '任务详情'] : section === 'runs' ? ['运行记录工作台', '运行记录列表区域', '运行记录列表', '运行详情'] : ['模板管理工作台', '模板列表区域', '模板列表', '模板详情'];
  const options = section === 'mine' ? [['all', '全部'], ['running', '运行中'], ['waiting', '待我处理'], ['completed', '已完成'], ['failed', '失败'], ['draft', '草稿'], ['archived', '已归档']] : section === 'runs' ? [['all', '全部'], ['waiting_human', '等待确认'], ['running', '运行中'], ['completed', '已完成'], ['failed', '失败'], ['canceled', '已取消']] : [['all', '全部']];
  const availableRows: Array<AppTask | AppRun | AppTemplate> = section === 'mine' ? tasks : section === 'runs' ? runs : templates;
  const source = listIds[section].flatMap(id => { const row = availableRows.find(item => item.id === id); return row ? [row] : []; });
  const rows = source;
  const pageSize = 20;
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const visibleRows = rows.slice((page - 1) * pageSize, page * pageSize);
  const content = section === 'mine' ? taskContent : section === 'runs' ? runContent : templateContent;
  const selectedId = section === 'mine' ? selectedTask?.id : section === 'runs' ? selectedRun?.id : selectedTemplate?.id;
  const select = (id: number) => { if (section === 'mine') void chooseTask(id); else if (section === 'runs') void chooseRun(id); else { setTemplateId(id); setDetailOpen(true); setCollapsed(false); } };

  return <section className="workbench-region" aria-label={names[0]}>
    <div ref={splitRef} style={{ '--detail-width': `${detailWidth}px` } as CSSProperties} className={`workbench-split ${section === 'mine' ? 'task' : section === 'runs' ? 'run' : 'template'}-detail-split${collapsed ? ' is-collapsed' : ''}${!content ? ' task-api-no-detail' : ''}`}>
      <section className="workbench-list" aria-label={names[1]}>
        <div className="workbench-toolbar"><div className="workbench-segmented" role="group" aria-label={section === 'mine' ? '任务状态筛选' : section === 'runs' ? '运行状态筛选' : '模板范围'}>{options.map(([value, label]) => <button key={value} aria-pressed={filter === value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{label} <span>{source.filter(row => value === 'all' || ('status' in row && row.status === value)).length}</span></button>)}</div>
          <label className="workbench-search"><span className="sr-only">{section === 'mine' ? '搜索任务' : section === 'runs' ? '搜索运行记录' : '搜索模板'}</span><input aria-label={section === 'mine' ? '搜索任务' : section === 'runs' ? '搜索运行记录' : '搜索模板'} placeholder="搜索名称或 ID" value={query} onChange={event => setQuery(event.target.value)} /></label>
          <div className="workbench-view-toggle" role="group" aria-label="展示方式"><button aria-label="列表视图" aria-pressed={view === 'list'} onClick={() => setView('list')}><UnorderedListOutlined /></button><button aria-label="卡片视图" aria-pressed={view === 'cards'} onClick={() => setView('cards')}><AppstoreOutlined /></button></div>
          <Button disabled={loading || busy} onClick={() => void load()}>刷新状态</Button>
          {section === 'mine' && <Button aria-label="新建任务" className="workbench-primary" type="primary" icon={<PlusOutlined />} disabled={busy} onClick={() => openCreate()}>新建任务</Button>}
          {section === 'templates' && <Button className="workbench-primary" icon={<PlusOutlined />} onClick={() => setEditor({ draft: { id: 'new', title: '新建工作流模板', description: '', version: 0, nodes: [] } })}>新建模板</Button>}
        </div>
        {loading && <p role="status" className="workbench-empty">正在加载任务数据…</p>}
        {error && <p role="alert" className="error-banner">{error}<button onClick={() => void (retryPage ? nextListPage() : load())}>重试</button></p>}
        {streamError && <p role="status" className="error-banner">{streamError}<button onClick={() => setStreamRetry(v => v + 1)}>重新连接</button></p>}
        <div className={view === 'list' ? 'workbench-table' : 'workbench-card-view'} role={view === 'list' ? 'table' : 'region'} aria-label={view === 'list' ? names[2] : `${names[2]}卡片视图`}>
          {view === 'list' && <div className="workbench-table-head task-grid" role="row"><span role="columnheader">{section === 'runs' ? '运行' : section === 'templates' ? '模板' : '任务'}</span><span role="columnheader">状态</span><span role="columnheader">节点</span><span role="columnheader">版本</span></div>}
          <div className={view === 'list' ? 'workbench-table-body' : 'workbench-card-grid'} role={view === 'list' ? 'rowgroup' : 'list'}>
            {visibleRows.map(row => {
              const task = section === 'mine' ? row as AppTask : undefined, run = section === 'runs' ? row as AppRun : task ? runs.find(r => r.id === task.latest_run_id) : undefined, template = section === 'templates' ? row as AppTemplate : undefined;
              const nodes = task?.workflow?.nodes || (template ? latestTemplateVersion(template)?.workflow.nodes : undefined) || run?.workflow?.nodes || [];
              const name = task?.title || template?.title || tasks.find(t => t.id === run?.task_id)?.title || (run as (AppRun & { task_title?: string }) | undefined)?.task_title || `任务 #${run?.task_id}`;
              const status = task?.status || run?.status || 'draft', label = task ? taskLabels[status] : run ? (run.paused ? '已暂停' : runLabels[status]) : '工作流定义';
              const version = task?.current_revision || run?.workflow_revision || (template ? latestTemplateVersion(template)?.version : undefined);
              return <div key={row.id} role={view === 'list' ? 'row' : 'listitem'} tabIndex={0} aria-current={selectedId === row.id ? 'true' : undefined} className={view === 'list' ? `workbench-table-row task-grid${selectedId === row.id ? ' selected' : ''}` : `workbench-card status-${statusTone(status)}${selectedId === row.id ? ' is-selected' : ''}`} onClick={() => select(row.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(row.id); } }}>
                {view === 'cards' ? <>
                  <div className="workbench-card-visual"><FlowThumb nodes={nodes} run={run} /></div>
                  <div className="workbench-card-body">
                    <div className="workbench-card-heading"><span className={`workbench-mark ${statusTone(status)}`}><FileTextOutlined /></span><strong title={name}>{name}</strong><Pill status={status} label={label || status} /></div>
                    <p title={task?.description || (run ? `绑定工作流 v${run.workflow_revision}` : `${nodes.length} 个节点`)}>{task?.description || (run ? `绑定工作流 v${run.workflow_revision}` : `${nodes.length} 个节点`)}</p>
                    <div className="workbench-card-meta"><span>{run ? `${taskProgress(run).done} / ${taskProgress(run).total}` : nodes.length} 节点</span><span>·</span><span>v{version}</span></div>
                  </div>
                </> : <>
                  <span className="table-primary" role="cell"><span className={`workbench-mark ${statusTone(status)}`}><FileTextOutlined /></span><span className="table-copy"><span className="table-title"><strong>{name}</strong><code>{section === 'runs' ? `Run #${row.id}` : `#${row.id}`}</code></span><small>{task?.description || (run ? `绑定工作流 v${run.workflow_revision}` : `${nodes.length} 个节点`)}</small></span></span>
                  <span role="cell"><Pill status={status} label={label || status} /></span><span role="cell">{run ? `${taskProgress(run).done} / ${taskProgress(run).total}` : nodes.length} 节点</span><span role="cell">v{version}</span>
                </>}
              </div>;
            })}
            {!loading && !rows.length && !error && <p className="workbench-empty">{source.length ? '没有符合条件的记录' : section === 'mine' ? '暂无任务' : section === 'runs' ? '暂无运行记录' : '暂无模板'}</p>}
          </div>
          <div className="workbench-table-foot"><span>{section === 'runs' ? '运行记录保留历史快照' : '当前工作区'}</span><span>已显示 {(page - 1) * pageSize + visibleRows.length} / 已加载 {rows.length}{hasMore ? ' · 还有更多' : ''}</span><span className="workbench-pagination"><button aria-label="上一页" disabled={page <= 1} onClick={() => setPage(value => Math.max(1, value - 1))}>‹</button><b>{page} / {pageCount}{hasMore ? '+' : ''}</b><button aria-label="下一页" disabled={loading || moreLoading || (page >= pageCount && !hasMore)} onClick={() => void nextListPage()}>›</button></span></div>
        </div>
      </section>
      {!mobile && content && <aside className={`workbench-detail ${section === 'mine' ? 'task' : section === 'runs' ? 'run' : 'template'}-detail`} aria-label={names[3]}>
        {!collapsed && <ResizeHandle label={`调整${names[3]}宽度`} width={detailWidth} max={maxWidth} onChange={updateWidth} />}
        {collapsed ? <button className="detail-handle" aria-label={`展开${names[3]}`} onClick={() => setCollapsed(false)}>{names[3]}</button> : <><header className="detail-head"><strong>{names[3]}</strong><button className="detail-collapse" aria-label={`收起${names[3]}`} onClick={() => setCollapsed(true)}>›</button></header><div className="detail-scroll">{detailLoading && <p role="status">正在刷新详情…</p>}{content}</div></>}
      </aside>}
    </div>
    {mobile && <Drawer title={names[3]} open={detailOpen} onClose={() => setDetailOpen(false)} closable={false} extra={<Button aria-label={`关闭${names[3]}`} onClick={() => setDetailOpen(false)}>×</Button>} width="min(560px, 94vw)" className="task-details-drawer">{content}</Drawer>}
    <Modal title="新建任务" open={creating} footer={null} onCancel={() => { if (!busy) setCreating(false); }} destroyOnHidden>
      <form className="task-api-form" onSubmit={event => { event.preventDefault(); void execute(async () => { const task = await appCreateTask({ title: title.trim(), description, input, workspace_id: workspaceId, workflow: { nodes: [] }, ...(sourceVersion ? { template_version_id: sourceVersion } : {}) }); setTasks(current => [task, ...current]); setListIds(current => ({ ...current, mine: [task.id, ...current.mine.filter(id => id !== task.id)] })); setTaskId(task.id); setCreating(false); onSectionChange?.('mine'); if (mobile) setDetailOpen(true); }); }}>
        <label>任务名称<input aria-label="任务名称" required maxLength={255} value={title} onChange={event => setTitle(event.target.value)} /></label>
        <label>任务说明<textarea aria-label="任务说明" value={description} maxLength={20000} onChange={event => setDescription(event.target.value)} /></label>
        <label>任务输入<textarea aria-label="任务输入" value={input} maxLength={200000} onChange={event => setInput(event.target.value)} /></label>
        <label>来源模板<select aria-label="来源模板" value={sourceVersion || ''} onChange={event => setSourceVersion(Number(event.target.value) || null)}><option value="">空白任务</option>{templates.flatMap(template => mergePage(template.versions, template.latest_version ? [template.latest_version] : []).map(version => <option key={version.id} value={version.id}>{template.title} · v{version.version}</option>))}</select></label>
        {error && <p role="alert">{error}</p>}<Button htmlType="submit" type="primary" loading={busy} disabled={!title.trim()}>创建任务</Button>
      </form>
    </Modal>
    <Modal title="确认运行任务" open={runConfirmOpen} onCancel={() => { if (!busy) setRunConfirmOpen(false); }} onOk={() => void start()} okText="确认运行" cancelText="取消" confirmLoading={busy}>
      <div className="run-confirm-summary"><strong>{selectedTask?.title}</strong><p>确认或修改任务输入，修改内容会先保存，再启动运行。</p><label>任务输入<textarea aria-label="本次任务输入" value={runInput} maxLength={200000} onChange={event => setRunInput(event.target.value)} /></label><div><span>工作流</span><b>v{selectedTask?.current_revision} · {selectedTask?.workflow?.nodes.length || 0} 个节点</b></div>{runError && <p role="alert">{runError}</p>}<small>运行开始后，本次输入和工作流会固定为历史快照；之后的编辑不会影响本次运行。</small></div>
    </Modal>
    <Modal title="保存为模板" open={saveTemplateOpen} onCancel={() => { if (!busy) setSaveTemplateOpen(false); }} footer={null}>
      <form className="task-api-form" onSubmit={event => { event.preventDefault(); if (selectedTask) void execute(async () => { const template = await appSaveTaskAsTemplate(selectedTask.id, { workflow_revision: selectedTask.current_revision, ...(targetTemplate ? { template_id: targetTemplate } : {}) }); setTemplates(current => [template, ...current.filter(t => t.id !== template.id)]); setSaveTemplateOpen(false); }); }}><p>使用已保存的工作流 v{selectedTask?.current_revision}。</p><label>保存目标<select aria-label="保存模板目标" value={targetTemplate || ''} onChange={event => setTargetTemplate(Number(event.target.value) || null)}><option value="">新建模板（默认）</option>{templates.map(t => <option key={t.id} value={t.id}>{t.title} · 追加新版本</option>)}</select></label>{error && <p role="alert">{error}</p>}<Button htmlType="submit" loading={busy} type="primary">保存模板</Button></form>
    </Modal>
  </section>;
}

function ResizeHandle({ label, width, max, onChange }: { label: string; width: number; max: number; onChange: (width: number) => void }) {
  const drag = useRef<{ x: number; width: number } | null>(null);
  return <div className="detail-resizer" role="separator" aria-label={label} aria-orientation="vertical" aria-valuemin={400} aria-valuemax={max} aria-valuenow={Math.round(width)} tabIndex={0}
    onPointerDown={event => { drag.current = { x: event.clientX, width }; event.currentTarget.setPointerCapture(event.pointerId); event.preventDefault(); }}
    onPointerMove={event => { if (drag.current) onChange(drag.current.width + drag.current.x - event.clientX); }}
    onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
    onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); onChange(event.key === 'Home' ? 400 : event.key === 'End' ? max : width + (event.key === 'ArrowLeft' ? 24 : -24)); } }}><span /></div>;
}

function FlowThumb({ nodes, run }: { nodes: AppTaskNode[]; run?: AppRun }) {
  const layout = layoutRunNodes(nodes.map(node => ({ id: node.id, name: node.name || node.id, deps: node.deps || [] })));
  const width = Math.max(...layout.map(n => n.x), 0) * 126 + 120, height = Math.max(...layout.map(n => n.y), 0) * 46 + 42;
  const statusOf = (id: string) => run?.nodes.find(n => n.node_id === id)?.status;
  return <div className={`task-api-flow-thumb${run ? ' has-run' : ''}`}>{nodes.length ? <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="工作流结构缩略图">
    {layout.flatMap(node => node.deps.map(dep => {
      const parent = layout.find(n => n.id === dep);
      if (!parent) return null;
      const from = statusOf(dep), to = statusOf(node.id), tone = flowEdgeTone(from, to);
      const flowing = tone === 'active';
      return <line key={`${dep}-${node.id}`} className={`flow-thumb-edge ${tone}${flowing ? ' is-flowing' : ''}`} x1={parent.x * 126 + 110} y1={parent.y * 46 + 20} x2={node.x * 126 + 6} y2={node.y * 46 + 20} />;
    }))}
    {layout.map(node => {
      const status = statusOf(node.id), tone = run ? nodeStatusTone(status) : 'gray', live = nodeStatusLive(status);
      return <g key={node.id} className={`flow-thumb-node ${tone} ${status || 'pending'}${live ? ' is-live' : ''}`} data-status={status || 'pending'}>
        <title>{`${node.name}${status ? ` · ${nodeLabels[status] || status}` : ''}`}</title>
        <rect className="flow-thumb-box" x={node.x * 126 + 6} y={node.y * 46 + 5} width="104" height="30" rx="6" />
        <circle className="flow-thumb-dot" cx={node.x * 126 + 16} cy={node.y * 46 + 20} r="2.6" />
        <text className="flow-thumb-label" x={node.x * 126 + 62} y={node.y * 46 + 24} textAnchor="middle">{node.name.length > 8 ? `${node.name.slice(0, 8)}…` : node.name}</text>
      </g>;
    })}
  </svg> : <p>尚未添加节点</p>}</div>;
}

function RunSnapshot({ run, onAction }: { run: AppRun; onAction: (action: () => Promise<unknown>) => Promise<void> }) {
  const mobile = useMobile();
  const [propertiesOpen, setPropertiesOpen] = useState(false), [collapsed, setCollapsed] = useState(false);
  const [tab, setTab] = useState<'node' | 'run' | 'events' | 'debug'>('node');
  const [scale, setScale] = useState(1), [pan, setPan] = useState({ x: 0, y: 0 });
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [selected, setSelected] = useState(run.workflow?.nodes[0]?.id || '');
  const [gateRefs, setGateRefs] = useState<string[]>([]);
  const [step, setStep] = useState<number | null>(null), [playing, setPlaying] = useState(false);
  const [direction, setDirection] = useState<'horizontal' | 'vertical'>('horizontal');
  const [debug, setDebug] = useState<Awaited<ReturnType<typeof appDebugNode>> | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [debugLoading, setDebugLoading] = useState(false);
  const [debugRetry, setDebugRetry] = useState(0), [debugFailed, setDebugFailed] = useState(false);
  const debugGeneration = useRef(0);
  const viewport = useRef<HTMLDivElement>(null), world = useRef<HTMLDivElement>(null);
  const events = snapshotEvents(run), currentStep = Math.min(step ?? events.length, events.length);
  const nodes = run.workflow?.nodes || [];
  const layout = layoutRunNodes(nodes.map(n => ({ id: n.id, name: n.name || n.id, deps: n.deps || [] })));
  const states = step === null ? Object.fromEntries(run.nodes.map(n => [n.node_id, n.status])) : replayStates(layout, events, currentStep);
  const xy = (id: string) => { const node = layout.find(n => n.id === id)!; return positions[id] || { x: direction === 'horizontal' ? node.x * 250 + 20 : node.y * 250 + 20, y: direction === 'horizontal' ? node.y * 130 + 80 : node.x * 130 + 80 }; };
  const centerGraph = () => {
    if (!viewport.current || !world.current || !nodes.length) return;
    const nodeRects = Array.from(world.current.querySelectorAll<HTMLElement>('[data-workflow-node-id]'));
    if (!nodeRects.length) return;
    const left = Math.min(...nodeRects.map(node => node.offsetLeft));
    const top = Math.min(...nodeRects.map(node => node.offsetTop));
    const right = Math.max(...nodeRects.map(node => node.offsetLeft + node.offsetWidth));
    const bottom = Math.max(...nodeRects.map(node => node.offsetTop + node.offsetHeight));
    setPan({ x: (viewport.current.clientWidth - (left + right) * scale) / 2 - world.current.offsetLeft, y: (viewport.current.clientHeight - (top + bottom) * scale) / 2 - world.current.offsetTop });
  };
  const selectedNode = nodes.find(n => n.id === selected), attempt = run.nodes.find(n => n.node_id === selected);
  const selectedGate = waitingGate(run);
  const selectedIsGate = !!selectedGate && selectedGate.id === selected;
  useEffect(() => { setGateRefs([]); }, [run.id, selectedGate?.id]);
  useEffect(() => {
    let alive = true; ++debugGeneration.current; setDebug(null); setError(''); setDebugFailed(false); setDebugLoading(false);
    if (attempt) { setDebugLoading(true); void appDebugNode(attempt.id, { limit: 50 }).then(value => { if (alive) setDebug(value); }).catch(cause => { if (alive) { setError(errorText(cause)); setDebugFailed(true); } }).finally(() => { if (alive) setDebugLoading(false); }); }
    return () => { alive = false; ++debugGeneration.current; };
  }, [attempt?.id, attempt?.status, selected, debugRetry]);
  const loadMoreDebugAttempts = async () => {
    if (!debug?.attempts_pagination?.has_more || debugLoading) return;
    const serial = debugGeneration.current;
    setDebugLoading(true); setError('');
    try {
      const page = await appDebugNode(attempt!.id, { offset: debug.attempts_pagination.offset + debug.attempts_pagination.limit, limit: debug.attempts_pagination.limit });
      if (serial !== debugGeneration.current) return;
      setDebug(current => current ? { ...current, attempts: mergePage(current.attempts, page.attempts), attempts_pagination: page.attempts_pagination } : current);
    } catch (cause) { if (serial === debugGeneration.current) setError(errorText(cause)); }
    finally { if (serial === debugGeneration.current) setDebugLoading(false); }
  };
  useEffect(() => { if (!playing) return; if (currentStep >= events.length) { setPlaying(false); return; } const timer = setTimeout(() => setStep(currentStep + 1), 700); return () => clearTimeout(timer); }, [playing, currentStep, events.length]);
  const action = async (operation: () => Promise<unknown>) => { setBusy(true); setError(''); try { await onAction(operation); } catch (cause) { setError(errorText(cause)); } finally { setBusy(false); } };
  const propertyContent = <><header className="run-properties-header"><h3>{selectedNode?.name || selected}</h3></header><div className="run-properties-tabs" role="tablist" aria-label="运行属性标签">{(['node', 'run', 'events', 'debug'] as const).map((value, index) => <button role="tab" key={value} aria-selected={tab === value} className={tab === value ? 'active' : ''} onClick={() => setTab(value)}>{['节点', '运行', '事件', '调试'][index]}</button>)}</div><div className="run-properties-body">
    <p>Run #{run.id} · Workflow v{run.workflow_revision}</p>
    {tab === 'node' && <><h4>{selectedNode?.name || selected}</h4><p>{nodeLabels[states[selected] || 'idle'] || states[selected]}</p><p>依赖：{selectedNode?.deps?.join('、') || '无'}</p><p>{selectedNode?.node_type === 'human' || selectedNode?.node_type === 'human_gate' || selectedNode?.requires_human ? '人工节点 · 不会调用 Agent' : `Agent：${selectedNode?.agent_id || '未提供'} · ${selectedNode?.model || '未提供'}`}</p><section aria-label="编排运行配置"><strong>编排配置</strong><p>最大并发数：{run.workflow?.max_concurrency ?? 50}</p>{selectedNode?.condition && <p>条件：{selectedNode.condition.source}.{selectedNode.condition.path} · {selectedNode.condition.op} {selectedNode.condition.op !== 'exists' ? JSON.stringify(selectedNode.condition.value) : ''}</p>}{selectedNode?.repeat && <p>有界重复 · 上限 {selectedNode.repeat.max_iterations} · 终止字段 {selectedNode.repeat.until.path}</p>}{selectedNode?.foreach && <p>串行集合展开 · {selectedNode.foreach.source}.{selectedNode.foreach.path} · 上限 {selectedNode.foreach.max_items}</p>}{selectedNode?.allow_missing_inputs && <p>允许缺失输入</p>}{attempt && <p>当前尝试：{attempt.attempt}{typeof attempt.input.foreach_index === 'number' ? ` · 集合项 ${attempt.input.foreach_index + 1}` : ''}</p>}{attempt?.error_code && <p>原因：{({ condition_not_matched: '条件未匹配', repeat_limit_exceeded: '达到重复上限', foreach_limit_exceeded: '集合超过上限', foreach_input_invalid: '集合输入不是数组' } as Record<string, string>)[attempt.error_code] || attempt.error_code}</p>}</section>{attempt?.progress && (attempt.progress.text || attempt.progress.execution?.reasoning || attempt.progress.execution?.steps?.length) ? <section className="run-node-progress" aria-label="节点实时过程"><strong>实时过程</strong>{attempt.progress.text && <p>{attempt.progress.text}</p>}{attempt.progress.execution?.reasoning && <p>{attempt.progress.execution.reasoning}</p>}{attempt.progress.execution?.steps?.map(tool => <span key={tool.id}><b>{tool.name}</b><em>{tool.status}</em></span>)}</section> : null}{selectedIsGate && selectedGate && <section className="run-human-gate" aria-label="人工确认"><div className="run-human-gate-head"><strong>人工确认</strong><span>{gateRefs.length} 项</span></div><p>选择上游结果后确认，勾选内容会进入下游上下文。</p>{(selectedGate.deps || []).map(id => { const candidate = run.nodes.find(node => node.node_id === id); const name = run.workflow?.nodes.find(node => node.id === id)?.name || id; return <div key={id} className="gate-candidate"><label className="dep"><input aria-label={name} type="checkbox" disabled={candidate?.status !== 'succeeded' || busy} checked={gateRefs.includes(id)} onChange={event => setGateRefs(current => event.target.checked ? [...current, id] : current.filter(ref => ref !== id))} />{name} · {nodeLabels[candidate?.status || 'idle'] || candidate?.status}</label><ResultOutput title={`查看 ${name} 的结果`} output={candidate?.output || null} /></div>; })}<div className="gate-actions"><Button type="primary" disabled={busy || !gateRefs.length} onClick={() => void action(() => appContinueRun(run.id, selectedGate.id, gateRefs, crypto.randomUUID()))}>确认并继续</Button><Button danger disabled={busy} onClick={() => void action(() => appControlRun(run.id, 'cancel', {}, crypto.randomUUID()))}>终止任务</Button></div></section>}{step === 0 && <p>尚无节点事件</p>}</>}
    {tab === 'run' && <><p>{runLabels[run.status]} · {taskProgress(run).done} / {taskProgress(run).total} 个节点完成</p><label>重放进度<input type="range" aria-label="重放进度" min={0} max={events.length} value={currentStep} onChange={event => { setStep(Number(event.target.value)); setPlaying(false); }} /></label><p>{currentStep} / {events.length} 个已记录事件</p><div className="task-api-actions"><Button onClick={() => { setStep(0); setPlaying(false); }}>从头重放</Button><Button disabled={!currentStep} onClick={() => { setPlaying(false); setStep(currentStep - 1); }}>上一步</Button><Button disabled={currentStep >= events.length} onClick={() => { setPlaying(false); setStep(currentStep + 1); }}>下一步</Button><Button onClick={() => { setStep(null); setPlaying(false); }}>返回最新</Button></div><p>重放与拖动仅调整查看方式。</p></>}
    {tab === 'events' && <ol>{events.filter(e => e.nodeId === selected).map((event, index) => <li key={index}>{event.label} · {event.time || '未提供时间'}</li>)}</ol>}
    {error && <p role="alert">{error}</p>}
    {tab === 'debug' && debugFailed && <Button loading={debugLoading} onClick={() => setDebugRetry(value => value + 1)}>重试加载调试</Button>}
    {tab === 'debug' && <><h4>节点调试</h4>{debug ? <><p>尝试 {debug.attempt} · {nodeLabels[debug.status] || debug.status}</p><h4>输入</h4><pre>{JSON.stringify(debug.input, null, 2)}</pre><h4>输出</h4><pre>{JSON.stringify(debug.output, null, 2)}</pre><PagedArtifacts key={`node-${debug.id}`} kind="node" id={debug.id} /><h4>错误</h4><p>{debug.error_code || '无'}</p><details><summary>执行环境与尝试历史</summary><pre>{JSON.stringify({ environment: debug.environment, attempts: debug.attempts }, null, 2)}</pre>{debug.attempts_pagination?.has_more && <Button loading={debugLoading} onClick={() => void loadMoreDebugAttempts()}>加载更多尝试</Button>}</details></> : <p>暂无调试记录</p>}</>}
    <div className="task-api-actions">{attempt?.status === 'succeeded' && <Button disabled={busy} onClick={() => void action(() => appAdoptNode(run.task_id, selected, attempt.id))}>采用为当前结果</Button>}
      {attempt && ['failed', 'canceled'].includes(attempt.status) && <Button disabled={busy} onClick={() => void action(() => activeRun(run) ? appRetryNode(run.id, selected) : appStartTaskRun(run.task_id, crypto.randomUUID(), { kind: 'rerun', target_node: selected }))}>{activeRun(run) ? '重试节点' : '新建重跑 Run'}</Button>}
      {activeRun(run) && selectedNode?.allow_skip && attempt && ['idle', 'failed', 'canceled'].includes(attempt.status) && <Button disabled={busy} onClick={() => void action(() => appSkipNode(run.id, selected))}>跳过节点</Button>}
    </div>
  </div></>;
  return <div className="task-run-flow task-run-flow-infinite" role="main" aria-label="运行流程图"><div className={`run-graph-layout${collapsed ? ' properties-collapsed' : ''}`}>
    <section className="task-flow-canvas run-graph-canvas run-graph-canvas-infinite" aria-label="运行状态画布"><div className="run-graph-toolbar"><strong>Workflow v{run.workflow_revision} · 只读快照</strong><div><Button onClick={() => { setPlaying(value => !value); if (currentStep >= events.length) setStep(0); }} aria-label={playing ? '暂停重放' : '重放'}>{playing ? '暂停重放' : '重放'}</Button><Button onClick={() => { setStep(null); setPlaying(false); }}>返回最新</Button><Button aria-label={direction === 'horizontal' ? '切换纵向布局' : '切换横向布局'} onClick={() => { setDirection(d => d === 'horizontal' ? 'vertical' : 'horizontal'); setPositions({}); setPan({ x: 0, y: 0 }); }}>切换布局</Button><Button onClick={centerGraph}>居中流程图</Button><Button aria-label="缩小流程图" onClick={() => setScale(s => Math.max(.25, s - .1))}>−</Button><Button aria-label="放大流程图" onClick={() => setScale(s => Math.min(2, s + .1))}>+</Button><span>{Math.round(scale * 100)}%</span></div></div>
      <WorkflowCanvas scale={scale} pan={pan} onScaleChange={setScale} onPanChange={setPan} viewportRef={viewport} worldRef={world} wheelMode="pan" viewportClassName="run-graph-viewport" viewportStyle={{ backgroundPosition: `${pan.x}px ${pan.y}px`, backgroundSize: `${18 * scale}px ${18 * scale}px` }} worldClassName="run-graph-world" worldStyle={{ width: 2000, minHeight: 1200 }} onNodeMove={(id, delta) => setPositions(p => ({ ...p, [id]: { x: xy(id).x + delta.x, y: xy(id).y + delta.y } }))}>
        <svg className="run-graph-edges" width="4000" height="4000" aria-hidden="true">
          <defs>{(['done', 'active', 'ready', 'failed', 'pending'] as const).map(tone => <marker key={tone} id={`run-graph-arrow-${tone}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path className={`run-graph-arrow ${tone}`} d="M0 0 L8 4 L0 8 z" /></marker>)}</defs>
          {nodes.flatMap(node => (node.deps || []).filter(dep => nodes.some(n => n.id === dep)).map(dep => {
            const tone = flowEdgeTone(states[dep], states[node.id]);
            return <line className={`react-flow__edge run-graph-edge ${tone}`} key={`${dep}-${node.id}`} x1={xy(dep).x + 205} y1={xy(dep).y + 38} x2={xy(node.id).x - 7} y2={xy(node.id).y + 38} />;
          }))}
        </svg>
        {nodes.map(node => {
          const status = states[node.id] || 'idle', live = nodeStatusLive(status);
          return <button key={node.id} data-workflow-node-id={node.id} className={`task-flow-node run-graph-node ${status}${live ? ' is-live' : ''}${selected === node.id ? ' selected' : ''}`} style={{ left: xy(node.id).x, top: xy(node.id).y }} aria-label={`${node.name || node.id} 节点`} onClick={() => { setSelected(node.id); setPropertiesOpen(true); }}><strong>{node.name || node.id}</strong><small>{nodeLabels[status] || status}</small></button>;
        })}
      </WorkflowCanvas>
    </section>
    {!mobile && (collapsed ? <aside className="run-properties run-properties-collapsed" aria-label="运行属性（已收起）"><Button aria-label="展开运行属性" onClick={() => setCollapsed(false)}>‹</Button></aside> : <aside className="run-properties" aria-label="运行属性">{propertyContent}<Button className="run-properties-collapse" aria-label="收起运行属性" onClick={() => setCollapsed(true)}>›</Button></aside>)}
    {mobile && <Drawer title="运行属性" open={propertiesOpen} onClose={() => setPropertiesOpen(false)} width="min(340px, 92vw)" className="run-properties-drawer">{propertyContent}</Drawer>}
  </div></div>;
}

function ResultOutput({ title, output, stale }: { title: string; output: Record<string, unknown> | null; stale?: boolean }) {
  const text = typeof output?.text === 'string' ? output.text : output ? JSON.stringify(output, null, 2) : '';
  return <details className="task-result" open><summary>{title}{stale && ' · 结果已过期'}</summary><pre>{text || '暂无文本输出'}</pre></details>;
}

function ArtifactList({ artifacts, hasMore = false, loading = false, onLoadMore }: { artifacts: Array<{ id: number; filename: string; media_type: string; bytes: number }>; hasMore?: boolean; loading?: boolean; onLoadMore?: () => void }) {
  const [error, setError] = useState('');
  if (!artifacts.length) return null;
  const download = async (artifact: { id: number; filename: string }) => {
    try {
      const blob = await appArtifactBlob(artifact.id), url = URL.createObjectURL(blob), anchor = document.createElement('a');
      anchor.href = url; anchor.download = artifact.filename; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { setError(errorText(cause)); }
  };
  return <section className="detail-section task-artifacts" aria-label="任务产物"><div className="detail-section-head"><strong>产物</strong><span>{artifacts.length} 个</span></div>{artifacts.map(artifact => <div className="task-artifact-row" key={artifact.id}><span><strong>{artifact.filename}</strong><small>{artifact.media_type} · {artifact.bytes} bytes</small></span><Button onClick={() => void download(artifact)}>下载</Button></div>)}{hasMore && <Button loading={loading} onClick={onLoadMore}>加载更多产物</Button>}{error && <p role="alert">{error}</p>}</section>;
}

function PagedArtifacts({ kind, id, refreshKey = '' }: { kind: 'task' | 'run' | 'node'; id: number; refreshKey?: string }) {
  const [artifacts, setArtifacts] = useState<AppArtifact[]>([]);
  const [pagination, setPagination] = useState<PageState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const nextOffsetRef = useRef<number | null>(null);
  const retryOffsetRef = useRef(0);

  const list = useCallback((offset: number, append: boolean, serial: number) => {
    retryOffsetRef.current = offset;
    setLoading(true);
    setError('');
    const options = { offset, limit: 50 };
    const request = kind === 'task' ? appListTaskArtifacts(id, options) : kind === 'run' ? appListRunArtifacts(id, options) : appListNodeArtifacts(id, options);
    void request.then(result => {
      if (serial !== generation.current) return;
      setArtifacts(current => append ? mergePage(current, result.artifacts) : result.artifacts);
      setPagination(result.pagination);
      nextOffsetRef.current = nextOffset(result.pagination);
    }).catch(cause => {
      if (serial === generation.current) setError(errorText(cause));
    }).finally(() => {
      if (serial === generation.current) setLoading(false);
    });
  }, [id, kind]);

  useEffect(() => {
    const serial = ++generation.current;
    nextOffsetRef.current = null;
    retryOffsetRef.current = 0;
    setArtifacts([]);
    setPagination(null);
    list(0, false, serial);
    return () => { ++generation.current; };
  }, [list, refreshKey]);

  const retry = () => list(retryOffsetRef.current, retryOffsetRef.current > 0, generation.current);
  const loadMore = () => {
    const offset = nextOffsetRef.current;
    if (offset === null || loading) return;
    list(offset, true, generation.current);
  };
  const hasContent = artifacts.length > 0;
  return <>
    {hasContent && <ArtifactList artifacts={artifacts} hasMore={!!pagination?.has_more} loading={loading} onLoadMore={loadMore} />}
    {loading && !hasContent && <p role="status">正在加载产物…</p>}
    {error && <div className="detail-section task-artifacts-error"><p role="alert">{error}</p><Button loading={loading} onClick={retry}>重试加载产物</Button></div>}
  </>;
}
