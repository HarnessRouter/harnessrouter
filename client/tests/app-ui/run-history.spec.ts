import { test, expect } from '@playwright/test';
import { taskFixture } from '../task-fixture';

test('run graph reads the bound snapshot, drags edges, replays without writes and isolates layouts', async ({ page }) => {
  const fixture = await taskFixture(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true }).click();
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /运行记录/ }).click();
  await page.getByRole('row', { name: /安全事件调查/ }).click();
  const detail = page.getByRole('complementary', { name: '运行详情' });
  await expect(detail).toContainText('Workflow v3');
  await detail.getByRole('button', { name: '打开流程图' }).click();
  const graph = page.getByRole('main', { name: '运行流程图' });
  await expect(graph.locator('.react-flow__edge')).toHaveCount(2);
  const node = graph.getByRole('button', { name: '资料收集 节点', exact: true });
  const before = (await node.boundingBox())!;
  const edgeBefore = await graph.locator('.react-flow__edge').first().getAttribute('x1');
  await page.mouse.move(before.x + 40, before.y + 30); await page.mouse.down();
  await page.mouse.move(before.x + 140, before.y + 95, { steps: 5 }); await page.mouse.up();
  expect((await node.boundingBox())!.x).toBeGreaterThan(before.x + 50);
  expect(await graph.locator('.react-flow__edge').first().getAttribute('x1')).not.toBe(edgeBefore);
  await page.getByRole('tab', { name: '调试', exact: true }).click();
  await expect(page.getByRole('complementary', { name: '运行属性' })).toContainText('来自 API 的节点输出');
  await graph.getByRole('button', { name: '重放', exact: true }).click();
  await page.getByRole('tab', { name: '运行', exact: true }).click();
  await page.getByRole('slider', { name: '重放进度' }).fill('0');
  await page.getByRole('tab', { name: '节点', exact: true }).click();
  await expect(page.getByRole('complementary', { name: '运行属性' })).toContainText('尚无节点事件');
  await page.getByRole('button', { name: '返回运行详情' }).click();
  await page.getByRole('row', { name: /产品方案评估/ }).click();
  await detail.getByRole('button', { name: '打开流程图' }).click();
  await expect(graph.getByRole('button', { name: '历史产品分析 节点', exact: true })).toBeVisible();
  await expect(graph.getByRole('button', { name: '当前产品分析 节点', exact: true })).toHaveCount(0);
  expect(fixture.writes).toEqual([]);
});

test('mobile node properties and playback use a bounded drawer', async ({ page }) => {
  await taskFixture(page); await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/runs/19');
  await page.getByRole('row', { name: /产品方案评估/ }).click();
  await page.getByRole('dialog', { name: '运行详情' }).getByRole('button', { name: '打开流程图' }).click();
  await page.getByRole('button', { name: '历史产品分析 节点', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: '运行属性' });
  await expect(drawer).toBeVisible();
  await drawer.getByRole('tab', { name: '运行', exact: true }).click();
  await drawer.getByRole('slider', { name: '重放进度' }).fill('0');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});
