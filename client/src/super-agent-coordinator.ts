import type { AppRun, AppTask } from './app-api';

export type CoordinatorRow = {
  taskId: number;
  taskTitle: string;
  task: AppTask;
  run?: AppRun;
  error?: string;
  reconnecting?: boolean;
  lastEvent?: string;
};

const terminalStatuses = new Set(['completed', 'failed', 'canceled']);
const activeStatuses = new Set(['pending', 'running']);

export const statusLabel = (status?: string) => ({
  pending: '排队中', running: '执行中', waiting_human: '等待人工', completed: '已完成', failed: '失败', canceled: '已取消', succeeded: '已完成', skipped: '已跳过', queued: '排队中', idle: '待执行', ready: '就绪',
}[status || ''] || status || '未启动');

export const statusTone = (status?: string) => ({
  pending: 'blue', running: 'amber', waiting_human: 'amber', completed: 'green', failed: 'red', canceled: 'gray', succeeded: 'green', skipped: 'green', queued: 'blue',
}[status || ''] || 'gray');

export function runProgress(run?: Pick<AppRun, 'workflow' | 'execution_snapshot' | 'nodes'>) {
  const workflow = run?.workflow || run?.execution_snapshot?.workflow;
  const latest = new Map<string, NonNullable<typeof run>['nodes'][number]>();
  for (const node of run?.nodes || []) {
    const prior = latest.get(node.node_id);
    if (!prior || node.attempt >= prior.attempt) latest.set(node.node_id, node);
  }
  const ids = workflow ? workflow.nodes.map(node => node.id) : [...latest.keys()];
  const total = ids.length;
  const done = ids.filter(id => ['succeeded', 'skipped'].includes(latest.get(id)?.status || '')).length;
  return { done, total, percent: total ? Math.round((done / total) * 100) : 0 };
}

export function coordinatorSummary(rows: Array<Pick<CoordinatorRow, 'run'>>) {
  const total = rows.length;
  const active = rows.filter(row => activeStatuses.has(row.run?.status || '')).length;
  const waiting = rows.filter(row => row.run?.status === 'waiting_human').length;
  const completed = rows.filter(row => row.run?.status === 'completed').length;
  const failed = rows.filter(row => ['failed', 'canceled'].includes(row.run?.status || '')).length;
  const terminal = rows.filter(row => terminalStatuses.has(row.run?.status || '')).length;
  return { total, active, waiting, completed, failed, percent: total ? Math.round((terminal / total) * 100) : 0 };
}

export function mergeCoordinatorRun(rows: CoordinatorRow[], run: AppRun): CoordinatorRow[] {
  return rows.map(row => row.run?.id === run.id && row.taskId === run.task_id ? { ...row, run } : row);
}

export function dispatchableTasks(tasks: AppTask[]): AppTask[] {
  return tasks.filter(task => task.workflow_state === 'saved' && Boolean(task.workflow?.nodes?.length) && ['draft', 'failed'].includes(task.status));
}

export function isRunActive(run?: AppRun) {
  return Boolean(run && (activeStatuses.has(run.status) || run.status === 'waiting_human') && !run.paused);
}

export function latestOutput(run?: AppRun): string {
  if (!run) return '';
  const finalNodes = new Set((run.workflow || run.execution_snapshot?.workflow)?.nodes.filter(node => node.final_report).map(node => node.id) || []);
  const node = [...run.nodes].reverse().find(item => item.status === 'succeeded' && (finalNodes.size === 0 || finalNodes.has(item.node_id)));
  const value = node?.output;
  if (!value || typeof value !== 'object') return '';
  const text = typeof value.text === 'string' ? value.text : typeof value.output_text === 'string' ? value.output_text :
    (Array.isArray(value.output) ? value.output : []).flatMap(item => item?.type === 'message' && Array.isArray(item.content)
      ? item.content.filter((part: { type?: string; text?: unknown }) => part.type === 'output_text' && typeof part.text === 'string').map((part: { text: string }) => part.text) : []).join('\n');
  return text.trim().slice(0, 240);
}
