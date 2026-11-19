import { test, expect } from '@playwright/test';
import { taskFixture } from '../task-fixture';
import { mkdir } from 'node:fs/promises';

const enter = async (page: import('@playwright/test').Page) => {
  await page.goto('/');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true }).click();
};
const artifact = (id: number, filename = `report-${id}.txt`) => ({ id, task_id: 71, run_id: 18, node_run_id: 1, filename, media_type: 'text/plain', bytes: 8 });

test('task and run pages load only when requested and server search reaches unseen records', async ({ page }) => {
  const fixture = await taskFixture(page);
  for (let i = 0; i < 25; i++) fixture.tasks.push({ ...fixture.tasks[2], id: 1000 + i, title: `分页任务 ${i}` });
  const requests: string[] = [];
  page.on('request', request => { if (request.url().includes('/api/hexa/')) requests.push(request.url()); });
  await page.goto('/');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true }).click();
  await expect(page.getByRole('row', { name: /分页任务 15/ })).toBeVisible();
  expect(requests.some(url => url.includes('offset=20'))).toBe(false);
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.getByRole('row', { name: /分页任务 24/ })).toBeVisible();
  await page.getByRole('textbox', { name: '搜索任务' }).fill('分页任务 24');
  await expect(page.getByRole('row', { name: /分页任务 24/ })).toBeVisible();
  await expect(page.getByRole('row', { name: /分页任务 23/ })).toHaveCount(0);
  expect(requests.some(url => new URL(url).searchParams.get('q') === '分页任务 24')).toBe(true);
  expect(requests.filter(url => /\/tasks\/\d+\/runs/.test(url))).toEqual([]);
});

test('template use and edit read the latest version without draining history pages', async ({ page }) => {
  await taskFixture(page, { paginatedTemplateVersions: true });
  const requests: string[] = [];
  page.on('request', req => requests.push(req.url()));
  await page.goto('/');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true }).click();
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /模板管理/ }).click();
  const detail = page.getByRole('complementary', { name: '模板详情' });
  await expect(detail).toContainText('当前版本 v3');
  await detail.getByRole('button', { name: '使用此模板' }).click();
  await expect(page.getByRole('dialog', { name: '新建任务', exact: true }).getByLabel('来源模板')).toHaveValue('303');
  expect(requests.some(url => new URL(url).searchParams.get('versions_offset') === '1')).toBe(false);
});

test('list append failure preserves rows and retries the same server offset', async ({ page }) => {
  const fixture = await taskFixture(page);
  for (let i = 0; i < 25; i++) fixture.tasks.push({ ...fixture.tasks[2], id: 1000 + i, title: `追加任务 ${i}` });
  const offsets: number[] = [];
  let fail = true;
  await page.route('**/api/hexa/tasks?*', route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
    offsets.push(offset);
    if (offset === 20 && fail) { fail = false; return route.fulfill({ status: 503, json: { detail: '追加页暂时不可用' } }); }
    return route.fallback();
  });
  await enter(page);
  await expect(page.getByRole('row', { name: /追加任务 15/ })).toBeVisible();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('追加页暂时不可用');
  await expect(page.getByRole('row', { name: /追加任务 15/ })).toBeVisible();
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.getByRole('row', { name: /追加任务 24/ })).toBeVisible();
  expect(offsets).toEqual([0, 20, 20]);
});

for (const kind of ['task', 'run'] as const) {
  test(`${kind} artifacts append on demand and retry without losing loaded files`, async ({ page }) => {
    await taskFixture(page);
    const offsets: number[] = [];
    let fail = true;
    await page.route(`**/api/hexa/${kind === 'task' ? 'tasks/71' : 'runs/20'}/artifacts?*`, route => {
      const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
      offsets.push(offset);
      if (offset === 50 && fail) { fail = false; return route.fulfill({ status: 503, json: { detail: '产物追加失败' } }); }
      return route.fulfill({ json: { artifacts: offset === 0 ? [artifact(1)] : [artifact(1), artifact(2)], pagination: { offset, limit: 50, has_more: offset === 0 } } });
    });
    await enter(page);
    if (kind === 'run') await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /运行记录/ }).click();
    const detail = page.getByRole('complementary', { name: kind === 'task' ? '任务详情' : '运行详情', exact: true });
    await expect(detail.getByText('report-1.txt', { exact: true })).toBeVisible();
    expect(offsets).toEqual([0]);
    await detail.getByRole('button', { name: '加载更多产物' }).click();
    await expect(detail.getByRole('alert')).toContainText('产物追加失败');
    await expect(detail.getByText('report-1.txt', { exact: true })).toBeVisible();
    await detail.getByRole('button', { name: '重试加载产物' }).click();
    await expect(detail.getByText('report-2.txt', { exact: true })).toBeVisible();
    await expect(detail.getByText('report-1.txt', { exact: true })).toHaveCount(1);
    await expect(detail.getByRole('button', { name: '加载更多产物' })).toHaveCount(0);
    expect(offsets).toEqual([0, 50, 50]);
  });

  test(`${kind} switching ignores delayed artifact responses`, async ({ page }) => {
    await taskFixture(page);
    let release!: () => void;
    const pending = new Promise<void>(resolve => { release = resolve; });
    let started!: () => void;
    const requested = new Promise<void>(resolve => { started = resolve; });
    const path = kind === 'task' ? 'tasks/71' : 'runs/20';
    await page.route(`**/api/hexa/${path}/artifacts?*`, async route => {
      started(); await pending;
      await route.fulfill({ json: { artifacts: [artifact(999, '旧对象产物.txt')], pagination: { offset: 0, limit: 50, has_more: false } } });
    });
    await enter(page);
    if (kind === 'run') await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /运行记录/ }).click();
    await requested;
    await page.getByRole('row', { name: kind === 'task' ? /产品方案评估/ : /Run #19/ }).click();
    const response = page.waitForResponse(res => res.url().includes(`/${path}/artifacts?`));
    release(); await response;
    const detail = page.getByRole('complementary', { name: kind === 'task' ? '任务详情' : '运行详情', exact: true });
    await expect(detail.getByRole('heading', { name: '产品方案评估' })).toBeVisible();
    await expect(detail).not.toContainText('旧对象产物.txt');
  });
}

test('node debug attempts and artifacts load additional pages only on request', async ({ page }) => {
  const fixture = await taskFixture(page);
  const node = fixture.runs[0].nodes[0], offsets: number[] = [];
  await page.route('**/api/hexa/node-runs/1?*', route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset')); offsets.push(offset);
    return route.fulfill({ json: { ...node, environment: {}, attempts: [{ ...node, id: offset + 1, attempt: offset + 1 }], attempts_pagination: { offset, limit: 50, has_more: offset === 0 } } });
  });
  await page.route('**/api/hexa/node-runs/1/artifacts?*', route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
    return route.fulfill({ json: { artifacts: [artifact(offset + 1)], pagination: { offset, limit: 50, has_more: offset === 0 } } });
  });
  await enter(page);
  await page.getByRole('button', { name: '查看流程图', exact: true }).click();
  await page.getByRole('tab', { name: '调试', exact: true }).click();
  const properties = page.getByRole('complementary', { name: '运行属性', exact: true });
  await properties.getByText('执行环境与尝试历史', { exact: true }).click();
  await properties.getByRole('button', { name: '加载更多尝试' }).click();
  await expect(properties).toContainText('"attempt": 51');
  await expect(properties.getByRole('button', { name: '加载更多尝试' })).toHaveCount(0);
  await properties.getByRole('button', { name: '加载更多产物' }).click();
  await expect(properties).toContainText('report-51.txt');
  expect(offsets).toEqual([0, 50]);
});

test('node debug initial failure offers a retry without leaving the flow', async ({ page }) => {
  await taskFixture(page);
  let failed = false;
  await page.route('**/api/hexa/node-runs/1?*', route => {
    if (!failed) { failed = true; return route.fulfill({ status: 503, json: { detail: '调试记录暂时不可用' } }); }
    return route.fallback();
  });
  await enter(page);
  await page.getByRole('button', { name: '查看流程图', exact: true }).click();
  await page.getByRole('tab', { name: '调试', exact: true }).click();
  const properties = page.getByRole('complementary', { name: '运行属性', exact: true });
  await expect(properties.getByRole('alert')).toContainText('调试记录暂时不可用');
  await properties.getByRole('button', { name: '重试加载调试' }).click();
  await expect(properties).toContainText('真实夹具输入');
  await expect(properties.getByRole('alert')).toHaveCount(0);
});

test('run completion refreshes artifacts without requiring a page reload', async ({ page }) => {
  const fixture = await taskFixture(page);
  fixture.runs[2].status = 'running'; fixture.tasks[3].status = 'running';
  let completed = false;
  await page.route('**/api/hexa/runs/20/artifacts?*', route => route.fulfill({ json: {
    artifacts: completed ? [artifact(55, '完成后报告.txt')] : [], pagination: { offset: 0, limit: 50, has_more: false },
  } }));
  await page.route('**/api/hexa/runs/20/events', route => route.abort());
  await page.route('**/api/hexa/runs/20', route => route.fulfill({ json: fixture.runs[2] }));
  await enter(page);
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /运行记录/ }).click();
  const detail = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(detail).toContainText('运行中');
  completed = true; fixture.runs[2].status = 'completed'; fixture.runs[2].nodes[0].status = 'succeeded';
  await expect(detail).toContainText('已完成');
  await expect(detail).toContainText('完成后报告.txt');
});

test('task state controls wait for detail reads so an old snapshot cannot overwrite archive', async ({ page }) => {
  const fixture = await taskFixture(page);
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/hexa/tasks/72', async route => {
    const before = structuredClone(fixture.tasks[1]);
    await pending;
    await route.fulfill({ json: before });
  });
  await page.route('**/api/hexa/tasks/72/state', route => {
    fixture.tasks[1].status = 'archived';
    return route.fulfill({ json: fixture.tasks[1] });
  });
  await enter(page);
  await page.getByRole('row', { name: /产品方案评估/ }).click();
  const detail = page.getByRole('complementary', { name: '任务详情', exact: true });
  await expect(detail.getByRole('button', { name: '归档任务', exact: true })).toBeDisabled();
  release();
  await detail.getByRole('button', { name: '归档任务', exact: true }).click();
  await expect(detail.getByRole('button', { name: '取消归档', exact: true })).toBeVisible();
});

for (const mobile of [false, true]) {
  test(`artifact paging and failure recovery stay usable at ${mobile ? '390x844' : '1440x900'}`, async ({ page }, testInfo) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 });
    await taskFixture(page);
    let fail = true;
    await page.route('**/api/hexa/tasks/71/artifacts?*', route => {
      const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
      if (offset === 50 && fail) { fail = false; return route.fulfill({ status: 503, json: { detail: '产物加载失败，请重试' } }); }
      return route.fulfill({ json: { artifacts: [artifact(offset + 1)], pagination: { offset, limit: 50, has_more: offset === 0 } } });
    });
    await enter(page);
    await page.getByRole('row', { name: /安全事件调查/ }).click();
    const detail = mobile ? page.getByRole('dialog', { name: '任务详情', exact: true }) : page.getByRole('complementary', { name: '任务详情', exact: true });
    await detail.getByRole('button', { name: '加载更多产物' }).click();
    await expect(detail.getByRole('alert')).toContainText('产物加载失败');
    await mkdir('.artifacts/pagination', { recursive: true });
    const prefix = `.artifacts/pagination/${testInfo.project.name}-${mobile ? 'mobile' : 'desktop'}`;
    await page.screenshot({ path: `${prefix}-failure.png` });
    await detail.getByRole('button', { name: '重试加载产物' }).click();
    await expect(detail.getByText('report-51.txt', { exact: true })).toBeVisible();
    await expect(detail.getByRole('button', { name: '加载更多产物' })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const box = await detail.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(mobile ? 391 : 1441);
    await page.screenshot({ path: `${prefix}-success.png` });
  });
}
