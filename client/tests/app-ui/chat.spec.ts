import { test, expect } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('reply details expand inline above the answer and omit unknown elapsed time', async ({ page }) => {
  await page.route('**/api/hexa/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'a1', name: '数据分析结论', base: 'pi' }] } });
    if (path.endsWith('/models')) return route.fulfill({ json: { default: 'm1', models: [{ id: 'm1', label: '模型一', available: true }] } });
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { workspaces: [], selected_id: null } });
    if (path.endsWith('/status')) return route.fulfill({ json: { status: 'completed' } });
    if (path.endsWith('/files')) return route.fulfill({ json: { files: [] } });
    if (path.endsWith('/conversations/1')) return route.fulfill({ json: { id: 1, title: '详情验收', agent_id: 'a1', model: 'm1', status: 'completed', messages: [
      { role: 'assistant', text: '第一条回答', execution: { harness_id: 'a1', model: 'deepseek/deepseek-v4.1-flash', elapsed_ms: 173000, status: 'completed', reasoning: '核对公开资料后整理答案。', steps: [{ id: 'search-1', name: 'web_search', status: 'completed' }] } },
      { role: 'assistant', text: '历史回答' },
    ] } });
    return route.fulfill({ json: { conversations: [{ id: 1, title: '详情验收' }] } });
  });
  await page.addInitScript(() => sessionStorage.setItem('hexa.app.recent', '1'));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  const replies = page.locator('.reply');
  const first = replies.first();
  const toggle = first.getByText('用时 2分钟 53秒', { exact: true });
  await expect(toggle).toBeVisible();
  await expect(first.getByText('deepseek/deepseek-v4.1-flash', { exact: true })).not.toBeVisible();
  const before = (await first.locator('.reply-body').boundingBox())!;
  await toggle.click();
  await expect(first.getByText('deepseek/deepseek-v4.1-flash', { exact: true })).toBeVisible();
  await expect(first.getByText('核对公开资料后整理答案。', { exact: true })).toBeVisible();
  await expect(first.getByText('web_search', { exact: true })).toBeVisible();
  const after = (await first.locator('.reply-body').boundingBox())!;
  expect(after.y - before.y).toBeGreaterThan(70);
  expect(await first.locator('.reply-details-content').evaluate(element => getComputedStyle(element).position)).toBe('static');
  await expect(replies.last().locator('summary')).toHaveText('›');
  await expect(page.getByRole('combobox', { name: '会话 Agent' })).toBeVisible();
  await expect(page.getByRole('tab', { name: '产物', exact: true })).toHaveText('产物');
  await page.screenshot({ path: join(tmpdir(), 'hexa-reply-details-desktop.png') });
  await toggle.click();
  await expect(first.getByText('核对公开资料后整理答案。', { exact: true })).not.toBeVisible();
  await first.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(first.getByText('核对公开资料后整理答案。', { exact: true })).toBeVisible();
  await page.reload();
  await expect(toggle).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await toggle.click();
  await expect(first.getByText('deepseek/deepseek-v4.1-flash', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: join(tmpdir(), 'hexa-reply-details-mobile.png') });
});

test('the conversation thread scrolls and keeps the end of a long reply reachable', async ({ page }) => {
  const reply = [
    '## 长回复',
    '',
    ...Array.from({ length: 80 }, (_, index) => `第 ${index + 1} 段：这是一段用于验证对话区域滚动的内容。`),
    '',
    '末尾标记：滚动到底部',
  ].join('\n\n');
  let conversation: any = null;
  let sent = false;
  await page.route('**/api/hexa/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { authenticated: true, username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'a1', name: '长文助手', base: 'codex', defaultModel: 'm1' }] } });
    if (path.endsWith('/models')) return route.fulfill({ json: { default: 'm1', models: [{ id: 'm1', label: '模型一', available: true }] } });
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { workspaces: [], selected_id: null } });
    if (path.endsWith('/conversations') && request.method() === 'POST') {
      conversation = { id: 1, title: '长回复', agent_id: 'a1', model: 'm1', previous_response_id: null };
      return route.fulfill({ status: 201, json: { ...conversation, messages: [] } });
    }
    if (path.endsWith('/conversations')) return route.fulfill({ json: { conversations: conversation ? [conversation] : [] } });
    if (path.endsWith('/messages')) {
      sent = true;
      conversation.previous_response_id = 'r1';
      return route.fulfill({ status: 202, json: { accepted: true, response_id: 'r1', status: 'completed', assistant: { role: 'assistant', text: reply } } });
    }
    if (path.endsWith('/status')) return route.fulfill({ json: { status: 'completed', response_id: conversation?.previous_response_id, error: null } });
    if (path.endsWith('/files')) return route.fulfill({ json: { files: [] } });
    if (path.endsWith('/1')) return route.fulfill({ json: { ...conversation, messages: sent ? [{ role: 'user', text: '写一篇长回复' }, { role: 'assistant', text: reply }] : [] } });
    return route.fulfill({ json: {} });
  });

  await page.goto('/');
  await page.getByRole('combobox', { name: '会话 Agent' }).selectOption('a1');
  await page.getByRole('textbox', { name: '消息输入' }).fill('写一篇长回复');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();

  const thread = page.getByRole('region', { name: '会话内容' });
  const marker = thread.getByText('末尾标记：滚动到底部', { exact: true });
  await expect(marker).toBeAttached();
  await expect(thread.locator('.bubble.user')).toHaveCSS('box-shadow', 'none');
  const replyBody = thread.locator('.reply-body').first();
  await expect(replyBody).toHaveCSS('box-shadow', 'none');
  await expect(replyBody).toHaveCSS('border-top-width', '0px');
  await expect(replyBody).toHaveCSS('padding-top', '0px');
  await expect(replyBody).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect(thread.locator('.reply-avatar').first()).toBeVisible();
  const replyMetaBox = (await thread.locator('.reply-meta').first().boundingBox())!;
  const replyBodyBox = (await replyBody.boundingBox())!;
  const replyAvatarBox = (await thread.locator('.reply-avatar').first().boundingBox())!;
  expect(replyAvatarBox.x).toBeLessThan(replyMetaBox.x);
  expect(Math.abs(replyMetaBox.x - replyBodyBox.x)).toBeLessThanOrEqual(1);
  expect(replyBodyBox.y - (replyMetaBox.y + replyMetaBox.height)).toBeGreaterThanOrEqual(7);
  const chat = thread.locator('.chat-scroll');
  await expect.poll(() => chat.evaluate(element => element.scrollHeight > element.clientHeight && element.scrollTop > 0)).toBe(true);
  expect(await chat.evaluate(element => getComputedStyle(element).overflowY)).toBe('auto');
  expect(await chat.evaluate(element => getComputedStyle(element).scrollbarWidth)).toBe('thin');
  await expect(marker).toBeInViewport();
  await page.screenshot({ path: join(tmpdir(), 'hexa-chat-long-reply-scroll.png') });
  await chat.evaluate(element => { element.scrollTop = 0; });
  await expect(thread.getByText('第 1 段：这是一段用于验证对话区域滚动的内容。', { exact: true })).toBeInViewport();
});

test('the conversation scrollbar sits on the divider and the divider resizes the context panel', async ({ page }) => {
  const longReply = Array.from({ length: 40 }, (_, index) => `第 ${index + 1} 段：用于验证分栏拖动后的滚动区域。`).join('\n\n');
  await page.route('**/api/hexa/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { authenticated: true, username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'a1', name: '长文助手', base: 'codex', defaultModel: 'm1' }] } });
    if (path.endsWith('/models')) return route.fulfill({ json: { default: 'm1', models: [{ id: 'm1', label: '模型一', available: true }] } });
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { workspaces: [], selected_id: null } });
    if (path.endsWith('/status')) return route.fulfill({ json: { status: 'completed', response_id: 'r1', error: null } });
    if (path.endsWith('/files')) return route.fulfill({ json: { files: [] } });
    if (path.endsWith('/conversations/1')) return route.fulfill({ json: { id: 1, title: '长回复', agent_id: 'a1', model: 'm1', previous_response_id: 'r1', status: 'completed', messages: [{ role: 'assistant', text: longReply }] } });
    return route.fulfill({ json: { conversations: [{ id: 1, title: '长回复', agent_id: 'a1', model: 'm1', previous_response_id: 'r1', status: 'completed' }] } });
  });
  await page.addInitScript(() => sessionStorage.setItem('hexa.app.recent', '1'));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');

  const main = page.getByRole('region', { name: '会话内容' });
  const scroll = main.locator('.chat-scroll');
  const inspector = page.getByRole('complementary', { name: '会话检查器' });
  const separator = page.getByRole('separator', { name: '调整上下文宽度' });
  await expect(scroll).toBeVisible();
  await expect(separator).toBeVisible();
  await expect.poll(() => scroll.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);

  const scrollBox = (await scroll.boundingBox())!;
  const initialPanel = (await inspector.boundingBox())!;
  expect(Math.abs(scrollBox.x + scrollBox.width - initialPanel.x)).toBeLessThanOrEqual(1);
  expect(Math.round(initialPanel.width)).toBe(304);

  const handle = (await separator.boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + 140);
  await page.mouse.down();
  await page.mouse.move(handle.x - 80, handle.y + 140, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => Math.round((await inspector.boundingBox())!.width)).toBeGreaterThan(360);
  const resizedWidth = Math.round((await inspector.boundingBox())!.width);
  const resizedScroll = (await scroll.boundingBox())!;
  const resizedPanel = (await inspector.boundingBox())!;
  expect(Math.abs(resizedScroll.x + resizedScroll.width - resizedPanel.x)).toBeLessThanOrEqual(1);

  await separator.focus();
  await page.keyboard.press('ArrowRight');
  await expect.poll(async () => Math.round((await inspector.boundingBox())!.width)).toBe(resizedWidth - 24);
  const keyboardWidth = Math.round((await inspector.boundingBox())!.width);
  await page.screenshot({ path: join(tmpdir(), 'hexa-chat-split-resize.png') });

  await page.reload();
  await expect(inspector).toBeVisible();
  await expect.poll(async () => Math.round((await inspector.boundingBox())!.width)).toBe(keyboardWidth);
});

test('assistant replies render GFM markdown with tables and copyable code blocks', async ({ page }) => {
  const reply = [
    '## 分析结果',
    '',
    '**重点**：先验证 `Gateway` 状态。',
    '',
    '- 第一项',
    '- 第二项',
    '',
    '| 能力 | 状态 |',
    '| --- | --- |',
    '| Markdown | 已支持 |',
    '',
    '```ts',
    'const ready = true;',
    '```',
  ].join('\n');
  let conversation: any = null;
  let sent = false;
  await page.route('**/api/hexa/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { authenticated: true, username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'a1', name: '文档助手', base: 'codex', defaultModel: 'm1' }] } });
    if (path.endsWith('/models')) return route.fulfill({ json: { default: 'm1', models: [{ id: 'm1', label: '模型一', available: true }] } });
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { workspaces: [], selected_id: null } });
    if (path.endsWith('/conversations') && request.method() === 'POST') {
      conversation = { id: 1, title: 'Markdown', agent_id: 'a1', model: 'm1', previous_response_id: null };
      return route.fulfill({ status: 201, json: { ...conversation, messages: [] } });
    }
    if (path.endsWith('/conversations')) return route.fulfill({ json: { conversations: conversation ? [conversation] : [] } });
    if (path.endsWith('/messages')) {
      sent = true;
      conversation.previous_response_id = 'r1';
      return route.fulfill({ status: 202, json: { accepted: true, response_id: 'r1', status: 'completed', assistant: { role: 'assistant', text: reply } } });
    }
    if (path.endsWith('/status')) return route.fulfill({ json: { status: 'completed', response_id: conversation?.previous_response_id, error: null } });
    if (path.endsWith('/files')) return route.fulfill({ json: { files: [] } });
    if (path.endsWith('/1')) return route.fulfill({ json: { ...conversation, messages: sent ? [{ role: 'user', text: '请输出报告' }, { role: 'assistant', text: reply }] : [] } });
    return route.fulfill({ json: {} });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await page.getByRole('combobox', { name: '会话 Agent' }).selectOption('a1');
  await page.getByRole('textbox', { name: '消息输入' }).fill('请输出报告');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();

  const thread = page.getByRole('region', { name: '会话内容' });
  await expect(thread.getByRole('heading', { name: '分析结果', level: 2 })).toBeVisible();
  await expect(thread.getByRole('table')).toBeVisible();
  await expect(thread.getByText('const ready = true;', { exact: true })).toBeVisible();
  await expect(thread.locator('.token.keyword').first()).toBeVisible();
  const copyCode = thread.getByRole('button', { name: '复制代码' });
  await expect(copyCode).toBeVisible();
  await expect(thread.getByText('```ts', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: join(tmpdir(), `hexa-chat-markdown-${test.info().project.name}.png`) });
  await copyCode.click();
  await expect(copyCode).toContainText('已复制');
  await expect(copyCode).toHaveText('复制', { timeout: 3000 });
  await page.getByRole('button', { name: '切换深色模式' }).click();
  await expect(page.locator('.app')).toHaveClass(/dark/);
  await page.screenshot({ path: join(tmpdir(), `hexa-chat-markdown-dark-${test.info().project.name}.png`) });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: join(tmpdir(), `hexa-chat-markdown-mobile-${test.info().project.name}.png`) });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

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
  await expect(page.getByRole('region', { name: '会话内容' }).getByText('Gateway 已连接', { exact: true })).toBeVisible();
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
