import { test, expect } from '@playwright/test';
import { taskFixture } from '../task-fixture';
import { mkdir } from 'node:fs/promises';

for (const width of [1440, 390]) test(`task deep link waits for workspace restoration before reads or creation at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const fixture = await taskFixture(page);
  for (const task of fixture.tasks) task.workspace_id = 9;
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let requested!: () => void;
  const started = new Promise<void>(resolve => { requested = resolve; });
  const taskReads: string[] = [];
  page.on('request', request => {
    if (/\/api\/hexa\/(tasks|templates|runs)(\/|\?|$)/.test(request.url())) taskReads.push(request.url());
  });
  await page.route('**/api/hexa/workspaces', async route => {
    requested();
    await held;
    await route.fulfill({ json: { workspaces: [{ id: 9, name: '恢复工作区', description: '' }], selected_id: 9 } });
  });
  try {
    await page.goto('/tasks/73');
    await started;
    await expect(page.getByRole('status')).toContainText('正在恢复工作区');
    if (width === 390) await expect(page.getByRole('button', { name: /新建任务/ })).toHaveCount(0);
    else await expect(page.getByRole('button', { name: /新建任务/ })).toBeDisabled();
    expect(taskReads).toEqual([]);
    await mkdir('.artifacts/orchestration', { recursive: true });
    await page.screenshot({ path: `.artifacts/orchestration/workspace-loading-${width}.png` });
  } finally { release(); }
  const detail = width === 390 ? page.getByRole('dialog', { name: '任务详情', exact: true }) : page.getByRole('complementary', { name: '任务详情', exact: true });
  if (width === 390) await page.getByRole('row', { name: /待配置的草稿/ }).click();
  await expect(detail).toBeVisible();
  await expect(detail).toContainText('待配置的草稿');
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(new URL(page.url()).pathname).toBe('/tasks/73');
  expect(fixture.writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `.artifacts/orchestration/workspace-ready-${width}.png`, animations: 'disabled' });
});

test('failed workspace restoration blocks the coordinator until explicit retry', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await taskFixture(page);
  let available = false;
  const taskReads: string[] = [];
  page.on('request', request => {
    if (/\/api\/hexa\/(tasks|templates|runs)(\/|\?|$)/.test(request.url())) taskReads.push(request.url());
  });
  await page.route('**/api/hexa/workspaces', route => available
    ? route.fulfill({ json: { workspaces: [], selected_id: null } })
    : route.fulfill({ status: 503, json: { detail: '工作空间读取失败。' } }));
  await page.goto('/coordinator');
  await expect(page.getByRole('alert')).toContainText('工作空间读取失败');
  expect(taskReads).toEqual([]);
  await expect(page.getByRole('button', { name: '创建任务', exact: true })).toHaveCount(0);
  const retry = page.getByRole('button', { name: '重试工作区', exact: true });
  await expect(retry).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await mkdir('.artifacts/orchestration', { recursive: true });
  await page.screenshot({ path: '.artifacts/orchestration/workspace-error-390.png' });
  available = true;
  await retry.click();
  await expect(page.getByRole('button', { name: '创建任务', exact: true })).toBeVisible();
  await expect.poll(() => taskReads.length).toBeGreaterThan(0);
});

test('restored null workspace and auxiliary catalog failure still allow task details', async ({ page }) => {
  await taskFixture(page);
  await page.route('**/api/hexa/agents', route => route.fulfill({ status: 503, json: { detail: 'Agent 目录暂不可用。' } }));
  await page.goto('/tasks/73');
  await expect(page.getByRole('complementary', { name: '任务详情', exact: true })).toContainText('待配置的草稿');
  await expect(page.getByRole('button', { name: '重试工作区', exact: true })).toHaveCount(0);
});
