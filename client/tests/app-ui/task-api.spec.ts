import { test, expect } from '@playwright/test';

test('empty tasks are real, creation edits and saves the task without publishing a template', async ({ page }) => {
  let task: any;
  const writes: string[] = [];
  await page.route('**/api/hexa/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') writes.push(path);
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { authenticated: true, username: 'admin' } });
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { workspaces: [], selected_id: null } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'a', name: '分析师' }] } });
    if (path.endsWith('/models')) return route.fulfill({ json: { default: 'm', models: [{ id: 'm', label: '模型 M' }] } });
    if (path.endsWith('/conversations')) return route.fulfill({ json: { conversations: [] } });
    if (path.endsWith('/artifacts')) return route.fulfill({ json: { artifacts: [], pagination: { offset: 0, limit: 50, has_more: false } } });
    if (path.endsWith('/templates')) return route.fulfill({ json: { templates: [] } });
    if (path.endsWith('/tasks') && request.method() === 'POST') { task = { ...request.postDataJSON(), id: 71, status: 'draft', current_revision: 1, current_result: {}, latest_run_id: null }; return route.fulfill({ status: 201, json: task }); }
    if (path.endsWith('/tasks')) return route.fulfill({ json: { tasks: task ? [task] : [] } });
    if (path.endsWith('/workflow')) { expect(request.postDataJSON().expected_revision).toBe(1); task = { ...task, workflow: request.postDataJSON().workflow, current_revision: 2 }; return route.fulfill({ json: task }); }
    if (path.endsWith('/tasks/71')) return route.fulfill({ json: task });
    if (path.endsWith('/runs')) return route.fulfill({ json: { runs: [] } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true }).click();
  await expect(page.getByText('暂无任务', { exact: true })).toBeVisible();
  await expect(page.getByRole('row', { name: /安全事件调查/ })).toHaveCount(0);
  await page.getByRole('region', { name: '任务列表区域' }).getByRole('button', { name: '新建任务', exact: true }).click();
  const create = page.getByRole('dialog', { name: '新建任务', exact: true });
  await create.getByLabel('任务名称', { exact: true }).fill('API 接入验收');
  await create.getByRole('button', { name: '创建任务', exact: true }).click();
  await page.getByRole('button', { name: '编辑流程', exact: true }).first().click();
  await page.getByRole('button', { name: '添加节点', exact: true }).click();
  await page.getByRole('group', { name: '节点 新节点 1', exact: true }).click();
  await page.getByLabel('节点 Agent', { exact: true }).selectOption('a');
  await expect(page.getByLabel('节点模型', { exact: true })).toHaveValue('m');
  await page.getByLabel('节点提示词', { exact: true }).fill('请分析');
  await page.getByRole('button', { name: '保存任务流程', exact: true }).click();
  await expect(page.getByRole('complementary', { name: '任务详情' })).toContainText('当前工作流 · v2');
  expect(task.workflow.nodes[0]).toMatchObject({ agent_id: 'a', model: 'm', prompt: '请分析' });
  expect(writes).toEqual(['/api/hexa/tasks', '/api/hexa/tasks/71/workflow']);
});
