import type { AppNodeRun, AppRun } from './app-api';

export function itemRetryAction(run: AppRun, control: AppNodeRun, item: AppNodeRun, replaying: boolean): { kind: 'retry'; itemId: number } | { kind: 'resume'; body: { kind: 'rerun'; target_node: string; resume_from_run_id: number; item_node_run_id: number } } | null {
  if (replaying || !run || !control || !item) return null;
  const manifest = control.input?.item_node_run_ids;
  if (!Array.isArray(manifest) || !manifest.includes(item.id)) return null;
  if (item.run_id !== run.id || item.node_id !== control.node_id || item.iteration !== control.iteration) return null;
  if (!['foreach_item', 'dynamic_item'].includes(item.execution_kind || '') || !['failed', 'canceled'].includes(item.status)) return null;
  if (['pending', 'running', 'waiting_human'].includes(run.status)) return { kind: 'retry', itemId: item.id };
  if (['failed', 'canceled'].includes(run.status)) return {
    kind: 'resume',
    body: { kind: 'rerun', target_node: control.node_id, resume_from_run_id: run.id, item_node_run_id: item.id },
  };
  return null;
}

export function attemptLabel(attempt: AppNodeRun): string {
  const round = typeof attempt.iteration === 'number' ? attempt.iteration : 1;
  const dynamic = attempt.input?.dynamic_item as { id?: string } | undefined;
  const item = attempt.execution_kind === 'foreach_nested_item'
    ? `外层项 ${Number(attempt.input?.outer_foreach_index ?? 0) + 1} / 内层项 ${Number(attempt.foreach_index ?? 0) + 1}`
    : attempt.execution_kind === 'foreach_nested_aggregate' ? `外层项 ${Number(attempt.foreach_index ?? 0) + 1} 聚合`
    : attempt.execution_kind === 'dynamic_item' && typeof dynamic?.id === 'string' ? `计划节点 ${dynamic.id}`
    : attempt.execution_kind?.endsWith('_aggregate') ? '聚合' : typeof attempt.foreach_index === 'number' ? `集合项 ${attempt.foreach_index + 1}` : '节点';
  return `第 ${round} 轮 · ${item} · 尝试 ${attempt.attempt || 1}`;
}
