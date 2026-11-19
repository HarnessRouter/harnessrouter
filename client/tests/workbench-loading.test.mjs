import test from 'node:test';
import assert from 'node:assert/strict';
import { loadWorkbenchLists } from '../src/workbench-loading.ts';
import { appListRuns, appListTasksPage, appListTemplates } from '../src/app-api.ts';

test('unavailable auxiliary lists retain the successful task page and identify the failed list', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async url => url.includes('/tasks?')
    ? Response.json({ tasks: [{ id: 8, title: 'existing' }], pagination: { offset: 0, limit: 20, has_more: true } })
    : Response.json({ detail: 'Not Found' }, { status: 404 });
  try {
    const result = await loadWorkbenchLists({
      tasks: appListTasksPage({ offset: 0, limit: 20, workspaceId: 1 }),
      templates: appListTemplates({ offset: 0, limit: 20, workspaceId: 1 }),
      runs: appListRuns({ offset: 0, limit: 20, workspaceId: 1 }),
    });
    assert.equal(result.tasks.tasks[0].id, 8);
    assert.equal(result.tasks.pagination.has_more, true);
    assert.equal(result.runs, undefined);
    assert.equal(result.templates, undefined);
    assert.deepEqual(result.failures.map(failure => failure.section).sort(), ['runs', 'templates']);
    assert.ok(result.failures.every(failure => failure.message.includes('接口不可用')));
  } finally { globalThis.fetch = original; }
});

test('session expiry is never converted to an empty workbench list', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ detail: '需要先登录。' }, { status: 401 });
  try { await assert.rejects(loadWorkbenchLists({ tasks: appListTasksPage({ limit: 20 }), templates: appListTemplates({ limit: 20 }), runs: appListRuns({ limit: 20 }) }), error => error.status === 401); }
  finally { globalThis.fetch = original; }
});

test('list failure preserves the safe service explanation with list context', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async url => url.includes('/tasks?')
    ? Response.json({ detail: '任务服务暂时不可用。' }, { status: 503 })
    : Response.json({ templates: [], runs: [], pagination: { offset: 0, limit: 20, has_more: false } });
  try {
    const result = await loadWorkbenchLists({ tasks: appListTasksPage({ limit: 20 }), templates: appListTemplates({ limit: 20 }), runs: appListRuns({ limit: 20 }) });
    assert.equal(result.tasks, undefined);
    assert.equal(result.failures[0].section, 'tasks');
    assert.match(result.failures[0].message, /任务列表/);
    assert.match(result.failures[0].message, /任务服务暂时不可用/);
  } finally { globalThis.fetch = original; }
});
