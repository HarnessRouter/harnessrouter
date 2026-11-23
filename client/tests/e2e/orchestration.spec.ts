import { test, expect } from '@playwright/test';
import { api, newTask, openTasks, saveWorkflow, signIn } from './helpers';

test('orchestration settings persist through the editor, execution and historical reload', async ({ page }) => {
  await signIn(page); await openTasks(page);
  await newTask(page, { title: `编排配置-${Date.now()}` });
  await saveWorkflow(page, { nodes: [
    { id: 'node-1', name: '来源', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:来源结果' },
    { id: 'node-2', name: '逐项处理', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:处理结果', deps: ['node-1'], inputRefs: ['node-1'], final_report: true },
  ] });
  const taskDetail = page.getByRole('complementary', { name: '任务详情', exact: true });
  await taskDetail.getByRole('button', { name: '编辑流程', exact: true }).click();
  await page.getByLabel('最大并发数').fill('2');
  await page.getByRole('group', { name: '节点 逐项处理', exact: true }).click();
  await page.getByLabel('条件分支', { exact: true }).check();
  await page.getByLabel('条件路径').fill('status');
  await page.getByLabel('条件值').fill('completed');
  await page.getByLabel('执行模式').selectOption('repeat');
  await page.getByLabel('重复终止路径').fill('status');
  await page.getByLabel('重复终止值').fill('completed');
  const savedRepeat = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith('/workflow'));
  await page.getByRole('button', { name: '保存任务流程' }).click();
  const repeatTask = await (await savedRepeat).json();
  expect(repeatTask.workflow.max_concurrency).toBe(2);
  expect(repeatTask.workflow.nodes[1].repeat.until.value).toBe('completed');
  await taskDetail.getByRole('button', { name: '编辑流程', exact: true }).click();
  await page.getByRole('group', { name: '节点 逐项处理', exact: true }).click();
  await expect(page.getByLabel('最大并发数')).toHaveValue('2');
  await page.getByLabel('执行模式').selectOption('foreach');
  // The HTTP fixture returns one file citation; the app exposes its protected Artifact metadata.
  await page.getByLabel('集合路径').fill('artifacts');
  await page.getByLabel('集合上限').fill('3');
  await page.getByRole('button', { name: '保存任务流程' }).click();
  await expect(taskDetail).toContainText('当前工作流 · v4');
  const started = await page.evaluate(async ({ taskId, key }) => {
    const response = await fetch(`/api/hexa/tasks/${taskId}/runs`, { method: 'POST', headers: { 'Idempotency-Key': key, 'content-type': 'application/json' }, body: '{}' });
    return { status: response.status, body: await response.json() };
  }, { taskId: repeatTask.id, key: crypto.randomUUID() });
  expect(started.status).toBe(202);
  let run: any;
  await expect.poll(async () => {
    run = (await api(page, `/api/hexa/runs/${started.body.id}`)).body;
    return run.status;
  }, { timeout: 30000 }).toBe('completed');
  const worker = run.nodes.find((node: any) => node.node_id === repeatTask.workflow.nodes[1].id);
  expect(worker.output.items).toHaveLength(1);
  const workerHistory = await api(page, `/api/hexa/node-runs/${worker.id}`);
  const itemAttempt = workerHistory.body.attempts.find((attempt: any) => attempt.execution_kind === 'foreach_item');
  expect(itemAttempt.foreach_index).toBe(0);
  await page.goto(`/runs/${run.id}`);
  await page.getByRole('button', { name: '打开流程图', exact: true }).click();
  await page.getByRole('button', { name: '逐项处理 节点', exact: true }).click();
  const properties = page.getByRole('region', { name: '编排运行配置' });
  await expect(properties).toContainText('最大并发数：2');
  await expect(properties).toContainText('串行集合展开');
  await expect(properties).toContainText('已聚合 1 个集合项');
});

test('nested collection executes and resumes through the browser with immutable old history', async ({ page }) => {
  await signIn(page);
  const identity = `nested-${Date.now()}`;
  const spaces = await api(page, '/api/hexa/workspaces');
  const created = await api(page, '/api/hexa/tasks', { method: 'POST', body: {
    title: identity, workspace_id: spaces.body.selected_id, input: 'nested lifecycle', workflow: { max_concurrency: 2, nodes: [
      { id: 'source', name: '来源', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:来源' },
      { id: 'prep', name: '分组', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:分组', deps: ['source'], inputRefs: ['source'], foreach: { source: 'source', path: 'artifacts', max_items: 1 } },
      { id: 'worker', name: '二层处理', agent_id: 'e2e-agent', model: 'e2e-model', prompt: `E2E_FAIL:${identity}`, deps: ['prep'], inputRefs: ['prep'], foreach: { source: 'prep', path: 'items', max_items: 1, nested: { path: 'artifacts', max_items: 1, mode: 'serial' } }, final_report: true },
    ] },
  } });
  expect(created.status).toBe(201);
  const started = await page.evaluate(async taskId => {
    const response = await fetch(`/api/hexa/tasks/${taskId}/runs`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } });
    return { status: response.status, body: await response.json() };
  }, created.body.id);
  expect(started.status).toBe(202);
  let failed: any;
  await expect.poll(async () => {
    failed = (await api(page, `/api/hexa/runs/${started.body.id}`)).body;
    return failed.status;
  }, { timeout: 30000 }).toBe('failed');
  const oldWorker = failed.nodes.find((row: any) => row.node_id === 'worker');
  const before = await api(page, `/api/hexa/node-runs/${oldWorker.id}`);
  await page.goto(`/runs/${started.body.id}`);
  await page.getByRole('button', { name: '打开流程图', exact: true }).click();
  await page.getByRole('button', { name: '二层处理 节点', exact: true }).click();
  await expect(page.getByRole('region', { name: '编排运行配置' })).toContainText('二层 artifacts');
  await page.getByRole('tab', { name: '调试' }).click();
  await expect(page.getByRole('region', { name: '集合项历史' })).toContainText('外层项 1 / 内层项 1');
  const resumed = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`/tasks/${created.body.id}/runs`));
  await page.getByRole('button', { name: '新建 Run 恢复此项' }).click();
  const newRun = await (await resumed).json();
  expect(newRun.id).not.toBe(started.body.id);
  let completed: any;
  await expect.poll(async () => {
    completed = (await api(page, `/api/hexa/runs/${newRun.id}`)).body;
    return completed.status;
  }, { timeout: 30000 }).toBe('completed');
  const worker = completed.nodes.find((row: any) => row.node_id === 'worker');
  expect(worker.output.items[0].items).toHaveLength(1);
  expect((await api(page, `/api/hexa/node-runs/${oldWorker.id}`)).body.attempts).toEqual(before.body.attempts);
  await page.goto(`/runs/${newRun.id}`);
  await page.reload();
  await page.getByRole('button', { name: '打开流程图', exact: true }).click();
  await page.getByRole('button', { name: '二层处理 节点', exact: true }).click();
  await page.getByRole('tab', { name: '调试' }).click();
  await expect(page.getByRole('region', { name: '集合项历史' })).toContainText('外层项 1 / 内层项 1');
  await expect(page.getByRole('button', { name: '新建 Run 恢复此项' })).toHaveCount(0);
});

test('dynamic DAG reads a JSON text plan through HTTP and preserves local result references', async ({ page }) => {
  await signIn(page);
  const spaces = await api(page, '/api/hexa/workspaces');
  const created = await api(page, '/api/hexa/tasks', { method: 'POST', body: {
    title: `DAG-${Date.now()}`, workspace_id: spaces.body.selected_id, workflow: { max_concurrency: 2, nodes: [
      { id: 'planner', name: '计划', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_DAG_PLAN' },
      { id: 'worker', name: '动态子图', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:子节点', deps: ['planner'], inputRefs: ['planner'], dynamic_plan: { source: 'planner', path: 'text', max_items: 3, topology: 'dag', mode: 'parallel' }, final_report: true },
    ] },
  } });
  expect(created.status).toBe(201);
  const started = await page.evaluate(async taskId => {
    const response = await fetch(`/api/hexa/tasks/${taskId}/runs`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } });
    return { status: response.status, body: await response.json() };
  }, created.body.id);
  expect(started.status).toBe(202);
  let result: any;
  await expect.poll(async () => {
    result = (await api(page, `/api/hexa/runs/${started.body.id}`)).body;
    return result.status;
  }, { timeout: 30000 }).toBe('completed');
  const worker = result.nodes.find((row: any) => row.node_id === 'worker');
  expect(worker.output.items.map((row: any) => row.id)).toEqual(['join', 'a', 'b']);
  const history = (await api(page, `/api/hexa/node-runs/${worker.id}/items`)).body.items;
  const join = history.find((row: any) => row.input.dynamic_item.id === 'join');
  expect(join.input.plan_refs.map((ref: any) => ref.id)).toEqual(['a', 'b']);
  expect(history.every((row: any) => row.run_id === result.id)).toBe(true);
  await page.goto(`/runs/${result.id}`);
  await page.getByRole('button', { name: '打开流程图', exact: true }).click();
  await page.getByRole('button', { name: '动态子图 节点', exact: true }).click();
  await expect(page.getByRole('region', { name: '编排运行配置' })).toContainText('DAG 子图');
  await page.getByRole('tab', { name: '调试' }).click();
  const items = page.getByRole('region', { name: '集合项历史' });
  await expect(items.getByRole('listitem')).toHaveCount(3);
});
