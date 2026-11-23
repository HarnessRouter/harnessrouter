import type { JsonValue, OrchestrationNode } from './app-types.ts';

const pathPattern = /^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$/;
export function parseComparison(text: string): JsonValue {
  try { return JSON.parse(text) as JsonValue; } catch { return text; }
}
export function orchestrationIssue(workflow: { max_concurrency?: number; nodes: Array<OrchestrationNode & { id: string; deps?: string[]; node_type?: string; requires_human?: boolean }> }): string | undefined {
  const bounded = (value: number | undefined, max: number) => Number.isInteger(value) && Number(value) >= 1 && Number(value) <= max;
  if (workflow.max_concurrency !== undefined && !bounded(workflow.max_concurrency, 50)) return '最大并发数必须是 1 到 50 的整数。';
  for (const node of workflow.nodes) {
    const prefix = `节点 ${node.id}：`;
    if (node.repeat && node.foreach) return `${prefix}重复与集合展开不能同时启用。`;
    if ((node.repeat || node.foreach) && (node.requires_human || ['human', 'human_gate'].includes(node.node_type || ''))) return `${prefix}人工确认节点仅支持单次执行。`;
    for (const config of [node.condition, node.foreach]) {
      if (config && !node.deps?.includes(config.source)) return `${prefix}条件或集合来源必须是前置依赖。`;
    }
    for (const predicate of [node.condition, node.repeat?.until, node.foreach]) {
      if (predicate && !pathPattern.test(predicate.path)) return `${prefix}字段路径应为点分隔的对象字段。`;
    }
    if (node.repeat && !bounded(node.repeat.max_iterations, 10)) return `${prefix}重复上限必须是 1 到 10 的整数。`;
    if (node.foreach && !bounded(node.foreach.max_items, 10)) return `${prefix}集合上限必须是 1 到 10 的整数。`;
    if (node.condition?.op === 'in' && !Array.isArray(node.condition.value)) return `${prefix}包含于条件需要 JSON 数组。`;
  }
}

export function withoutDependency<T extends OrchestrationNode & { deps: string[]; inputRefs?: string[] }>(node: T, source: string): T {
  return { ...node, deps: node.deps.filter(id => id !== source), inputRefs: node.inputRefs?.filter(id => id !== source),
    condition: node.condition?.source === source ? undefined : node.condition,
    foreach: node.foreach?.source === source ? undefined : node.foreach };
}
