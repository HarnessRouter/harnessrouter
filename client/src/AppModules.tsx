import React, { useEffect, useRef, useState } from 'react';
import { Button, Tag } from 'antd';
import { DeleteOutlined, NodeIndexOutlined, PlusOutlined } from '@ant-design/icons';
import type { ClientTemplate, TemplateNode } from './app-types';
import { NODE_HEIGHT, NODE_WIDTH, clamp, connectionIssue, edgePath, graphBounds, nodeRole } from './template-graph';
import { WorkflowCanvas } from './workflow-canvas';
import { appListAgentModels, appModelSelection, type AppAgent } from './app-api';
import { OrchestrationFields } from './OrchestrationFields';
import { orchestrationIssue, withoutDependency } from './orchestration';

const defaultTemplate: ClientTemplate = {
  id: 'product-evaluation',
  title: 'AI 产品方案评估',
  description: '产品与技术并行分析，交叉评审后输出最终方案。',
  version: 1,
  nodes: [
    { id: 'node-1', name: '理解任务目标', x: 20, y: 210, deps: [] },
    { id: 'node-2', name: '产品价值分析', x: 220, y: 60, deps: ['node-1'] },
    { id: 'node-3', name: '技术可行性分析', x: 220, y: 360, deps: ['node-1'] },
    { id: 'node-4', name: '风险评审', x: 420, y: 210, deps: ['node-2', 'node-3'] },
    { id: 'node-5', name: '最终总结', x: 620, y: 210, deps: ['node-4'] },
  ],
};
export function createTemplate(overrides: Partial<ClientTemplate> = {}): ClientTemplate {
  return {
    ...defaultTemplate,
    ...overrides,
    nodes: overrides.nodes?.map(node => ({ ...node, deps: [...node.deps] })) || defaultTemplate.nodes.map(node => ({ ...node, deps: [...node.deps] })),
  };
}
function fallbackNode(name: string, index: number, count: number): TemplateNode {
  if (index === 0) return { id: 'node-1', name, x: 20, y: 210, deps: [] };
  if (count > 2 && index <= 2) return { id: `node-${index + 1}`, name, x: 220, y: index === 1 ? 60 : 360, deps: ['node-1'] };
  return { id: `node-${index + 1}`, name, x: 220 + (index - 2) * 200, y: 210, deps: [`node-${index}`] };
}
function normalizeTemplate(value: unknown): ClientTemplate {
  const input = value && typeof value === 'object' ? value as Partial<ClientTemplate> & { nodes?: unknown[] } : {};
  const rawNodes = Array.isArray(input.nodes) ? input.nodes : defaultTemplate.nodes;
  const nodes = rawNodes.map((raw, index) => {
    if (typeof raw === 'string') return fallbackNode(raw, index, rawNodes.length);
    const node = raw && typeof raw === 'object' ? raw as Partial<TemplateNode> : {};
    const fallback = fallbackNode('', index, rawNodes.length);
    return {
      ...node,
      id: typeof node.id === 'string' && node.id ? node.id : fallback.id,
      name: typeof node.name === 'string' ? node.name : `节点 ${index + 1}`,
      x: Number.isFinite(node.x) ? Number(node.x) : fallback.x,
      y: Number.isFinite(node.y) ? Number(node.y) : fallback.y,
      deps: Array.isArray(node.deps) ? node.deps.filter((dep): dep is string => typeof dep === 'string') : fallback.deps,
    };
  });
  return {
    id: typeof input.id === 'string' && input.id ? input.id : defaultTemplate.id,
    max_concurrency: input.max_concurrency,
    title: typeof input.title === 'string' && input.title ? input.title : defaultTemplate.title,
    description: typeof input.description === 'string' ? input.description : defaultTemplate.description,
    version: Number.isFinite(input.version) ? Number(input.version) : 1,
    nodes,
  };
}
export function loadTemplate(): ClientTemplate { try { return normalizeTemplate(JSON.parse(localStorage.getItem('hexa.client.template') || '')); } catch { return defaultTemplate; } }
export function Templates({ template, onSave, onUse, onBack, persist = true, mode = 'template', agents = [], taskSaveLabel = '保存任务流程' }: { template: ClientTemplate; onSave: (template: ClientTemplate) => void | Promise<void>; onUse: () => void; onBack?: () => void; persist?: boolean; mode?: 'task' | 'template'; agents?: AppAgent[]; taskSaveLabel?: string }) {
  const [draft, setDraft] = useState(template);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const errorRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  const [modelOptions, setModelOptions] = useState<Array<{ id: string; label: string }>>([]);
  const [modelError, setModelError] = useState('');
  const [modelLoading, setModelLoading] = useState(false);
  const [modelRetry, setModelRetry] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [orchestration, setOrchestration] = useState<'manual' | 'ai'>('manual');
  const [aiPrompt, setAiPrompt] = useState('');
  const [zoom, setZoom] = useState(0.72);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [panning, setPanning] = useState(false);
  const [connectingSource, setConnectingSource] = useState<string | null>(null);
  const [connectingPoint, setConnectingPoint] = useState<{ x: number; y: number } | null>(null);
  const worldRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ id: string; clientX: number; clientY: number; originX: number; originY: number } | null>(null);
  const draftRef = useRef(draft);
  const zoomRef = useRef(zoom);
  const panStateRef = useRef(pan);
  draftRef.current = draft;
  zoomRef.current = zoom;
  panStateRef.current = pan;
  const nodes = draft.nodes;
  const bounds = graphBounds(nodes);
  const edgePadding = 120;
  const edgeLeft = bounds.left - edgePadding;
  const edgeTop = bounds.top - edgePadding;
  const edgeRight = Math.max(bounds.left + bounds.width, connectingPoint?.x ?? 0) + edgePadding;
  const edgeBottom = Math.max(bounds.top + bounds.height, connectingPoint?.y ?? 0) + edgePadding;
  const edgeWidth = Math.max(1, edgeRight - edgeLeft);
  const edgeHeight = Math.max(1, edgeBottom - edgeTop);
  const selected = nodes.find(node => node.id === selectedId) || null;
  useEffect(() => {
    let alive = true;
    setModelOptions([]); setModelError('');
    if (!selected?.agent_id) { setModelLoading(false); return; }
    const id = selected.id;
    setModelLoading(true);
    void appListAgentModels(selected.agent_id).then(catalog => {
      if (!alive) return;
      const selection = appModelSelection(catalog);
      setModelOptions(selection.models);
      if (!selection.models.length) setModelError('该 Agent 暂无可用模型。');
      setDraft(current => ({ ...current, nodes: current.nodes.map(node => node.id === id && !node.model ? { ...node, model: selection.model } : node) }));
    }).catch(cause => { if (alive) setModelError(cause instanceof Error ? cause.message : '模型读取失败。'); })
      .finally(() => { if (alive) setModelLoading(false); });
    return () => { alive = false; };
  }, [selected?.id, selected?.agent_id, modelRetry]);
  const updateConfig = (patch: Partial<TemplateNode>) => {
    if (selected) setDraft(current => ({ ...current, nodes: current.nodes.map(node => node.id === selected.id ? { ...node, ...patch } : node) }));
  };
  const selectedIndex = selected ? nodes.findIndex(node => node.id === selected.id) : -1;
  const edgeCount = nodes.reduce((count, node) => count + node.deps.length, 0);
  const pointAt = (clientX: number, clientY: number) => {
    const rect = worldRef.current?.getBoundingClientRect();
    return rect ? { x: (clientX - rect.left) / zoomRef.current, y: (clientY - rect.top) / zoomRef.current } : { x: 0, y: 0 };
  };
  const connectNodes = (sourceId: string, targetId: string) => {
    const current = draftRef.current;
    const target = current.nodes.find(node => node.id === targetId);
    if (!target) return;
    const issue = connectionIssue(current.nodes, sourceId, targetId);
    if (issue === 'self') { setError('节点不能连接自身。'); return; }
    if (issue === 'duplicate') { setError('这两个节点已经连接。'); return; }
    if (issue === 'cycle') { setError('该连接会创建循环依赖，已阻止。'); return; }
    setError('');
    setDraft({ ...current, nodes: current.nodes.map(node => node.id === targetId ? { ...node, deps: [...node.deps, sourceId] } : node) });
  };
  const removeDependency = (targetId: string, sourceId: string) => {
    setError('');
    setDraft({ ...draftRef.current, nodes: draftRef.current.nodes.map(node => node.id === targetId ? withoutDependency(node, sourceId) : node) });
  };
  const updateNode = (id: string, value: string) => setDraft({ ...draft, nodes: draft.nodes.map(node => node.id === id ? { ...node, name: value } : node) });
  const addNode = () => {
    const nextIndex = Math.max(0, ...nodes.map(node => Number(node.id.replace(/\D/g, ''))).filter(Number.isFinite)) + 1;
    const id = `node-${nextIndex}`;
    const node: TemplateNode = {
      id,
      name: `新节点 ${nextIndex}`,
      x: selected ? selected.x + 220 : Math.round(bounds.left + bounds.width + 120),
      y: selected ? selected.y + 110 : Math.round(bounds.top + 80),
      deps: selected ? [selected.id] : [],
    };
    setError('');
    setDraft({ ...draft, nodes: [...nodes, node] });
    setSelectedId(null);
    window.requestAnimationFrame(fitCanvas);
  };
  const removeNode = (id: string) => {
    setError('');
    setDraft({ ...draft, nodes: draft.nodes.filter(node => node.id !== id).map(node => withoutDependency(node, id)) });
    setSelectedId(null);
  };
  const beginDrag = (event: React.PointerEvent<HTMLDivElement>, node: TemplateNode) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest('.node-port')) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedId(node.id);
    setError('');
    dragRef.current = { id: node.id, clientX: event.clientX, clientY: event.clientY, originX: node.x, originY: node.y };
  };
  const beginConnection = (event: React.PointerEvent<HTMLButtonElement>, node: TemplateNode) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedId(node.id);
    setError('');
    setConnectingSource(node.id);
    setConnectingPoint({ x: node.x + NODE_WIDTH, y: node.y + NODE_HEIGHT / 2 });
  };
  const zoomAt = (nextZoom: number, clientX?: number, clientY?: number) => {
    const viewport = viewportRef.current;
    const world = worldRef.current;
    if (!viewport || !world) return;
    const viewportRect = viewport.getBoundingClientRect();
    const worldRect = world.getBoundingClientRect();
    const anchorX = clientX ?? viewportRect.left + viewportRect.width / 2;
    const anchorY = clientY ?? viewportRect.top + viewportRect.height / 2;
    const currentZoom = zoomRef.current;
    const currentPan = panStateRef.current;
    const worldX = (anchorX - worldRect.left) / currentZoom;
    const worldY = (anchorY - worldRect.top) / currentZoom;
    const value = Number(clamp(nextZoom, 0.25, 2).toFixed(2));
    const naturalLeft = worldRect.left - currentPan.x;
    const naturalTop = worldRect.top - currentPan.y;
    setPan({ x: anchorX - worldX * value - naturalLeft, y: anchorY - worldY * value - naturalTop });
    setZoom(value);
  };
  const fitCanvas = () => {
    const viewport = viewportRef.current;
    const world = worldRef.current;
    if (!viewport || !world) return;
    const graph = graphBounds(draftRef.current.nodes);
    const next = Number(clamp(Math.min((viewport.clientWidth - 80) / graph.width, (viewport.clientHeight - 80) / graph.height), 0.25, 1.15).toFixed(2));
    const viewportRect = viewport.getBoundingClientRect();
    const worldRect = world.getBoundingClientRect();
    const naturalLeft = worldRect.left - panStateRef.current.x;
    const naturalTop = worldRect.top - panStateRef.current.y;
    setZoom(next);
    setPan({
      x: viewportRect.left + viewportRect.width / 2 - (graph.left + graph.width / 2) * next - naturalLeft,
      y: viewportRect.top + viewportRect.height / 2 - (graph.top + graph.height / 2) * next - naturalTop,
    });
  };
  useEffect(() => {
    const frame = window.requestAnimationFrame(fitCanvas);
    return () => window.cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    const move = (event: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const dx = (event.clientX - drag.clientX) / zoomRef.current;
      const dy = (event.clientY - drag.clientY) / zoomRef.current;
      setDraft(current => ({
        ...current,
        nodes: current.nodes.map(node => node.id === drag.id ? {
          ...node,
          x: Math.round(drag.originX + dx),
          y: Math.round(drag.originY + dy),
        } : node),
      }));
    };
    const up = () => { dragRef.current = null; };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
  }, []);
  useEffect(() => {
    if (!connectingSource) return;
    const move = (event: PointerEvent) => setConnectingPoint(pointAt(event.clientX, event.clientY));
    const up = (event: PointerEvent) => {
      const targetElement = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-node-id]') as HTMLElement | null;
      const targetId = targetElement?.dataset.nodeId;
      if (targetId) connectNodes(connectingSource, targetId);
      setConnectingSource(null);
      setConnectingPoint(null);
    };
    const cancel = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setConnectingSource(null);
      setConnectingPoint(null);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up, { once: true });
    window.addEventListener('keydown', cancel);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('keydown', cancel);
    };
  }, [connectingSource]);
  const save = async () => {
    if (saving) return;
    if (!draft.title.trim() || !draft.nodes.length || draft.nodes.some(node => !node.name.trim())) { setError('名称和节点不能为空。'); return; }
    const issue = orchestrationIssue(draft);
    if (issue) { setError(issue); errorRef.current?.focus(); return; }
    setError('');
    setSaving(true);
    const next = { ...draft, version: draft.version + 1, nodes: draft.nodes.map(node => ({ ...node, name: node.name.trim() })) };
    try {
      await onSave(next);
      if (persist) localStorage.setItem('hexa.client.template', JSON.stringify(next));
    } catch (cause) { setError(cause instanceof Error ? cause.message : '保存失败，草稿已保留。'); }
    finally { setSaving(false); }
  };
  const generateFlow = () => {
    if (!aiPrompt.trim()) return;
    const steps = aiPrompt.split(/[，,;；]|->|→/).map(step => step.trim()).filter(Boolean).slice(0, 8);
    if (!steps.length) return;
    setDraft({
      ...draft,
      description: aiPrompt.trim(),
      nodes: steps.map((step, index) => {
        const row = Math.floor(index / 4);
        const lane = row % 2 === 0 ? index % 4 : 3 - index % 4;
        return {
          id: `node-${index + 1}`,
          name: step,
          x: 20 + lane * 200,
          y: row === 0 ? 70 : 260,
          deps: index ? [`node-${index}`] : [],
        };
      }),
    });
    setOrchestration('manual');
    setSelectedId('node-1');
  };
  return <section className="page">
    <header className="editor-header">
      <button className="icon-btn" disabled={saving} aria-label={mode === 'task' ? '返回任务详情' : '返回模板列表'} onClick={() => { if (onBack) onBack(); else setSelectedId(null); }}>←</button>
      <div className="head-title">
        <small>{mode === 'task' ? '任务流程 / 编辑' : '模板 / 编辑'}</small>
        <h1>{draft.title}</h1>
        <span className="pill amber">{`草稿 · 基于 v${template.version}`}</span>
        <span className="muted-count">{draft.nodes.length} 个节点</span>
      </div>
      <div className="header-actions">
        {mode === 'template' && <Button disabled={saving} onClick={onUse}>使用已保存版本</Button>}
        <Button type="primary" loading={saving} onClick={() => void save()}>{mode === 'task' ? taskSaveLabel : '保存模板新版本'}</Button>
      </div>
    </header>
    {error && <p ref={errorRef} tabIndex={-1} className="error-banner" role="alert">{error}</p>}
    <div className="editor-body" inert={saving}>
      <aside className="org-panel" aria-label="对话编排">
        <div className="org-head"><strong>对话编排</strong><p>选择节点编辑属性，或描述目标让系统先生成流程草稿。</p></div>
        <div className="org-tabs" role="tablist" aria-label="编排方式">
          <button className={orchestration === 'manual' ? 'active' : ''} role="tab" aria-selected={orchestration === 'manual'} onClick={() => setOrchestration('manual')}>拖拽编辑</button>
          <button className={orchestration === 'ai' ? 'active' : ''} role="tab" aria-selected={orchestration === 'ai'} onClick={() => setOrchestration('ai')}>AI 生成</button>
        </div>
        {orchestration === 'manual' ? <><div className="org-quick"><button onClick={addNode}><PlusOutlined aria-hidden="true" /> 添加节点</button></div><div className="org-label">节点 {nodes.length}</div><div className="org-list">{nodes.map(node => <button key={node.id} className={node.id === selectedId ? 'active' : ''} onClick={() => setSelectedId(node.id)}><span className="status-dot" /><span className="t">{node.name}</span><span className="a">{nodeRole(nodes, node)}</span></button>)}</div><div className="org-tip"><span className="status-dot" />{edgeCount} 条连接 · 点击画布节点编辑</div></> : <><textarea aria-label="AI 生成要求" placeholder="例如：市场与技术并行分析，风险评审汇总，最后输出方案" value={aiPrompt} onChange={event => setAiPrompt(event.target.value)} /><Button type="primary" onClick={generateFlow}>生成流程图</Button></>}
      </aside>
      <div className="canvas-area">
        <div className="canvas-toolbar">
          <strong>流程画布</strong>
          <span className="editor-hint">拖动节点自由布局 · 空白处平移 · 端点连线</span>
          <span className="toolbar-meta">{nodes.length} 个节点 · <span>{edgeCount} 条依赖</span></span>
          <div className="zoom-controls" aria-label="画布缩放">
            <button aria-label="缩小" onClick={() => zoomAt(zoom - 0.1)}>−</button>
            <span>{Math.round(zoom * 100)}%</span>
            <button aria-label="放大" onClick={() => zoomAt(zoom + 0.1)}>+</button>
            <button aria-label="适配画布" onClick={fitCanvas}>适配</button>
          </div>
        </div>
        <div className="template-canvas" role="region" aria-label="模板节点画布">
          <WorkflowCanvas
            scale={zoom}
            pan={pan}
            onScaleChange={setZoom}
            onPanChange={setPan}
            onPanningChange={setPanning}
            onBackgroundPointerDown={() => setSelectedId(null)}
            viewportRef={viewportRef}
            worldRef={worldRef}
            wheelMode="pan"
            viewportClassName={`canvas-viewport${panning ? ' panning' : ''}`}
            viewportStyle={{ backgroundPosition: `${pan.x}px ${pan.y}px`, backgroundSize: `${18 * zoom}px ${18 * zoom}px` }}
            worldClassName="canvas-world"
          >
                <svg
                  className="canvas-edges"
                  style={{ left: edgeLeft, top: edgeTop }}
                  width={edgeWidth}
                  height={edgeHeight}
                  viewBox={`${edgeLeft} ${edgeTop} ${edgeWidth} ${edgeHeight}`}
                  aria-hidden="true"
                >
                  <defs><marker id="template-arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="var(--hx-edge)" /></marker></defs>
                  {nodes.flatMap(source => nodes.filter(target => target.deps.includes(source.id)).map(target => {
                    const id = `${source.id}->${target.id}`;
                    return <g key={id} data-edge-id={id}>
                      <path className="flow-edge" d={edgePath(source, target)} markerEnd="url(#template-arrow)" />
                      <path className="flow-edge-hit" d={edgePath(source, target)} onClick={event => { event.stopPropagation(); removeDependency(target.id, source.id); }} />
                    </g>;
                  }))}
                  {connectingSource && connectingPoint ? (() => {
                    const source = nodes.find(node => node.id === connectingSource);
                    if (!source) return null;
                    return <path className="flow-edge temp" d={`M ${source.x + NODE_WIDTH} ${source.y + NODE_HEIGHT / 2} C ${source.x + NODE_WIDTH + 70} ${source.y + NODE_HEIGHT / 2}, ${connectingPoint.x - 70} ${connectingPoint.y}, ${connectingPoint.x} ${connectingPoint.y}`} />;
                  })() : null}
                </svg>
                {nodes.map((node, index) => {
                  const role = nodeRole(nodes, node);
                  const target = Boolean(connectingSource && connectingSource !== node.id);
                  return <div key={node.id} data-node-id={node.id} role="group" aria-label={`节点 ${node.name}`} tabIndex={0} style={{ left: node.x, top: node.y }} className={`template-node ${node.id === selectedId ? 'selected' : ''}${target ? ' connect-target' : ''}`} onPointerDown={event => beginDrag(event, node)} onClick={() => setSelectedId(node.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedId(node.id); } }}>
                    <button type="button" className="node-port input" data-input-node={node.id} aria-label={`连接到 ${node.name}`} onPointerDown={event => event.stopPropagation()} onClick={event => { event.stopPropagation(); if (connectingSource) connectNodes(connectingSource, node.id); }} />
                    <div className="node-title"><span className="node-index">{index + 1}</span><span>{node.name}</span><span className="node-role">{role}</span></div>
                    <small>{(node.node_type === 'human' || node.node_type === 'human_gate') ? '等待结果选择后继续' : node.deps.length ? `依赖 ${node.deps.length} 个节点` : '并行起点'}</small>
                    <div className="node-foot"><span>{(node.node_type === 'human' || node.node_type === 'human_gate') ? '人工处理节点' : nodes.some(item => item.deps.includes(node.id)) ? '已连接下游' : '流程末端'}</span><span>{node.x}, {node.y}</span></div>
                    <button type="button" className="node-port output" aria-label={`从 ${node.name} 开始连接`} onPointerDown={event => beginConnection(event, node)} />
                  </div>;
                })}
          </WorkflowCanvas>
          <div className="canvas-tip">拖动节点调整位置 · 空白处拖动平移 · 从右侧圆点拖到目标节点创建连接 · 点击连线可移除</div>
        </div>
      </div>
      <aside className="template-inspector" aria-label={mode === 'task' ? '任务节点检查器' : '模板检查器'}>
        <div className="inspector-head"><b>节点属性</b><span>{selected ? `${nodeRole(nodes, selected)}节点` : '未选择节点'}</span></div>
        <div className="inspector-body">
          <fieldset className="workflow-settings"><legend>工作流设置</legend><div className="field"><label>最大并发数<input name="max_concurrency" type="number" min={1} max={50} step={1} value={Number.isFinite(draft.max_concurrency ?? 50) ? draft.max_concurrency ?? 50 : ''} onChange={event => setDraft(current => ({ ...current, max_concurrency: event.target.valueAsNumber }))} /></label><small>1–50 个 Agent 节点；人工节点不占名额。</small></div></fieldset>
          {selected ? <>
            {mode === 'template' && <><div className="field"><label htmlFor="template-title">模板名称</label><input id="template-title" aria-label="模板标题" value={draft.title} onChange={event => setDraft({ ...draft, title: event.target.value })} /></div>
            <div className="field"><label htmlFor="template-description">模板说明</label><textarea id="template-description" aria-label="模板说明" value={draft.description} onChange={event => setDraft({ ...draft, description: event.target.value })} /></div></>}
            <div className="field"><label htmlFor="node-name">节点名称</label><input id="node-name" aria-label="节点名称" value={selected.name} onChange={event => updateNode(selected.id, event.target.value)} /></div>
            <label className="dep"><input type="checkbox" checked={selected.node_type === 'human' || selected.node_type === 'human_gate'} onChange={event => updateConfig({ node_type: event.target.checked ? 'human' : 'agent', human_action: event.target.checked ? 'select_outputs' : undefined, requires_human: false, ...(event.target.checked ? { repeat: undefined, foreach: undefined } : {}) })} />人工处理节点（不调用 Agent）</label>
            {(selected.node_type !== 'human' && selected.node_type !== 'human_gate') && <><div className="field"><label htmlFor="node-agent">Agent</label><select id="node-agent" aria-label="节点 Agent" value={selected.agent_id || ''} onChange={event => updateConfig({ agent_id: event.target.value, model: '' })}><option value="">请选择 Agent</option>{selected.agent_id && !agents.some(a => a.id === selected.agent_id) && <option value={selected.agent_id}>{selected.agent_id}（不可用）</option>}{agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></div>
            <div className="field"><label htmlFor="node-model">模型</label><select id="node-model" aria-label="节点模型" disabled={modelLoading || !!modelError} value={selected.model || ''} onChange={event => updateConfig({ model: event.target.value })}><option value="">请选择模型</option>{selected.model && !modelOptions.some(m => m.id === selected.model) && <option value={selected.model}>{selected.model}（不可用）</option>}{modelOptions.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}</select>{modelLoading && <small role="status">正在加载模型…</small>}{modelError && <p role="alert">{modelError}<button onClick={() => setModelRetry(v => v + 1)}>重试模型</button></p>}</div>
            <div className="field"><label htmlFor="node-prompt">提示词</label><textarea id="node-prompt" aria-label="节点提示词" value={selected.prompt || ''} onChange={event => updateConfig({ prompt: event.target.value })} /></div></>}
            <div className="field"><label>输入结果</label>{nodes.filter(node => selected.deps.includes(node.id)).map(node => <label className="dep" key={node.id}><input type="checkbox" checked={selected.inputRefs?.includes(node.id) || false} onChange={event => updateConfig({ inputRefs: event.target.checked ? [...(selected.inputRefs || []), node.id] : selected.inputRefs?.filter(id => id !== node.id) })} />{node.name}</label>)}</div>
            {(selected.node_type !== 'human' && selected.node_type !== 'human_gate') && <label className="dep"><input type="checkbox" checked={!!selected.requires_human} onChange={event => updateConfig({ requires_human: event.target.checked, ...(event.target.checked ? { repeat: undefined, foreach: undefined } : {}) })} />执行 Agent 前人工确认输入</label>}
            <OrchestrationFields key={selected.id} node={selected} nodes={nodes} update={updateConfig} />
            <label className="dep"><input type="checkbox" checked={!!selected.final_report} onChange={event => updateConfig({ final_report: event.target.checked })} />最终报告</label>
            <label className="dep"><input type="checkbox" checked={!!selected.allow_skip} onChange={event => updateConfig({ allow_skip: event.target.checked })} />允许跳过</label>
            <div className="field"><label>前置依赖</label><div className="dep-list">{nodes.filter(node => node.id !== selected.id).map(node => <label key={node.id} className="dep"><input type="checkbox" checked={selected.deps.includes(node.id)} onChange={event => { if (event.target.checked) connectNodes(node.id, selected.id); else removeDependency(selected.id, node.id); }} /><span>{node.name}</span></label>)}</div><small className="field-warning">拖动节点右侧端点到另一个节点，或勾选上游节点。</small></div>
            <div className="node-stats"><span>入边 {selected.deps.length}</span><span>出边 {nodes.filter(node => node.deps.includes(selected.id)).length}</span></div>
            <button className="danger-btn" aria-label={`删除 节点 ${selectedIndex + 1}`} disabled={nodes.length <= 1} onClick={() => removeNode(selected.id)}><DeleteOutlined /> 删除节点</button>
          </> : <><div className="empty-panel"><NodeIndexOutlined />选择一个节点查看并编辑属性。</div><div className="inspector-note"><strong>当前模板</strong><p>{draft.description || '补充模板目标与执行边界。'}</p><small>当前模板包含 {draft.nodes.length} 个执行节点。</small></div></>}
        </div>
      </aside>
    </div>
  </section>;
}
