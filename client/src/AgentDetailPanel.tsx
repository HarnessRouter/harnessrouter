import { useMemo, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react';
import { Button, Tag } from 'antd';
import { ArrowLeftOutlined, CopyOutlined, MessageOutlined, RobotOutlined } from '@ant-design/icons';
import type { AppAgent } from './app-api';
import { AGENT_LAYERS, agentDetailOf, type AgentCapabilityRow, type AgentLayer } from './agent-detail';

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return <div className="agent-detail-fact"><dt>{label}</dt><dd>{children}</dd></div>;
}

function CapabilityGroup({ title, rows }: { title: string; rows: AgentCapabilityRow[] }) {
  if (!rows.length) return null;
  return <section className="agent-cap-group"><h4>{title} <span>{rows.length}</span></h4><ul className="agent-cap-list">{rows.map(row => (
    <li key={row.name}>
      <span className="agent-cap-copy"><strong>{row.name}</strong>{row.detail ? <small>{row.detail}</small> : null}</span>
      {row.on === false ? <Tag>停用</Tag> : row.on === true ? <Tag color="green">启用</Tag> : null}
    </li>
  ))}</ul></section>;
}

function layerSummary(layer: AgentLayer, detail: ReturnType<typeof agentDetailOf>): string {
  if (layer === 'instructions') return detail.instructions.known ? `${detail.instructions.chars} 字符` : 'Gateway 未返回';
  if (layer === 'harness') return [detail.harness.runtime, detail.harness.model, detail.harness.reasoning].filter(Boolean).join(' · ') || 'Gateway 未返回';
  if (layer === 'capabilities') {
    const { skills, mcpServers, tools, plugins } = detail.capabilities.counts;
    return [skills ? `${skills} 个技能` : '', mcpServers ? `${mcpServers} 个 MCP` : '', tools ? `${tools} 个工具停用` : '', plugins ? `${plugins} 个插件` : ''].filter(Boolean).join(' · ') || (detail.capabilities.known ? '暂无额外能力' : 'Gateway 未返回');
  }
  if (layer === 'memory') return detail.memory.configured ? [detail.memory.name, detail.memory.engine].filter(Boolean).join(' · ') : detail.memory.known ? '未配置' : 'Gateway 未返回';
  const { vars, headers, maxStep, timeoutSeconds } = detail.environment;
  return [vars.length ? `${vars.length} 个变量` : '', headers.length ? `${headers.length} 个请求头` : '', maxStep ? `${maxStep} 步` : '', timeoutSeconds ? `${timeoutSeconds} 秒` : ''].filter(Boolean).join(' · ') || (detail.environment.known ? '使用默认限制' : 'Gateway 未返回');
}

export function AgentDetailPanel({ agent, deleting, onBack, onChat, onDelete }: {
  agent: AppAgent;
  deleting: boolean;
  onBack: () => void;
  onChat: (id: string) => void;
  onDelete: () => void;
}) {
  const detail = useMemo(() => agentDetailOf(agent), [agent]);
  const [layer, setLayer] = useState<AgentLayer>('instructions');
  const [copied, setCopied] = useState(false);
  const activeLabel = AGENT_LAYERS.find(item => item.id === layer)?.label || 'Instructions';

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(agent.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* Clipboard access is optional. */ }
  };

  const moveLayer = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowDown', 'ArrowRight', 'ArrowUp', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const current = AGENT_LAYERS.findIndex(item => item.id === layer);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? AGENT_LAYERS.length - 1
      : event.key === 'ArrowDown' || event.key === 'ArrowRight' ? (current + 1) % AGENT_LAYERS.length
        : (current - 1 + AGENT_LAYERS.length) % AGENT_LAYERS.length;
    const id = AGENT_LAYERS[next].id;
    setLayer(id);
    requestAnimationFrame(() => document.getElementById(`agent-layer-${id}`)?.focus());
  };

  const createdDate = detail.harness.createdAt === null ? null : new Date(detail.harness.createdAt);
  const created = createdDate && !Number.isNaN(createdDate.getTime()) ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(createdDate) : '';
  const hasCapabilities = detail.capabilities.skills.length || detail.capabilities.mcpServers.length || detail.capabilities.tools.length || detail.capabilities.plugins.length;

  return <section className="agent-detail" role="region" aria-label={`${agent.name}详情`}>
    <header className="agent-detail-head">
      <div className="agent-detail-title">
        <div className="agent-detail-eyebrow"><RobotOutlined aria-hidden="true" /> 智能体详情</div>
        <h2>{agent.name}</h2>
        <div className="agent-detail-tags">
          <Tag>{detail.harness.runtime || '运行时未返回'}</Tag>
          <Tag>{detail.harness.model || '模型未返回'}</Tag>
          {detail.memory.configured ? <Tag color="blue">Memory · {detail.memory.engine || detail.memory.name || '已配置'}</Tag> : null}
        </div>
        <p className="agent-detail-hint">展示 Gateway 中保存的 Agent 配置；修改请前往 Gateway 的 Agent 设置。</p>
      </div>
      <div className="app-agent-actions agent-detail-actions">
        <Button icon={<ArrowLeftOutlined aria-hidden="true" />} onClick={onBack}>返回列表</Button>
        <Button type="primary" icon={<MessageOutlined aria-hidden="true" />} onClick={() => onChat(agent.id)}>开始对话</Button>
        <Button danger disabled={deleting} onClick={onDelete}>删除</Button>
      </div>
    </header>
    <div className="agent-detail-layout">
      <div className="agent-detail-nav" role="tablist" aria-label="智能体设置" aria-orientation="vertical" onKeyDown={moveLayer}>
        {AGENT_LAYERS.map(item => <button key={item.id} id={`agent-layer-${item.id}`} type="button" role="tab" aria-selected={layer === item.id} aria-controls="agent-layer-panel" tabIndex={layer === item.id ? 0 : -1} onClick={() => setLayer(item.id)}>
          <strong>{item.label}</strong>
          <small>{layerSummary(item.id, detail)}</small>
        </button>)}
      </div>
      <div className="agent-detail-panel" id="agent-layer-panel" role="tabpanel" aria-label={activeLabel}>
        {layer === 'instructions' ? <>
          <div className="agent-detail-panel-head"><div><small>Instructions</small><h3>智能体工作说明</h3></div><span>{detail.instructions.known ? `${detail.instructions.chars} 字符` : '未返回'}</span></div>
          {detail.instructions.known
            ? <pre className="agent-detail-instructions">{detail.instructions.text.trim() || '该 Agent 未设置系统提示词。'}</pre>
            : <p className="agent-detail-empty">Gateway 未返回 Instructions。</p>}
        </> : null}
        {layer === 'harness' ? <>
          <div className="agent-detail-panel-head"><div><small>Agent harness</small><h3>运行时与模型</h3></div></div>
          <dl className="agent-detail-facts">
            <Fact label="智能体 ID"><span className="agent-detail-id"><code>{agent.id}</code><Button size="small" aria-label="复制智能体 ID" icon={<CopyOutlined aria-hidden="true" />} onClick={() => void copyId()}>{copied ? '已复制' : '复制'}</Button></span></Fact>
            <Fact label="名称">{agent.name}</Fact>
            <Fact label="Agent harness">{detail.harness.runtimeKnown ? detail.harness.runtime || '默认运行时' : 'Gateway 未返回'}</Fact>
            <Fact label="默认模型">{detail.harness.modelKnown ? detail.harness.model || '运行时默认模型' : 'Gateway 未返回'}</Fact>
            <Fact label="Reasoning effort">{detail.harness.reasoningKnown ? detail.harness.reasoning || '默认' : 'Gateway 未返回'}</Fact>
            <Fact label="创建时间">{created || 'Gateway 未返回'}</Fact>
          </dl>
        </> : null}
        {layer === 'capabilities' ? <>
          <div className="agent-detail-panel-head"><div><small>Capabilities</small><h3>技能、工具与插件</h3></div></div>
          {!detail.capabilities.known ? <p className="agent-detail-empty">Gateway 未返回 Capabilities。</p> : !hasCapabilities ? <p className="agent-detail-empty">该 Agent 暂无额外能力。</p> : <>
            <div className="agent-cap-summary">
              <span><b>{detail.capabilities.counts.skills}</b> Skills</span>
              <span><b>{detail.capabilities.counts.mcpServers}</b> MCP servers</span>
              <span><b>{detail.capabilities.counts.tools}</b> 停用工具</span>
              <span><b>{detail.capabilities.counts.plugins}</b> Plugins</span>
            </div>
            <CapabilityGroup title="Skills" rows={detail.capabilities.skills} />
            <CapabilityGroup title="MCP servers" rows={detail.capabilities.mcpServers} />
            <CapabilityGroup title="Disabled tools" rows={detail.capabilities.tools} />
            <CapabilityGroup title="Plugins" rows={detail.capabilities.plugins} />
          </>}
        </> : null}
        {layer === 'memory' ? <>
          <div className="agent-detail-panel-head"><div><small>Memory</small><h3>长期记忆</h3></div></div>
          {!detail.memory.known ? <p className="agent-detail-empty">Gateway 未返回 Memory。</p> : <dl className="agent-detail-facts">
            <Fact label="状态">{detail.memory.configured ? '已配置' : detail.memory.engine === 'none' ? '关闭' : '未配置'}</Fact>
            <Fact label="名称">{detail.memory.name || '未返回'}</Fact>
            <Fact label="引擎">{detail.memory.engine || '未返回'}</Fact>
            <Fact label="范围">{detail.memory.scope || '未返回'}</Fact>
            <Fact label="原因">{detail.memory.reason || 'Gateway 未提供说明'}</Fact>
            {detail.memory.configured ? <>
              <Fact label="Observe">{detail.memory.observe ? '开启' : '关闭'}</Fact>
              <Fact label="Provisioned">{detail.memory.provisioned ? '由该 Agent 创建' : '否'}</Fact>
            </> : null}
          </dl>}
        </> : null}
        {layer === 'limits' ? <>
          <div className="agent-detail-panel-head"><div><small>Environment &amp; limits</small><h3>运行环境与限制</h3></div></div>
          {!detail.environment.known ? <p className="agent-detail-empty">Gateway 未返回 Environment &amp; limits。</p> : <>
            <section className="agent-cap-group"><h4>环境变量 <span>{detail.environment.vars.length}</span></h4>
              {detail.environment.vars.length ? <ul className="agent-cap-list">{detail.environment.vars.map(row => <li key={row.name}><span className="agent-cap-copy"><strong>{row.name}</strong><small>{row.valueKind === 'reference' ? '已保存的引用' : row.valueKind === 'empty' ? '空值' : '已设置（值已隐藏）'}</small></span></li>)}</ul> : <p className="agent-detail-empty">未设置环境变量。</p>}
            </section>
            <section className="agent-cap-group"><h4>请求头 <span>{detail.environment.headers.length}</span></h4>
              {detail.environment.headers.length ? <ul className="agent-cap-list">{detail.environment.headers.map(name => <li key={name}><span className="agent-cap-copy"><strong>{name}</strong><small>由调用方按请求传入</small></span></li>)}</ul> : <p className="agent-detail-empty">未声明额外请求头。</p>}
            </section>
            <dl className="agent-detail-facts">
              <Fact label="最大步数">{detail.environment.maxStepKnown ? detail.environment.maxStep ? `${detail.environment.maxStep} 步` : '使用默认限制' : 'Gateway 未返回'}</Fact>
              <Fact label="超时">{detail.environment.timeoutKnown ? detail.environment.timeoutSeconds ? `${detail.environment.timeoutSeconds} 秒` : '使用默认限制' : 'Gateway 未返回'}</Fact>
              <Fact label="绑定环境">{detail.environment.environmentKnown ? detail.environment.environmentId || '未绑定' : 'Gateway 未返回'}</Fact>
            </dl>
          </>}
        </> : null}
      </div>
    </div>
  </section>;
}
