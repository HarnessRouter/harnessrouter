import type { AppRun, AppTaskNode } from './app-api';
import type { HistoryEvent } from './run-history';

export const taskLabels: Record<string, string> = { draft: '草稿', running: '运行中', waiting: '等待处理', completed: '已完成', failed: '失败', archived: '已归档' };
export const runLabels: Record<string, string> = { pending: '等待启动', running: '运行中', waiting_human: '等待确认', completed: '已完成', failed: '失败', canceled: '已取消' };
export const nodeLabels: Record<string, string> = { idle: '待执行', pending: '待执行', ready: '就绪', queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', canceled: '已取消', skipped: '已跳过' };
export const activeRun = (run?: AppRun) => !!run && ['pending', 'running', 'waiting_human'].includes(run.status);
export const statusTone = (status: string) => ({ completed: 'green', succeeded: 'green', running: 'blue', pending: 'blue', waiting: 'amber', waiting_human: 'amber', failed: 'red' } as Record<string, string>)[status] || 'gray';

export const nodeStatusTone = (status?: string) => ({
  succeeded: 'green', skipped: 'green', running: 'amber', queued: 'blue', ready: 'blue', pending: 'blue', failed: 'red', canceled: 'gray', idle: 'gray',
} as Record<string, string>)[status || ''] || 'gray';

export const nodeStatusLive = (status?: string) => status === 'running';
export const statusLive = (status?: string) => ['running', 'pending', 'waiting', 'waiting_human'].includes(status || '');

export function flowEdgeTone(from?: string, to?: string): 'done' | 'active' | 'ready' | 'failed' | 'pending' {
  if (to === 'running' || from === 'running') return 'active';
  if (to === 'failed' || from === 'failed') return 'failed';
  if (['succeeded', 'skipped'].includes(to || '') && ['succeeded', 'skipped'].includes(from || '')) return 'done';
  if (['succeeded', 'skipped'].includes(from || '') && ['queued', 'ready'].includes(to || '')) return 'ready';
  return 'pending';
}

export function latestRunOutputs(run?: AppRun): Array<{ nodeId: string; status: string; output: Record<string, unknown> }> {
  return (run?.nodes || []).filter(node => node.output != null).map(node => ({ nodeId: node.node_id, status: node.status, output: node.output as Record<string, unknown> }));
}

export function taskProgress(run?: AppRun): { done: number; total: number; percent: number } {
  const nodes = run?.workflow?.nodes || [];
  const done = nodes.filter(node => run?.nodes.some(attempt => attempt.node_id === node.id && ['succeeded', 'skipped'].includes(attempt.status))).length;
  return { done, total: nodes.length, percent: nodes.length ? Math.round(done / nodes.length * 100) : 0 };
}

export function workflowDraft(workflow?: { nodes: AppTaskNode[] } | null) {
  return { nodes: (workflow?.nodes || []).map((node, index) => ({
    ...structuredClone(node), name: node.name || node.id, deps: [...(node.deps || [])],
    x: Number.isFinite(node.x) ? Number(node.x) : 20 + index * 220,
    y: Number.isFinite(node.y) ? Number(node.y) : 80,
  })) };
}

export function snapshotEvents(run: AppRun): Array<HistoryEvent & { time: string }> {
  return run.nodes.flatMap(node => {
    const events: Array<HistoryEvent & { time: string }> = [];
    if (node.started_at) events.push({ nodeId: node.node_id, status: 'running', label: '开始执行', time: node.started_at });
    if (node.status !== 'idle' && (node.status !== 'running' || !node.started_at)) events.push({ nodeId: node.node_id, status: node.status, label: nodeLabels[node.status] || node.status, time: node.finished_at || node.started_at || '' });
    return events;
  }).sort((a, b) => a.time.localeCompare(b.time));
}

export function waitingGate(run?: AppRun) {
  if (run?.status !== 'waiting_human') return undefined;
  return run.workflow?.nodes.find(node => (node.node_type === 'human' || node.node_type === 'human_gate' || node.requires_human) && !run.decisions?.some(d => d.node_id === node.id)
    && run.nodes.some(attempt => attempt.node_id === node.id && attempt.status === 'idle')
    && (node.deps || []).every(dep => run.nodes.some(attempt => attempt.node_id === dep && attempt.status === 'succeeded')));
}
