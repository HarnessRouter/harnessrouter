export interface AppAgent {
  id: string;
  name: string;
  base?: string;
  baseLabel?: string;
  default_model?: string;
  defaultModel?: string;
  system_prompt?: string;
  systemPrompt?: string;
  reasoningEffort?: string;
  skills?: unknown;
  mcpServers?: unknown;
  plugins?: unknown;
  disabledTools?: unknown;
  additionalHeaders?: unknown;
  env?: unknown;
  maxStep?: number | null;
  timeoutSeconds?: number | null;
  environment?: string;
  createdAt?: number;
  memory?: unknown;
  memory_reason?: string;
  member?: string;
  workspace?: string;
}

export interface AppConversation {
  id: number;
  title: string;
  previous_response_id: string | null;
  status?: string;
  agent_id?: string;
  model?: string;
}
export interface AppExecutionStep { id: string; name: string; status: string }
export interface AppMessageExecution { elapsed_ms?: number; started_at?: number; harness_id?: string; model?: string; reasoning?: string; steps?: AppExecutionStep[]; status?: string }
export interface AppMessage { id?: number; role: 'user' | 'assistant'; text: string; execution?: AppMessageExecution }
export interface AppConversationDetail extends AppConversation { messages: AppMessage[] }

export class AppApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'AppApiError';
    this.status = status;
    this.code = code;
  }
}

const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env || {};
const sessionExpiryListeners = new Set<() => void>();
export function onAppSessionExpired(listener: () => void): () => void {
  sessionExpiryListeners.add(listener);
  return () => { sessionExpiryListeners.delete(listener); };
}

function appUrl(path: string): string {
  const base = (env.VITE_HEXA_API_URL || '').replace(/\/$/, '');
  return `${base}${path}`;
}

async function appRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has('content-type')) headers.set('content-type', 'application/json');
  let response: Response;
  try { response = await fetch(appUrl(path), { ...init, headers, credentials: 'include' }); }
  catch (cause) {
    if ((cause as Error).name === 'AbortError') throw cause;
    throw new AppApiError('应用服务连接中断，请刷新会话确认状态。', 0);
  }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/api/hexa/auth/')) {
      for (const listener of sessionExpiryListeners) listener();
    }
    let detail = '';
    let code: string | undefined;
    try {
      const body = await response.json() as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
      else if (body.detail && typeof body.detail === 'object' && typeof (body.detail as { message?: unknown }).message === 'string') {
        detail = (body.detail as { message: string }).message;
        const value = (body.detail as { code?: unknown }).code;
        if (typeof value === 'string' && /^[a-z_]{1,80}$/.test(value)) code = value;
      }
    } catch { /* safe fallback below */ }
    throw new AppApiError(safeAppError(detail, `应用服务请求失败（${response.status}）。`), response.status, code);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function safeAppError(value: string, fallback: string): string {
  const text = value.trim();
  if (!text || text.length > 300 || /(?:api\s*key|authorization|bearer|token|password)\s*[:=]/i.test(text)) return fallback;
  return text;
}

export function appLogin(username: string, password: string): Promise<{ authenticated: true; username: string }> {
  return appRequest('/api/hexa/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
}

export function appSession(): Promise<{ authenticated: true; username: string }> {
  return appRequest('/api/hexa/auth/session');
}

export function appLogout(): Promise<{ authenticated: false }> {
  return appRequest('/api/hexa/auth/logout', { method: 'POST' });
}

export async function appListAgents(): Promise<AppAgent[]> {
  const data = await appRequest<{ agents?: AppAgent[] }>('/api/hexa/agents');
  return Array.isArray(data.agents) ? data.agents : [];
}

export function appListAgentModels(agentId: string): Promise<Record<string, unknown>> {
  return appRequest(`/api/hexa/agents/${encodeURIComponent(agentId)}/models`);
}

export type AppAgentInput = { name: string; base: string; default_model: string; system_prompt: string };
export type AppAgentTemplateInput = AppAgentInput & { description: string };
export type AppAgentTemplate = AppAgentTemplateInput & { id: number | string; source: 'gateway' | 'custom'; available: boolean };
export async function appListAgentTemplates(): Promise<AppAgentTemplate[]> {
  const data = await appRequest<{ templates?: AppAgentTemplate[] }>('/api/hexa/agent-templates');
  return Array.isArray(data.templates) ? data.templates : [];
}
export async function appListGatewayAgentTemplates(): Promise<AppAgentTemplate[]> {
  const data = await appRequest<{ templates?: AppAgentTemplate[] }>('/api/hexa/agent-templates/gateway');
  return Array.isArray(data.templates) ? data.templates : [];
}
export function appSaveAgentTemplate(input: AppAgentTemplateInput, id?: number): Promise<AppAgentTemplate> {
  return appRequest(`/api/hexa/agent-templates${id === undefined ? '' : `/${id}`}`, { method: id === undefined ? 'POST' : 'PUT', body: JSON.stringify(input) });
}
export function appDeleteAgentTemplate(id: number): Promise<void> {
  return appRequest(`/api/hexa/agent-templates/${id}`, { method: 'DELETE' });
}
export function appCreateAgent(input: AppAgentInput): Promise<AppAgent> {
  return appRequest('/api/hexa/agents', { method: 'POST', body: JSON.stringify(input) });
}
export function appDeleteAgent(id: string): Promise<void> {
  return appRequest(`/api/hexa/agents/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
export function appModelSelection(value: Record<string, unknown>, fixedModel = '') {
  const models = (Array.isArray(value.models) ? value.models : []).flatMap(row => {
    if (!row || typeof row !== 'object' || row.available === false || typeof row.id !== 'string' || !row.id) return [];
    return [{ id: row.id as string, label: typeof row.label === 'string' ? row.label : row.id as string }];
  });
  const preferred = typeof value.default === 'string' && models.some(row => row.id === value.default) ? value.default : models[0]?.id || '';
  return { models, model: fixedModel || preferred };
}

export function appListWorkspaces(): Promise<{ workspaces: Array<{ id: number; name: string; description: string }>; selected_id: number | null }> {
  return appRequest('/api/hexa/workspaces');
}

export function appCreateConversation(title: string, workspaceId?: number, agentId?: string, model?: string): Promise<AppConversationDetail> {
  return appRequest('/api/hexa/conversations', { method: 'POST', body: JSON.stringify({ title, ...(workspaceId === undefined ? {} : { workspace_id: workspaceId }), agent_id: agentId || '', model: model || '' }) });
}

export function appListConversations(): Promise<{ conversations: AppConversation[] }> {
  return appRequest('/api/hexa/conversations');
}

export function appGetConversation(id: number): Promise<AppConversationDetail> {
  return appRequest(`/api/hexa/conversations/${encodeURIComponent(String(id))}`);
}

export function appConversationStatus(id: number): Promise<{ conversation_id: number; status: string; response_id: string | null; error: string | null }> {
  return appRequest(`/api/hexa/conversations/${encodeURIComponent(String(id))}/status`);
}

export function appSendMessage(id: number, text: string, _previousResponseId: string | null, idempotencyKey: string, fileIds: number[] = []): Promise<{ response_id: string; status: string; assistant: AppMessage }> {
  return appRequest(`/api/hexa/conversations/${encodeURIComponent(String(id))}/messages`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ text, ...(fileIds.length ? { file_ids: fileIds } : {}) }) });
}

export interface AppFile { id: number; filename: string; bytes: number; media_type: string; direction?: 'input' | 'output' }
export function appUploadFile(file: File): Promise<AppFile> {
  if (file.size > 25 * 1024 * 1024) return Promise.reject(new AppApiError('文件超过 25 MiB 限制。', 413));
  const body = new FormData(); body.set('file', file);
  return appRequest('/api/hexa/files', { method: 'POST', body });
}
export function appDeleteFile(id: number) { return appRequest<void>(`/api/hexa/files/${id}`, { method: 'DELETE' }); }
export async function appConversationFiles(id: number): Promise<AppFile[]> {
  const data = await appRequest<{ files?: AppFile[] }>(`/api/hexa/conversations/${id}/files`);
  return Array.isArray(data.files) ? data.files : [];
}
export function appCancelConversation(id: number) { return appRequest<{ status: string }>(`/api/hexa/conversations/${id}/cancel`, { method: 'POST' }); }
export function appWatchConversation(id: number, onSnapshot: (value: { status: string; text: string; response_id: string | null; execution?: AppMessageExecution }) => void): () => void {
  const source = new EventSource(appUrl(`/api/hexa/conversations/${id}/events`), { withCredentials: true });
  source.onmessage = event => {
    try { const data = JSON.parse(event.data); onSnapshot(data); if (data.status !== 'running') source.close(); }
    catch { source.close(); }
  };
  source.onerror = () => source.close();
  return () => source.close();
}
export async function appFileBlob(id: number): Promise<Blob> {
  try {
    const response = await fetch(appUrl(`/api/hexa/files/${id}/content`), { credentials: 'include' });
    if (!response.ok) throw new AppApiError('文件下载失败，请重试。', response.status);
    return response.blob();
  } catch (cause) { if (cause instanceof AppApiError) throw cause; throw new AppApiError('文件下载连接中断。', 0); }
}

export function appCreateWorkspace(name: string, description: string) {
  return appRequest<{ id: number; name: string; description: string }>('/api/hexa/workspaces', { method: 'POST', body: JSON.stringify({ name, description }) });
}
export function appUpdateWorkspace(workspaceId: number, name: string, description: string) {
  return appRequest<{ id: number; name: string; description: string }>(`/api/hexa/workspaces/${encodeURIComponent(String(workspaceId))}`, { method: 'PATCH', body: JSON.stringify({ name, description }) });
}
export function appSelectWorkspace(workspaceId: number) {
  return appRequest('/api/hexa/workspaces/select', { method: 'POST', body: JSON.stringify({ workspace_id: workspaceId }) });
}

export interface AppTaskNode { id: string; name?: string; agent_id?: string; model?: string; prompt?: string; deps?: string[]; inputRefs?: string[]; final_report?: boolean; requires_human?: boolean; node_type?: 'agent' | 'human' | 'human_gate'; human_action?: 'select_outputs' | 'approve' | 'edit'; allow_skip?: boolean; x?: number; y?: number; [key: string]: unknown }
export interface AppPagination { offset: number; limit: number; has_more: boolean }
export interface AppTask { id: number; title: string; description: string; input?: string; workspace_id?: number | null; status: string; current_revision: number; current_revision_id?: number | null; workflow_state?: 'draft' | 'saved'; workflow_revision?: { id: number; revision: number; kind: 'saved' } | null; source_template?: { id: number; version_id: number; version: number } | null; workflow: { nodes: AppTaskNode[] } | null; current_result: Record<string, number>; stale_nodes?: string[]; latest_run_id?: number | null; source_template_id?: number | null; source_template_version_id?: number | null; source_template_version?: number | null }
export interface AppArtifact { id: number; task_id: number; run_id: number; node_run_id: number; filename: string; media_type: string; bytes: number; cleanup_status?: string; created_at?: string | null }
export interface AppNodeRun { id: number; node_id: string; run_id: number; attempt: number; status: string; input: Record<string, unknown>; output: Record<string, unknown> | null; error_code: string | null; response_id?: string | null; started_at?: string | null; finished_at?: string | null }
export interface AppRun { id: number; task_id: number; workflow_revision: number; workflow_revision_id?: number | null; workflow_revision_ref?: { id: number | null; revision: number } | null; status: string; paused?: boolean; kind: string; superseded_by?: number | null; execution_snapshot?: { workflow: { nodes: AppTaskNode[] }; workflow_revision_id?: number | null; source?: { kind: string; revision: number }; [key: string]: unknown }; workflow?: { nodes: AppTaskNode[] }; nodes: AppNodeRun[]; decisions?: Array<{ node_id: string; input_refs: string[] }> }

export interface AppTemplateVersion { id: number; version: number; workflow: { nodes: AppTaskNode[] } }
export interface AppTemplate { id: number; title: string; workspace_id?: number | null; versions: AppTemplateVersion[]; latest_version?: AppTemplateVersion | null; versions_pagination?: AppPagination }
export type AppPage = { offset?: number; limit?: number; q?: string; status?: string };
function pageQuery(options?: AppPage & { workspaceId?: number | null }) {
  if (!options) return '';
  const query = new URLSearchParams({ offset: String(options.offset ?? 0), limit: String(options.limit ?? 100) });
  if (options.workspaceId != null) query.set('workspace_id', String(options.workspaceId));
  if (options.q?.trim()) query.set('q', options.q.trim());
  if (options.status && options.status !== 'all') query.set('status', options.status);
  return `?${query}`;
}
export async function appListTasks(options?: AppPage & { workspaceId?: number | null }): Promise<AppTask[]> {
  const data = await appRequest<{ tasks?: AppTask[] }>(`/api/hexa/tasks${pageQuery(options)}`);
  return Array.isArray(data.tasks) ? data.tasks : [];
}
export async function appListTasksPage(options?: AppPage & { workspaceId?: number | null }): Promise<{ tasks: AppTask[]; pagination: AppPagination }> {
  const data = await appRequest<{ tasks?: AppTask[]; pagination?: AppPagination }>(`/api/hexa/tasks${pageQuery(options)}`);
  return { tasks: Array.isArray(data.tasks) ? data.tasks : [], pagination: data.pagination || { offset: options?.offset ?? 0, limit: options?.limit ?? 100, has_more: false } };
}
export function appCreateTask(input: { title: string; description?: string; input?: string; workspace_id?: number | null; workflow: { nodes: AppTaskNode[] }; template_version_id?: number }): Promise<AppTask> {
  return appRequest('/api/hexa/tasks', { method: 'POST', body: JSON.stringify(input) });
}
export function appSaveTaskInput(id: number, input: string, expectedInput: string): Promise<AppTask> {
  return appRequest(`/api/hexa/tasks/${id}/input`, { method: 'PUT', body: JSON.stringify({ input, expected_input: expectedInput }) });
}
export function appSaveTaskWorkflow(id: number, expectedRevision: number, workflow: { nodes: AppTaskNode[] }): Promise<AppTask> {
  return appRequest(`/api/hexa/tasks/${id}/workflow`, { method: 'PUT', body: JSON.stringify({ expected_revision: expectedRevision, workflow }) });
}
export function appGetTask(id: number): Promise<AppTask> { return appRequest(`/api/hexa/tasks/${id}`); }
export function appStartTaskRun(id: number, key: string = crypto.randomUUID(), body: { kind?: 'normal' | 'rerun'; target_node?: string; reuse_refs?: number[] } = {}): Promise<AppRun> {
  return appRequest(`/api/hexa/tasks/${id}/runs`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) });
}
export function appListTaskRuns(id: number, options?: AppPage): Promise<{ runs: AppRun[]; pagination?: AppPagination }> { return appRequest(`/api/hexa/tasks/${id}/runs${pageQuery(options)}`); }
export function appListRuns(options?: AppPage & { workspaceId?: number | null }): Promise<{ runs: Array<AppRun & { task_title?: string }>; pagination?: AppPagination }> { return appRequest(`/api/hexa/runs${pageQuery(options)}`); }
export function appListRunNodes(id: number, options?: AppPage): Promise<{ nodes: AppNodeRun[]; pagination: AppPagination }> { return appRequest(`/api/hexa/runs/${id}/nodes${pageQuery(options)}`); }
export function appGetRun(id: number): Promise<AppRun> { return appRequest(`/api/hexa/runs/${id}`); }
export function appControlRun(id: number, action: 'continue' | 'pause' | 'cancel', body: Record<string, unknown> = {}, key: string = crypto.randomUUID()): Promise<{ id: number; status: string; paused?: boolean }> {
  return appRequest(`/api/hexa/runs/${id}/${action}`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) });
}
export function appContinueRun(id: number, nodeId: string, inputRefs: string[], key: string = crypto.randomUUID()): Promise<{ id: number; status: string }> {
  return appControlRun(id, 'continue', { node_id: nodeId, input_refs: inputRefs }, key);
}
export function appRetryNode(runId: number, nodeId: string, key: string = crypto.randomUUID()) { return appRequest<{ id: number; status: string }>(`/api/hexa/runs/${runId}/nodes/${encodeURIComponent(nodeId)}/retry`, { method: 'POST', headers: { 'Idempotency-Key': key } }); }
export function appSkipNode(runId: number, nodeId: string, key: string = crypto.randomUUID()) { return appRequest<{ id: number; status: string }>(`/api/hexa/runs/${runId}/nodes/${encodeURIComponent(nodeId)}/skip`, { method: 'POST', headers: { 'Idempotency-Key': key } }); }
export function appDebugNode(attemptId: number, options?: AppPage): Promise<AppNodeRun & { environment: Record<string, unknown>; attempts: AppNodeRun[]; attempts_pagination?: AppPagination; artifacts?: AppArtifact[] }> { return appRequest(`/api/hexa/node-runs/${attemptId}${pageQuery(options)}`); }
export function appListTaskArtifacts(taskId: number, options?: AppPage): Promise<{ artifacts: AppArtifact[]; pagination: AppPagination }> { return appRequest(`/api/hexa/tasks/${taskId}/artifacts${pageQuery(options)}`); }
export function appListRunArtifacts(runId: number, options?: AppPage): Promise<{ artifacts: AppArtifact[]; pagination: AppPagination }> { return appRequest(`/api/hexa/runs/${runId}/artifacts${pageQuery(options)}`); }
export function appListNodeArtifacts(nodeRunId: number, options?: AppPage): Promise<{ artifacts: AppArtifact[]; pagination: AppPagination }> { return appRequest(`/api/hexa/node-runs/${nodeRunId}/artifacts${pageQuery(options)}`); }
export function appGetArtifact(id: number): Promise<AppArtifact> { return appRequest(`/api/hexa/artifacts/${id}`); }
export async function appArtifactBlob(id: number): Promise<Blob> {
  const response = await fetch(appUrl(`/api/hexa/artifacts/${id}/content`), { credentials: 'include' });
  if (!response.ok) throw new AppApiError('产物下载失败，请重试。', response.status);
  return response.blob();
}
export function appAdoptNode(taskId: number, nodeId: string, nodeRunId: number, key: string = crypto.randomUUID()) { return appRequest<{ current_result: Record<string, number> }>(`/api/hexa/tasks/${taskId}/nodes/${encodeURIComponent(nodeId)}/adopt`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ node_run_id: nodeRunId }) }); }
export function appSaveTaskAsTemplate(taskId: number, input?: { workflow_revision: number; template_id?: number }): Promise<AppTemplate> { return appRequest(`/api/hexa/tasks/${taskId}/save-as-template`, { method: 'POST', body: JSON.stringify(input || {}) }); }
export function appListTemplates(options?: AppPage & { workspaceId?: number | null }): Promise<{ templates: AppTemplate[]; pagination?: AppPagination }> { return appRequest(`/api/hexa/templates${pageQuery(options)}`); }
export function appGetTemplate(id: number, options?: { versionsOffset?: number; versionsLimit?: number }): Promise<AppTemplate> {
  const query = new URLSearchParams({ versions_offset: String(options?.versionsOffset ?? 0), versions_limit: String(options?.versionsLimit ?? 100) });
  return appRequest(`/api/hexa/templates/${id}?${query}`);
}
export function appSaveTemplate(input: { title: string; workspace_id?: number | null; workflow: { nodes: AppTaskNode[] }; expected_revision?: number }, id?: number): Promise<AppTemplate> {
  return appRequest(id === undefined ? '/api/hexa/templates' : `/api/hexa/templates/${id}/versions`, { method: 'POST', body: JSON.stringify(input) });
}
export function appTaskState(id: number, action: 'reopen' | 'finish' | 'archive' | 'unarchive'): Promise<AppTask> { return appRequest(`/api/hexa/tasks/${id}/state`, { method: 'POST', body: JSON.stringify({ action }) }); }
export function appCreateTaskFromTemplate(input: { title: string; description?: string; input?: string; workspace_id?: number | null; template_version_id: number }): Promise<AppTask> { return appCreateTask({ ...input, workflow: { nodes: [] } }); }
export function appWatchTaskRun(id: number, onSnapshot: (run: AppRun) => void, onError?: () => void): () => void {
  const source = new EventSource(appUrl(`/api/hexa/runs/${id}/events`), { withCredentials: true });
  source.onmessage = event => { try { const run = JSON.parse(event.data) as AppRun; onSnapshot(run); if (!['pending', 'running'].includes(run.status) || run.paused) source.close(); } catch { source.close(); onError?.(); } };
  source.onerror = () => { source.close(); onError?.(); };
  return () => source.close();
}
