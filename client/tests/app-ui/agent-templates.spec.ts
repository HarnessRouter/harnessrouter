import { test, expect } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('templates support Gateway pull, customer editing, use and persistent list/card views', async ({ page }) => {
  const gateway = { id: 'codex', name: 'Codex', description: '', base: 'codex', default_model: 'm1', system_prompt: 'Code carefully', source: 'gateway', available: true };
  let templates: Record<string, unknown>[] = [];
  let gatewayFailed = false, saveFailed = true;
  let agents: Record<string, unknown>[] = [];
  await page.route('**/api/hexa/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (path.endsWith('/agent-templates/gateway')) return route.fulfill(gatewayFailed ? { status: 502, json: { detail: 'Gateway 模板暂时无法读取，请重试。' } } : { json: { templates: [gateway, { ...gateway, id: 'pi', name: 'Pi', available: false }] } });
    if (path.endsWith('/agent-templates') && req.method() === 'POST') {
      if (saveFailed) { saveFailed = false; return route.fulfill({ status: 502, json: { detail: '模板保存失败。' } }); }
      templates.push({ ...req.postDataJSON(), id: 1, source: 'custom', available: true });
      return route.fulfill({ status: 201, json: templates[0] });
    }
    if (path.endsWith('/agent-templates/1')) {
      if (req.method() === 'PUT') { templates[0] = { ...templates[0], ...req.postDataJSON() }; return route.fulfill({ json: templates[0] }); }
      templates = []; return route.fulfill({ status: 204 });
    }
    if (path.endsWith('/agent-templates')) return route.fulfill({ json: { templates } });
    if (path.endsWith('/agents') && req.method() === 'POST') {
      expect(req.postDataJSON()).toEqual({ name: '客户代码助手', base: 'codex', default_model: 'm1', system_prompt: 'Code carefully' });
      agents = [{ ...req.postDataJSON(), id: 'a1' }]; return route.fulfill({ status: 201, json: agents[0] });
    }
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents } });
    return route.fulfill({ json: { conversations: [], workspaces: [], selected_id: null } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await page.getByRole('button', { name: '智能体', exact: true }).click();
  await page.getByRole('tab', { name: '模板库', exact: true }).click();
  await page.keyboard.press('ArrowLeft');
  await expect(page.getByRole('tab', { name: /我的 Agent/ })).toBeFocused();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: '模板库', exact: true })).toBeFocused();
  const cards = page.getByRole('region', { name: 'Agent 模板' });
  const codex = cards.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Codex', exact: true }) });
  await expect(codex).toContainText('Gateway');
  await expect(cards.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Pi', exact: true }) }).getByRole('button', { name: '使用模板', exact: true })).toBeDisabled();
  await codex.getByRole('button', { name: '另存为自定义', exact: true }).click();
  const form = page.getByRole('dialog', { name: '新建自定义模板', exact: true });
  await form.getByLabel('模板名称', { exact: true }).fill('客户模板');
  await form.getByLabel('说明', { exact: true }).fill('客户自己的工作方式');
  await form.getByRole('button', { name: '保存模板', exact: true }).click();
  await expect(form.getByRole('alert')).toContainText('模板保存失败');
  await expect(form.getByRole('textbox', { name: '模板名称', exact: true })).toHaveValue('客户模板');
  await form.getByRole('button', { name: '保存模板', exact: true }).click();
  await expect(form).toBeHidden();
  await page.getByRole('combobox', { name: '模板来源' }).selectOption('custom');
  const custom = cards.getByRole('article').filter({ has: page.getByRole('heading', { name: '客户模板', exact: true }) });
  await expect(custom).toContainText('自定义');
  await custom.getByRole('button', { name: '编辑模板', exact: true }).click();
  const edit = page.getByRole('dialog', { name: '编辑自定义模板', exact: true });
  await edit.getByLabel('模板名称', { exact: true }).fill('客户新模板');
  await edit.getByRole('button', { name: '保存模板', exact: true }).click();
  await expect(edit).toBeHidden();
  await page.getByRole('button', { name: '列表视图', exact: true }).click();
  await expect(page.getByRole('button', { name: '列表视图', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(cards).toHaveAttribute('data-view', 'list');
  await page.reload();
  await page.getByRole('button', { name: '智能体', exact: true }).click();
  await page.getByRole('tab', { name: '模板库', exact: true }).click();
  await expect(cards).toHaveAttribute('data-view', 'list');
  await page.getByRole('textbox', { name: '搜索 Agent 或模板' }).fill('客户新');
  await cards.getByRole('button', { name: '使用模板', exact: true }).click();
  const create = page.getByRole('dialog', { name: '创建 Agent', exact: true });
  await expect(create.getByLabel('后端', { exact: true })).toHaveValue('codex');
  await expect(create.getByRole('textbox', { name: '系统提示词', exact: true })).toHaveValue('Code carefully');
  await create.getByRole('textbox', { name: 'Agent 名称', exact: true }).fill('客户代码助手');
  await create.getByRole('button', { name: '创建', exact: true }).click();
  await expect(create).toBeHidden();
  await expect(page.getByRole('heading', { name: '客户代码助手', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: '模板库', exact: true }).click();
  gatewayFailed = true;
  await page.getByRole('button', { name: '拉取 Gateway 模板', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Gateway 模板暂时无法读取');
  await expect(cards.getByRole('heading', { name: '客户新模板', exact: true })).toBeVisible();
  gatewayFailed = false;
  await page.getByRole('button', { name: '拉取 Gateway 模板', exact: true }).click();
  await page.getByRole('textbox', { name: '搜索 Agent 或模板' }).fill('不存在');
  await expect(page.getByText('没有匹配的模板。', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: '搜索 Agent 或模板' }).fill('');
  await page.getByRole('button', { name: '卡片视图', exact: true }).click();
  await expect(cards).not.toHaveClass(/agent-catalog-list/);
  await page.screenshot({ path: join(tmpdir(), 'hexa-agent-templates-cards.png') });
  await page.getByRole('button', { name: '列表视图', exact: true }).click();
  await expect(cards).toHaveClass(/agent-catalog-list/);
  const listRows = cards.getByRole('article');
  const firstBox = (await listRows.nth(0).boundingBox())!;
  const secondBox = (await listRows.nth(1).boundingBox())!;
  expect(secondBox.y).toBeGreaterThanOrEqual(firstBox.y + firstBox.height);
  await page.screenshot({ path: join(tmpdir(), 'hexa-agent-templates-list.png') });
  await page.getByRole('button', { name: '切换深色模式', exact: true }).click();
  await page.screenshot({ path: join(tmpdir(), 'hexa-agent-templates-dark.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: join(tmpdir(), 'hexa-agent-templates-mobile.png') });
  await page.getByRole('button', { name: '卡片视图', exact: true }).click();
  await expect(cards).not.toHaveClass(/agent-catalog-list/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await cards.getByRole('article').filter({ has: page.getByRole('heading', { name: '客户新模板', exact: true }) }).getByRole('button', { name: '删除模板', exact: true }).click();
  const confirm = page.getByRole('dialog', { name: '删除自定义模板', exact: true });
  await confirm.getByRole('button', { name: '取消', exact: true }).click();
  await expect(cards.getByRole('heading', { name: '客户新模板', exact: true })).toBeVisible();
  await cards.getByRole('article').filter({ has: page.getByRole('heading', { name: '客户新模板', exact: true }) }).getByRole('button', { name: '删除模板', exact: true }).click();
  await confirm.getByRole('button', { name: '删除', exact: true }).click();
  await expect(cards.getByRole('heading', { name: '客户新模板', exact: true })).toBeHidden();
});

test('customers can create a blank template and recover independent list and deletion failures', async ({ page }) => {
  let rows: Record<string, unknown>[] = [], readFailed = false, deleteFailed = true;
  await page.route('**/api/hexa/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (path.endsWith('/agent-templates/gateway')) return route.fulfill({ status: 502, json: { detail: 'Gateway 模板暂时无法读取，请重试。' } });
    if (path.endsWith('/agent-templates') && request.method() === 'POST') {
      rows = [{ ...request.postDataJSON(), id: 3, source: 'custom', available: true }];
      return route.fulfill({ status: 201, json: rows[0] });
    }
    if (path.endsWith('/agent-templates/3')) {
      if (deleteFailed) { deleteFailed = false; return route.fulfill({ status: 503, json: { detail: '暂时无法删除模板。' } }); }
      rows = []; return route.fulfill({ status: 204 });
    }
    if (path.endsWith('/agent-templates')) return route.fulfill(readFailed ? { status: 503, json: { detail: '客户模板暂时无法读取。' } } : { json: { templates: rows } });
    return route.fulfill({ json: { agents: [], conversations: [], workspaces: [], selected_id: null } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '智能体', exact: true }).click();
  await page.getByRole('tab', { name: '模板库', exact: true }).click();
  await page.getByRole('button', { name: '新建自定义模板', exact: true }).click();
  const form = page.getByRole('dialog', { name: '新建自定义模板', exact: true });
  await form.getByRole('textbox', { name: '模板名称', exact: true }).fill('从零创建');
  await form.getByRole('textbox', { name: '后端', exact: true }).fill('codex');
  await form.getByRole('textbox', { name: '默认模型', exact: true }).fill('a-long-model-name/'.repeat(12));
  await form.getByRole('button', { name: '保存模板', exact: true }).click();
  await expect(form).toBeHidden();
  const catalog = page.getByRole('region', { name: 'Agent 模板' });
  await expect(catalog.getByRole('heading', { name: '从零创建', exact: true })).toBeVisible();
  readFailed = true;
  await page.getByRole('button', { name: '刷新列表', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '客户模板暂时无法读取' })).toBeVisible();
  await expect(catalog.getByRole('heading', { name: '从零创建', exact: true })).toBeVisible();
  readFailed = false;
  await page.getByRole('button', { name: '重试自定义模板', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await catalog.getByRole('button', { name: '删除模板', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '删除自定义模板', exact: true });
  await dialog.getByRole('button', { name: '删除', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('暂时无法删除模板');
  await dialog.getByRole('button', { name: '删除', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(catalog.getByRole('heading', { name: '从零创建', exact: true })).toBeHidden();
});

test('session expiry clears customer template data and editor state', async ({ page }) => {
  let expired = false;
  await page.route('**/api/hexa/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (expired) return route.fulfill({ status: 401, json: { detail: '需要先登录。' } });
    if (path.endsWith('/agent-templates')) return route.fulfill({ json: { templates: [{ id: 1, name: '账户私有模板', description: '', base: 'codex', default_model: 'm1', system_prompt: '', source: 'custom', available: true }] } });
    if (path.endsWith('/agent-templates/gateway')) return route.fulfill({ json: { templates: [] } });
    return route.fulfill({ json: { agents: [], conversations: [], workspaces: [], selected_id: null } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '智能体', exact: true }).click();
  await page.getByRole('tab', { name: '模板库', exact: true }).click();
  await expect(page.getByRole('heading', { name: '账户私有模板', exact: true })).toBeVisible();
  expired = true;
  await page.getByRole('button', { name: '拉取 Gateway 模板', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '登录 Hexa', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '账户私有模板', exact: true })).toBeHidden();
});
