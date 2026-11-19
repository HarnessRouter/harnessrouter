import { test, expect } from '@playwright/test';
import { api, newTask, openTasks, openTasks as enterTasks, saveWorkflow, signIn } from './helpers';

test('archiving and unarchiving a completed task keeps its run history readable', async ({ page }) => {
  await signIn(page);
  await openTasks(page);
  const title = `E2E 归档 ${Date.now()}`;
  const detail = await newTask(page, { title, taskInput: 'E2E_OUT:归档前输出' });
  await saveWorkflow(page, { nodes: [{ id: 'node-1', name: '归档节点', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:归档前输出', final_report: true }] });
  await detail.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const run = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(run.locator('.run-detail-head')).toContainText('已完成', { timeout: 40000 });
  await run.getByRole('button', { name: '返回所属任务', exact: true }).click();
  await expect(detail).toContainText('已完成');

  await detail.getByRole('button', { name: '归档任务', exact: true }).click();
  await expect(detail).toContainText('已归档');
  await expect(detail.getByRole('button', { name: '运行', exact: true })).toBeDisabled();
  const archived = await api(page, '/api/hexa/tasks?offset=0&limit=100');
  expect(archived.body.tasks.find((row: { title: string }) => row.title === title).status).toBe('archived');
  await page.getByRole('group', { name: '任务状态筛选' }).getByRole('button', { name: /^已归档/ }).click();
  await expect(page.getByRole('row', { name: new RegExp(title) })).toBeVisible();
  await page.getByRole('group', { name: '任务状态筛选' }).getByRole('button', { name: /^全部/ }).click();

  await detail.getByRole('button', { name: '取消归档', exact: true }).click();
  await expect(detail).toContainText('已完成');
  await expect(detail.getByRole('button', { name: '运行', exact: true })).toBeDisabled();
  const reopened = await api(page, '/api/hexa/tasks?offset=0&limit=100');
  expect(reopened.body.tasks.find((row: { title: string }) => row.title === title).status).toBe('completed');
  await expect(detail.getByRole('button', { name: '查看运行记录', exact: true })).toBeEnabled();
});

test('a failed node can start a rerun Run from the run graph and history keeps both runs', async ({ page }) => {
  await signIn(page);
  await openTasks(page);
  const title = `E2E 节点重跑 ${Date.now()}`;
  const detail = await newTask(page, { title, taskInput: 'E2E_OUT:重跑前输出' });
  const scope = `node-rerun-${Date.now()}`;
  await saveWorkflow(page, {
    nodes: [
      { id: 'node-1', name: '前置节点', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:前置结果' },
      { id: 'node-2', name: '易失败节点', agent_id: 'e2e-agent', model: 'e2e-model', prompt: `E2E_FAIL:${scope} E2E_OUT:重跑结果`, deps: ['node-1'], inputRefs: ['node-1'], final_report: true },
    ],
  });
  await detail.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const failedRun = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(failedRun.locator('.run-detail-head')).toContainText('失败', { timeout: 40000 });
  const failedId = Number((await failedRun.locator('.run-detail-head').textContent())?.match(/Run #(\d+)/)?.[1]);

  await failedRun.getByRole('button', { name: '打开流程图', exact: true }).click();
  const graph = page.getByRole('main', { name: '运行流程图' });
  await graph.getByRole('button', { name: '易失败节点 节点', exact: true }).click();
  await page.getByRole('tab', { name: '调试', exact: true }).click();
  const properties = page.getByRole('complementary', { name: '运行属性', exact: true });
  await expect(properties).toContainText('agent_failed');
  await properties.getByRole('button', { name: '新建重跑 Run', exact: true }).click();
  await expect(page.getByRole('main', { name: '运行流程图' })).toContainText('Workflow v2');
  await page.getByRole('button', { name: '返回运行详情', exact: true }).click();
  const rerun = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(rerun.locator('.run-detail-head')).toContainText('已完成', { timeout: 40000 });
  const rerunId = Number((await rerun.locator('.run-detail-head').textContent())?.match(/Run #(\d+)/)?.[1]);
  expect(rerunId).toBeGreaterThan(failedId);
  const task = (await api(page, '/api/hexa/tasks?offset=0&limit=100')).body.tasks.find((row: { title: string }) => row.title === title);
  const history = await api(page, `/api/hexa/tasks/${task.id}/runs?limit=100`);
  expect(history.body.runs.map((row: { id: number }) => row.id).sort()).toEqual([failedId, rerunId].sort());
  const kinds = history.body.runs.map((row: { kind: string }) => row.kind);
  expect(kinds).toContain('rerun');
  const failedSnapshot = await api(page, `/api/hexa/runs/${failedId}`);
  expect(failedSnapshot.body.status).toBe('failed');
  expect(failedSnapshot.body.nodes.find((node: { node_id: string }) => node.node_id === 'node-2').error_code).toBe('agent_failed');
  const rerunSnapshot = await api(page, `/api/hexa/runs/${rerunId}`);
  expect(rerunSnapshot.body.status).toBe('completed');
  expect(rerunSnapshot.body.nodes.every((node: { status: string }) => node.status === 'succeeded')).toBe(true);
  expect(rerunSnapshot.body.nodes.find((node: { node_id: string }) => node.node_id === 'node-2').error_code).toBeNull();
  expect(JSON.stringify(rerunSnapshot.body)).not.toContain('{{SECRET');
});

test('an interrupted run event stream recovers through read-only polling', async ({ page }) => {
  await signIn(page);
  await enterTasks(page);
  const title = `E2E SSE 恢复 ${Date.now()}`;
  const detail = await newTask(page, { title, taskInput: 'E2E_SLOW:5 SSE 恢复输入' });
  await saveWorkflow(page, { nodes: [{ id: 'node-1', name: '慢速节点', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_SLOW:5', final_report: true }] });
  const requests: Array<{ method: string; path: string }> = [];
  page.on('request', request => requests.push({ method: request.method(), path: new URL(request.url()).pathname }));
  await page.route('**/api/hexa/runs/*/events', route => route.abort());
  await detail.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const run = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(page.getByText('实时连接中断，正在定时刷新运行状态。')).toBeVisible({ timeout: 20000 });
  await expect(run.locator('.run-detail-head')).toContainText('已完成', { timeout: 40000 });
  const writes = requests.filter(request => request.method !== 'GET');
  expect(writes.every(request => !request.path.endsWith('/continue'))).toBe(true);
  await run.getByRole('button', { name: '返回所属任务', exact: true }).click();
  await expect(detail).toContainText('已完成');
});
