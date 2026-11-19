import { test, expect } from '@playwright/test';
import { newTask, openTasks, saveWorkflow, signIn } from './helpers';

test('Edge completes the same authenticated conversation and task path without layout overflow', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await signIn(page);

  await page.getByRole('combobox', { name: '会话 Agent' }).selectOption('e2e-agent');
  await page.getByRole('textbox', { name: '消息输入' }).fill('E2E_MARKDOWN Edge 渲染检查');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  const thread = page.getByRole('region', { name: '会话内容' });
  await expect(thread.getByRole('heading', { name: '分析结果', level: 2 })).toBeVisible();
  await expect(thread.getByRole('table')).toBeVisible();
  const chatWidth = page.viewportSize()!.width;
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(chatWidth);

  await openTasks(page);
  const detail = await newTask(page, { title: `Edge 任务 ${Date.now()}`, taskInput: 'E2E_OUT:Edge 输出' });
  await saveWorkflow(page, { nodes: [{ id: 'node-1', name: 'Edge 节点', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:Edge 输出', final_report: true }] });
  await detail.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const run = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(run.locator('.run-detail-head')).toContainText('已完成', { timeout: 40000 });
  await run.getByRole('button', { name: '返回所属任务', exact: true }).click();
  await expect(detail).toContainText('当前工作流 · v2');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
  expect(errors).toEqual([]);
});
