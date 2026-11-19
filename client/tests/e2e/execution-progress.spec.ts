import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { api, E2E_APP, signIn } from './helpers';

const evidence = '.artifacts/execution-progress';
test.beforeAll(() => mkdirSync(evidence, { recursive: true }));

test('reloaded running conversation restores its progress and reaches the persisted terminal reply', async ({ page }) => {
  await signIn(page);
  await page.getByRole('combobox', { name: '会话 Agent' }).selectOption('e2e-agent');
  await page.getByRole('textbox', { name: '消息输入' }).fill('E2E_EXECUTION E2E_SLOW:12 E2E_OUT:刷新恢复回答');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.locator('.reply-live')).toBeVisible();
  await page.locator('.reply-live summary').click();
  await expect(page.locator('.reply-live')).toContainText('核对公开资料后整理答案。');
  // Reload while the real HTTP request and Gateway stream are still active.
  await page.reload();
  const live = page.locator('.reply-live');
  await expect(live).toBeVisible();
  await live.locator('summary').click();
  await expect(live).toContainText('核对公开资料后整理答案。');
  await expect(live).toHaveCount(0, { timeout: 30000 });
  const reply = page.locator('.reply').last();
  await expect(reply).toContainText('E2E-OUT:刷新恢复回答');
  await reply.locator('summary').click();
  await expect(reply).toContainText('web_search');
  await expect(page.getByRole('button', { name: '发送消息', exact: true })).toBeEnabled();
  await page.screenshot({ path: `${evidence}/chat-restored-desktop.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(reply).toContainText('核对公开资料后整理答案。');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: `${evidence}/chat-restored-mobile.png` });
});

test('parallel node progress crosses API SSE, remains separate and readable after reload on desktop and mobile', async ({ page }) => {
  await signIn(page);
  const spaces = await api<{ workspaces?: Array<{ id: number }>; selected_id?: number | null }>(page, '/api/hexa/workspaces');
  const workspaceId = spaces.body.selected_id ?? spaces.body.workspaces?.[0]?.id;
  expect(workspaceId).toBeTruthy();
  const longText = '证据'.repeat(300);
  const made = await api(page, '/api/hexa/tasks', { method: 'POST', body: {
    title: `过程验收 ${Date.now()}`, workspace_id: workspaceId, workflow: { nodes: [
      { id: 'a', name: '收集资料', agent_id: 'e2e-agent', model: 'e2e-model', prompt: `E2E_EXECUTION E2E_SLOW:12 E2E_OUT:节点A${longText}` },
      { id: 'b', name: '独立核查', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_EXECUTION E2E_SLOW:12 E2E_OUT:节点B' },
    ] },
  } });
  expect(made.status).toBe(201);
  const started = await page.evaluate(async taskId => {
    const response = await fetch(`/api/hexa/tasks/${taskId}/runs`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } });
    return { status: response.status, body: await response.json() };
  }, made.body.id);
  expect(started.status).toBe(202);
  await page.goto(`${E2E_APP}/runs/${started.body.id}`);
  const openGraph = async () => {
    await page.getByRole('complementary', { name: '运行详情', exact: true }).getByRole('button', { name: '打开流程图', exact: true }).click();
  };
  await openGraph();
  const progress = page.getByRole('region', { name: '节点实时过程' });
  await expect(progress).toContainText('核对公开资料后整理答案。');
  await expect(progress).toContainText('web_search');
  await expect(page.getByRole('button', { name: '收集资料 节点', exact: true })).toContainText('执行中');
  await page.screenshot({ path: `${evidence}/nodes-live-desktop.png` });
  await page.getByRole('button', { name: '独立核查 节点', exact: true }).click();
  await expect(progress).toContainText('核对公开资料后整理答案。');
  await page.reload();
  await openGraph();
  await expect(page.getByRole('button', { name: '收集资料 节点', exact: true })).toContainText('已完成', { timeout: 60000 });
  await expect(progress).toContainText(longText);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '收集资料 节点', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: '运行属性' });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('region', { name: '节点实时过程' })).toContainText(longText);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  expect(await progress.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: `${evidence}/nodes-persisted-mobile.png` });
});
