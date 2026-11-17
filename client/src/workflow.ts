export type TaskNodeStatus = 'pending' | 'running' | 'done' | 'failed' | 'blocked';
export type ClientTaskStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface TaskNodeSnapshot {
  id: string;
  name: string;
  agentId: string;
  agentName: string;
  deps: string[];
  retryLimit: number;
  attempts: number;
  status: TaskNodeStatus;
  output: string;
  responseId: string | null;
}

export interface ClientTask {
  id: string;
  title: string;
  templateId: string;
  templateVersion: number;
  createdAt: number;
  status: ClientTaskStatus;
  input: string;
  snapshot: { title: string; description: string; nodes: TaskNodeSnapshot[] };
  lastUpdated: number;
}

export interface WorkflowTaskRecord {
  id: string;
  title: string;
  input: string;
  status: string;
  created_at: number;
  updated_at: number;
  snapshot: {
    template_id?: string;
    template_version?: number;
    title: string;
    description?: string;
    nodes: Array<{
      id: string;
      name: string;
      agent_id?: string;
      agent_name?: string;
      deps?: string[];
      retry_limit?: number;
      attempts?: number;
      status?: string;
      output?: string;
      response_id?: string | null;
    }>;
  };
}

const NODE_STATUSES = new Set<TaskNodeStatus>(['pending', 'running', 'done', 'failed', 'blocked']);
const TASK_STATUSES = new Set<ClientTaskStatus>(['pending', 'running', 'completed', 'failed']);

function nodeStatus(value: string | undefined): TaskNodeStatus {
  return NODE_STATUSES.has(value as TaskNodeStatus) ? value as TaskNodeStatus : 'pending';
}

function taskStatus(value: string | undefined): ClientTaskStatus {
  return TASK_STATUSES.has(value as ClientTaskStatus) ? value as ClientTaskStatus : 'pending';
}

export function fromWorkflowRecord(record: WorkflowTaskRecord): ClientTask {
  return {
    id: record.id,
    title: record.title,
    templateId: record.snapshot.template_id || '',
    templateVersion: record.snapshot.template_version || 1,
    createdAt: record.created_at,
    status: taskStatus(record.status),
    input: record.input,
    snapshot: {
      title: record.snapshot.title,
      description: record.snapshot.description || '',
      nodes: record.snapshot.nodes.map((node) => ({
        id: node.id,
        name: node.name,
        agentId: node.agent_id || '',
        agentName: node.agent_name || '默认 Agent',
        deps: node.deps || [],
        retryLimit: node.retry_limit ?? 1,
        attempts: node.attempts ?? 0,
        status: nodeStatus(node.status),
        output: node.output || '',
        responseId: node.response_id || null,
      })),
    },
    lastUpdated: record.updated_at,
  };
}

/**
 * Merge a Gateway snapshot into the local list. Remote rows are authoritative for their own id;
 * local-only drafts remain available when the Gateway is temporarily unavailable. A response that
 * is older than the local remote row is ignored so a slow poll cannot roll a task back.
 */
export function mergeWorkflowTasks(current: ClientTask[], records: WorkflowTaskRecord[]): ClientTask[] {
  const remote = records.map(fromWorkflowRecord);
  const byId = new Map(current.map((task) => [task.id, task]));
  for (const task of remote) {
    const previous = byId.get(task.id);
    if (previous && task.lastUpdated < previous.lastUpdated) continue;
    byId.set(task.id, task);
  }
  const remoteIds = new Set(remote.map((task) => task.id));
  return [
    ...remote.map((task) => byId.get(task.id)!),
    ...current.filter((task) => !remoteIds.has(task.id)),
  ];
}
