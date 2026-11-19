import { test, expect, type Page } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

async function fixture(page: Page, options: { failStart?: boolean; active?: boolean; empty?: boolean } = {}) {
  const workflow = { nodes: [{ id: 'report', name: '研究报告', agent_id: 'agent-1', model: 'model-1', prompt: '输出报告', deps: [], final_report: true }] };
  const tasks = options.empty ? [] : Array.from({ length: 22 }, (_, i) => ({
    id: i + 1, title: `研究任务 ${i + 1}`, description: '', workspace_id: null, current_revision: 1,
    workflow_state: 'saved', workflow, status: options.active && i < 2 ? 'running' : 'draft',
    latest_run_id: options.active && i < 2 ? i + 101 : null, current_result: {},
  }));
  const runs = new Map<number, any>();
  const makeRun = (taskId: number) => ({ id: taskId + 100, task_id: taskId, workflow_revision: 1, kind: 'normal', status: 'running', workflow, nodes: [{ id: taskId, node_id: 'report', attempt: 1, status: 'running', output: null }] });
  if (options.active) { runs.set(101, makeRun(1)); runs.set(102, makeRun(2)); }
  const writes: Array<{ path: string; body: any; key?: string }> = [], reads: number[] = [];
  let failStart = options.failStart;
  await page.route('**/api/hexa/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    if (req.method() !== 'GET') writes.push({ path, body: req.postData() ? req.postDataJSON() : null, key: req.headers()['idempotency-key'] });
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'agent-1', name: '研究 Agent' }] } });
    if (path.endsWith('/models')) return route.fulfill({ json: { default: 'model-1', models: [{ id: 'model-1' }] } });
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { workspaces: [], selected_id: null } });
    if (path.endsWith('/conversations')) return route.fulfill({ json: { conversations: [] } });
    if (path.endsWith('/templates') && req.method() === 'POST') return route.fulfill({ status: 201, json: { id: 9, title: req.postDataJSON().title, workspace_id: null, versions: [{ id: 90, version: 1, workflow: req.postDataJSON().workflow }] } });
    if (path.endsWith('/tasks')) {
      if (req.method() === 'POST') {
        const task = { ...tasks[0], ...req.postDataJSON(), id: 99, status: 'draft', current_revision: 1, workflow_state: 'saved', current_result: {}, latest_run_id: null };
        tasks.unshift(task); return route.fulfill({ status: 201, json: task });
      }
      const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 20);
      return route.fulfill({ json: { tasks: tasks.slice(offset, offset + limit), pagination: { offset, limit, has_more: tasks.length > offset + limit } } });
    }
    const start = path.match(/\/tasks\/(\d+)\/runs$/);
    if (start && req.method() === 'POST') {
      const id = Number(start[1]);
      if (id === 2 && failStart) return route.fulfill({ status: 503, json: { detail: '分发暂时失败，请重试。' } });
      const run = makeRun(id); runs.set(run.id, run);
      const task = tasks.find(t => t.id === id)!; task.status = 'running'; task.latest_run_id = run.id;
      return route.fulfill({ status: 202, json: run });
    }
    const match = path.match(/\/runs\/(\d+)(?:\/(.*))?$/);
    if (match) {
      const id = Number(match[1]), tail = match[2], run = runs.get(id);
      if (tail === 'events') return route.abort();
      if (tail && req.method() === 'POST') {
        if (tail === 'pause') run.paused = true;
        if (tail === 'continue') run.paused = false;
        if (tail === 'cancel') run.status = 'canceled';
        return route.fulfill({ json: { id, status: run.status, paused: run.paused } });
      }
      reads.push(id); return route.fulfill({ json: run });
    }
    const task = path.match(/\/tasks\/(\d+)$/);
    if (task) return route.fulfill({ json: tasks.find(t => t.id === Number(task[1])) });
    return route.fulfill({ json: { tasks: [], runs: [], templates: [], artifacts: [], pagination: { offset: 0, limit: 20, has_more: false } } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/coordinator');
  await expect(page.getByRole('heading', { name: '协调 Agent', exact: true })).toBeVisible();
  await expect(page.getByText('正在读取当前工作区任务…')).toHaveCount(0);
  return { tasks, runs, writes, reads, recoverStart: () => { failStart = false; }, workflow };
}

test('dispatches independently, recovers uncertain starts with the same key and retains results across navigation', async ({ page }) => {
  const f = await fixture(page, { failStart: true });
  const choose = (name: string) => page.getByRole('checkbox', { name, exact: true });
  await choose('选择任务 研究任务 1').check(); await choose('选择任务 研究任务 2').check();
  await page.getByRole('button', { name: '分发已选择任务', exact: true }).click();
  const cards = page.locator('.coordinator-run-card');
  await expect(cards).toHaveCount(2);
  await expect(cards.filter({ hasText: '研究任务 2' })).toContainText('分发暂时失败');
  expect(f.writes.filter(w => w.path.endsWith('/runs'))).toHaveLength(2);
  f.recoverStart(); await choose('选择任务 研究任务 2').check();
  await page.getByRole('button', { name: '分发已选择任务', exact: true }).click();
  await expect(cards.filter({ hasText: '研究任务 2' })).toContainText('Run #102');
  expect(f.writes[1].key).toBe(f.writes[2].key);
  f.runs.get(101).status = 'completed'; f.runs.get(101).nodes[0] = { ...f.runs.get(101).nodes[0], status: 'succeeded', output: { text: '已完成研究并生成报告' } };
  f.runs.get(102).status = 'waiting_human';
  await expect(cards.filter({ hasText: '研究任务 1' })).toContainText('已完成研究并生成报告', { timeout: 15000 });
  await expect(cards.filter({ hasText: '研究任务 2' })).toContainText('等待人工');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '智能体', exact: true }).click();
  f.runs.get(102).status = 'completed';
  await expect.poll(() => f.reads.filter(id => id === 102).length).toBeGreaterThan(0);
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '协调 Agent', exact: true }).click();
  await expect(cards).toHaveCount(2);
  await page.getByRole('button', { name: '刷新状态', exact: true }).click();
  await expect(cards).toHaveCount(2);
});

test('creates tasks and reusable templates with separate explicit saves', async ({ page }) => {
  const f = await fixture(page, { empty: true });
  await page.getByRole('button', { name: '创建任务', exact: true }).click();
  const form = page.getByRole('dialog', { name: '创建任务方案', exact: true });
  await form.getByLabel('任务名称', { exact: true }).fill('委派研究');
  await form.getByLabel('任务输入', { exact: true }).fill('调查竞争对手');
  await form.getByRole('button', { name: '设计工作流', exact: true }).click();
  await page.getByRole('button', { name: /添加节点/ }).click();
  await page.locator('.template-node').first().click();
  await page.getByLabel('节点 Agent', { exact: true }).selectOption('agent-1');
  await page.getByLabel('节点模型', { exact: true }).selectOption('model-1');
  await page.getByLabel('节点提示词', { exact: true }).fill('调查并生成报告');
  await page.getByRole('button', { name: '保存任务方案', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '选择任务 委派研究', exact: true })).toBeVisible();
  expect(f.writes.filter(w => w.path === '/api/hexa/tasks')).toHaveLength(1);
  expect(f.writes.filter(w => w.path.includes('/templates'))).toHaveLength(0);
  await page.getByRole('button', { name: '创建任务模板', exact: true }).click();
  await page.getByRole('button', { name: /添加节点/ }).click();
  await page.getByRole('button', { name: '保存模板新版本', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '模板已保存' })).toBeVisible();
  expect(f.writes.filter(w => w.path === '/api/hexa/templates')).toHaveLength(1);
  expect(f.writes.filter(w => w.path.endsWith('/runs'))).toHaveLength(0);
});

test('controls runs, reads extra tasks on demand and remains usable on mobile and dark theme', async ({ page }) => {
  const f = await fixture(page, { active: true });
  const first = page.locator('.coordinator-run-card').filter({ hasText: '研究任务 1' });
  await first.getByRole('button', { name: '暂停', exact: true }).click();
  await expect(first).toContainText('已暂停');
  await first.getByRole('button', { name: '继续', exact: true }).click();
  await expect(first.getByRole('button', { name: '暂停', exact: true })).toBeVisible();
  await first.getByRole('button', { name: '取消运行', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '取消运行', exact: true })).toBeVisible();
  await page.getByRole('dialog', { name: '取消运行', exact: true }).getByRole('button', { name: '确认取消', exact: true }).click();
  await expect(first).toContainText('已取消');
  await expect(page.getByRole('checkbox', { name: '选择任务 研究任务 22', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '加载更多任务', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '选择任务 研究任务 22', exact: true })).toBeVisible();
  await mkdir('.artifacts/coordinator', { recursive: true });
  await page.locator('.coordinator-page').evaluate(el => { el.scrollTop = 0; });
  await expect(page.getByRole('heading', { name: '协调 Agent', exact: true })).toBeInViewport();
  await page.screenshot({ path: '.artifacts/coordinator/desktop.png' });
  await page.getByRole('button', { name: '切换深色模式' }).click();
  await page.screenshot({ path: '.artifacts/coordinator/dark.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.coordinator-page').evaluate(el => { el.scrollTop = 0; });
  await expect(page.getByRole('button', { name: '创建任务', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: '.artifacts/coordinator/mobile.png', fullPage: true });
  expect(f.writes.filter(w => w.path.includes('/v1/'))).toHaveLength(0);
});
