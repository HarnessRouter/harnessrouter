import test from 'node:test';
import assert from 'node:assert/strict';
import { appConversationStatus, appCreateConversation, appCreateTask, appGetRun, appListAgents, appLogin, appSendMessage, appStartTaskRun, AppApiError } from '../src/app-api.ts';

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

test('Agent model catalog excludes unavailable models and preserves only fixed conversation models', async () => {
  const api = await import('../src/app-api.ts');
  assert.equal(typeof api.appModelSelection, 'function');
  const catalog = { default: 'disabled', models: [{ id: 'disabled', available: false }, { id: 'new', label: '新模型' }, { label: '无效' }] };
  assert.deepEqual(api.appModelSelection(catalog), { models: [{ id: 'new', label: '新模型' }], model: 'new' });
  assert.equal(api.appModelSelection(catalog, 'old-fixed').model, 'old-fixed');
  assert.deepEqual(api.appModelSelection({ models: [] }), { models: [], model: '' });
});
