import { test, expect } from '@playwright/test';

test('cookie login, Agent selection, conversation, follow-up and refresh use only Hexa App API', async ({ page }) => {
  let loggedIn = false;
  let messages: Array<{ role: string; text: string }> = [];
  let conversation: any = null;
  const outbound: string[] = [];
  page.on('request', request => outbound.push(request.url()));
  await page.route('**/api/hexa/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    expect(request.headers()['authorization']).toBeUndefined();
    if (path.endsWith('/auth/login')) { loggedIn = true; return route.fulfill({ json: { authenticated: true, username: 'admin' } }); }
    if (path.endsWith('/auth/session')) return route.fulfill({ status: loggedIn ? 200 : 401, json: loggedIn ? { authenticated: true, username: 'admin' } : { detail: '需要先登录。' } });
    if (!loggedIn) return route.fulfill({ status: 401, json: { detail: '需要先登录。' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'a1', name: '真实分析师', base: 'codex', defaultModel: 'm1' }] } });
    if (path.endsWith('/models')) return route.fulfill({ json: { default: 'm1', models: [{ id: 'm1', label: '模型一', available: true }] } });
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { workspaces: [], selected_id: null } });
    if (path.endsWith('/conversations')) {
      if (request.method() === 'POST') { conversation = { id: 1, title: request.postDataJSON().title, agent_id: 'a1', model: 'm1', previous_response_id: null }; return route.fulfill({ status: 201, json: { ...conversation, messages } }); }
      if (messages.length) await new Promise(resolve => setTimeout(resolve, 250));
      return route.fulfill({ json: { conversations: conversation ? [conversation] : [] } });
    }
    if (path.endsWith('/messages')) {
      const body = request.postDataJSON();
      expect(body.previous_response_id).toBeUndefined();
      expect(request.headers()['idempotency-key']).toBeTruthy();
      messages.push({ role: 'user', text: body.text }, { role: 'assistant', text: `回答：${body.text}` });
      conversation.previous_response_id = `r${messages.length}`;
      return route.fulfill({ status: 202, json: { accepted: true, response_id: conversation.previous_response_id, status: 'completed', assistant: messages.at(-1) } });
    }
    if (path.endsWith('/status')) return route.fulfill({ json: { status: 'completed', response_id: conversation?.previous_response_id, error: null } });
    if (path.endsWith('/1')) return route.fulfill({ json: { ...conversation, messages } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/');
  await expect(page.getByRole('dialog', { name: '登录 Hexa' })).toBeVisible();
  await page.getByLabel('密码', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('main > section > header').getByText('Gateway 已连接', { exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: '会话 Agent' }).selectOption('a1');
  for (const text of ['首轮', '追问']) {
    await page.getByRole('textbox', { name: '消息输入' }).fill(text);
    await page.getByRole('button', { name: '发送消息', exact: true }).click();
    await expect(page.getByText(`回答：${text}`, { exact: true })).toBeVisible();
    await expect(page.getByText(`回答：${text}`, { exact: true })).toHaveCount(1);
  }
  await page.reload();
  await expect(page.getByText('回答：追问', { exact: true })).toBeVisible();
  expect(outbound.some(url => url.includes('/v1/') || url.includes('/api/harness'))).toBe(false);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.getByRole('button', { name: '展开上下文' }).click();
  await expect(page.getByRole('complementary', { name: '会话检查器' })).toBeVisible();
});
