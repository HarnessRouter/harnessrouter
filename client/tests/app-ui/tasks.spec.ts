import { test, expect } from '@playwright/test';

test('app task page exposes the task workspace menu and static views', async ({ page }) => {
  await page.route('**/api/hexa/auth/session', async route => route.fulfill({ json: { authenticated: true, username: 'admin' } }));
  await page.route('**/api/hexa/agents', async route => route.fulfill({ json: { agents: [] } }));
  await page.route('**/api/hexa/conversations', async route => route.fulfill({ json: { conversations: [] } }));
  await page.route('**/api/hexa/workspaces', async route => route.fulfill({ json: { workspaces: [], selected_id: null } }));
  await page.route('**/api/hexa/tasks', async route => {
    if (route.request().method() === 'POST') return route.fulfill({ status: 201, json: { id: 1, title: '安全事件调查', description: '', status: 'draft', current_revision: 1, workflow: { nodes: [{ id: 'collect-a' }, { id: 'summary', deps: ['collect-a'] }] }, current_result: {} } });
    return route.fulfill({ json: { tasks: [{ id: 1, title: '安全事件调查', description: '', status: 'draft', current_revision: 1, workflow: { nodes: [{ id: 'collect-a' }, { id: 'summary', deps: ['collect-a'] }] }, current_result: {} }] } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '任务' }).click();
  await expect(page.getByRole('heading', { name: '任务', exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '任务菜单' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /我的任务/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /安全事件调查/ }).first()).toBeVisible();
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /模板管理/ }).click();
  await expect(page.getByRole('heading', { name: '模板管理', exact: true })).toBeVisible();
  await expect(page.getByText('产品方案评估', { exact: true })).toBeVisible();
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /运行记录/ }).click();
  await expect(page.getByRole('heading', { name: '运行记录', exact: true })).toBeVisible();
  await expect(page.getByRole('main', { name: '运行流程图' }).getByText('等待人工输入', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('complementary').getByRole('button', { name: /安全事件调查案例 执行中/ })).toBeVisible();
  await expect(page.getByRole('main', { name: '运行流程图' })).toBeVisible();
  await expect(page.getByText('告警分析', { exact: true })).toBeVisible();
  await page.getByRole('complementary').getByRole('button', { name: /产品方案评估 已完成/ }).click();
  await expect(page.getByRole('main', { name: '运行流程图' })).toContainText('已生成最终报告');
});
