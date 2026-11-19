import { test, expect } from '@playwright/test';
import { api, signIn } from './helpers';

test('coordinator dispatches two persisted workflows, observes SSE and restores reports after reload', async ({ page }) => {
  await signIn(page);
  const spaces = await api(page, '/api/hexa/workspaces');
  const workspaceId = spaces.body.selected_id ?? null;
  const names = [`协调研究 A ${Date.now()}`, `协调研究 B ${Date.now()}`];
  const created = [];
  for (const title of names) {
    const result = await api(page, '/api/hexa/tasks', { method: 'POST', body: {
      title, workspace_id: workspaceId, input: title,
      workflow: { nodes: [{ id: 'report', name: '专业研究', agent_id: 'e2e-agent', model: 'e2e-model', prompt: `E2E_OUT:${title}\nE2E_SLOW:3`, deps: [], final_report: true }] },
    } });
    expect(result.status).toBe(201); created.push(result.body);
  }
  const browserRequests: string[] = [];
  page.on('request', req => browserRequests.push(new URL(req.url()).pathname));
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '协调 Agent', exact: true }).click();
  for (const name of names) await page.getByRole('checkbox', { name: `选择任务 ${name}`, exact: true }).check();
  await page.getByRole('button', { name: '分发已选择任务', exact: true }).click();
  for (const name of names) {
    const card = page.getByRole('article', { name: `${name}运行汇报`, exact: true });
    await expect(card).toContainText('已完成', { timeout: 45000 });
    await expect(card.locator('.coordinator-output')).toContainText(name);
  }
  const details = [];
  for (const task of created) {
    const detail = await api(page, `/api/hexa/tasks/${task.id}`);
    expect(detail.body.workflow_state).toBe('saved');
    const run = await api(page, `/api/hexa/runs/${detail.body.latest_run_id}`);
    expect(run.body.status).toBe('completed');
    expect(run.body.task_id).toBe(task.id);
    expect(run.body.workflow_revision_id).toBe(detail.body.current_revision_id);
    details.push(run.body.id);
  }
  expect(new Set(details).size).toBe(2);
  expect(details.every(id => browserRequests.includes(`/api/hexa/runs/${id}/events`))).toBe(true);
  expect(browserRequests.some(path => path.startsWith('/v1/'))).toBe(false);
  await page.goto('/coordinator');
  for (const name of names) await expect(page.getByRole('article', { name: `${name}运行汇报`, exact: true })).toContainText('已完成', { timeout: 20000 });
});
