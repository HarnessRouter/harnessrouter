import { test, expect } from '@playwright/test';
import { api, openTasks, signIn } from './helpers';

test('persisted tasks page and search across unseen rows while global runs retain task titles', async ({ page }) => {
  await signIn(page);
  const prefix = `分页持久化-${Date.now()}`;
  const space = await api(page, '/api/hexa/workspaces', { method: 'POST', body: { name: prefix } });
  expect(space.status).toBe(201);
  expect((await api(page, '/api/hexa/workspaces/select', { method: 'POST', body: { workspace_id: space.body.id } })).status).toBe(200);
  const ids: number[] = [];
  for (let index = 0; index < 23; index++) {
    const created = await api(page, '/api/hexa/tasks', { method: 'POST', body: {
      title: `${prefix}-${index}`, workspace_id: space.body.id,
      workflow: { nodes: [{ id: 'report', name: '分页报告', agent_id: 'e2e-agent', model: 'e2e-model', final_report: true }] },
    } });
    expect(created.status).toBe(201); ids.push(created.body.id);
  }
  const run = await page.request.post(`/api/hexa/tasks/${ids[0]}/runs`, { headers: { 'Idempotency-Key': crypto.randomUUID() }, data: {} });
  expect(run.status()).toBe(202);
  const runId = (await run.json()).id;
  await expect.poll(async () => (await api(page, `/api/hexa/runs/${runId}`)).body.status, { timeout: 45000 }).toBe('completed');
  await page.reload(); await openTasks(page);
  await expect(page.getByRole('row', { name: new RegExp(`${prefix}-22`) })).toBeVisible();
  await expect(page.getByRole('row', { name: new RegExp(`${prefix}-0`) })).toHaveCount(0);
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.getByRole('row', { name: new RegExp(`${prefix}-0`) })).toBeVisible();
  await page.getByRole('textbox', { name: '搜索任务' }).fill(`${prefix}-0`);
  await expect(page.getByRole('row', { name: new RegExp(`${prefix}-0`) })).toBeVisible();
  const searched = await api(page, `/api/hexa/tasks?workspace_id=${space.body.id}&offset=0&limit=20&q=${encodeURIComponent(`${prefix}-0`)}`);
  expect(searched.body.tasks.map((task: { title: string }) => task.title)).toEqual([`${prefix}-0`]);
  await page.reload();
  await expect(page.locator('.sidebar header small')).toHaveText(prefix);
  await openTasks(page);
  await page.getByRole('textbox', { name: '搜索任务' }).fill(`${prefix}-0`);
  await expect(page.getByRole('row', { name: new RegExp(`${prefix}-0`) })).toBeVisible();
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /运行记录/ }).click();
  await expect(page.getByRole('row', { name: new RegExp(`Run #${runId}`) })).toContainText(`${prefix}-0`);
  await page.getByRole('row', { name: new RegExp(`Run #${runId}`) }).click();
  const detail = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(detail.getByRole('region', { name: '任务产物' })).toContainText('report.txt');
  await page.setViewportSize({ width: 390, height: 844 });
  const drawer = page.getByRole('dialog', { name: '运行详情', exact: true });
  await expect(drawer).toBeVisible();
  const download = page.waitForEvent('download');
  await drawer.getByRole('region', { name: '任务产物' }).getByRole('button', { name: /下\s*载/ }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe('report.txt');
  expect(await file.failure()).toBeNull();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
