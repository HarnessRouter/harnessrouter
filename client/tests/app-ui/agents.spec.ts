import { test, expect } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('Agent management confirms mutations, retains failed state and reloads authoritative list', async ({ page }) => {
  let agents = [{ id: 'a1', name: '产品分析师', base: 'openai', default_model: 'm1' }];
  let reads = 0, deletes = 0, creates = 0;
  let listFailed = false;
  await page.route('**/api/hexa/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (path.endsWith('/agents') && request.method() === 'POST') {
      creates++;
      expect(request.postDataJSON()).toEqual({ name: '研究助手', base: 'openai', default_model: 'm2', system_prompt: '研究产品' });
      if (creates === 1) return route.fulfill({ status: 502, json: { detail: 'Agent 创建失败。' } });
      agents.push({ id: 'a2', name: '研究助手', base: 'openai', default_model: 'm2' });
      return route.fulfill({ status: 201, json: { id: 'a2' } });
    }
    if (path.endsWith('/agents')) {
      reads++;
      return route.fulfill(listFailed ? { status: 502, json: { detail: 'Gateway 暂时无法读取 Agent。' } } : { json: { agents } });
    }
    if (request.method() === 'DELETE') {
      deletes++;
      if (deletes === 1) return route.fulfill({ status: 502, json: { detail: 'Agent 删除失败。' } });
      agents = agents.filter(row => row.id !== 'a2');
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { workspaces: [], selected_id: null } });
    return route.fulfill({ json: { conversations: [] } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '智能体', exact: true }).click();
  await expect(page.getByRole('heading', { name: '产品分析师' })).toBeVisible();
  await page.getByRole('button', { name: '创建 Agent', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '创建 Agent', exact: true });
  await dialog.getByLabel('Agent 名称', { exact: true }).fill('研究助手');
  await dialog.getByLabel('后端', { exact: true }).fill('openai');
  await dialog.getByLabel('默认模型', { exact: true }).fill('m2');
  await dialog.getByLabel('系统提示词', { exact: true }).fill('研究产品');
  await dialog.getByRole('button', { name: '创建', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Agent 创建失败');
  await expect(dialog.getByLabel('Agent 名称', { exact: true })).toHaveValue('研究助手');
  await dialog.getByRole('button', { name: '创建', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('heading', { name: '研究助手' })).toBeVisible();
  expect(reads).toBeGreaterThanOrEqual(2);
  await page.getByRole('button', { name: '删除 研究助手', exact: true }).click();
  const confirm = page.getByRole('dialog', { name: '删除 Agent', exact: true });
  await confirm.getByRole('button', { name: '取消', exact: true }).click();
  expect(deletes).toBe(0);
  await page.getByRole('button', { name: '删除 研究助手', exact: true }).click();
  await confirm.getByRole('button', { name: '删除', exact: true }).click();
  await expect(confirm.getByRole('alert')).toContainText('Agent 删除失败');
  await confirm.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.getByRole('heading', { name: '研究助手' })).toBeVisible();
  listFailed = true;
  await page.getByRole('button', { name: '刷新列表', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Gateway 暂时无法读取 Agent');
  await expect(page.getByRole('heading', { name: '产品分析师' })).toBeVisible();
  listFailed = false;
  await page.getByRole('button', { name: '刷新列表', exact: true }).click();
  await page.getByRole('button', { name: '删除 研究助手', exact: true }).click();
  await confirm.getByRole('button', { name: '删除', exact: true }).click();
  await expect(confirm).toBeHidden();
  await expect(page.getByRole('heading', { name: '研究助手' })).toBeHidden();
  await page.screenshot({ path: join(tmpdir(), 'hexa-agents-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.getByRole('button', { name: '创建 Agent', exact: true }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel('Agent 名称', { exact: true })).toBeVisible();
  await dialog.getByLabel('Agent 名称', { exact: true }).focus();
  await page.screenshot({ path: join(tmpdir(), 'hexa-agents-mobile.png') });
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  agents = [];
  await page.getByRole('button', { name: '刷新列表', exact: true }).click();
  await expect(page.getByText('暂无可用 Agent。', { exact: true })).toBeVisible();
});

test('Agent model switching ignores stale results and prevents sends after model load failure', async ({ page }) => {
  let releaseOld!: () => void;
  const oldGate = new Promise<void>(resolve => { releaseOld = resolve; });
  let modelFailed = true;
  await page.route('**/api/hexa/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'a1', name: '慢 Agent' }, { id: 'a2', name: '新 Agent' }] } });
    if (path.endsWith('/a1/models')) { await oldGate; return route.fulfill({ json: { default: 'old', models: [{ id: 'old' }] } }); }
    if (path.endsWith('/a2/models')) return route.fulfill(modelFailed ? { status: 502, json: { detail: '模型读取失败。' } } : { json: { default: 'new', models: [{ id: 'new' }] } });
    return route.fulfill({ json: { conversations: [], workspaces: [], selected_id: null } });
  });
  await page.goto('/');
  const select = page.getByRole('combobox', { name: '会话 Agent' });
  await select.selectOption('a1');
  await select.selectOption('a2');
  await expect(page.getByText('模型读取失败。', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: '消息输入' }).fill('不能使用旧模型');
  await expect(page.getByRole('button', { name: '发送消息', exact: true })).toBeDisabled();
  releaseOld();
  modelFailed = false;
  await page.getByRole('button', { name: '重试模型', exact: true }).click();
  await expect(page.getByRole('combobox', { name: '会话模型' })).toHaveValue('new');
  await expect(page.getByRole('button', { name: '发送消息', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '智能体', exact: true }).click();
  await page.locator('.agent-grid article').filter({ has: page.getByRole('heading', { name: '新 Agent', exact: true }) }).getByRole('button', { name: '开始对话' }).click();
  await expect(page.getByRole('combobox', { name: '会话 Agent' })).toHaveValue('a2');
  await expect(page.getByRole('combobox', { name: '会话模型' })).toHaveValue('new');
  await page.getByRole('textbox', { name: '消息输入' }).fill('新对话');
  await expect(page.getByRole('button', { name: '发送消息', exact: true })).toBeEnabled();
});
