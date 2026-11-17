import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, PointerEvent, WheelEvent } from 'react';
import { Button, Drawer, Select, Tag } from 'antd';
import { CarryOutOutlined, ClockCircleOutlined, FileTextOutlined, PauseOutlined, PlayCircleOutlined, PlusOutlined, RightOutlined, StepBackwardOutlined, StepForwardOutlined, UndoOutlined, ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons';
import { layoutRunNodes, replayStates, type HistoryEvent } from './run-history';

export type TaskSection = 'mine' | 'templates' | 'runs';
type SampleTask = { id: string; title: string; description: string; status: '执行中' | '等待处理' | '已完成' | '草稿'; updated: string; progress: number; nodes: string[] };
const sampleTasks: SampleTask[] = [
  { id: 'incident', title: '安全事件调查', description: '并行收集、人工筛选、双重校验并生成报告。', status: '执行中', updated: '刚刚', progress: 62, nodes: ['5 个收集 Agent', '总结', '2 个校验 Agent', '最终报告'] },
  { id: 'market', title: '竞品市场研究', description: '从公开资料中提炼市场变化和竞争风险。', status: '等待处理', updated: '今天 10:24', progress: 45, nodes: ['资料收集', '观点归纳', '风险审查'] },
  { id: 'product', title: '产品方案评估', description: '产品、技术和风险角色协作输出决策建议。', status: '已完成', updated: '昨天 18:10', progress: 100, nodes: ['产品分析', '技术分析', '风险评审', '最终总结'] },
];
const sampleTemplates = [
  { title: '安全事件调查', description: '5 个调查 Agent 并行执行，人工选择结果后进行总结和双重校验。', count: '9 个节点', version: 'v3' },
  { title: '产品方案评估', description: '产品、技术和风险分析并行执行，最后生成决策报告。', count: '5 个节点', version: 'v2' },
  { title: '资料核查与报告', description: '资料收集、事实核查和报告撰写的标准流程。', count: '6 个节点', version: 'v1' },
];
export type SampleRun = { id: string; title: string; status: string; time: string; detail: string; current: string; nodes: Array<{ name: string; status: 'done' | 'current' | 'idle' }> };
export const sampleRuns: SampleRun[] = [
  { id: 'run-18', title: '安全事件调查案例', status: '执行中', time: '刚刚', detail: '等待人工输入', current: '等待人工输入', nodes: [{ name: '告警分析', status: 'done' }, { name: '威胁狩猎', status: 'done' }, { name: '日志取证', status: 'done' }, { name: '资产核查', status: 'done' }, { name: '情报检索', status: 'done' }, { name: '人工选择', status: 'current' }, { name: '总结报告', status: 'idle' }, { name: '双重校验', status: 'idle' }, { name: '最终报告', status: 'idle' }] },
  { id: 'run-17', title: '产品方案评估', status: '已完成', time: '昨天 18:10', detail: '运行耗时 12 分 48 秒', current: '已生成最终报告', nodes: [{ name: '产品分析', status: 'done' }, { name: '技术分析', status: 'done' }, { name: '风险评审', status: 'done' }, { name: '最终总结', status: 'done' }] },
  { id: 'run-16', title: '竞品市场研究', status: '已暂停', time: '今天 10:24', detail: '等待确认总结节点的输入结果', current: '运行已暂停', nodes: [{ name: '资料收集', status: 'done' }, { name: '观点归纳', status: 'current' }, { name: '风险审查', status: 'idle' }] },
];
const runEvents: Record<string, HistoryEvent[]> = {
  'run-18': ['告警分析', '威胁狩猎', '日志取证', '资产核查', '情报检索'].flatMap(nodeId => [{ nodeId, status: 'running', label: '开始执行' }, { nodeId, status: 'succeeded', label: '执行完成' }]).concat([{ nodeId: '人工选择', status: 'waiting_human', label: '等待人工输入' }]),
  'run-17': ['产品分析', '技术分析', '风险评审', '最终总结'].map(nodeId => ({ nodeId, status: 'succeeded', label: '执行完成' })),
  'run-16': [{ nodeId: '资料收集', status: 'succeeded', label: '执行完成' }, { nodeId: '观点归纳', status: 'running', label: '执行中' }],
};
const statusColor: Record<string, string> = { 执行中: 'blue', 等待处理: 'gold', 已完成: 'green', 草稿: 'default', 已暂停: 'orange' };
type RunPropertyTab = 'node' | 'run' | 'events' | 'debug';
const runPropertyTabs: Array<{ id: RunPropertyTab; label: string }> = [
  { id: 'node', label: '节点' },
  { id: 'run', label: '运行' },
  { id: 'events', label: '事件' },
  { id: 'debug', label: '调试' },
];

export function AppTasks({ section = 'mine', onSectionChange, onCreate, selectedRunId = 'run-18', onRunChange }: { section?: TaskSection; onSectionChange?: (section: TaskSection) => void; onCreate?: () => void; selectedRunId?: string; onRunChange?: (id: string) => void }) {
  const [selectedId, setSelectedId] = useState('incident');
  const selected = sampleTasks.find(task => task.id === selectedId) || sampleTasks[0];
  const selectedRun = sampleRuns.find(run => run.id === selectedRunId) || sampleRuns[0];
  const selectSection = (next: TaskSection) => onSectionChange?.(next);
  return <section className={`task-module${section === 'runs' ? ' task-module-runs' : ''}`} aria-label="任务工作区">
    {section !== 'runs' && <header className="task-module-header"><div><span className="eyebrow">工作流中心</span><h1>任务</h1><p>把多个 Agent 组织成可执行、可追溯的工作流程。</p></div><Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>新建任务</Button></header>}
    {section !== 'runs' && <nav className="task-section-tabs" aria-label="任务菜单"><button className={section === 'mine' ? 'active' : ''} onClick={() => selectSection('mine')}><CarryOutOutlined /><span>我的任务</span><small>3</small></button><button className={section === 'templates' ? 'active' : ''} onClick={() => selectSection('templates')}><FileTextOutlined /><span>模板管理</span><small>3</small></button></nav>}
    {section === 'mine' && <div className="task-section-content"><div className="task-section-toolbar"><div><h2>我的任务</h2><p>管理任务定义、运行状态和最新结果。</p></div><div className="task-filters"><button className="active">全部 <b>3</b></button><button>执行中 <b>1</b></button><button>等待处理 <b>1</b></button><button>已完成 <b>1</b></button></div></div><div className="task-list-layout"><div className="task-list-cards">{sampleTasks.map(task => <button key={task.id} className={`task-list-card${task.id === selected.id ? ' selected' : ''}`} onClick={() => setSelectedId(task.id)}><span className="task-list-card-title"><strong>{task.title}</strong><Tag color={statusColor[task.status]}>{task.status}</Tag></span><span className="task-list-card-description">{task.description}</span><span className="task-list-card-meta"><span>{task.nodes.length} 个阶段</span><span>更新于 {task.updated}</span></span><span className="task-progress"><i style={{ width: `${task.progress}%` }} /></span></button>)}</div><TaskPreview task={selected} /></div></div>}
    {section === 'templates' && <div className="task-section-content"><div className="task-section-toolbar"><div><h2>模板管理</h2><p>创建、编辑和复用工作流模板。</p></div><Button icon={<PlusOutlined />} onClick={() => selectSection('mine')}>新建模板</Button></div><div className="task-template-grid">{sampleTemplates.map(template => <article className="task-template-card" key={template.title}><div className="task-template-icon"><FileTextOutlined /></div><div className="task-template-copy"><span className="task-template-version">{template.version} · {template.count}</span><h3>{template.title}</h3><p>{template.description}</p></div><div className="task-template-actions"><Button type="primary" onClick={() => selectSection('mine')}>使用模板</Button><Button type="text" aria-label={`查看 ${template.title}`}><RightOutlined /></Button></div></article>)}</div></div>}
    {section === 'runs' && <div className="task-section-content task-runs-content"><RunFlowPreview run={selectedRun} onRunChange={onRunChange} /></div>}
  </section>;
}

function RunFlowPreview({ run, onRunChange }: { run: typeof sampleRuns[number]; onRunChange?: (id: string) => void }) {
  const [replayStep, setReplayStep] = useState(runEvents[run.id]?.length || 0);
  const [playing, setPlaying] = useState(false);
  const [selectedNode, setSelectedNode] = useState(run.nodes[0]?.name || '');
  const [scale, setScale] = useState(1);
  const [layoutDirection, setLayoutDirection] = useState<'horizontal' | 'vertical'>('horizontal');
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [propertiesCollapsed, setPropertiesCollapsed] = useState(false);
  const events = runEvents[run.id] || [];
  const states = replayStates(run.nodes.map((node, index) => ({ id: node.name, name: node.name, deps: index ? [run.nodes[index - 1].name] : [] })), events, replayStep);
  const baseLayout = layoutRunNodes(run.nodes.map((node, index) => ({ id: node.name, name: node.name, deps: index ? [run.nodes[index - 1].name] : [] })));
  const layout = baseLayout.map(node => layoutDirection === 'horizontal' ? node : { ...node, x: node.y, y: node.x });
  const eventFor = events.slice(0, replayStep).filter(event => event.nodeId === selectedNode).at(-1);
  const selectedState = states[selectedNode] || 'pending';
  useEffect(() => { setReplayStep(runEvents[run.id]?.length || 0); setPlaying(false); setSelectedNode(run.nodes[0]?.name || ''); setScale(1); setPan({ x: 0, y: 0 }); setLayoutDirection('horizontal'); setPropertiesCollapsed(false); }, [run.id]);
  useEffect(() => {
    if (!playing) return;
    if (replayStep >= events.length) { setPlaying(false); return; }
    const timer = window.setTimeout(() => setReplayStep(step => Math.min(events.length, step + 1)), 700);
    return () => window.clearTimeout(timer);
  }, [playing, replayStep, events.length]);
  const setStep = (step: number) => { setPlaying(false); setReplayStep(Math.max(0, Math.min(events.length, step))); };
  const nodeStatus = (name: string) => states[name] || 'pending';
  const statusText = (value: string) => ({ pending: '待执行', running: '执行中', succeeded: '已完成', failed: '失败', waiting_human: '等待处理' } as Record<string, string>)[value] || value;
  const graphWidth = Math.max(620, Math.max(...layout.map(node => node.x), 0) * 235 + 260);
  const graphHeight = Math.max(360, (Math.max(...layout.map(node => node.y), 0) + 1) * 125 + 80);
  const beginPan = (event: PointerEvent<HTMLDivElement>) => { if ((event.target as HTMLElement).closest('button')) return; event.currentTarget.setPointerCapture(event.pointerId); dragStart.current = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y }; setDragging(true); };
  const movePan = (event: PointerEvent<HTMLDivElement>) => { if (!dragStart.current) return; setPan({ x: dragStart.current.panX + event.clientX - dragStart.current.x, y: dragStart.current.panY + event.clientY - dragStart.current.y }); };
  const endPan = () => { dragStart.current = null; setDragging(false); };
  const toggleReplay = () => { if (replayStep >= events.length) setReplayStep(0); setPlaying(value => !value); };
  const zoomByWheel = (event: WheelEvent<HTMLDivElement>) => { event.preventDefault(); setScale(value => Math.max(.5, Math.min(2, value + (event.deltaY < 0 ? .1 : -.1)))); };
  const edgeFor = (node: typeof layout[number]) => { const parent = layout.find(candidate => candidate.id === node.deps[0]); if (!parent) return null; return layoutDirection === 'horizontal' ? <line className="react-flow__edge" key={`${parent.id}-${node.id}`} x1={parent.x * 235 + 115} y1={parent.y * 125 + 130} x2={node.x * 235 + 10} y2={node.y * 125 + 130} /> : <line className="react-flow__edge" key={`${parent.id}-${node.id}`} x1={parent.x * 235 + 112} y1={parent.y * 125 + 166} x2={node.x * 235 + 112} y2={node.y * 125 + 90} />; };
  return <main className="task-run-flow task-run-flow-infinite" aria-label="运行流程图"><div className={`run-graph-layout${propertiesCollapsed ? ' properties-collapsed' : ''}`}><section className="task-flow-canvas run-graph-canvas run-graph-canvas-infinite" aria-label="运行状态画布"><div className="run-graph-toolbar"><span>无限画布 · 状态流程图</span><div><span className="run-layout-label">{layoutDirection === 'horizontal' ? '横向布局' : '纵向布局'}</span><Button aria-label={playing ? '暂停重放' : '重放'} type={playing ? 'primary' : 'default'} icon={playing ? <PauseOutlined /> : <PlayCircleOutlined />} onClick={toggleReplay}>{playing ? '暂停' : '重放'}</Button><Button aria-label={layoutDirection === 'horizontal' ? '切换纵向布局' : '切换横向布局'} onClick={() => { setLayoutDirection(value => value === 'horizontal' ? 'vertical' : 'horizontal'); setPan({ x: 0, y: 0 }); }}>{layoutDirection === 'horizontal' ? '纵向' : '横向'}</Button><Button aria-label="缩小流程图" icon={<ZoomOutOutlined />} onClick={() => setScale(value => Math.max(.5, value - .1))} /><Button aria-label="放大流程图" icon={<ZoomInOutlined />} onClick={() => setScale(value => Math.min(2, value + .1))} /><Button aria-label="适应流程图" onClick={() => { setScale(1); setPan({ x: 0, y: 0 }); }}>适应</Button><Tag>{Math.round(scale * 100)}%</Tag></div></div><div className={`run-graph-viewport${dragging ? ' is-dragging' : ''}`} onWheel={zoomByWheel} onPointerDown={beginPan} onPointerMove={movePan} onPointerUp={endPan} onPointerCancel={endPan} onPointerLeave={endPan}><div className="run-graph-world" style={{ width: graphWidth, minHeight: graphHeight, transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`, transformOrigin: 'top left' }}><svg className="run-graph-edges" width={graphWidth} height={graphHeight} aria-hidden="true">{layout.filter(node => node.deps.length).map(edgeFor)}</svg>{layout.map((node, index) => <button key={node.id} className={`task-flow-node run-graph-node ${nodeStatus(node.id)}${selectedNode === node.id ? ' selected' : ''}`} style={{ left: node.x * 235 + 10, top: node.y * 125 + 90 }} aria-label={`${node.name} 节点`} onClick={() => { setSelectedNode(node.name); setPropertiesOpen(true); }}><span className="task-flow-node-index">{nodeStatus(node.id) === 'succeeded' ? '✓' : index + 1}</span><strong>{node.name}</strong><small>{statusText(nodeStatus(node.id))}</small></button>)}</div></div></section><RunProperties run={run} node={selectedNode} state={selectedState} event={eventFor} events={events} replayStep={replayStep} playing={playing} onRunChange={onRunChange} onStep={setStep} onTogglePlaying={toggleReplay} onClose={() => setPropertiesOpen(false)} mobileOpen={propertiesOpen} collapsed={propertiesCollapsed} onToggleCollapsed={() => setPropertiesCollapsed(value => !value)} /></div></main>;
}

function RunProperties({ run, node, state, event, events, replayStep, playing, onRunChange, onStep, onTogglePlaying, onClose, mobileOpen, collapsed, onToggleCollapsed }: { run: SampleRun; node: string; state: string; event?: HistoryEvent; events: HistoryEvent[]; replayStep: number; playing: boolean; onRunChange?: (id: string) => void; onStep: (step: number) => void; onTogglePlaying: () => void; onClose: () => void; mobileOpen: boolean; collapsed: boolean; onToggleCollapsed: () => void }) {
  const [mobile, setMobile] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 640px)').matches);
  const [tab, setTab] = useState<RunPropertyTab>('node');
  useEffect(() => { const media = window.matchMedia('(max-width: 640px)'); const sync = () => setMobile(media.matches); sync(); media.addEventListener('change', sync); return () => media.removeEventListener('change', sync); }, []);
  const stateLabel = ({ pending: '待执行', running: '执行中', succeeded: '已完成', failed: '失败', waiting_human: '等待处理' } as Record<string, string>)[state] || state;
  const runStates = replayStates(run.nodes.map((item, index) => ({ id: item.name, name: item.name, deps: index ? [run.nodes[index - 1].name] : [] })), events, replayStep);
  const nodeIndex = run.nodes.findIndex(item => item.name === node);
  const nodeEvents = runEvents[run.id]?.filter(item => item.nodeId === node) || [];
  const playback = <div className="run-property-playback" aria-label="运行重放控制"><label>运行记录<select aria-label="选择运行记录" value={run.id} onChange={event => onRunChange?.(event.target.value)}>{sampleRuns.map(item => <option key={item.id} value={item.id}>{item.title} {item.status}</option>)}</select></label><div className="run-property-playback-actions"><Button aria-label="从头重放" icon={<UndoOutlined />} onClick={() => onStep(0)}>从头</Button><Button aria-label={playing ? '暂停重放' : '重放'} type={playing ? 'default' : 'primary'} icon={playing ? <PauseOutlined /> : <PlayCircleOutlined />} onClick={onTogglePlaying}>{playing ? '暂停' : '重放'}</Button><Button aria-label="上一步" icon={<StepBackwardOutlined />} disabled={!replayStep} onClick={() => onStep(replayStep - 1)}>上一步</Button><Button aria-label="下一步" icon={<StepForwardOutlined />} disabled={replayStep >= events.length} onClick={() => onStep(replayStep + 1)}>下一步</Button></div><input aria-label="重放进度" type="range" min="0" max={events.length} value={replayStep} onChange={event => onStep(Number(event.target.value))} /><div className="run-property-playback-footer"><span>{replayStep}/{events.length} 个事件</span><Button aria-label="返回最新" onClick={() => onStep(events.length)}>返回最新</Button></div></div>;
  const tabContent = tab === 'node' ? <>
    <div className="run-property-title"><strong>{node || '未选择节点'}</strong><Tag color={state === 'failed' ? 'red' : state === 'succeeded' ? 'green' : 'blue'}>{stateLabel}</Tag></div>
    <dl><div><dt>运行</dt><dd>{run.id}</dd></div><div><dt>来源</dt><dd>示例运行</dd></div><div><dt>状态</dt><dd>{state === 'pending' ? '尚无节点事件' : event?.label || '状态快照'}</dd></div><div><dt>依赖</dt><dd>{nodeIndex <= 0 ? '无' : '前置节点完成后执行'}</dd></div></dl>
    {state === 'pending' ? <p className="inspector-empty">该节点尚未进入当前回放位置。</p> : <div className="run-property-output"><strong>输出摘要</strong><p>{state === 'succeeded' ? '输出已生成，可在真实运行记录中打开调试详情。' : event?.label || '暂无输出摘要。'}</p></div>}
  </> : tab === 'run' ? <>
    <div className="run-property-run-title"><span className="eyebrow">示例运行 · {run.id}</span><h4>{run.title}</h4><Tag color={statusColor[run.status]}>{run.status}</Tag></div>
    <dl><div><dt>阶段</dt><dd>{run.current}</dd></div><div><dt>完成</dt><dd>{run.nodes.filter(item => runStates[item.name] === 'succeeded').length}/{run.nodes.length} 节点</dd></div><div><dt>更新</dt><dd>{run.time}</dd></div><div><dt>版本</dt><dd>Workflow v7</dd></div></dl>
    {playback}<p className="inspector-empty">重放只读回看，不会重新执行 Agent。</p>
  </> : tab === 'events' ? <>
    {nodeEvents.length ? <ol className="run-property-events">{nodeEvents.map((item, index) => <li key={`${item.nodeId}-${item.status}-${index}`}><strong>{item.label}</strong><small>{item.status}</small></li>)}</ol> : <p className="inspector-empty">尚无节点事件</p>}
  </> : <p className="inspector-empty">真实调试详情将在 FastAPI 运行历史接入后提供。</p>;
  const content = <><header className="run-properties-header"><div><span className="eyebrow">运行属性</span><h3>{runPropertyTabs.find(item => item.id === tab)?.label}</h3></div><Button aria-label="关闭运行属性" onClick={onClose}>×</Button></header><div className="run-properties-tabs" role="tablist" aria-label="运行属性标签">{runPropertyTabs.map(item => <button key={item.id} role="tab" type="button" aria-selected={tab === item.id} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}>{item.label}</button>)}</div><div className="run-properties-body">{tabContent}</div></>;
  return <>{!mobile && (collapsed ? <aside className="run-properties run-properties-collapsed" aria-label="运行属性（已收起）"><Button aria-label="展开运行属性" onClick={onToggleCollapsed}>‹</Button></aside> : <aside className="run-properties" aria-label="运行属性">{content}<Button className="run-properties-collapse" aria-label="收起运行属性" onClick={onToggleCollapsed}>›</Button></aside>)}{mobile && <Drawer title="运行属性" placement="right" open={mobileOpen} onClose={onClose} width="min(340px, 92vw)" className="run-properties-drawer">{content}</Drawer>}</>;
}

function TaskPreview({ task }: { task: SampleTask }) {
  return <article className="task-preview"><header><div><span className="eyebrow">任务详情</span><h2>{task.title}</h2></div><Tag color={statusColor[task.status]}>{task.status}</Tag></header><p className="task-preview-description">{task.description}</p><div className="task-preview-summary"><span><b>{task.progress}%</b><small>当前进度</small></span><span><b>{task.nodes.length}</b><small>工作阶段</small></span><span><b>Run 18</b><small>最近运行</small></span></div><div className="task-preview-flow"><div className="task-preview-flow-label"><strong>当前工作流</strong><button>打开画布 <RightOutlined /></button></div><div className="task-preview-nodes">{task.nodes.map((node, index) => <span key={node} className={index < Math.ceil(task.nodes.length * task.progress / 100) ? 'done' : ''}><i>{index + 1}</i>{node}</span>)}</div></div><footer><span>最后更新于 {task.updated}</span><Button type="primary">继续处理</Button></footer></article>;
}
