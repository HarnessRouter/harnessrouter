import { test, expect } from '@playwright/test';
import { taskFixture } from '../task-fixture';

const enter = async (page: import('@playwright/test').Page) => {
  await page.goto('/');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true }).click();
};

test('task table, filters, counts and details use API rows, including failed and draft tasks', async ({ page }) => {
  await taskFixture(page); await enter(page);
  await expect(page.getByRole('row', { name: /安全事件调查/ })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '任务菜单' })).toContainText('我的任务4');
  const filters = page.getByRole('group', { name: '任务状态筛选' });
  await filters.getByRole('button', { name: /^失败/ }).click();
  await expect(page.getByRole('row', { name: /执行失败的任务/ })).toBeVisible();
  await expect(page.getByRole('row', { name: /安全事件调查/ })).toHaveCount(0);
  await filters.getByRole('button', { name: /^全部/ }).click();
  await page.getByRole('textbox', { name: '搜索任务' }).fill('草稿');
  await page.getByRole('row', { name: /待配置的草稿/ }).click();
  const detail = page.getByRole('complementary', { name: '任务详情' });
  await expect(detail).toContainText('当前工作流 · v1');
  await expect(detail.getByRole('button', { name: '查看运行记录' })).toBeDisabled();
  await detail.getByRole('button', { name: '查看流程图' }).click();
  const flow = page.getByRole('region', { name: '任务流程图' });
  await expect(flow).toContainText('尚未运行');
  await flow.getByRole('button', { name: '返回任务详情' }).click();
  await expect(detail).toBeVisible();
});

test('task detail shows latest run outputs and opens the flow without switching to run history', async ({ page }) => {
  await taskFixture(page); await enter(page);
  await page.getByRole('row', { name: /安全事件调查/ }).click();
  const detail = page.getByRole('complementary', { name: '任务详情' });
  const outputs = detail.getByRole('region', { name: '最近运行节点输出' });
  await expect(outputs).toContainText('资料收集');
  await expect(outputs).toContainText('来自 API 的节点输出');

  await detail.getByRole('button', { name: '查看流程图' }).click();
  const flow = page.getByRole('region', { name: '任务流程图' });
  await expect(flow).toBeVisible();
  await expect(flow).toContainText('Run #18');
  await expect(page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /我的任务/ })).toHaveClass(/selected/);
  await flow.getByRole('button', { name: '返回任务详情' }).click();
  await expect(detail).toBeVisible();
});

test('workflow conflict keeps edited prompt and retries without publishing a template', async ({ page }) => {
  const fixture = await taskFixture(page, { failSave: true }); await enter(page);
  await page.getByRole('row', { name: /待配置的草稿/ }).click();
  await page.getByRole('button', { name: '编辑流程', exact: true }).click();
  await page.getByRole('group', { name: '节点 资料收集', exact: true }).click();
  await page.getByLabel('节点提示词', { exact: true }).fill('保存失败也要保留');
  await page.getByRole('button', { name: '保存任务流程' }).click();
  await expect(page.getByRole('alert')).toContainText('工作流版本已变化');
  await expect(page.getByLabel('节点提示词', { exact: true })).toHaveValue('保存失败也要保留');
  fixture.allowSave();
  await page.getByRole('button', { name: '保存任务流程' }).click();
  await expect(page.getByRole('complementary', { name: '任务详情' })).toContainText('当前工作流 · v2');
  expect(fixture.writes.every(row => row.path.endsWith('/workflow'))).toBe(true);
  expect(fixture.tasks[2].workflow.nodes[0]).toMatchObject({ x: 0, y: 0, agent_id: 'agent-1', model: 'model-1', prompt: '保存失败也要保留' });
});

test('task list failure has retry and never presents example records as saved data', async ({ page }) => {
  const fixture = await taskFixture(page, { failList: true }); await enter(page);
  await expect(page.getByRole('alert')).toContainText('任务服务暂时不可用');
  await expect(page.getByRole('row', { name: /安全事件调查/ })).toHaveCount(0);
  fixture.allowList();
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.getByRole('row', { name: /安全事件调查/ })).toBeVisible();
});

test('human decision selects actual gate dependencies and sends an idempotent continue request', async ({ page }) => {
  const fixture = await taskFixture(page); await enter(page);
  const detail = page.getByRole('complementary', { name: '任务详情' });
  await expect(detail.getByRole('button', { name: '编辑流程' })).toBeDisabled();
  await detail.getByLabel('资料收集', { exact: true }).check();
  await detail.getByRole('button', { name: '确认并继续' }).click();
  await expect.poll(() => fixture.writes.length).toBe(1);
  expect(fixture.writes[0]).toMatchObject({ path: '/api/hexa/runs/18/continue', body: { node_id: 'report', input_refs: ['a'] } });
  expect(fixture.writes[0].key).toBeTruthy();
});

test('human node can be operated from the selected flow node properties', async ({ page }) => {
  const fixture = await taskFixture(page); await enter(page);
  const detail = page.getByRole('complementary', { name: '任务详情' });
  await detail.getByRole('button', { name: '查看流程图' }).click();
  const flow = page.getByRole('region', { name: '任务流程图' });
  await flow.getByRole('button', { name: '汇总报告 节点' }).click();
  const properties = page.getByRole('complementary', { name: '运行属性' });
  await expect(properties).toContainText('不会调用 Agent');
  await properties.getByLabel('资料收集', { exact: true }).check();
  await properties.getByRole('button', { name: '确认并继续' }).click();
  await expect.poll(() => fixture.writes.length).toBe(1);
  expect(fixture.writes[0]).toMatchObject({ path: '/api/hexa/runs/18/continue', body: { node_id: 'report', input_refs: ['a'] } });
});

test('template editing appends an API version and does not write a task', async ({ page }) => {
  const fixture = await taskFixture(page); await enter(page);
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /模板管理/ }).click();
  await page.getByRole('button', { name: '编辑模板' }).click();
  await page.getByRole('group', { name: '节点 资料收集', exact: true }).click();
  await page.getByLabel('节点名称', { exact: true }).fill('升级后的收集');
  await page.getByRole('button', { name: '保存模板新版本' }).click();
  await expect(page.getByRole('complementary', { name: '模板详情' })).toContainText('当前版本 v2');
  expect(fixture.writes.map(row => row.path)).toEqual(['/api/hexa/templates/41/versions']);
  expect(fixture.templates[0].versions[0].workflow.nodes[0].name).toBe('资料收集');
});

test('template detail loads additional versions on demand instead of assuming the first page is complete', async ({ page }) => {
  await taskFixture(page, { paginatedTemplateVersions: true }); await enter(page);
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /模板管理/ }).click();
  const detail = page.getByRole('complementary', { name: '模板详情' });
  await expect(detail).toContainText('版本历史');
  await expect(detail).toContainText('版本 #301');
  await expect(detail).not.toContainText('版本 #302');
  await expect(detail.getByRole('button', { name: '加载更多版本' })).toBeVisible();
  await detail.getByRole('button', { name: '加载更多版本' }).click();
  await expect(detail).toContainText('版本 #302');
  await expect(detail).toContainText('版本 #303');
  await expect(detail.getByRole('button', { name: '加载更多版本' })).toHaveCount(0);
});

test('restored running task recovers after SSE disconnect using read-only snapshots', async ({ page }) => {
  const fixture = await taskFixture(page);
  fixture.tasks[0].status = 'running'; fixture.runs[0].status = 'running';
  let polls = 0;
  await page.route('**/api/hexa/runs/18/events', route => route.abort());
  await page.route('**/api/hexa/runs/18', route => { polls++; fixture.runs[0].status = 'completed'; fixture.runs[0].nodes.forEach(node => node.status = 'succeeded'); fixture.tasks[0].status = 'completed'; return route.fulfill({ json: fixture.runs[0] }); });
  await enter(page);
  await expect.poll(() => polls).toBeGreaterThan(0);
  await expect(page.getByRole('row', { name: /安全事件调查/ })).toContainText('已完成');
  expect(fixture.writes).toEqual([]);
});

test('an inaccessible deep-linked task shows an error instead of another task detail', async ({ page }) => {
  await taskFixture(page); await page.goto('/tasks/999');
  await expect(page.getByRole('alert')).toContainText('任务不存在');
  await expect(page.getByRole('complementary', { name: '任务详情' })).toHaveCount(0);
});
