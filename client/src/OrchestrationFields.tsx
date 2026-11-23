import { useState } from 'react';
import type { JsonValue, OutputPredicate, TemplateNode } from './app-types';
import { parseComparison } from './orchestration';

function ComparisonValue({ label, value, onChange }: { label: string; value: JsonValue; onChange: (value: JsonValue) => void }) {
  const [text, setText] = useState(JSON.stringify(value));
  return <div className="field"><label>{label}<input name={label} value={text} onChange={event => { setText(event.target.value); onChange(parseComparison(event.target.value)); }} /></label><small>支持 JSON；普通文本按字符串保存。文本 true 请写为 "true"。</small></div>;
}

function PredicateFields({ prefix, predicate, onChange, repeat = false }: { prefix: string; predicate: OutputPredicate; onChange: (predicate: OutputPredicate) => void; repeat?: boolean }) {
  return <>
    <div className="field"><label>{prefix}路径<input name={`${prefix}路径`} autoCapitalize="none" spellCheck={false} value={predicate.path} onChange={event => onChange({ ...predicate, path: event.target.value })} /></label></div>
    <div className="field"><label>{prefix}比较<select name={`${prefix}比较`} value={predicate.op} onChange={event => {
      const op = event.target.value as OutputPredicate['op'];
      onChange(op === 'exists' ? { path: predicate.path, op } : op === 'in' ? { path: predicate.path, op, value: [] } : { path: predicate.path, op, value: predicate.value ?? '' });
    }}><option value="eq">等于</option>{!repeat && <><option value="neq">不等于</option><option value="in">包含于数组</option></>}<option value="exists">字段存在</option></select></label></div>
    {predicate.op !== 'exists' && <ComparisonValue key={predicate.op} label={`${prefix}值`} value={predicate.value} onChange={value => onChange({ ...predicate, value } as OutputPredicate)} />}
  </>;
}

export function OrchestrationFields({ node, nodes, update }: { node: TemplateNode; nodes: TemplateNode[]; update: (patch: Partial<TemplateNode>) => void }) {
  const dependencies = nodes.filter(candidate => node.deps.includes(candidate.id));
  const human = ['human', 'human_gate'].includes(node.node_type || '') || node.requires_human;
  const mode = node.foreach ? 'foreach' : node.repeat ? 'repeat' : 'once';
  const sourceField = (label: string, source: string, change: (source: string) => void) => <div className="field"><label>{label}<select name={label} value={source} onChange={event => change(event.target.value)}><option value="">请选择前置依赖</option>{dependencies.map(candidate => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}</select></label></div>;
  return <div className="orchestration-fields">
    <fieldset><legend>条件与汇合</legend>
      <label className="dep"><input name="allow_missing_inputs" type="checkbox" checked={!!node.allow_missing_inputs} onChange={event => update({ allow_missing_inputs: event.target.checked })} />允许缺失输入</label>
      <small>汇合时允许跳过的分支，只传递成功输入。</small>
      <label className="dep"><input name="condition" type="checkbox" checked={!!node.condition} disabled={!node.condition && !dependencies.length} onChange={event => update({ condition: event.target.checked ? { source: dependencies[0]?.id || '', path: '', op: 'eq', value: '' } : undefined })} />条件分支</label>
      {!dependencies.length && <small>添加前置依赖后可配置条件来源。</small>}
      {node.condition && <>{sourceField('条件来源', node.condition.source, source => update({ condition: { ...node.condition!, source } }))}<PredicateFields prefix="条件" predicate={node.condition} onChange={predicate => update({ condition: { ...predicate, source: node.condition!.source } })} /></>}
    </fieldset>
    <fieldset><legend>执行方式</legend>
      <div className="field"><label>执行模式<select name="execution_mode" value={mode} disabled={!!human} onChange={event => update({
        repeat: event.target.value === 'repeat' ? { max_iterations: 3, until: { path: 'done', op: 'eq', value: true } } : undefined,
        foreach: event.target.value === 'foreach' ? { source: dependencies[0]?.id || '', path: 'items', max_items: 10 } : undefined,
      })}><option value="once">单次执行</option><option value="repeat">有界重复</option><option value="foreach" disabled={!dependencies.length}>有限集合展开（串行）</option></select></label></div>
      {human && <small>人工确认节点仅支持单次执行。</small>}
      {node.repeat && <><div className="field"><label>重复上限<input name="max_iterations" type="number" min={1} max={10} step={1} value={Number.isFinite(node.repeat.max_iterations) ? node.repeat.max_iterations : ''} onChange={event => update({ repeat: { ...node.repeat!, max_iterations: event.target.valueAsNumber } })} /></label></div><PredicateFields prefix="重复终止" predicate={node.repeat.until} repeat onChange={until => update({ repeat: { ...node.repeat!, until: until as NonNullable<TemplateNode['repeat']>['until'] } })} /></>}
      {node.foreach && <>{sourceField('集合来源', node.foreach.source, source => update({ foreach: { ...node.foreach!, source } }))}<div className="field"><label>集合路径<input name="collection_path" autoCapitalize="none" spellCheck={false} value={node.foreach.path} onChange={event => update({ foreach: { ...node.foreach!, path: event.target.value } })} /></label></div><div className="field"><label>集合上限<input name="max_items" type="number" min={1} max={10} step={1} value={Number.isFinite(node.foreach.max_items) ? node.foreach.max_items : ''} onChange={event => update({ foreach: { ...node.foreach!, max_items: event.target.valueAsNumber } })} /></label></div><small>全部集合项成功后才将聚合结果传递下游。</small></>}
    </fieldset>
  </div>;
}
