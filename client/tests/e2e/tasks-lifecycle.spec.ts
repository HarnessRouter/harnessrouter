import { test, expect, type Page } from '@playwright/test';
import { api, E2E_APP, newTask, openTasks, revisionOf, saveWorkflow, signIn, type TaskNode } from './helpers';

const artifactDownload = async (page: Page, artifacts: ReturnType<Page['getByRole']>) => {
  const response = page.waitForResponse(row => /\/api\/hexa\/artifacts\/\d+\/content$/.test(new URL(row.url()).pathname));
  const download = page.waitForEvent('download');
  await artifacts.getByRole('button', { name: /下\s*载/ }).first().click();
  const [res, file] = await Promise.all([response, download]);
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toBe('application/octet-stream');
  expect(res.headers()['content-disposition']).toMatch(/^attachment;/);
  expect(res.headers()['x-content-type-options']).toBe('nosniff');
  expect(file.suggestedFilename()).toBe('report.txt');
};

const openRunFlow = async (page: Page) => {
  const run = page.getByRole('complementary', { name: '运行详情', exact: true });
  await run.getByRole('button', { name: '打开流程图', exact: true }).click();
  return page.getByRole('main', { name: '运行流程图' });
};

const finishRun = async (page: Page, detailName = '运行详情') => {
  const run = page.getByRole('complementary', { name: detailName, exact: true });
  await expect(run.locator('.run-detail-head')).toContainText('已完成', { timeout: 40000 });
  return run;
};

/** Reloads the run route so run/task artifact lists are fetched after the run completed. */
const reopenRun = async (page: Page, runId: number) => {
  await page.goto(`${E2E_APP}/runs/${runId}`);
  const run = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(run.locator('.run-detail-head')).toContainText('已完成', { timeout: 40000 });
  return run;
};

test('blank task to workflow, execution, artifacts, adopt, save-as-template and template reuse', async ({ page }) => {
  const writes: string[] = [];
  const gatewayPaths: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') writes.push(`${request.method()} ${path}`);
    if (path.startsWith('/v1/')) gatewayPaths.push(path);
  });
  await signIn(page);
  await openTasks(page);
  const title = `E2E 主链路 ${Date.now()}`;
  const detail = await newTask(page, { title, description: '完整 E2E 主链路', taskInput: 'E2E_OUT:主链路输出' });
  await expect(detail).toContainText('无来源模板');
  await expect(detail).toContainText('尚未运行');
  await expect(detail.getByRole('button', { name: '查看运行记录', exact: true })).toBeDisabled();

  await detail.getByRole('button', { name: '编辑流程', exact: true }).click();
  const emptyEditor = page.getByRole('region', { name: '任务流程设计工作区' });
  await emptyEditor.getByRole('button', { name: '保存任务流程', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('名称和节点不能为空');
  await emptyEditor.getByRole('button', { name: '返回任务详情', exact: true }).click();

  const workflow = {
    nodes: [
      { id: 'node-1', name: '资料收集', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:收集结果' },
      { id: 'node-2', name: '风险分析', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:风险结果', deps: ['node-1'], inputRefs: ['node-1'] },
      { id: 'node-3', name: '汇总报告', agent_id: 'e2e-agent', model: 'e2e-model', prompt: '输出最终报告', deps: ['node-2'], inputRefs: ['node-2'], final_report: true },
    ] satisfies TaskNode[],
  };
  await saveWorkflow(page, workflow);
  await expect(detail).toContainText('3 个节点');

  const images = await api(page, '/api/hexa/tasks?offset=0&limit=100');
  const created = images.body.tasks.find((row: { title: string }) => row.title === title);
  expect(created.workflow.nodes.map((node: TaskNode) => node.name)).toEqual(['资料收集', '风险分析', '汇总报告']);
  expect(created.current_revision).toBe(2);

  await detail.getByRole('button', { name: '运行', exact: true }).click();
  const confirm = page.getByRole('dialog', { name: '确认运行任务', exact: true });
  await expect(confirm.getByLabel('本次任务输入', { exact: true })).toHaveValue('E2E_OUT:主链路输出');
  await confirm.getByRole('button', { name: '确认运行', exact: true }).click();
  const finished = await finishRun(page);
  const runId = Number((await finished.locator('.run-detail-head').textContent())?.match(/Run #(\d+)/)?.[1]);
  const run = await reopenRun(page, runId);

  const artifacts = run.getByRole('region', { name: '任务产物' });
  await expect(artifacts).toContainText('report.txt');
  const artifactsResponse = await api(page, `/api/hexa/tasks/${created.id}/artifacts?limit=50`);
  expect(artifactsResponse.body.artifacts.length).toBeGreaterThan(0);
  expect(JSON.stringify(artifactsResponse.body)).not.toContain('gateway_file_id');
  await artifactDownload(page, artifacts);

  const graph = await openRunFlow(page);
  await graph.getByRole('button', { name: '汇总报告 节点', exact: true }).click();
  await page.getByRole('tab', { name: '调试', exact: true }).click();
  const properties = page.getByRole('complementary', { name: '运行属性', exact: true });
  await expect(properties).toContainText('REFS:node-2');
  await expect(properties).toContainText('E2E-OUT:风险结果');
  await page.getByRole('tab', { name: '节点', exact: true }).click();
  await properties.getByRole('button', { name: '采用为当前结果', exact: true }).click();
  await page.getByRole('button', { name: '返回运行详情', exact: true }).click();
  await run.getByRole('button', { name: '返回所属任务', exact: true }).click();
  await expect(detail.getByRole('region', { name: '任务结果' })).toContainText('已采用 1 项');

  await detail.getByRole('button', { name: '保存为模板', exact: true }).click();
  const save = page.getByRole('dialog', { name: '保存为模板', exact: true });
  await expect(save.getByLabel('保存模板目标')).toHaveValue('');
  await save.getByRole('button', { name: '保存模板', exact: true }).click();
  await expect(save).toBeHidden();
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /模板管理/ }).click();
  const templateDetail = page.getByRole('complementary', { name: '模板详情', exact: true });
  await expect(templateDetail).toContainText(title);
  await expect(templateDetail).toContainText('当前版本 v1');

  await templateDetail.getByRole('button', { name: '使用此模板', exact: true }).click();
  const form = page.getByRole('dialog', { name: '新建任务', exact: true });
  await expect(form.getByLabel('任务名称', { exact: true })).toHaveValue(title);
  await form.getByLabel('任务名称', { exact: true }).fill(`${title}-副本`);
  await form.getByRole('button', { name: '创建任务', exact: true }).click();
  await expect(detail).toContainText('来源模板：#');
  await expect(detail).toContainText('尚未运行');
  expect(writes.some(row => /POST \/api\/hexa\/tasks\/\d+\/runs$/.test(row))).toBe(true);
  expect(gatewayPaths).toEqual([]);
  await expect(page.locator('body')).not.toContainText('{{SECRET');
});

test('parallel collectors, human gate, pause, cancel and active-run locking', async ({ page }) => {
  await signIn(page);
  await openTasks(page);
  const title = `E2E 人工门控 ${Date.now()}`;
  const detail = await newTask(page, { title, taskInput: '并行调查任务' });
  const collectors: TaskNode[] = ['一线', '二线', '三线', '四线', '五线'].map((name, index) => ({
    id: `node-${index + 1}`,
    name: `调查${name}`,
    agent_id: 'e2e-agent',
    model: 'e2e-model',
    prompt: `E2E_OUT:${name}结论`,
  }));
  await saveWorkflow(page, {
    nodes: [
      ...collectors,
      { id: 'node-6', name: '人工汇总裁决', agent_id: 'e2e-agent', model: 'e2e-model', prompt: '汇总选定结果', deps: collectors.map(node => node.id), inputRefs: ['node-1', 'node-2'], requires_human: true, final_report: true },
    ],
  });

  await detail.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const run = page.getByRole('complementary', { name: '运行详情', exact: true });
  const gate = run.getByRole('region', { name: '人工确认' });
  await expect(gate).toBeVisible({ timeout: 30000 });
  for (const name of ['调查一线', '调查二线', '调查三线', '调查四线', '调查五线']) await expect(run).toContainText(name);
  await expect(gate.getByRole('button', { name: '确认并继续', exact: true })).toBeDisabled();
  await gate.getByLabel('调查一线', { exact: true }).check();
  await gate.getByLabel('调查二线', { exact: true }).check();
  await gate.getByRole('button', { name: '确认并继续', exact: true }).click();
  await finishRun(page);
  await expect(run.locator('.run-metrics')).toContainText('人工决定1 项');

  const runs = await api(page, `/api/hexa/tasks/${(await api(page, '/api/hexa/tasks?offset=0&limit=100')).body.tasks.find((row: { title: string }) => row.title === title).id}/runs`);
  const runId = runs.body.runs[0].id;
  const snapshot = await api(page, `/api/hexa/runs/${runId}`);
  expect(snapshot.body.decisions).toEqual([{ node_id: 'node-6', input_refs: ['node-1', 'node-2'] }]);
  const gateNode = snapshot.body.nodes.find((node: { node_id: string }) => node.node_id === 'node-6');
  expect(gateNode.input.refs.map((ref: { node_id: string }) => ref.node_id)).toEqual(['node-1', 'node-2']);
  expect(gateNode.output.text).toContain('REFS:node-1,node-2');

  const graph = await openRunFlow(page);
  await graph.getByRole('button', { name: '人工汇总裁决 节点', exact: true }).click();
  await page.getByRole('tab', { name: '调试', exact: true }).click();
  await expect(page.getByRole('complementary', { name: '运行属性', exact: true })).toContainText('REFS:node-1,node-2');
  await page.getByRole('button', { name: '返回运行详情', exact: true }).click();
  await run.getByRole('button', { name: '返回所属任务', exact: true }).click();

  const locking = await newTask(page, { title: `${title}-锁定`, taskInput: 'E2E_RUNNING 长时间运行' });
  await saveWorkflow(page, { nodes: [{ id: 'node-1', name: '长任务', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_RUNNING' }] });
  await locking.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const running = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(running.locator('.run-detail-head')).toContainText('运行中', { timeout: 30000 });
  const lockedTask = (await api(page, '/api/hexa/tasks?offset=0&limit=100')).body.tasks.find((row: { title: string }) => row.title === `${title}-锁定`);
  const blocked = await page.evaluate(async ({ taskId, revision }) => {
    const response = await fetch(`/api/hexa/tasks/${taskId}/workflow`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ expected_revision: revision, workflow: { nodes: [] } }) });
    return { status: response.status, body: await response.json() };
  }, { taskId: lockedTask.id, revision: lockedTask.current_revision });
  expect(blocked.status).toBe(409);
  expect(blocked.body.detail.code).toBe('active_run_exists');

  await running.getByRole('button', { name: '暂停运行', exact: true }).click();
  await expect(running.locator('.run-detail-head')).toContainText('已暂停');
  await running.getByRole('button', { name: '继续运行', exact: true }).click();
  await expect(running.locator('.run-detail-head')).toContainText('运行中');
  await running.getByRole('button', { name: '取消运行', exact: true }).click();
  await expect(running.locator('.run-detail-head')).toContainText('已取消');
  const canceled = (await api(page, '/api/hexa/tasks?offset=0&limit=100')).body.tasks.find((row: { title: string }) => row.title === `${title}-锁定`);
  expect(canceled.status).toBe('waiting');
  await running.getByRole('button', { name: '返回所属任务', exact: true }).click();
  await expect(locking.getByRole('button', { name: '编辑流程', exact: true })).toBeEnabled();
});

test('explicit human node pauses the run until the user confirms it', async ({ page }) => {
  await signIn(page);
  await openTasks(page);
  const title = `E2E 显式人工节点 ${Date.now()}`;
  const detail = await newTask(page, { title, taskInput: '等待人工审核' });
  await saveWorkflow(page, { nodes: [
    { id: 'collect', name: '资料收集', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:资料完成' },
    { id: 'review', name: '人工审核', node_type: 'human', deps: ['collect'], inputRefs: ['collect'], final_report: true },
  ] });

  await detail.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const run = page.getByRole('complementary', { name: '运行详情', exact: true });
  const gate = run.getByRole('region', { name: '人工确认' });
  await expect(gate).toBeVisible({ timeout: 30000 });
  await expect(run.locator('.run-detail-head')).toContainText('等待确认');
  const runId = Number((await run.locator('.run-detail-head').textContent())?.match(/Run #(\d+)/)?.[1]);
  const snapshot = await api(page, `/api/hexa/runs/${runId}`);
  expect(snapshot.status).toBe(200);
  const reviewNode = snapshot.body.workflow.nodes.find((node: { name: string }) => node.name === '人工审核');
  expect(reviewNode).toMatchObject({ node_type: 'human', requires_human: false });
  const reviewId = reviewNode.id;
  expect(snapshot.body.nodes.find((node: { node_id: string }) => node.node_id === reviewId).status).toBe('idle');
  expect(snapshot.body.decisions).toEqual([]);
  await page.goto(`${E2E_APP}/runs/${runId}`);
  await expect(gate).toBeVisible();
  await page.reload();
  await expect(gate).toBeVisible();
  await expect(run.locator('.run-detail-head')).toContainText('等待确认');
  const restored = await api(page, `/api/hexa/runs/${runId}`);
  expect(restored.body.status).toBe('waiting_human');
  expect(restored.body.decisions).toEqual([]);
  expect(restored.body.nodes.find((node: { node_id: string }) => node.node_id === reviewId)).toMatchObject({ status: 'idle', output: null });
  await expect(gate.getByRole('button', { name: '确认并继续', exact: true })).toBeDisabled();
  await gate.getByLabel('资料收集', { exact: true }).check();
  await gate.getByRole('button', { name: '确认并继续', exact: true }).click();
  await finishRun(page);
  const finished = await api(page, `/api/hexa/runs/${runId}`);
  expect(finished.body.id).toBe(runId);
  expect(finished.body.decisions).toEqual([{ node_id: reviewId, input_refs: reviewNode.deps }]);
  expect(finished.body.nodes.find((node: { node_id: string }) => node.node_id === reviewId)).toMatchObject({ status: 'succeeded', response_id: null, output: { selected_input_refs: reviewNode.deps, status: 'confirmed' } });
});

test('workflow revisions keep historical run snapshots and replay never writes', async ({ page }) => {
  const writes: string[] = [];
  page.on('request', request => { if (request.method() !== 'GET') writes.push(`${request.method()} ${new URL(request.url()).pathname}`); });
  await signIn(page);
  await openTasks(page);
  const title = `E2E 版本快照 ${Date.now()}`;
  const detail = await newTask(page, { title, taskInput: '版本一输入' });
  await saveWorkflow(page, { nodes: [
    { id: 'node-1', name: '第一版分析', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:版本一分析' },
    { id: 'node-2', name: '第一版报告', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:版本一', deps: ['node-1'], inputRefs: ['node-1'], final_report: true },
  ] });
  await detail.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const runA = await finishRun(page);
  const runAId = Number((await runA.locator('.run-detail-head').textContent())?.match(/Run #(\d+)/)?.[1]);
  await runA.getByRole('button', { name: '返回所属任务', exact: true }).click();

  await detail.getByRole('button', { name: '重新打开任务', exact: true }).click();
  await expect.poll(async () => revisionOf(detail)).toBe(2);
  await saveWorkflow(page, { nodes: [
    { id: 'node-1', name: '第二版分析', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:版本二分析' },
    { id: 'node-2', name: '第二版报告', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:版本二', deps: ['node-1'], inputRefs: ['node-1'], final_report: true },
  ] });
  await expect(detail).toContainText('当前工作流 · v3');
  await detail.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByLabel('本次任务输入', { exact: true }).fill('版本二输入');
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const runB = await finishRun(page);
  await expect(runB.locator('.run-detail-head')).toContainText('Workflow v3');

  const task = (await api(page, '/api/hexa/tasks?offset=0&limit=100')).body.tasks.find((row: { title: string }) => row.title === title);
  const history = await api(page, `/api/hexa/tasks/${task.id}/runs`);
  expect(history.body.runs).toHaveLength(2);
  expect(history.body.runs.map((row: { workflow_revision: number }) => row.workflow_revision).sort()).toEqual([2, 3]);
  const first = await api(page, `/api/hexa/runs/${runAId}`);
  expect(first.body.workflow.nodes[0].name).toBe('第一版分析');
  expect(first.body.nodes[0].input.task_input).toBe('版本一输入');
  const second = await api(page, `/api/hexa/runs/${history.body.runs[0].id}`);
  expect(second.body.workflow.nodes[0].name).toBe('第二版分析');
  expect(second.body.nodes[0].input.task_input).toBe('版本二输入');

  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /运行记录/ }).click();
  await page.getByRole('row', { name: new RegExp(`${title}.*Run #${runAId}`) }).click();
  const historyRun = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(historyRun).toContainText('Workflow v2');
  const graph = await openRunFlow(page);
  await expect(graph.getByRole('button', { name: '第一版分析 节点', exact: true })).toBeVisible();
  await expect(graph.getByRole('button', { name: '第二版分析 节点', exact: true })).toHaveCount(0);

  const beforeWrites = writes.length;
  const node = graph.getByRole('button', { name: '第一版分析 节点', exact: true });
  const origin = (await node.boundingBox())!;
  const edgeBefore = await graph.locator('.react-flow__edge').first().getAttribute('x1');
  await page.mouse.move(origin.x + 40, origin.y + 30);
  await page.mouse.down();
  await page.mouse.move(origin.x + 150, origin.y + 100, { steps: 6 });
  await page.mouse.up();
  expect((await node.boundingBox())!.x).toBeGreaterThan(origin.x + 40);
  if (edgeBefore) expect(await graph.locator('.react-flow__edge').first().getAttribute('x1')).not.toBe(edgeBefore);
  await graph.getByRole('button', { name: '重放', exact: true }).click();
  await page.getByRole('tab', { name: '运行', exact: true }).click();
  await page.getByRole('slider', { name: '重放进度' }).fill('0');
  await page.getByRole('tab', { name: '节点', exact: true }).click();
  await expect(page.getByRole('complementary', { name: '运行属性', exact: true })).toContainText('尚无节点事件');
  await graph.getByRole('button', { name: '返回最新', exact: true }).click();
  expect(writes.length).toBe(beforeWrites);

  await page.reload();
  await expect(page.getByRole('complementary', { name: '运行详情', exact: true })).toContainText('Workflow v2');
  const refreshed = await openRunFlow(page);
  const restored = (await refreshed.getByRole('button', { name: '第一版分析 节点', exact: true }).boundingBox())!;
  expect(Math.abs(restored.x - origin.x)).toBeLessThan(4);
});

test('template versions do not upgrade existing tasks and save-as-template stays explicit', async ({ page }) => {
  await signIn(page);
  await openTasks(page);
  const title = `E2E 模板来源 ${Date.now()}`;
  const detail = await newTask(page, { title, taskInput: '模板来源输入' });
  const originalTaskId = Number((await detail.locator('.task-detail-id').textContent())?.match(/\d+/)?.[0]);
  await saveWorkflow(page, { nodes: [{ id: 'node-1', name: '来源流程节点', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:来源版本一', final_report: true }] });
  await detail.getByRole('button', { name: '保存为模板', exact: true }).click();
  const save = page.getByRole('dialog', { name: '保存为模板', exact: true });
  await save.getByRole('button', { name: '保存模板', exact: true }).click();
  await expect(save).toBeHidden();

  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /模板管理/ }).click();
  const templateDetail = page.getByRole('complementary', { name: '模板详情', exact: true });
  await expect(templateDetail).toContainText(title);
  await templateDetail.getByRole('button', { name: '编辑模板', exact: true }).click();
  const editor = page.getByRole('region', { name: '模板设计工作区' });
  await editor.getByRole('group', { name: '节点 来源流程节点', exact: true }).click();
  await editor.getByLabel('节点名称', { exact: true }).fill('升级后模板节点');
  await editor.getByRole('button', { name: '保存模板新版本', exact: true }).click();
  await expect(templateDetail).toContainText('当前版本 v2');
  await expect(templateDetail.locator('.template-version-list')).toContainText('v1');
  await expect(templateDetail.locator('.template-version-list')).toContainText('v2');

  const templates = (await api(page, '/api/hexa/templates?offset=0&limit=100')).body.templates;
  const template = templates.find((row: { title: string }) => row.title === title);
  expect(template.versions.map((row: { version: number }) => row.version)).toEqual([1, 2]);
  await expect(templateDetail).not.toContainText('E2E_OUT');

  await templateDetail.getByRole('button', { name: '使用此模板', exact: true }).click();
  const create = page.getByRole('dialog', { name: '新建任务', exact: true });
  await expect(create.getByLabel('来源模板', { exact: true })).toHaveValue(String(template.versions[1].id));
  await create.getByLabel('任务名称', { exact: true }).fill(`${title}-v2任务`);
  await create.getByRole('button', { name: '创建任务', exact: true }).click();
  await expect(detail).toContainText('来源模板：#' + template.id);
  await expect(detail).toContainText(`v${template.versions[1].version}`);
  await expect(detail).toContainText('升级后模板节点');

  await page.goto(`${E2E_APP}/tasks/${originalTaskId}`);
  await expect(detail).toContainText('来源流程节点');
  await expect(detail).toContainText('当前工作流 · v2');
  await detail.getByRole('button', { name: '保存为模板', exact: true }).click();
  const append = page.getByRole('dialog', { name: '保存为模板', exact: true });
  await expect(append.getByLabel('保存模板目标')).toHaveValue('');
  await append.getByLabel('保存模板目标').selectOption(String(template.id));
  await append.getByRole('button', { name: '保存模板', exact: true }).click();
  await expect(append).toBeHidden();
  const appended = (await api(page, `/api/hexa/templates/${template.id}`)).body;
  expect(appended.versions.map((row: { version: number }) => row.version)).toEqual([1, 2, 3]);
  expect(appended.versions[2].workflow.nodes[0].name).toBe('来源流程节点');
});

test('failed run reaches failed state, reopen plus rerun creates a new Run and keeps history', async ({ page }) => {
  await signIn(page);
  await openTasks(page);
  const title = `E2E 失败恢复 ${Date.now()}`;
  const detail = await newTask(page, { title, taskInput: '失败恢复输入' });
  await saveWorkflow(page, { nodes: [{ id: 'node-1', name: '易失败节点', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_FAIL:recover-once E2E_OUT:首次执行', final_report: true }] });
  await detail.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const failedRun = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(failedRun.locator('.run-detail-head')).toContainText('失败', { timeout: 30000 });
  const failedId = Number((await failedRun.locator('.run-detail-head').textContent())?.match(/Run #(\d+)/)?.[1]);
  await failedRun.getByRole('button', { name: '返回所属任务', exact: true }).click();
  await expect(detail).toContainText('失败');
  await expect(detail).toContainText(`Run #${failedId} · 失败`);

  await detail.getByRole('button', { name: '重新打开任务', exact: true }).click();
  await expect.poll(async () => revisionOf(detail)).toBe(2);
  await saveWorkflow(page, { nodes: [{ id: 'node-1', name: '易失败节点', agent_id: 'e2e-agent', model: 'e2e-model', prompt: 'E2E_OUT:恢复成功', final_report: true }] });
  await detail.getByRole('button', { name: '运行', exact: true }).click();
  await page.getByRole('dialog', { name: '确认运行任务', exact: true }).getByRole('button', { name: '确认运行', exact: true }).click();
  const recovered = await finishRun(page);
  const recoveredId = Number((await recovered.locator('.run-detail-head').textContent())?.match(/Run #(\d+)/)?.[1]);
  expect(recoveredId).toBeGreaterThan(failedId);
  await recovered.getByRole('button', { name: '返回所属任务', exact: true }).click();
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /运行记录/ }).click();
  await expect(page.getByRole('row', { name: new RegExp(`${title}.*Run #${failedId}`) })).toBeVisible();
  await expect(page.getByRole('row', { name: new RegExp(`${title}.*Run #${recoveredId}`) })).toBeVisible();
  const task = (await api(page, '/api/hexa/tasks?offset=0&limit=100')).body.tasks.find((row: { title: string }) => row.title === title);
  const history = await api(page, `/api/hexa/tasks/${task.id}/runs`);
  expect(history.body.runs).toHaveLength(2);
  await page.goto(`${E2E_APP}/runs/${failedId}`);
  await expect(page.getByRole('complementary', { name: '运行详情', exact: true })).toContainText('Workflow v2');
  await page.getByRole('complementary', { name: '运行详情', exact: true }).getByRole('button', { name: '返回所属任务', exact: true }).click();
  await expect(detail).toContainText('已完成');
});

test('mobile task workbench keeps one column, a bounded drawer and 44px touch targets', async ({ page }) => {
  await signIn(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await openTasks(page);
  await expect(page.getByRole('region', { name: '我的任务工作台' })).toBeVisible();
  await expect(page.getByRole('complementary', { name: '任务详情', exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  const row = page.getByRole('row').filter({ has: page.locator('.table-title') }).first();
  if (await row.count()) {
    await row.click();
    const drawer = page.getByRole('dialog', { name: '任务详情', exact: true });
    await expect(drawer).toBeVisible();
    await expect.poll(async () => (await drawer.boundingBox())!.width).toBeLessThanOrEqual(390);
    await drawer.getByRole('button', { name: '关闭任务详情', exact: true }).click();
  }
  const filter = page.getByRole('group', { name: '任务状态筛选' }).getByRole('button').first();
  expect((await filter.boundingBox())!.height).toBeGreaterThanOrEqual(34);
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '对话', exact: true }).click();
  expect(await page.getByRole('textbox', { name: '消息输入' }).evaluate(element => Number.parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16);
});
