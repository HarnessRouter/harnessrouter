import { test, expect } from '@playwright/test';
import { api, E2E_APP, signIn } from './helpers';

test('reply execution details cross SSE and remain inline after a database reload', async ({ page }) => {
  await signIn(page);
  await page.getByRole('combobox', { name: '会话 Agent' }).selectOption('e2e-agent');
  await page.getByRole('textbox', { name: '消息输入' }).fill('E2E_EXECUTION E2E_SLOW:3');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  const live = page.locator('.reply-live');
  await expect(live).toBeVisible();
  await live.locator('summary').click();
  await expect(live).toContainText('核对公开资料后整理答案。');
  await expect(page.locator('.reply-live')).toHaveCount(0);
  const reply = page.locator('.reply').last();
  await expect(reply.locator('summary')).toContainText('用时');
  await reply.locator('summary').click();
  await expect(reply).toContainText('web_search');
  await expect(reply.locator('.reply-details-content')).toContainText('e2e-model');
  const saved = await reply.locator('summary').textContent();
  await page.reload();
  await expect(reply.locator('summary')).toHaveText(saved!);
  await reply.locator('summary').click();
  await expect(reply).toContainText('核对公开资料后整理答案。');
  const details = (await reply.locator('.reply-details-content').boundingBox())!;
  const body = (await reply.locator('.reply-body').boundingBox())!;
  expect(body.y).toBeGreaterThan(details.y + details.height);
});

test('conversation persists through Cookie API, SSE, follow-up, attachments, markdown and cancellation', async ({ page, context }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await signIn(page);
  await expect(page.getByRole('combobox', { name: '会话 Agent' })).toBeVisible();
  await page.getByRole('combobox', { name: '会话 Agent' }).selectOption('e2e-agent');
  await expect(page.getByRole('combobox', { name: '会话模型' })).toHaveValue('e2e-model');
  await page.locator('input[type="file"]').setInputFiles({ name: 'input.txt', mimeType: 'text/plain', buffer: Buffer.from('attachment content') });
  await expect(page.getByText('文件 · input.txt', { exact: false })).toBeVisible();

  await page.getByRole('textbox', { name: '消息输入' }).fill('E2E_OUT:第一轮');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.locator('.reply-live')).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.reply-live')).toContainText('集成测试 Agent');
  await expect(page.getByText('E2E-OUT:第一轮', { exact: true })).toBeVisible();

  await page.getByRole('textbox', { name: '消息输入' }).fill('E2E_OUT:第二轮追问');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.getByText('E2E-OUT:第二轮追问', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('E2E-OUT:第二轮追问', { exact: true })).toBeVisible();
  const cookie = (await context.cookies()).find(row => row.name === 'hexa_session');
  expect(cookie?.httpOnly).toBe(true);

  await page.getByRole('tab', { name: '产物', exact: true }).click();
  await expect(page.getByText('report.txt', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: '安全预览', exact: true }).first().click();
  await expect(page.getByText('generated report', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '下载', exact: true }).first().click();
  expect((await download).suggestedFilename()).toBe('report.txt');

  await page.getByRole('button', { name: /新建对话/ }).click();
  await page.getByRole('tab', { name: '会话', exact: true }).click();
  await page.getByRole('combobox', { name: '会话 Agent' }).selectOption('e2e-agent');
  await page.getByRole('textbox', { name: '消息输入' }).fill('E2E_RUNNING 记录长时间执行');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.locator('.reply-live')).toContainText('仍在执行', { timeout: 20000 });
  const stop = page.getByRole('button', { name: '取消生成', exact: true });
  await expect(stop).toBeVisible();
  await stop.click();
  await expect.poll(async () => page.locator('.composer-actions > span').textContent(), { timeout: 30000 }).not.toBe('生成中');
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('assistant markdown renders GFM tables, code highlighting and a copy action', async ({ page }) => {
  await signIn(page);
  await page.getByRole('combobox', { name: '会话 Agent' }).selectOption('e2e-agent');
  await page.getByRole('textbox', { name: '消息输入' }).fill('E2E_MARKDOWN 请输出报告');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  const thread = page.getByRole('region', { name: '会话内容' });
  await expect(thread.getByRole('heading', { name: '分析结果', level: 2 })).toBeVisible();
  await expect(thread.getByRole('table')).toBeVisible();
  await expect(thread.getByText('const ready = true;', { exact: true })).toBeVisible();
  await expect(thread.locator('.token.keyword').first()).toBeVisible();
  await expect(thread.getByText('```ts', { exact: true })).toHaveCount(0);
  const copy = thread.getByRole('button', { name: '复制代码' });
  await copy.click();
  await expect(copy).toContainText('已复制');
  await page.getByRole('button', { name: '切换深色模式' }).click();
  await expect(page.locator('.app')).toHaveClass(/dark/);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('agent detail layers read Gateway-provided configuration and never render secret values', async ({ page }) => {
  await signIn(page);
  await page.getByRole('button', { name: '智能体', exact: true }).click();
  await page.getByRole('region', { name: '我的 Agent' }).getByRole('article').filter({ hasText: '集成测试 Agent' }).click();
  const detail = page.getByRole('region', { name: '集成测试 Agent详情' });
  await expect(detail.getByRole('heading', { name: '集成测试 Agent', exact: true })).toBeVisible();
  const layers = detail.getByRole('tablist', { name: '智能体设置' });
  await expect(layers.getByRole('tab')).toHaveCount(5);
  await expect(detail).toContainText('你是端到端测试使用的分析助手');

  await layers.getByRole('tab', { name: /Agent harness/ }).click();
  await expect(detail).toContainText('codex');
  await expect(detail).toContainText('e2e-model');
  await expect(detail).toContainText('medium');

  await layers.getByRole('tab', { name: /Capabilities/ }).click();
  await expect(detail).toContainText('analysis');
  await expect(detail).toContainText('docs');
  await expect(detail).toContainText('report-kit');
  await expect(detail).toContainText('shell');

  await layers.getByRole('tab', { name: /Memory/ }).click();
  await expect(detail).toContainText('工作记忆');
  await layers.getByRole('tab', { name: /Environment/ }).click();
  await expect(detail).toContainText('E2E_TOKEN');
  await expect(detail).toContainText('已保存的引用');
  await expect(detail).not.toContainText('team-secret');
  await expect(detail).toContainText('X-Tenant');
  await expect(detail).toContainText('12 步');

  await layers.getByRole('tab', { name: /Instructions/ }).click();
  await page.keyboard.press('ArrowDown');
  await expect(layers.getByRole('tab', { name: /Agent harness/ })).toHaveAttribute('aria-selected', 'true');
  await detail.getByRole('button', { name: '开始对话', exact: true }).click();
  await expect(page.getByRole('combobox', { name: '会话 Agent' })).toHaveValue('e2e-agent');
});

test('agent templates, agent creation and deletion cross the real API and database', async ({ page }) => {
  const name = `E2E 模板 Agent ${Date.now()}`;
  await signIn(page);
  await page.getByRole('button', { name: '智能体', exact: true }).click();
  await page.getByRole('tab', { name: '模板库', exact: true }).click();
  const templates = page.getByRole('region', { name: 'Agent 模板' });
  const gateway = templates.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Codex HTTP 模板', exact: true }) });
  await gateway.getByRole('button', { name: '另存为自定义', exact: true }).click();
  const custom = `E2E 自定义模板 ${Date.now()}`;
  const form = page.getByRole('dialog', { name: '新建自定义模板', exact: true });
  await form.getByRole('textbox', { name: '模板名称', exact: true }).fill(custom);
  await form.getByLabel('说明', { exact: true }).fill('E2E 持久化检查');
  await form.getByRole('button', { name: '保存模板', exact: true }).click();
  await expect(form).toBeHidden();
  const card = templates.getByRole('article').filter({ has: page.getByRole('heading', { name: custom, exact: true }) }).first();
  await expect(card).toContainText('E2E 持久化检查');
  await page.reload();
  await page.getByRole('button', { name: '智能体', exact: true }).click();
  await page.getByRole('tab', { name: '模板库', exact: true }).click();
  await expect(card).toBeVisible();

  await card.getByRole('button', { name: '使用模板', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '创建 Agent', exact: true });
  await expect(editor.getByRole('textbox', { name: '系统提示词', exact: true })).toHaveValue('HTTP 模板提示词');
  await editor.getByRole('textbox', { name: 'Agent 名称', exact: true }).fill(name);
  await editor.getByRole('button', { name: '创建', exact: true }).click();
  await expect(editor).toBeHidden();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();

  await page.getByRole('button', { name: `删除 ${name}`, exact: true }).click();
  await page.getByRole('dialog', { name: '删除 Agent', exact: true }).getByRole('button', { name: '删除', exact: true }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeHidden();

  await page.getByRole('tab', { name: '模板库', exact: true }).click();
  await card.getByRole('button', { name: '删除模板', exact: true }).click();
  await page.getByRole('dialog', { name: '删除自定义模板', exact: true }).getByRole('button', { name: '删除', exact: true }).click();
  await expect(card).toBeHidden();
  const remaining = await api(page, '/api/hexa/agent-templates');
  expect(remaining.body.templates.some((row: { name: string }) => row.name === custom)).toBe(false);
});
