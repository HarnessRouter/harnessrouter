import test from 'node:test';
import assert from 'node:assert/strict';
import { appConversationStatus, appCreateConversation, appCreateTask, appGetRun, appListAgents, appLogin, appSendMessage, appStartTaskRun, AppApiError } from '../src/app-api.ts';

test('conversation watch waits for new execution and reconnects without dropping progress', async () => {
  const { appWatchConversation } = await import('../src/app-api.ts');
  const previous = globalThis.EventSource;
  let source;
  globalThis.EventSource = class {
    closed = false;
    constructor() { source = this; }
    close() { this.closed = true; }
  };
  try {
    const seen = [];
    const stop = appWatchConversation(1, value => seen.push(value), { waitForStart: true });
    source.onmessage({ data: JSON.stringify({ status: 'completed', response_id: 'old', text: 'old' }) });
    assert.equal(source.closed, false);
    assert.equal(seen.length, 0);
    source.onmessage({ data: JSON.stringify({ status: 'running', response_id: 'new', text: 'partial' }) });
    source.onerror?.({});
    assert.equal(source.closed, false);
    source.onmessage({ data: JSON.stringify({ status: 'completed', response_id: 'new', text: 'done' }) });
    assert.equal(source.closed, true);
    assert.deepEqual(seen.map(value => value.text), ['partial', 'done']);
    stop();
  } finally { globalThis.EventSource = previous; }
});

test('Agent template APIs use session transport and keep workflow templates separate', async () => {
  const api = await import('../src/app-api.ts');
  const original = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url, init) => { seen.push({ url, init }); return init.method === 'DELETE' ? new Response(null, { status: 204 }) : Response.json({ templates: [] }); };
  try {
    await api.appListAgentTemplates();
    await api.appListGatewayAgentTemplates();
    const body = { name: '模板', description: '', base: 'codex', default_model: 'm1', system_prompt: '严谨' };
    await api.appSaveAgentTemplate(body);
    await api.appSaveAgentTemplate(body, 7);
    await api.appDeleteAgentTemplate(7);
    assert.deepEqual(seen.map(row => [row.url, row.init.method || 'GET']), [
      ['/api/hexa/agent-templates', 'GET'], ['/api/hexa/agent-templates/gateway', 'GET'],
      ['/api/hexa/agent-templates', 'POST'], ['/api/hexa/agent-templates/7', 'PUT'], ['/api/hexa/agent-templates/7', 'DELETE'],
    ]);
    assert.deepEqual(JSON.parse(seen[2].init.body), body);
    assert.ok(seen.every(row => row.init.credentials === 'include' && !row.init.headers.has('authorization')));
  } finally { globalThis.fetch = original; }
});

function withFetch(handler) {
  const previous = globalThis.fetch;
  globalThis.fetch = handler;
  return () => { globalThis.fetch = previous; };
}

test('app API login uses HttpOnly-cookie compatible credentials and never sends an Authorization header', async () => {
  let request;
  const restore = withFetch(async (input, init) => {
    request = { input, init };
    return Response.json({ authenticated: true, username: 'admin' });
  });
  try { assert.deepEqual(await appLogin('admin', 'correct-password'), { authenticated: true, username: 'admin' }); }
  finally { restore(); }
  assert.equal(request.input, '/api/hexa/auth/login');
  assert.equal(request.init.credentials, 'include');
  assert.equal(request.init.headers.get('content-type'), 'application/json');
  assert.equal(request.init.headers.has('authorization'), false);
});

test('app API agent and message calls encode IDs and preserve idempotency', async () => {
  const seen = [];
  const restore = withFetch(async (input, init) => {
    seen.push({ input, init });
    if (input.endsWith('/agents')) return Response.json({ agents: [{ id: 'agent-1', name: '分析师' }] });
    if (input.endsWith('/conversations')) return Response.json({ id: 7, title: '对话', previous_response_id: null, messages: [] });
    return Response.json({ accepted: true });
  });
  try {
    assert.deepEqual(await appListAgents(), [{ id: 'agent-1', name: '分析师' }]);
    await appCreateConversation('对话');
    await appSendMessage(7, '继续', 'resp-1', 'hexa-message-1');
  } finally { restore(); }
  assert.equal(seen[0].init.credentials, 'include');
  assert.equal(seen[2].input, '/api/hexa/conversations/7/messages');
  assert.equal(seen[2].init.headers.get('Idempotency-Key'), 'hexa-message-1');
  assert.equal(JSON.parse(seen[2].init.body).previous_response_id, undefined);
});

test('app API errors remain readable and do not echo sensitive upstream text', async () => {
  const restore = withFetch(async () => Response.json({ detail: 'Gateway API Key: secret' }, { status: 502 }));
  try {
    await assert.rejects(() => appConversationStatus(7), error => {
      assert.equal(error instanceof AppApiError, true);
      assert.equal(error.status, 502);
      assert.equal(error.message, '应用服务请求失败（502）。');
      return true;
    });
  } finally { restore(); }
});

test('protected 401 expires the session while login failures and logout failures do not', async () => {
  const { onAppSessionExpired, appLogout } = await import('../src/app-api.ts');
  let expiries = 0;
  const unsubscribe = onAppSessionExpired(() => { expiries++; });
  const restore = withFetch(async input => Response.json({ detail: '需要登录。' }, { status: input.endsWith('/logout') ? 503 : 401 }));
  try {
    await assert.rejects(() => appLogin('admin', 'wrong-password'), { status: 401 });
    await assert.rejects(() => appLogout(), { status: 503 });
    assert.equal(expiries, 0);
    await assert.rejects(() => appListAgents(), { status: 401 });
    assert.equal(expiries, 1);
    unsubscribe();
    await assert.rejects(() => appListAgents(), { status: 401 });
    assert.equal(expiries, 1);
  } finally { unsubscribe(); restore(); }
});

test('app task API uses cookie credentials and idempotent run requests', async () => {
  const seen = [];
  const restore = withFetch(async (input, init) => {
    seen.push({ input, init });
    if (input.endsWith('/tasks')) return Response.json({ id: 7, title: '调查', current_revision: 1, status: 'draft', workflow: { nodes: [] }, current_result: {} }, { status: 201 });
    if (input.endsWith('/runs')) return Response.json({ id: 9, task_id: 7, status: 'pending', nodes: [] }, { status: 202 });
    return Response.json({ id: 9, task_id: 7, status: 'completed', nodes: [] });
  });
  try {
    const task = await appCreateTask({ title: '调查', workflow: { nodes: [] } });
    assert.equal(task.id, 7);
    await appStartTaskRun(7, 'run-key');
    await appGetRun(9);
  } finally { restore(); }
  assert.equal(seen[0].input, '/api/hexa/tasks');
  assert.equal(seen[1].init.headers.get('Idempotency-Key'), 'run-key');
  for (const row of seen) assert.equal(row.init.credentials, 'include');
});

test('app Agent mutations use Cookie credentials, encode IDs and propagate safe failures', async () => {
  const api = await import('../src/app-api.ts');
  assert.equal(typeof api.appCreateAgent, 'function');
  assert.equal(typeof api.appDeleteAgent, 'function');
  const seen = [];
  const restore = withFetch(async (input, init) => {
    seen.push({ input, init });
    if (init.method === 'POST') return Response.json({ id: 'new-agent', name: '分析师' });
    if (seen.length === 2) return new Response(null, { status: 204 });
    return Response.json({ detail: 'Agent 删除失败。' }, { status: 502 });
  });
  try {
    const body = { name: '分析师', base: 'openai', default_model: 'model-a', system_prompt: '分析任务' };
    assert.equal((await api.appCreateAgent(body)).id, 'new-agent');
    assert.deepEqual(JSON.parse(seen[0].init.body), body);
    await api.appDeleteAgent('agent /?#');
    assert.equal(seen[1].input, '/api/hexa/agents/agent%20%2F%3F%23');
    await assert.rejects(() => api.appDeleteAgent('new-agent'), { message: 'Agent 删除失败。', status: 502 });
    for (const row of seen) {
      assert.equal(row.init.credentials, 'include');
      assert.equal(row.init.headers.has('authorization'), false);
    }
  } finally { restore(); }
});

test('app workspace update uses PATCH, cookie credentials and an encoded local id', async () => {
  const api = await import('../src/app-api.ts');
  let seen;
  const restore = withFetch(async (input, init) => {
    seen = { input, init };
    return Response.json({ id: 7, name: '研究空间', description: '论文与实验' });
  });
  try {
    const updated = await api.appUpdateWorkspace(7, '研究空间', '论文与实验');
    assert.equal(updated.name, '研究空间');
  } finally { restore(); }
  assert.equal(seen.input, '/api/hexa/workspaces/7');
  assert.equal(seen.init.method, 'PATCH');
  assert.equal(seen.init.credentials, 'include');
  assert.equal(seen.init.headers.get('content-type'), 'application/json');
  assert.deepEqual(JSON.parse(seen.init.body), { name: '研究空间', description: '论文与实验' });
});

test('Agent model catalog excludes unavailable models and preserves only fixed conversation models', async () => {
  const api = await import('../src/app-api.ts');
  assert.equal(typeof api.appModelSelection, 'function');
  const catalog = { default: 'disabled', models: [{ id: 'disabled', available: false }, { id: 'new', label: '新模型' }, { label: '无效' }] };
  assert.deepEqual(api.appModelSelection(catalog), { models: [{ id: 'new', label: '新模型' }], model: 'new' });
  assert.equal(api.appModelSelection(catalog, 'old-fixed').model, 'old-fixed');
  assert.deepEqual(api.appModelSelection({ models: [] }), { models: [], model: '' });
});

test('task lists page explicitly within the selected workspace and template saves select a revision', async () => {
  const api = await import('../src/app-api.ts');
  const seen = [];
  const restore = withFetch(async (input, init) => { seen.push({ input, init }); return Response.json({ tasks: [], runs: [], templates: [] }); });
  try {
    await api.appListTasks({ workspaceId: 7, offset: 100, limit: 100 });
    await api.appListTaskRuns(9, { offset: 30, limit: 30 });
    await api.appSaveTaskAsTemplate(9, { workflow_revision: 3, template_id: 4 });
  } finally { restore(); }
  assert.equal(seen[0].input, '/api/hexa/tasks?offset=100&limit=100&workspace_id=7');
  assert.equal(seen[1].input, '/api/hexa/tasks/9/runs?offset=30&limit=30');
  assert.deepEqual(JSON.parse(seen[2].init.body), { workflow_revision: 3, template_id: 4 });
});

test('structured task errors preserve their code and safe message', async () => {
  const api = await import('../src/app-api.ts');
  const restore = withFetch(async () => Response.json({ detail: { code: 'revision_conflict', message: '工作流版本已变化。' } }, { status: 409 }));
  try { await assert.rejects(() => api.appSaveTaskWorkflow(1, 1, { nodes: [] }), { code: 'revision_conflict', status: 409, message: '工作流版本已变化。' }); }
  finally { restore(); }
});

test('workbench search and every detail page retain server cursors and cookie authorization', async () => {
  const api = await import('../src/app-api.ts');
  const seen = [];
  const restore = withFetch(async (input, init) => {
    seen.push({ input, init });
    return Response.json({ tasks: [], runs: [], artifacts: [], versions: [], pagination: { offset: 50, limit: 50, has_more: true } });
  });
  try {
    await api.appListTasksPage({ workspaceId: 7, offset: 20, limit: 20, q: ' %_调查 ', status: 'failed' });
    await api.appListRuns({ workspaceId: 7, offset: 20, limit: 20, q: '调查', status: 'all' });
    await api.appListTaskArtifacts(1, { offset: 50, limit: 50 });
    await api.appListRunArtifacts(2, { offset: 50, limit: 50 });
    await api.appListNodeArtifacts(3, { offset: 50, limit: 50 });
    await api.appDebugNode(3, { offset: 50, limit: 50 });
    await api.appGetTemplate(4, { versionsOffset: 20, versionsLimit: 20 });
  } finally { restore(); }
  const taskQuery = new URL(seen[0].input, 'http://localhost').searchParams;
  assert.equal(taskQuery.get('q'), '%_调查');
  assert.equal(taskQuery.get('status'), 'failed');
  assert.equal(taskQuery.get('workspace_id'), '7');
  assert.equal(new URL(seen[1].input, 'http://localhost').searchParams.has('status'), false);
  assert.deepEqual(seen.slice(2).map(row => row.input), [
    '/api/hexa/tasks/1/artifacts?offset=50&limit=50', '/api/hexa/runs/2/artifacts?offset=50&limit=50',
    '/api/hexa/node-runs/3/artifacts?offset=50&limit=50', '/api/hexa/node-runs/3?offset=50&limit=50',
    '/api/hexa/templates/4?versions_offset=20&versions_limit=20',
  ]);
  for (const { init } of seen) {
    assert.equal(init.credentials, 'include');
    assert.equal(init.headers.has('authorization'), false);
  }
});

test('item history requests a fixed anchor and retains server pagination', async () => {
  const api = await import('../src/app-api.ts');
  const seen = [];
  const restore = withFetch(async (input, init) => {
    seen.push({ input, init });
    return Response.json({ anchor_node_run_id: 19, items: [], pagination: { offset: 50, limit: 50, has_more: false } });
  });
  try {
    const result = await api.appListNodeItems(19, { offset: 50, limit: 50 });
    assert.equal(result.anchor_node_run_id, 19);
    assert.equal(result.pagination.offset, 50);
  } finally { restore(); }
  assert.equal(seen[0].input, '/api/hexa/node-runs/19/items?offset=50&limit=50');
  assert.equal(seen[0].init.credentials, 'include');
  assert.equal(seen[0].init.method || 'GET', 'GET');
});

test('reconciliation posts only the node attempt and preserves idempotency', async () => {
  const api = await import('../src/app-api.ts');
  let seen;
  const restore = withFetch(async (input, init) => {
    seen = { input, init };
    return Response.json({ id: 4, node_run_id: 19, command_id: 'command-19', request_hash: 'a'.repeat(64), side_effect_state: 'unknown', reconciliation_required: true, response_id: 'response-19' }, { status: 202 });
  });
  try {
    const result = await api.appReconcileNode(7, 19, 'reconcile-key');
    assert.equal(result.node_run_id, 19);
  } finally { restore(); }
  assert.equal(seen.input, '/api/hexa/runs/7/nodes/19/reconcile');
  assert.equal(seen.init.method, 'POST');
  assert.equal(seen.init.headers.get('idempotency-key'), 'reconcile-key');
  assert.equal(seen.init.credentials, 'include');
});
