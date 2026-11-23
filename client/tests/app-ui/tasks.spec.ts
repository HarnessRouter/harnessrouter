import { test, expect } from '@playwright/test';
import { taskFixture } from '../task-fixture';
import { mkdir } from 'node:fs/promises';

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

test('workflow inspector edits bounded orchestration settings and persists them with the revision', async ({ page }) => {
  const fixture = await taskFixture(page);
  fixture.tasks[2].workflow = structuredClone(fixture.tasks[0].workflow);
  await enter(page);
  await page.getByRole('row', { name: /待配置的草稿/ }).click();
  await page.getByRole('button', { name: '编辑流程', exact: true }).click();
  await page.getByRole('group', { name: '节点 汇总报告', exact: true }).click();

  await page.getByLabel('最大并发数').fill('2');
  await page.getByLabel('允许缺失输入').check();
  await page.getByLabel('条件分支').check();
  await page.getByLabel('条件路径').fill('route');
  await page.getByLabel('条件值').fill('fast');
  await page.getByLabel('执行 Agent 前人工确认输入').uncheck();
  await page.getByLabel('执行模式').selectOption('repeat');
  await page.getByLabel('重复上限').fill('3');
  await page.getByLabel('重复终止路径').fill('done');
  await page.getByLabel('重复终止值').fill('true');
  await page.getByRole('button', { name: '保存任务流程' }).click();
  await expect.poll(() => fixture.writes.length).toBe(1);
  expect(fixture.writes[0].body.workflow).toMatchObject({ max_concurrency: 2 });
  expect(fixture.writes[0].body.workflow.nodes.find((node: any) => node.id === 'report')).toMatchObject({
    allow_missing_inputs: true,
    condition: { source: 'a', path: 'route', op: 'eq', value: 'fast' },
    repeat: { max_iterations: 3, until: { path: 'done', op: 'eq', value: true } },
  });
  await page.getByRole('button', { name: '编辑流程', exact: true }).click();
  await page.getByRole('group', { name: '节点 汇总报告', exact: true }).click();
  await expect(page.getByLabel('最大并发数')).toHaveValue('2');
  await page.getByLabel('执行模式').selectOption('foreach');
  await page.getByLabel('集合路径').fill('items');
  await page.getByLabel('集合上限').fill('3');
  await page.getByRole('button', { name: '保存任务流程' }).click();

  await expect.poll(() => fixture.writes.length).toBe(2);
  const saved = fixture.writes[1].body.workflow.nodes.find((node: any) => node.id === 'report');
  expect(saved).toMatchObject({
    foreach: { source: 'a', path: 'items', max_items: 3 },
  });
  expect(saved.repeat).toBeUndefined();
});

test('invalid orchestration retains the draft and makes no write until corrected', async ({ page }) => {
  const fixture = await taskFixture(page); await enter(page);
  await page.getByRole('row', { name: /待配置的草稿/ }).click();
  await page.getByRole('button', { name: '编辑流程', exact: true }).click();
  await page.getByLabel('最大并发数').fill('51');
  await page.getByRole('button', { name: '保存任务流程' }).click();
  const error = page.getByRole('alert');
  await expect(error).toContainText('最大并发数必须是');
  await expect(error).toBeFocused();
  await expect(page.getByLabel('最大并发数')).toHaveValue('51');
  expect(fixture.writes).toHaveLength(0);
  await page.getByLabel('最大并发数').fill('2');
  await page.getByRole('button', { name: '保存任务流程' }).click();
  await expect.poll(() => fixture.writes.length).toBe(1);
});

test('template revision saves concurrency without changing an existing task', async ({ page }) => {
  const fixture = await taskFixture(page); await enter(page);
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /模板管理/ }).click();
  await page.getByRole('button', { name: '编辑模板' }).click();
  await page.getByLabel('最大并发数').fill('4');
  await page.getByRole('button', { name: '保存模板新版本' }).click();
  await expect.poll(() => fixture.writes.length).toBe(1);
  expect(fixture.writes[0].body.workflow.max_concurrency).toBe(4);
  expect(fixture.tasks[0].workflow.max_concurrency).toBeUndefined();
});

test('run properties show bound orchestration and recorded skip reason', async ({ page }) => {
  const fixture = await taskFixture(page);
  const run = fixture.runs[0];
  run.workflow = structuredClone(run.workflow);
  run.workflow.max_concurrency = 2;
  Object.assign(run.workflow.nodes[2], { condition: { source: 'a', path: 'route', op: 'eq', value: 'fast' }, foreach: { source: 'a', path: 'items', max_items: 3 }, requires_human: false });
  Object.assign(run.nodes[2], { status: 'skipped', error_code: 'condition_not_matched', attempt: 2, input: { foreach_index: 1 } });
  fixture.tasks[0].workflow = { max_concurrency: 50, nodes: [] };
  await page.goto('/runs/18');
  await page.getByRole('button', { name: '打开流程图' }).click();
  await page.getByRole('button', { name: '汇总报告 节点' }).click();
  const config = page.getByRole('region', { name: '编排运行配置' });
  await expect(config).toContainText('最大并发数：2');
  await expect(config).toContainText('a.route');
  await expect(config).toContainText('集合项 2');
  await expect(config).toContainText('条件未匹配');
});

for (const width of [1440, 800, 390]) test(`orchestration inspector remains usable at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 });
  const fixture = await taskFixture(page);
  fixture.tasks[2].workflow = structuredClone(fixture.tasks[0].workflow);
  await page.goto('/tasks/73');
  if (width < 901) await page.getByRole('row', { name: /待配置的草稿/ }).click();
  await page.getByRole('button', { name: '编辑流程', exact: true }).click();
  await page.getByRole('group', { name: '节点 汇总报告', exact: true }).click();
  await page.getByLabel('最大并发数').fill('2');
  await page.getByLabel('执行 Agent 前人工确认输入').uncheck();
  await page.getByLabel('执行模式').selectOption('foreach');
  await page.getByLabel('集合路径').fill('items');
  await expect(page.getByLabel('集合上限')).toBeVisible();
  await page.getByLabel('集合上限').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await mkdir('.artifacts/orchestration', { recursive: true });
  await page.screenshot({ path: `.artifacts/orchestration/${testInfo.project.name}-${width}.png` });
  await page.getByRole('button', { name: '保存任务流程' }).click();
  await expect.poll(() => fixture.writes.length).toBe(1);
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
