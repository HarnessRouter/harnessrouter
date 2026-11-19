import { test, expect } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('app mode preserves all four navigation entries, original styling and local modules without Gateway requests', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', request => requests.push(request.url()));
  await page.route('**/api/hexa/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (path.endsWith('/tasks')) return route.fulfill({ json: { tasks: [] } });
    if (path.endsWith('/templates')) return route.fulfill({ json: { templates: [] } });
    return route.fulfill({ json: { agents: [], conversations: [], workspaces: [], selected_id: null } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await expect(page.getByRole('button', { name: '用户菜单：admin', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '用户菜单：admin', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '用户菜单', exact: true })).toContainText('应用服务端会话');
  await page.getByRole('button', { name: '用户菜单：admin', exact: true }).click();
  const nav = page.getByRole('navigation', { name: '主导航' });
  for (const name of ['对话', '任务', '智能体']) {
    await expect(nav.getByRole('button', { name, exact: true })).toBeVisible();
    await expect(nav.getByRole('button', { name, exact: true }).locator('.rail-label')).toHaveCSS('font-size', '10.5px');
  }
  await expect(nav.getByRole('button', { name: '对话', exact: true })).toHaveCSS('background-color', 'rgb(27, 43, 70)');
  await page.getByRole('textbox', { name: '消息输入' }).fill('切换后保留的草稿');
  await nav.getByRole('button', { name: '任务', exact: true }).click();
  await expect(page.getByRole('region', { name: '我的任务工作台' })).toBeVisible();
  await expect(page.getByRole('table', { name: '任务列表' })).toBeVisible();
  await expect(page.getByRole('region', { name: '任务列表区域' }).getByRole('button', { name: /新建任务/ })).toBeVisible();
  await nav.getByRole('button', { name: '智能体', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Agent 列表', exact: true })).toBeVisible();
  await nav.getByRole('button', { name: '对话', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '消息输入' })).toHaveValue('切换后保留的草稿');
  await page.screenshot({ path: join(tmpdir(), 'hexa-restored-navigation-desktop.png') });
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const settings = page.getByRole('dialog', { name: '设置', exact: true });
  await settings.getByRole('tab', { name: '界面与导航', exact: true }).click();
  await expect(settings).toBeVisible();
  await settings.getByRole('checkbox', { name: '一级导航显示文字' }).uncheck();
  await settings.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(nav.locator('.rail-label')).toHaveCount(0);
  await page.reload();
  await expect(nav.locator('.rail-label')).toHaveCount(0);
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await settings.getByRole('tab', { name: '界面与导航', exact: true }).click();
  await settings.getByRole('checkbox', { name: '一级导航显示文字' }).check();
  await settings.getByRole('button', { name: '保存设置', exact: true }).click();
  await page.getByRole('button', { name: '切换深色模式' }).click();
  await expect(nav.getByRole('button', { name: '对话', exact: true })).toHaveCSS('background-color', 'rgb(27, 43, 70)');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: join(tmpdir(), 'hexa-restored-navigation-mobile.png') });
  expect(requests.some(url => url.includes('/v1/') || url.includes('/api/harness'))).toBe(false);
});

test('shared user menu logs out through the application session API', async ({ page }) => {
  let signedIn = true;
  let logoutCalls = 0;
  await page.route('**/api/hexa/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ status: signedIn ? 200 : 401, json: { username: 'admin' } });
    if (path.endsWith('/auth/logout')) {
      expect(route.request().method()).toBe('POST');
      expect(route.request().headers()['authorization']).toBeUndefined();
      signedIn = false;
      logoutCalls++;
      return route.fulfill({ json: { authenticated: false } });
    }
    return route.fulfill({ json: { agents: [], conversations: [], workspaces: [], selected_id: null } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '用户菜单：admin', exact: true }).click();
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '登录 Hexa', exact: true })).toBeVisible();
  expect(logoutCalls).toBe(1);
  await page.reload();
  await expect(page.getByRole('dialog', { name: '登录 Hexa', exact: true })).toBeVisible();
});

test('conversation history remains visible when the Agent catalog is unavailable', async ({ page }) => {
  await page.route('**/api/hexa/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ status: 502, json: { detail: 'Gateway 暂时无法读取 Agent。' } });
    if (path.endsWith('/conversations')) return route.fulfill({ json: { conversations: [
      { id: 22, title: '昨天的产品讨论', previous_response_id: 'resp-22', status: 'completed' },
      { id: 21, title: '待恢复的任务', previous_response_id: null, status: 'unknown' },
    ] } });
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { workspaces: [], selected_id: null } });
    return route.fulfill({ json: { id: 22, title: '昨天的产品讨论', messages: [], previous_response_id: 'resp-22', status: 'completed' } });
  });
  await page.goto('/');
  await expect(page.getByText('对话历史', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '昨天的产品讨论', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '待恢复的任务', exact: true })).toContainText('待恢复');
  await page.getByRole('button', { name: '昨天的产品讨论', exact: true }).click();
  await expect(page.getByRole('heading', { name: '昨天的产品讨论', exact: true })).toBeVisible();
});

test('inspector preserves the reference layout, fills the height and collapses on desktop and mobile', async ({ page }) => {
  await page.route('**/api/hexa/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'a1', name: '分析 Agent', base: 'codex' }] } });
    if (path.endsWith('/models')) return route.fulfill({ json: { default: 'm1', models: [{ id: 'm1', label: '模型一' }] } });
    return route.fulfill({ json: { conversations: [], workspaces: [], selected_id: null } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  const inspector = page.getByRole('complementary', { name: '会话检查器' });
  await expect(inspector).toBeVisible();
  await expect(inspector.getByRole('heading', { name: '参与 Agent', exact: true })).toBeVisible();
  const tabs = inspector.getByRole('tablist', { name: '上下文标签' });
  await expect(tabs.getByRole('tab')).toHaveCount(4);
  await expect(inspector.locator('.inspector-head')).toHaveCSS('height', '56px');
  await expect(inspector.getByRole('tab', { name: '会话', exact: true })).toHaveCSS('border-radius', '10px');
  const panelBox = (await inspector.boundingBox())!;
  expect(panelBox.y).toBe(0);
  expect(panelBox.width).toBe(304);
  expect(panelBox.height).toBe(900);
  await expect(inspector).toContainText('由应用后端管理');
  await expect(inspector).toContainText('未使用模板');
  await inspector.getByRole('combobox', { name: '会话 Agent' }).selectOption('a1');
  await expect(inspector.getByRole('combobox', { name: '会话模型' })).toHaveValue('m1');
  for (const name of ['产物', '审批', '工具']) {
    await inspector.getByRole('tab', { name, exact: true }).click();
    await expect(inspector.getByRole('tab', { name, exact: true })).toHaveAttribute('aria-selected', 'true');
  }
  await inspector.getByRole('tab', { name: '会话', exact: true }).click();
  await page.screenshot({ path: join(tmpdir(), 'hexa-app-inspector-desktop.png') });
  await page.getByRole('button', { name: '收起上下文', exact: true }).click();
  await expect(inspector).toHaveCount(0);
  const expandedComposerWidth = (await page.locator('.composer').boundingBox())!.width;
  await page.getByRole('button', { name: '展开上下文' }).click();
  expect((await page.locator('.composer').boundingBox())!.width).toBeLessThan(expandedComposerWidth);
  await page.getByRole('button', { name: '切换深色模式' }).click();
  await page.screenshot({ path: join(tmpdir(), 'hexa-app-inspector-dark.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(inspector).toHaveCount(0);
  await page.getByRole('button', { name: '展开上下文' }).click();
  await expect(inspector).toBeVisible();
  const mobileBox = (await inspector.boundingBox())!;
  expect(mobileBox.y).toBe(0);
  expect(mobileBox.x + mobileBox.width).toBe(390);
  expect(mobileBox.height).toBe(844);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: join(tmpdir(), 'hexa-app-inspector-mobile.png') });
  await page.getByRole('button', { name: '关闭上下文遮罩', exact: true }).click({ position: { x: 8, y: 400 } });
  await expect(inspector).toHaveCount(0);
});

test('history failure preserves the draft and can retry to an empty or recovered list', async ({ page }) => {
  let historyRequests = 0;
  await page.route('**/api/hexa/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (path.endsWith('/conversations')) {
      historyRequests++;
      return historyRequests === 1
        ? route.fulfill({ status: 503, json: { detail: '对话历史暂时不可用。' } })
        : route.fulfill({ json: { conversations: [] } });
    }
    return route.fulfill({ json: { agents: [], workspaces: [], selected_id: null } });
  });
  await page.goto('/');
  const input = page.getByRole('textbox', { name: '消息输入' });
  await input.fill('保留的草稿');
  const sidebar = page.locator('.sidebar');
  await expect(sidebar.getByRole('alert')).toContainText('对话历史暂时不可用');
  await sidebar.getByRole('button', { name: '重试', exact: true }).click();
  await expect(sidebar.getByText('暂无历史对话', { exact: true })).toBeVisible();
  await expect(input).toHaveValue('保留的草稿');
  await page.reload();
  await expect(sidebar.getByText('暂无历史对话', { exact: true })).toBeVisible();
  await expect(input).toHaveValue('保留的草稿');
});
