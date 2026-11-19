import { test, expect } from '@playwright/test';

type Workspace = { id: number; name: string; description: string };

async function expectCentered(page: import('@playwright/test').Page, dialog: import('@playwright/test').Locator) {
  await expect.poll(async () => {
    const box = await dialog.boundingBox();
    if (!box) return Number.POSITIVE_INFINITY;
    const viewport = page.viewportSize()!;
    return Math.max(
      Math.abs(box.x + box.width / 2 - viewport.width / 2),
      Math.abs(box.y + box.height / 2 - viewport.height / 2),
    );
  }).toBeLessThanOrEqual(2);
}

async function expectWidth(dialog: import('@playwright/test').Locator, width: number) {
  await expect.poll(async () => Math.round((await dialog.boundingBox())?.width ?? 0)).toBe(width);
}

async function expectInsideViewport(page: import('@playwright/test').Page, dialog: import('@playwright/test').Locator) {
  await expect.poll(async () => {
    const box = await dialog.boundingBox();
    if (!box) return false;
    const viewport = page.viewportSize()!;
    return box.x >= 0 && box.x + box.width <= viewport.width;
  }).toBe(true);
}

async function mockWorkspaceApi(page: import('@playwright/test').Page) {
  let workspaces: Workspace[] = [
    { id: 1, name: 'Default Workspace', description: '默认工作空间' },
    { id: 2, name: '设计研究', description: '设计系统与用户研究' },
  ];
  let selectedId = 1;
  const updates: Array<{ id: number; body: { name: string; description: string } }> = [];
  const creates: Array<{ body: { name: string; description: string }; id: number }> = [];
  const selections: number[] = [];

  await page.route('**/api/hexa/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { authenticated: true, username: 'admin' } });
    if (path === '/api/hexa/agents') return route.fulfill({ json: { agents: [] } });
    if (path === '/api/hexa/conversations') return route.fulfill({ json: { conversations: [] } });
    if (path === '/api/hexa/workspaces' && request.method() === 'GET') {
      return route.fulfill({ json: { workspaces, selected_id: selectedId } });
    }
    if (path === '/api/hexa/workspaces' && request.method() === 'POST') {
      const body = request.postDataJSON() as { name: string; description: string };
      const created = { id: 3, name: body.name, description: body.description };
      workspaces = [...workspaces, created];
      creates.push({ body, id: created.id });
      return route.fulfill({ status: 201, json: created });
    }
    const update = path.match(/^\/api\/hexa\/workspaces\/(\d+)$/);
    if (update && request.method() === 'PATCH') {
      const id = Number(update[1]);
      const body = request.postDataJSON() as { name: string; description: string };
      updates.push({ id, body });
      workspaces = workspaces.map(row => row.id === id ? { ...row, ...body } : row);
      return route.fulfill({ json: workspaces.find(row => row.id === id) });
    }
    if (path === '/api/hexa/workspaces/select') {
      selectedId = Number(request.postDataJSON().workspace_id);
      selections.push(selectedId);
      return route.fulfill({ json: { selected_id: selectedId } });
    }
    return route.fulfill({ json: {} });
  });

  return { updates, creates, selections };
}

test('workspace menu uses the existing navigation style and centers its settings and creation forms', async ({ page }) => {
  const calls = await mockWorkspaceApi(page);
  await page.setViewportSize({ width: 1007, height: 780 });
  await page.goto('/');

  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  const menu = page.getByRole('dialog', { name: '工作空间', exact: true });
  await expect(menu).toBeVisible();
  await expectWidth(menu, 380);
  await expect(menu.getByRole('button', { name: 'Default Workspace', exact: true })).toHaveAttribute('aria-current', 'true');
  await expect(menu.getByRole('button', { name: '设计研究', exact: true })).toContainText('设计系统与用户研究');
  await expect(menu.getByRole('button', { name: 'Default Workspace', exact: true }).locator('.workspace-avatar')).toHaveCSS('background-color', 'rgb(27, 43, 70)');
  await expect(menu).toHaveCSS('background-color', 'rgb(255, 255, 255)');

  await menu.getByRole('button', { name: '工作区设置', exact: true }).click();
  const settings = page.getByRole('dialog', { name: '工作区设置', exact: true });
  await expect(settings).toBeVisible();
  await expect(menu).toBeHidden();
  await expectCentered(page, settings);
  await expectWidth(settings, 480);
  await expect(settings.getByLabel('工作区名称')).toHaveValue('Default Workspace');
  await expect(settings.getByLabel('工作区说明')).toHaveValue('默认工作空间');
  await settings.getByLabel('工作区名称').fill('Default Workspace 2');
  await settings.getByLabel('工作区说明').fill('更新后的说明');
  await settings.getByRole('button', { name: '保存工作区', exact: true }).click();
  await expect(settings).toBeHidden();
  expect(calls.updates).toEqual([{ id: 1, body: { name: 'Default Workspace 2', description: '更新后的说明' } }]);

  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  await expect(menu.getByRole('button', { name: 'Default Workspace 2', exact: true })).toBeVisible();
  await menu.getByRole('button', { name: '新建工作区', exact: true }).click();
  const create = page.getByRole('dialog', { name: '新建工作区', exact: true });
  await expect(create).toBeVisible();
  await expectCentered(page, create);
  await expectWidth(create, 480);
  await create.getByLabel('新工作区名称').fill('增长实验室');
  await create.getByLabel('新工作区说明').fill('增长实验与复盘');
  await create.getByRole('button', { name: '创建工作区', exact: true }).click();
  await expect(create).toBeHidden();
  expect(calls.creates).toEqual([{ id: 3, body: { name: '增长实验室', description: '增长实验与复盘' } }]);
  expect(calls.selections).toEqual([3]);

  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  await expect(menu.getByRole('button', { name: '增长实验室', exact: true })).toHaveAttribute('aria-current', 'true');
});

test('settings keeps bookmark tabs and the application-managed connection panel', async ({ page }) => {
  await mockWorkspaceApi(page);
  await page.setViewportSize({ width: 1007, height: 780 });
  await page.goto('/');
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '设置', exact: true });
  const tabs = dialog.getByRole('tablist', { name: '设置分区' });
  await expect(tabs).toHaveAttribute('aria-orientation', 'vertical');
  await expect(tabs.getByRole('tab')).toHaveCount(2);
  await expect(tabs.getByRole('tab', { name: '连接', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(dialog.getByRole('tabpanel', { name: '连接', exact: true })).toContainText('Gateway 连接由应用后端管理');
  await expect(dialog.getByRole('tabpanel', { name: '连接', exact: true })).toContainText('无需在浏览器中保存连接地址或 API Key');
  await tabs.getByRole('tab', { name: '界面与导航', exact: true }).click();
  await expect(tabs.getByRole('tab', { name: '界面与导航', exact: true })).toHaveCSS('background-color', 'rgb(255, 255, 255)');
  const activeTabBox = (await tabs.getByRole('tab', { name: '界面与导航', exact: true }).boundingBox())!;
  const panelBox = (await dialog.getByRole('tabpanel', { name: '界面与导航', exact: true }).boundingBox())!;
  expect(Math.abs(activeTabBox.x + activeTabBox.width - panelBox.x)).toBeLessThanOrEqual(1);
  await expect(dialog.getByRole('checkbox', { name: '一级导航显示文字' })).toBeChecked();
});

test('workspace menu and settings fit a 390px viewport without horizontal overflow', async ({ page }) => {
  await mockWorkspaceApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  const menu = page.getByRole('dialog', { name: '工作空间', exact: true });
  await expect(menu).toBeVisible();
  await expectInsideViewport(page, menu);
  await menu.getByRole('button', { name: '工作区设置', exact: true }).click();
  const settings = page.getByRole('dialog', { name: '工作区设置', exact: true });
  await expect(settings).toBeVisible();
  await expectInsideViewport(page, settings);
  await settings.getByRole('button', { name: /取\s*消/ }).click();

  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  await menu.getByRole('button', { name: '新建工作区', exact: true }).click();
  const create = page.getByRole('dialog', { name: '新建工作区', exact: true });
  await expect(create).toBeVisible();
  await expectInsideViewport(page, create);
  await create.getByRole('button', { name: /取\s*消/ }).click();

  await page.getByRole('button', { name: '设置', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '设置', exact: true });
  await expect(dialog.getByRole('tablist', { name: '设置分区' })).toHaveAttribute('aria-orientation', 'horizontal');
  await expectInsideViewport(page, dialog);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('workspace forms keep the entered values and readable errors when saving fails', async ({ page }) => {
  await page.route('**/api/hexa/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { authenticated: true, username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [] } });
    if (path.endsWith('/conversations')) return route.fulfill({ json: { conversations: [] } });
    if (path === '/api/hexa/workspaces' && request.method() === 'GET') return route.fulfill({ json: { workspaces: [{ id: 1, name: 'Default Workspace', description: '' }], selected_id: 1 } });
    if (path === '/api/hexa/workspaces' && request.method() === 'POST') return route.fulfill({ status: 502, json: { detail: '工作空间创建失败。' } });
    if (/^\/api\/hexa\/workspaces\/\d+$/.test(path) && request.method() === 'PATCH') return route.fulfill({ status: 502, json: { detail: '工作空间保存失败。' } });
    return route.fulfill({ json: {} });
  });

  await page.goto('/');
  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  const menu = page.getByRole('dialog', { name: '工作空间', exact: true });
  await menu.getByRole('button', { name: '工作区设置', exact: true }).click();
  const settings = page.getByRole('dialog', { name: '工作区设置', exact: true });
  await settings.getByLabel('工作区名称').fill('保留的名称');
  await settings.getByLabel('工作区说明').fill('保留的说明');
  await settings.getByRole('button', { name: '保存工作区', exact: true }).click();
  await expect(settings.getByRole('alert')).toContainText('工作空间保存失败');
  await expect(settings.getByLabel('工作区名称')).toHaveValue('保留的名称');
  await expect(settings.getByLabel('工作区说明')).toHaveValue('保留的说明');
  await settings.getByRole('button', { name: /取\s*消/ }).click();

  await page.getByRole('button', { name: '切换工作区', exact: true }).click();
  await menu.getByRole('button', { name: '新建工作区', exact: true }).click();
  const create = page.getByRole('dialog', { name: '新建工作区', exact: true });
  await create.getByLabel('新工作区名称').fill('保留的新名称');
  await create.getByRole('button', { name: '创建工作区', exact: true }).click();
  await expect(create.getByRole('alert')).toContainText('工作空间创建失败');
  await expect(create.getByLabel('新工作区名称')).toHaveValue('保留的新名称');
});
