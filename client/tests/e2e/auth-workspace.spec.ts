import { test, expect } from '@playwright/test';
import { api, E2E_APP, openTasks, signIn } from './helpers';

test('login rejects bad passwords, restores the draft after session expiry and logs out', async ({ page, context }) => {
  const outbound: string[] = [];
  page.on('request', request => outbound.push(request.url()));
  await page.goto(`${E2E_APP}/`);
  const login = page.getByRole('dialog', { name: '登录 Hexa', exact: true });
  await expect(login).toBeVisible();
  await login.getByLabel('密码', { exact: true }).fill('definitely-wrong');
  await login.getByRole('button', { name: '登录', exact: true }).click();
  await expect(login.getByRole('alert')).toContainText('用户名或密码错误');

  await login.getByLabel('密码', { exact: true }).fill(process.env.HEXA_E2E_PASSWORD || 'integration-password');
  await login.getByRole('button', { name: '登录', exact: true }).click();
  await expect(login).toBeHidden();
  const session = (await context.cookies()).find(cookie => cookie.name === 'hexa_session');
  expect(session?.httpOnly).toBe(true);
  expect(await page.evaluate(() => document.cookie)).not.toContain('hexa_session');

  await page.getByRole('textbox', { name: '消息输入' }).fill('刷新后仍然保留的草稿');
  await page.reload();
  await expect(page.getByRole('textbox', { name: '消息输入' })).toHaveValue('刷新后仍然保留的草稿');

  await context.clearCookies();
  await page.reload();
  await expect(login).toBeVisible();
  await login.getByLabel('密码', { exact: true }).fill(process.env.HEXA_E2E_PASSWORD || 'integration-password');
  await login.getByRole('button', { name: '登录', exact: true }).click();
  await expect(login).toBeHidden();
  await expect(page.getByRole('textbox', { name: '消息输入' })).toHaveValue('刷新后仍然保留的草稿');

  await page.getByRole('button', { name: '用户菜单：admin', exact: true }).click();
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(login).toBeVisible();
  await page.reload();
  await expect(login).toBeVisible();
  expect(outbound.some(url => url.includes('/v1/') || url.includes('/api/harness'))).toBe(false);
});

test('workspaces isolate tasks, templates, runs and deep links', async ({ page }) => {
  await signIn(page);
  await openTasks(page);
  const unique = `隔离工作区-${Date.now()}`;
  const firstTitle = `隔离任务-${Date.now()}`;

  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  const menu = page.getByRole('dialog', { name: '工作空间', exact: true });
  await menu.getByRole('button', { name: '新建工作区', exact: true }).click();
  const create = page.getByRole('dialog', { name: '新建工作区', exact: true });
  await create.getByLabel('新工作区名称').fill(unique);
  await create.getByLabel('新工作区说明').fill('E2E 工作区隔离');
  await create.getByRole('button', { name: '创建工作区', exact: true }).click();
  await expect(create).toBeHidden();
  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  await expect(menu.getByRole('button', { name: unique, exact: true })).toHaveAttribute('aria-current', 'true');
  await menu.getByRole('button', { name: unique, exact: true }).click();
  await openTasks(page);

  await page.getByRole('button', { name: '新建任务', exact: true }).first().click();
  const dialog = page.getByRole('dialog', { name: '新建任务', exact: true });
  await dialog.getByLabel('任务名称', { exact: true }).fill(firstTitle);
  await dialog.getByLabel('任务输入', { exact: true }).fill('隔离输入');
  await dialog.getByRole('button', { name: '创建任务', exact: true }).click();
  const detail = page.getByRole('complementary', { name: '任务详情', exact: true });
  await expect(detail).toContainText(firstTitle);
  const taskId = Number((await detail.locator('.task-detail-id').textContent())?.match(/\d+/)?.[0]);
  expect(taskId).toBeGreaterThan(0);

  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  await expect(menu.getByRole('button', { name: '测试工作区', exact: true })).toBeVisible();
  await menu.getByRole('button', { name: '测试工作区', exact: true }).click();
  await openTasks(page);
  await expect(page.getByRole('row', { name: new RegExp(firstTitle) })).toHaveCount(0);

  await page.goto(`${E2E_APP}/tasks/${taskId}`);
  await expect(page.getByRole('alert')).toContainText(/该任务不在当前工作区|任务不存在/);
  await expect(page.getByRole('complementary', { name: '任务详情', exact: true })).toHaveCount(0);

  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  await menu.getByRole('button', { name: unique, exact: true }).click();
  await openTasks(page);
  await expect(page.getByRole('row', { name: new RegExp(firstTitle) })).toBeVisible();
});

test('workspace settings rename the current space and survive a reload', async ({ page }) => {
  await signIn(page);
  const original = `设置工作区-${Date.now()}`;
  const renamed = `${original}-已重命名`;
  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  const menu = page.getByRole('dialog', { name: '工作空间', exact: true });
  await menu.getByRole('button', { name: '新建工作区', exact: true }).click();
  const create = page.getByRole('dialog', { name: '新建工作区', exact: true });
  await create.getByLabel('新工作区名称').fill(original);
  await create.getByRole('button', { name: '创建工作区', exact: true }).click();
  await expect(create).toBeHidden();

  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  await menu.getByRole('button', { name: '工作区设置', exact: true }).click();
  const settings = page.getByRole('dialog', { name: '工作区设置', exact: true });
  await expect(settings.getByLabel('工作区名称')).toHaveValue(original);
  await settings.getByLabel('工作区名称').fill(renamed);
  await settings.getByLabel('工作区说明').fill('重命名后的说明');
  await settings.getByRole('button', { name: '保存工作区', exact: true }).click();
  await expect(settings).toBeHidden();
  await page.reload();
  await expect(page.locator('.sidebar small').first()).toHaveText(renamed);
});

test('unconfigured task lists expose retry instead of demo records', async ({ page }) => {
  await signIn(page);
  const list = await api(page, '/api/hexa/tasks?offset=0&limit=5');
  expect(list.status).toBe(200);
  expect(Array.isArray(list.body.tasks)).toBe(true);
  await openTasks(page);
  await expect(page.getByRole('region', { name: '任务列表区域' })).toBeVisible();
});
