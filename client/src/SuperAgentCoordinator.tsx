import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Modal } from 'antd';
import { PlusOutlined, ReloadOutlined, RobotOutlined, SendOutlined } from '@ant-design/icons';
import { Templates } from './AppModules';
import type { ClientTemplate } from './app-types';
import { AppApiError, appControlRun, appCreateTask, appGetRun, appGetTask, appListTasksPage, appSaveTemplate, appStartTaskRun, appWatchTaskRun, type AppAgent, type AppRun, type AppTask } from './app-api';
import { watchCoordinatorRun } from './coordinator-monitor';
import { coordinatorSummary, dispatchableTasks, latestOutput, mergeCoordinatorRun, runProgress, statusLabel, statusTone, type CoordinatorRow } from './super-agent-coordinator';
import { mergePage, nextOffset } from './pagination';

const errorText = (cause: unknown) => cause instanceof AppApiError ? cause.message : '服务暂时不可用，请重试。';
const terminal = (run?: AppRun) => !!run && ['completed', 'failed', 'canceled'].includes(run.status);
function RowStatus({ run }: { run?: AppRun }) {
  return <span className={`coordinator-status ${statusTone(run?.status)}${run?.status === 'running' && !run.paused ? ' is-live' : ''}`}><i aria-hidden="true" />{run?.paused ? '已暂停' : statusLabel(run?.status)}</span>;
}

export function SuperAgentCoordinator({ workspaceId, agents, onOpenTasks, visible = true }: {
  workspaceId: number | null; agents: AppAgent[]; onOpenTasks: (mode?: 'mine' | 'templates') => void; visible?: boolean;
}) {
  const [tasks, setTasks] = useState<AppTask[]>([]), [rows, setRows] = useState<CoordinatorRow[]>([]), [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(true), [moreLoading, setMoreLoading] = useState(false), [dispatching, setDispatching] = useState(false);
  const [offset, setOffset] = useState<number | null>(null), [query, setQuery] = useState('');
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [creating, setCreating] = useState(false), [title, setTitle] = useState(''), [input, setInput] = useState('');
  const [editor, setEditor] = useState<{ kind: 'task' | 'template'; draft: ClientTemplate; input: string } | null>(null);
  const [cancelRun, setCancelRun] = useState<AppRun | null>(null), [controlBusy, setControlBusy] = useState<number | null>(null), [subscriptionRevision, observeRevision] = useState(0);
  const serial = useRef(0), mounted = useRef(true), dispatchLock = useRef(false), controlLock = useRef(false);
  const commandKeys = useRef(new Map<string, string>()), observers = useRef(new Map<number, () => void>());
  const latestRows = useRef(rows); latestRows.current = rows;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; serial.current++; observers.current.forEach(stop => stop()); observers.current.clear(); }; }, []);

  const load = useCallback(async (appendOffset?: number) => {
    const request = ++serial.current;
    if (appendOffset === undefined) setLoading(true); else setMoreLoading(true);
    setError('');
    try {
      const page = await appListTasksPage({ workspaceId, offset: appendOffset ?? 0, limit: 20, q: query });
      if (!mounted.current || request !== serial.current) return;
      const scoped = page.tasks.filter(t => (t.workspace_id ?? null) === workspaceId);
      setTasks(current => appendOffset === undefined ? scoped : mergePage(current, scoped)); setOffset(nextOffset(page.pagination));
      const all = appendOffset === undefined ? mergePage(latestRows.current.map(r => r.task), scoped) : scoped;
      const snapshots = await Promise.all(all.filter(t => t.latest_run_id).map(async task => {
        try { return { taskId: task.id, taskTitle: task.title, task, run: await appGetRun(task.latest_run_id!) } as CoordinatorRow; }
        catch (cause) { return { taskId: task.id, taskTitle: task.title, task, error: errorText(cause) } as CoordinatorRow; }
      }));
      if (!mounted.current || request !== serial.current) return;
      setRows(current => {
        let next = current;
        for (const row of snapshots) {
          const old = next.find(item => item.taskId === row.taskId);
          if (old?.run && row.run && (old.run.id > row.run.id || (old.run.id === row.run.id && terminal(old.run) && !terminal(row.run)))) continue;
          next = [row.error && old?.run ? { ...old, error: row.error } : row, ...next.filter(item => item.taskId !== row.taskId)];
        }
        return next;
      });
    } catch (cause) { if (mounted.current && request === serial.current) setError(errorText(cause)); }
    finally { if (mounted.current && request === serial.current) { setLoading(false); setMoreLoading(false); } }
  }, [workspaceId, query]);
  useEffect(() => { void load(); }, [load]);

  const runIds = rows.flatMap(row => row.run ? [row.run.id] : []).sort((a, b) => a - b).join(',');
  useEffect(() => {
    const ids = new Set(runIds.split(',').filter(Boolean).map(Number));
    for (const [id, stop] of observers.current) if (!ids.has(id)) { stop(); observers.current.delete(id); }
    for (const row of latestRows.current) {
      if (!row.run || observers.current.has(row.run.id)) continue;
      const id = row.run.id;
      observers.current.set(id, watchCoordinatorRun(row.run, {
        read: appGetRun, watch: appWatchTaskRun,
        onChange: run => {
          if (!mounted.current) return;
          setRows(current => mergeCoordinatorRun(current, run));
          if (terminal(run)) void appGetTask(run.task_id).then(task => {
            if (!mounted.current) return;
            setTasks(current => current.map(t => t.id === task.id ? task : t));
            setRows(current => current.map(item => item.run?.id === id ? { ...item, task } : item));
          }).catch(() => {});
        },
        onConnection: state => { if (mounted.current) setRows(current => current.map(item => item.run?.id === id ? { ...item, reconnecting: state === 'recovering', ...(state === 'unavailable' ? { error: '无法继续读取此运行，请刷新或重新登录。' } : {}) } : item)); },
        schedule: (callback, delay) => setTimeout(() => void callback(), delay), cancel: timer => clearTimeout(timer as ReturnType<typeof setTimeout>),
      }));
    }
  }, [runIds, subscriptionRevision]);

  const candidates = useMemo(() => dispatchableTasks(tasks).filter(task => !rows.some(row => row.taskId === task.id && row.run && !terminal(row.run))), [tasks, rows]);
  const selected = candidates.filter(task => selectedIds.includes(task.id)), summary = coordinatorSummary(rows);
  const toggle = (id: number) => setSelectedIds(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]);
  const keyed = async <T,>(identity: string, action: (key: string) => Promise<T>): Promise<T> => {
    const key = commandKeys.current.get(identity) || crypto.randomUUID(); commandKeys.current.set(identity, key);
    try { const value = await action(key); commandKeys.current.delete(identity); return value; }
    catch (cause) { if (cause instanceof AppApiError && cause.status > 0 && cause.status < 500) commandKeys.current.delete(identity); throw cause; }
  };
  const dispatch = async () => {
    if (!selected.length || dispatchLock.current) return;
    dispatchLock.current = true; setDispatching(true); setError(''); setNotice('');
    // Publish independently so one slow dispatch cannot delay the others' monitoring.
    await Promise.all(selected.map(async task => {
      let row: CoordinatorRow;
      try { row = { taskId: task.id, taskTitle: task.title, task, run: await keyed(`start:${task.id}:${task.current_revision}`, key => appStartTaskRun(task.id, key)) }; }
      catch (cause) { row = { taskId: task.id, taskTitle: task.title, task, error: errorText(cause) }; }
      if (!mounted.current) return;
      setRows(current => [row, ...current.filter(item => item.taskId !== task.id)]);
      if (row.run) { setTasks(current => current.map(t => t.id === task.id ? { ...t, latest_run_id: row.run!.id, status: 'running' } : t)); setSelectedIds(current => current.filter(id => id !== task.id)); }
    }));
    dispatchLock.current = false;
    if (mounted.current) { setDispatching(false); setNotice('分发结束，请查看每项运行与错误。'); }
  };
  const control = async (run: AppRun, action: 'pause' | 'continue' | 'cancel') => {
    if (controlLock.current) return;
    controlLock.current = true; setControlBusy(run.id); setError('');
    try {
      await keyed(`control:${run.id}:${action}`, key => appControlRun(run.id, action, {}, key));
      const snapshot = await appGetRun(run.id);
      if (!mounted.current) return;
      observers.current.get(run.id)?.(); observers.current.delete(run.id);
      setRows(current => mergeCoordinatorRun(current, snapshot)); observeRevision(value => value + 1); setCancelRun(null);
    } catch (cause) { if (mounted.current) setError(errorText(cause)); }
    finally { controlLock.current = false; if (mounted.current) setControlBusy(null); }
  };
  const savePlan = async (draft: ClientTemplate) => {
    if (!editor) return;
    if (editor.kind === 'task') {
      const task = await appCreateTask({ title: draft.title, description: draft.description, input: editor.input, workspace_id: workspaceId, workflow: { nodes: draft.nodes, ...(draft.max_concurrency !== undefined ? { max_concurrency: draft.max_concurrency } : {}) } });
      if (!mounted.current) return;
      setTasks(current => mergePage(current, [task])); setNotice('任务方案已保存，可以选择并分发。');
    } else {
      await appSaveTemplate({ title: draft.title, workspace_id: workspaceId, workflow: { nodes: draft.nodes, ...(draft.max_concurrency !== undefined ? { max_concurrency: draft.max_concurrency } : {}) } });
      if (!mounted.current) return;
      setNotice('模板已保存，可在模板管理中使用该版本创建任务。');
    }
    setEditor(null);
  };
  return <section hidden={!visible} className={`coordinator-page${editor ? ' coordinator-editing' : ''}`} aria-label="协调 Agent 工作台">
    {editor ? <Templates key={editor.draft.id} template={editor.draft} agents={agents} persist={false} mode={editor.kind === 'task' ? 'task' : 'template'} taskSaveLabel="保存任务方案" onBack={() => setEditor(null)} onUse={() => { setEditor(null); onOpenTasks('templates'); }} onSave={savePlan} /> : <>
      <header className="coordinator-head"><div><div className="coordinator-eyebrow"><span className="coordinator-mark"><RobotOutlined /></span><span>Super Agent</span></div><h1>协调 Agent</h1><p>分发任务、跟进各 Agent 进展，将结果汇报到一处。</p></div><div className="coordinator-actions"><Button aria-label="刷新状态" icon={<ReloadOutlined />} onClick={() => void load()} disabled={loading || dispatching}>刷新状态</Button><Button aria-label="创建任务" icon={<PlusOutlined />} onClick={() => { setTitle(''); setInput(''); setCreating(true); }}>创建任务</Button><Button onClick={() => setEditor({ kind: 'template', input: '', draft: { id: 'new-template', title: '新任务模板', description: '', version: 0, nodes: [] } })}>创建任务模板</Button></div></header>
      <div className="coordinator-boundary"><strong>任务交给专业 Agent，进展交给协调 Agent</strong><span>保存方案后分发执行；遇到需要你决定的步骤，会明确提醒。</span></div>
      <div className="coordinator-summary" aria-label="协调摘要"><div><strong>{summary.total}</strong><span>已跟进任务</span></div><div><strong>{summary.active}</strong><span>执行中</span></div><div><strong>{summary.waiting}</strong><span>待人工</span></div><div><strong>{summary.completed}</strong><span>已完成</span></div><div><strong>{summary.failed}</strong><span>失败/取消</span></div></div>
      {error && <p className="error-banner" role="alert">{error}<button onClick={() => void load()}>重新读取</button></p>}{notice && <p className="coordinator-stream-note" role="status">{notice}</p>}
      <div className="coordinator-layout">
        <section className="coordinator-dispatch" aria-label="分发任务"><div className="coordinator-section-head"><div><small>任务分发</small><h2>选择要分发的任务</h2></div><span>{selected.length} 个已选择</span></div><p className="coordinator-help">仅分发已保存且可以运行的任务；已完成任务请先在任务工作台重新打开。</p>
          <label className="coordinator-search">搜索任务<input aria-label="搜索分发任务" value={query} onChange={event => setQuery(event.target.value)} placeholder="名称或 ID" /></label>
          {loading && <p role="status">正在读取当前工作区任务…</p>}
          <div className="coordinator-candidate-list">{candidates.map(task => <label className={`coordinator-candidate${selectedIds.includes(task.id) ? ' selected' : ''}`} key={task.id}><input type="checkbox" aria-label={`选择任务 ${task.title}`} disabled={dispatching} checked={selectedIds.includes(task.id)} onChange={() => toggle(task.id)} /><span className="coordinator-candidate-copy"><strong>{task.title}</strong><small>{task.workflow?.nodes.length || 0} 个节点 · 流程 v{task.current_revision}{task.source_template ? ` · 来源模板 v${task.source_template.version}` : ' · 无来源模板'}</small></span></label>)}</div>
          {!loading && !candidates.length && <div className="coordinator-empty"><strong>暂无可分发任务</strong><span>创建并保存任务方案，或去工作台处理现有任务。</span><Button onClick={() => onOpenTasks('mine')}>打开任务工作台</Button></div>}
          {offset !== null && <Button loading={moreLoading} disabled={loading} onClick={() => void load(offset)}>加载更多任务</Button>}
          <Button aria-label="分发已选择任务" className="coordinator-dispatch-button" type="primary" icon={<SendOutlined />} disabled={!selected.length || dispatching} loading={dispatching} onClick={() => void dispatch()}>分发已选择任务</Button>
          <p className="coordinator-help">已加载 {tasks.length} 个任务。监控当前已加载任务的最近运行；切换工作台后继续跟进。</p><Button type="link" onClick={() => onOpenTasks('templates')}>使用已保存模板创建任务</Button>
        </section>
        <section className="coordinator-monitor" aria-label="实时监控"><div className="coordinator-section-head"><div><small>实时监控</small><h2>运行汇报</h2></div><span>{summary.percent}% 已结束</span></div>
          <div className="coordinator-live-summary" role="status" aria-live="polite">{summary.active} 项执行中，{summary.waiting} 项待人工，{summary.completed} 项已完成。</div>
          {rows.length ? <div className="coordinator-run-list">{rows.map(row => {
            const run = row.run, progress = runProgress(run), output = latestOutput(run), definition = run?.workflow || run?.execution_snapshot?.workflow;
            return <article className={`coordinator-run-card ${statusTone(run?.status)}`} key={row.taskId} aria-label={`${row.taskTitle}运行汇报`}>
              <header><div><strong>{row.taskTitle}</strong><small>{run ? `Run #${run.id} · 流程 v${run.workflow_revision}` : '尚未确认分发成功'}</small></div><RowStatus run={run} /></header>
              {row.error && <p className="coordinator-run-error" role="alert">{row.error}</p>}
              {run && <><div className="coordinator-progress-row"><span>{progress.done} / {progress.total} 个节点完成</span><b>{progress.percent}%</b></div><div className="coordinator-progress"><span style={{ width: `${progress.percent}%` }} /></div>
                {row.reconnecting && <p className="coordinator-recovering" role="status">实时连接恢复中，保留最近快照</p>}
                <div className="coordinator-node-strip">{run.nodes.slice(-5).map(node => <span className={statusTone(node.status)} key={`${node.node_id}-${node.id}`}>{definition?.nodes.find(n => n.id === node.node_id)?.name || node.node_id} · {statusLabel(node.status)}</span>)}</div>
                {run.status === 'waiting_human' && <p className="coordinator-help">需要你的决定，请打开运行详情处理。</p>}
                {output && <p className="coordinator-output"><strong>{run.status === 'completed' ? '结果汇报' : '已返回结果'}</strong>{output}</p>}
                <div className="coordinator-run-controls">{!terminal(run) && <>{run.paused ? <Button aria-label="继续" size="small" disabled={controlBusy !== null} onClick={() => void control(run, 'continue')}>继续</Button> : run.status !== 'waiting_human' && <Button aria-label="暂停" size="small" disabled={controlBusy !== null} onClick={() => void control(run, 'pause')}>暂停</Button>}<Button aria-label="取消运行" size="small" danger disabled={controlBusy !== null} onClick={() => setCancelRun(run)}>取消运行</Button></>}</div>
                <footer><a href={`/tasks/${row.taskId}`}>查看任务</a><a href={`/runs/${run.id}`}>查看运行{run.status === 'waiting_human' ? '并处理' : ''}</a></footer>
              </>}
            </article>;
          })}</div> : <div className="coordinator-empty monitor-empty"><RobotOutlined /><strong>还没有监控中的运行</strong><span>选择已保存任务并分发，多任务进展会在这里同步。</span></div>}
        </section>
      </div>
    </>}
    <Modal title="创建任务方案" open={creating} footer={null} onCancel={() => setCreating(false)}><form className="task-api-form" onSubmit={event => { event.preventDefault(); setCreating(false); setEditor({ kind: 'task', input, draft: { id: 'new-task', title: title.trim(), description: '', version: 0, nodes: [] } }); }}><label>任务名称<input aria-label="任务名称" required maxLength={255} value={title} onChange={event => setTitle(event.target.value)} /></label><label>任务输入<textarea aria-label="任务输入" maxLength={200000} value={input} onChange={event => setInput(event.target.value)} /></label><Button htmlType="submit" type="primary" disabled={!title.trim()}>设计工作流</Button></form></Modal>
    <Modal title="取消运行" open={!!cancelRun} onCancel={() => !controlLock.current && setCancelRun(null)} onOk={() => cancelRun && void control(cancelRun, 'cancel')} okText="确认取消" cancelText="继续监控" confirmLoading={controlBusy !== null}><p>取消 Run #{cancelRun?.id}？已完成的节点与历史结果会保留。</p>{error && <p role="alert">{error}</p>}</Modal>
  </section>;
}
