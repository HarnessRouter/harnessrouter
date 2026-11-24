import { test, expect } from '@playwright/test';
import { api, openTasks, signIn } from './helpers';

for (const width of [1440, 390]) test(`saved approval requirements survive editing and refuse autonomous execution at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 });
  await signIn(page);
  const spaces = await api(page, '/api/hexa/workspaces');
  const policy = { require: ['external_write'] };
  const created = await api(page, '/api/hexa/tasks', { method: 'POST', body: {
    title: `审批要求-${Date.now()}`, workspace_id: spaces.body.selected_id,
    workflow: { tool_approval_policy: policy, nodes: [{
      id: 'work', name: '受控节点', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:受控',
      tool_approval_policy: { require: ['destructive'] },
    }] },
  } });
  expect(created.status).toBe(201);
  await page.goto(`/tasks/${created.body.id}`);
  if (width === 390) await page.getByRole('row').filter({ hasText: created.body.title }).click();
  const detail = page.getByRole(width === 390 ? 'dialog' : 'complementary', { name: '任务详情', exact: true });
  await detail.getByRole('button', { name: '编辑流程', exact: true }).click();
  await page.getByLabel('最大并发数', { exact: true }).fill('2');
  const saving = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().endsWith('/workflow'));
  await page.getByRole('button', { name: '保存任务流程', exact: true }).click();
  const saved = await (await saving).json();
  expect(saved.workflow.tool_approval_policy).toEqual(policy);
  expect(saved.workflow.nodes[0].tool_approval_policy).toEqual({ require: ['destructive'] });
  await page.reload();
  if (width === 390) await page.getByRole('row').filter({ hasText: created.body.title }).click();
  await detail.getByRole('button', { name: '运行', exact: true }).click();
  const starting = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(`/tasks/${created.body.id}/runs`));
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const refused = await starting;
  expect(refused.status()).toBe(422);
  expect((await refused.json()).detail.code).toBe('configuration_unavailable');
  await expect(page.getByRole('alert').filter({ hasText: '工具审批运行时尚未接通' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  const dialog = page.getByRole('dialog', { name: '确认运行任务', exact: true });
  const bounds = (await dialog.boundingBox())!;
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
  await page.screenshot({ path: testInfo.outputPath('approval-unavailable.png') });
  const history = await api(page, `/api/hexa/tasks/${created.body.id}/runs`);
  expect(history.body.runs).toEqual([]);
  const reloaded = await api(page, `/api/hexa/tasks/${created.body.id}`);
  expect(reloaded.body.status).toBe('draft');
  expect(reloaded.body.workflow.tool_approval_policy).toEqual(policy);
});

test('template editor preserves approval requirements in a new immutable version', async ({ page }) => {
  await signIn(page);
  const spaces = await api(page, '/api/hexa/workspaces');
  const policy = { require: ['external_write'] };
  const workflow = { tool_approval_policy: policy, nodes: [{
    id: 'work', name: '受控模板节点', agent_id: 'e2e-agent', model: 'e2e-model', prompt: '受控操作',
    tool_approval_policy: { require: ['destructive'] },
  }] };
  const title = `审批模板-${Date.now()}`;
  const created = await api(page, '/api/hexa/templates', { method: 'POST', body: {
    title, workspace_id: spaces.body.selected_id, workflow,
  } });
  expect(created.status).toBe(201);
  await openTasks(page);
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /模板管理/ }).click();
  await page.getByRole('row').filter({ hasText: title }).click();
  const detail = page.getByRole('complementary', { name: '模板详情', exact: true });
  await detail.getByRole('button', { name: '编辑模板', exact: true }).click();
  await page.getByLabel('最大并发数', { exact: true }).fill('2');
  const saving = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(`/templates/${created.body.id}/versions`));
  await page.getByRole('button', { name: '保存模板新版本', exact: true }).click();
  expect((await saving).status()).toBe(201);
  await expect(detail).toContainText('当前版本 v2');
  await page.reload();
  const saved = await api(page, `/api/hexa/templates/${created.body.id}`);
  expect(saved.body.versions[0].workflow).toEqual(workflow);
  expect(saved.body.latest_version.workflow.tool_approval_policy).toEqual(policy);
  expect(saved.body.latest_version.workflow.nodes[0].tool_approval_policy).toEqual({ require: ['destructive'] });
  expect(saved.body.latest_version.workflow.max_concurrency).toBe(2);
});
