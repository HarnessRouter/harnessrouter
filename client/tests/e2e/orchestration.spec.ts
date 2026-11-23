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
