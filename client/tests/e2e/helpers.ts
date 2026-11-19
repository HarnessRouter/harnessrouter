import { expect, type Browser, type Page } from '@playwright/test';

export type TaskNode = {
  id: string; name?: string; agent_id?: string; model?: string; prompt?: string; deps?: string[];
  inputRefs?: string[]; final_report?: boolean; requires_human?: boolean; node_type?: 'agent' | 'human' | 'human_gate'; allow_skip?: boolean; x?: number; y?: number;
};

export type Workflow = { nodes: TaskNode[] };

export const E2E_APP = process.env.HEXA_E2E_APP_URL || 'http://127.0.0.1:4020';
export const E2E_PASSWORD = process.env.HEXA_E2E_PASSWORD || 'integration-password';

export async function signIn(page: Page, password = E2E_PASSWORD) {
  await page.goto(`${E2E_APP}/`);
  const login = page.getByRole('dialog', { name: '登录 Hexa', exact: true });
  const signedIn = page.getByRole('button', { name: '用户菜单：admin', exact: true });
  await expect(login.or(signedIn).first()).toBeVisible({ timeout: 20000 });
  if (await login.isVisible()) {
    await login.getByLabel('密码', { exact: true }).fill(password);
    await login.getByRole('button', { name: '登录', exact: true }).click();
    await expect(login).toBeHidden();
  }
  // Pin a deterministic workspace. Workspace state is persisted server-side, and a
  // later selection would otherwise re-key the workbench while a modal is open.
  const spaces = await page.evaluate(async () => {
    const response = await fetch('/api/hexa/workspaces', { credentials: 'include' });
    return response.ok ? response.json() : null;
  }) as { workspaces?: Array<{ id: number; name: string }>; selected_id?: number | null } | null;
  const selected = spaces?.workspaces?.length ? spaces.selected_id ?? spaces.workspaces[0].id : null;
  if (spaces?.workspaces?.length && !spaces.selected_id) {
    await page.evaluate(async id => {
      await fetch('/api/hexa/workspaces/select', {
        method: 'POST', credentials: 'include',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ workspace_id: id }),
      });
    }, selected);
    await page.reload();
    await expect(page.getByRole('button', { name: '用户菜单：admin', exact: true })).toBeVisible({ timeout: 20000 });
  }
  if (selected !== null) {
    await expect(page.locator('.sidebar header small')).not.toHaveText('Hexa 工作空间', { timeout: 20000 });
  }
}

export async function openTasks(page: Page) {
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true }).click();
  await expect(page.getByRole('region', { name: '我的任务工作台' })).toBeVisible();
}

export async function newTask(page: Page, input: { title: string; description?: string; taskInput?: string }) {
  const dialog = page.getByRole('dialog', { name: '新建任务', exact: true });
  // The workbench is re-keyed when the selected workspace arrives from the API,
  // which can unmount an already-open modal. Retry the whole form until it sticks.
  for (let attempt = 0; ; attempt += 1) {
    await page.getByRole('region', { name: '任务列表区域' }).getByRole('button', { name: '新建任务', exact: true }).click();
    await expect(dialog).toBeVisible();
    try {
      await dialog.getByLabel('任务名称', { exact: true }).fill(input.title, { timeout: 8000 });
      if (input.description) await dialog.getByLabel('任务说明', { exact: true }).fill(input.description);
      await dialog.getByLabel('任务输入', { exact: true }).fill(input.taskInput || 'E2E 任务输入');
      await dialog.locator('form').evaluate(form => (form as HTMLFormElement).requestSubmit());
      break;
    } catch (cause) {
      if (attempt >= 2) throw cause;
    }
  }
  await expect(dialog).toBeHidden();
  const detail = page.getByRole('complementary', { name: '任务详情', exact: true });
  await expect(detail).toContainText(input.title, { timeout: 20000 });
  await expect(detail.getByRole('button', { name: '编辑流程', exact: true })).toBeEnabled();
  return detail;
}

/** Starts from the empty task workflow and saves exactly the requested node graph. */
export async function saveWorkflow(page: Page, workflow: Workflow, options: { expectRevision?: boolean } = {}) {
  const task = page.getByRole('complementary', { name: '任务详情', exact: true });
  const current = await revisionOf(task);
  await task.getByRole('button', { name: '编辑流程', exact: true }).click();
  const editor = page.getByRole('region', { name: '任务流程设计工作区' });
  await expect(editor).toBeVisible();

  if (workflow.nodes.length === 0) {
    await editor.getByRole('button', { name: '保存任务流程', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('名称和节点不能为空');
    return;
  }

  // The editor starts from the previous revision. Reduce it to exactly one node,
  // then rebuild the requested graph so the saved revision is not a merge.
  const nodeGroups = () => editor.getByRole('group', { name: /^节点 / });
  while (await nodeGroups().count() > 1) {
    await nodeGroups().last().click();
    await editor.getByRole('button', { name: /删除 节点/ }).click();
  }
  if (await nodeGroups().count() === 0) await editor.getByRole('button', { name: /添加节点/ }).click();

  const syncCheck = async (label: string, value: boolean | undefined) => {
    const box = editor.getByLabel(label, { exact: true });
    if (value) await box.check();
    else await box.uncheck();
  };

  for (const [index, node] of workflow.nodes.entries()) {
    if (index > 0) await editor.getByRole('button', { name: /添加节点/ }).click();
    await (index === 0 ? nodeGroups().first() : nodeGroups().last()).click();
    await editor.getByLabel('节点名称', { exact: true }).fill(node.name || node.id);
    await syncCheck('人工处理节点（不调用 Agent）', node.node_type === 'human' || node.node_type === 'human_gate');
    if (node.node_type !== 'human' && node.node_type !== 'human_gate') {
      if (node.agent_id) await editor.getByLabel('节点 Agent', { exact: true }).selectOption(node.agent_id);
      await expect(editor.getByLabel('节点模型', { exact: true })).toHaveValue(node.model || 'e2e-model');
      await editor.getByLabel('节点提示词', { exact: true }).fill(node.prompt || '');
      await syncCheck('执行 Agent 前人工确认输入', node.requires_human);
    }
    await syncCheck('最终报告', node.final_report);
    await syncCheck('允许跳过', node.allow_skip);
  }

  for (const node of workflow.nodes) {
    await editor.getByRole('group', { name: `节点 ${node.name || node.id}`, exact: true }).click();
    const dependencyBoxes = editor.locator('.dep-list label');
    const count = await dependencyBoxes.count();
    for (let index = 0; index < count; index += 1) {
      const checkbox = dependencyBoxes.nth(index).getByRole('checkbox');
      if (await checkbox.isChecked()) await checkbox.uncheck();
    }
    for (const dep of node.deps || []) {
      const source = workflow.nodes.find(item => item.id === dep);
      if (!source) continue;
      await dependencyBoxes.filter({ hasText: source.name || source.id }).getByRole('checkbox').check();
    }
  }

  for (const node of workflow.nodes) {
    if (!node.inputRefs?.length) continue;
    await editor.getByRole('group', { name: `节点 ${node.name || node.id}`, exact: true }).click();
    for (const ref of node.inputRefs || []) {
      const source = workflow.nodes.find(item => item.id === ref);
      if (!source) continue;
      const field = editor.locator('.field').filter({ hasText: '输入结果' });
      await field.locator('label').filter({ hasText: source.name || source.id }).getByRole('checkbox').check();
    }
  }

  await editor.getByRole('button', { name: '保存任务流程', exact: true }).click();
  if (options.expectRevision !== false) await expect(task).toContainText(`当前工作流 · v${current + 1}`);
}

export async function revisionOf(task: ReturnType<Page['getByRole']>) {
  const head = await task.locator('.detail-section-head strong').filter({ hasText: '当前工作流' }).textContent();
  return Number(head?.match(/v(\d+)/)?.[1] || 1);
}

export async function generateWorkflowViaAi(page: Page, requirement: string) {
  const task = page.getByRole('complementary', { name: '任务详情', exact: true });
  const before = await task.locator('.detail-section-head strong').filter({ hasText: '当前工作流' }).textContent();
  const current = Number(before?.match(/v(\d+)/)?.[1] || 1);
  await task.getByRole('button', { name: '编辑流程', exact: true }).click();
  const editor = page.getByRole('region', { name: '任务流程设计工作区' });
  await editor.getByRole('tab', { name: 'AI 生成', exact: true }).click();
  await editor.getByLabel('AI 生成要求', { exact: true }).fill(requirement);
  await editor.getByRole('button', { name: '生成流程图', exact: true }).click();
  await expect(editor.getByRole('group', { name: /节点 / }).first()).toBeVisible();
  await editor.getByRole('button', { name: '保存任务流程', exact: true }).click();
  await expect(task).toContainText(`当前工作流 · v${current + 1}`);
}

export async function api<T = any>(page: Page, path: string, init: { method?: string; body?: unknown } = {}): Promise<{ status: number; body: T }> {
  return page.evaluate(async ({ path, init }) => {
    const response = await fetch(path, {
      method: init.method || 'GET',
      headers: init.body === undefined ? undefined : { 'content-type': 'application/json' },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
    const text = await response.text();
    return { status: response.status, body: text ? JSON.parse(text) : null };
  }, { path, init });
}

/** Logs in once and shares the HttpOnly session cookie with a second browser context. */
export async function secondSession(browser: Browser, page: Page) {
  const cookies = await page.context().cookies();
  const context = await browser.newContext();
  await context.addCookies(cookies);
  const other = await context.newPage();
  await other.goto(`${E2E_APP}/`);
  return { context, page: other };
}
