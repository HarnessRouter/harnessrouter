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
    if (node.loop && (node.repeat || node.foreach)) return `${prefix}循环不能与重复或集合展开同时启用。`;
    if (node.dynamic_plan && (node.repeat || node.foreach || node.loop)) return `${prefix}动态计划不能与重复、集合展开或循环同时启用。`;
    if (node.subgraph && (node.repeat || node.foreach || node.loop || node.dynamic_plan)) return `${prefix}子编排不能与其他展开或循环同时启用。`;
    if (node.subgraph && !node.deps?.length) return `${prefix}子编排节点必须依赖父工作流节点。`;
    if (node.subgraph && (!Number.isInteger(node.subgraph.max_concurrency ?? 1) || (node.subgraph.max_concurrency ?? 1) < 1 || (node.subgraph.max_concurrency ?? 1) > 10)) return `${prefix}子编排并发数必须是 1 到 10 的整数。`;
    if (node.subgraph && (!Array.isArray(node.subgraph.nodes) || !node.subgraph.nodes.length || node.subgraph.nodes.length > 10)) return `${prefix}子编排必须包含 1 到 10 个静态子节点。`;
    if (node.subgraph) {
      const children = node.subgraph.nodes;
      if (children.some(child => typeof child.id !== 'string' || !child.id.trim() || child.subgraph || child.repeat || child.foreach || child.loop || child.dynamic_plan)) return `${prefix}子编排只支持不可递归的静态 Agent 子节点。`;
      const ids = children.map(child => child.id);
      if (new Set(ids).size !== ids.length) return `${prefix}子编排子节点 ID 不能重复。`;
      const known = new Set(ids);
      for (const child of children) {
        const deps = child.deps || [], inputRefs = child.inputRefs || [];
        if (!Array.isArray(deps) || !Array.isArray(inputRefs)) return `${prefix}子编排子节点 deps 和 inputRefs 必须是数组。`;
        if (new Set(deps).size !== deps.length || new Set(inputRefs).size !== inputRefs.length) return `${prefix}子编排子节点依赖或 inputRefs 不能重复。`;
        if (deps.some(dep => !known.has(dep))) return `${prefix}子编排子节点包含未知依赖。`;
        if (inputRefs.some(ref => !deps.includes(ref))) return `${prefix}子编排子节点 inputRefs 必须属于 deps。`;
      }
      const visiting = new Set<string>(), visited = new Set<string>();
      const visit = (id: string): boolean => {
        if (visiting.has(id)) return false;
        if (visited.has(id)) return true;
        visiting.add(id);
        const child = children.find(item => item.id === id)!;
        if ((child.deps || []).every(dep => visit(dep))) {
          visiting.delete(id); visited.add(id); return true;
        }
        return false;
      };
      if (ids.some(id => !visit(id))) return `${prefix}子编排子节点依赖不能形成环。`;
    }
    if ((node.repeat || node.foreach) && (node.requires_human || ['human', 'human_gate'].includes(node.node_type || ''))) return `${prefix}人工确认节点仅支持单次执行。`;
    for (const config of [node.condition, node.foreach]) {
      if (config && !node.deps?.includes(config.source)) return `${prefix}条件或集合来源必须是前置依赖。`;
    }
    for (const predicate of [node.condition, node.repeat?.until, node.foreach]) {
      if (predicate && !pathPattern.test(predicate.path)) return `${prefix}字段路径应为点分隔的对象字段。`;
    }
    if (node.repeat && !bounded(node.repeat.max_iterations, 10)) return `${prefix}重复上限必须是 1 到 10 的整数。`;
    if (node.foreach && !bounded(node.foreach.max_items, 10)) return `${prefix}集合上限必须是 1 到 10 的整数。`;
    if (node.foreach && node.foreach.mode && !['serial', 'parallel'].includes(node.foreach.mode)) return `${prefix}集合执行模式无效。`;
    if (node.foreach?.nested && (!node.foreach.nested.path || !pathPattern.test(node.foreach.nested.path))) return `${prefix}嵌套集合字段路径无效。`;
    if (node.foreach?.nested && !bounded(node.foreach.nested.max_items, 10)) return `${prefix}嵌套集合上限必须是 1 到 10 的整数。`;
    if (node.foreach?.nested?.mode && !['serial', 'parallel'].includes(node.foreach.nested.mode)) return `${prefix}嵌套集合执行模式无效。`;
    if (node.dynamic_plan && !node.deps?.includes(node.dynamic_plan.source)) return `${prefix}动态计划来源必须是前置依赖。`;
    if (node.dynamic_plan && (!Number.isInteger(node.dynamic_plan.max_items) || node.dynamic_plan.max_items < 1 || node.dynamic_plan.max_items > 10)) return `${prefix}动态计划上限必须是 1 到 10 的整数。`;
    if (node.dynamic_plan && node.dynamic_plan.mode && !['serial', 'parallel'].includes(node.dynamic_plan.mode)) return `${prefix}动态计划执行模式无效。`;
    if (node.dynamic_plan?.topology !== undefined && !['list', 'dag'].includes(node.dynamic_plan.topology)) return `${prefix}动态计划拓扑无效。`;
    if (node.loop && (!Number.isInteger(node.loop.max_iterations) || node.loop.max_iterations < 1 || node.loop.max_iterations > 10)) return `${prefix}循环上限必须是 1 到 10 的整数。`;
    if (node.loop && (!node.loop.body.length || !node.loop.body.includes(node.id))) return `${prefix}循环体必须包含当前检查节点。`;
    if (node.loop && !node.loop.body.every(id => node.deps?.includes(id) || id === node.id)) return `${prefix}循环体节点必须是当前节点或依赖节点。`;
    if (node.loop && (!node.loop.body.includes(node.loop.until.source) || !node.loop.until.path || !pathPattern.test(node.loop.until.path))) return `${prefix}循环终止条件来源必须位于循环体内。`;
    if (node.condition?.op === 'in' && !Array.isArray(node.condition.value)) return `${prefix}包含于条件需要 JSON 数组。`;
  }
}

export function withoutDependency<T extends OrchestrationNode & { deps: string[]; inputRefs?: string[] }>(node: T, source: string): T {
  return { ...node, deps: node.deps.filter(id => id !== source), inputRefs: node.inputRefs?.filter(id => id !== source),
    condition: node.condition?.source === source ? undefined : node.condition,
    foreach: node.foreach?.source === source ? undefined : node.foreach,
    loop: node.loop?.body.includes(source) ? undefined : node.loop,
    dynamic_plan: node.dynamic_plan?.source === source ? undefined : node.dynamic_plan };
}
