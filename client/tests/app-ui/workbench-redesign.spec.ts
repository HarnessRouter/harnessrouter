import { test, expect } from '@playwright/test';
import { taskFixture } from '../task-fixture';
import { mkdirSync } from 'node:fs';

const screenshots = '.artifacts/task-api';

test.beforeEach(async ({ page }) => {
  await taskFixture(page); await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true }).click();
  await expect(page.getByRole('row', { name: /安全事件调查/ })).toBeVisible();
});

test('API management pages retain full-height, independently resizable and collapsible details', async ({ page }) => {
  const sidebar = page.getByRole('navigation', { name: '任务菜单' });
  for (const [menu, label] of [['我的任务', '任务详情'], ['运行记录', '运行详情'], ['模板管理', '模板详情']]) {
    await sidebar.getByRole('button', { name: new RegExp(menu) }).click();
    const detail = page.getByRole('complementary', { name: label, exact: true });
    await expect(detail).toBeVisible();
    const box = (await detail.boundingBox())!, main = (await page.locator('.main').boundingBox())!;
    expect(Math.round(box.width)).toBe(720); expect(box.y).toBe(main.y); expect(box.height).toBe(main.height);
    const resize = page.getByRole('separator', { name: `调整${label}宽度` });
    await resize.focus(); await page.keyboard.press('ArrowRight');
    await expect(resize).toHaveAttribute('aria-valuenow', '696');
    await page.getByRole('button', { name: `收起${label}` }).click();
    await expect.poll(async () => Math.round((await detail.boundingBox())!.width)).toBe(44);
    await page.getByRole('button', { name: `展开${label}` }).click();
    await expect(resize).toHaveAttribute('aria-valuenow', '696');
  }
});

test('list and cards preserve the selected API record across all three management pages', async ({ page }) => {
  const sidebar = page.getByRole('navigation', { name: '任务菜单' });
  for (const [menu, label, selected] of [['我的任务', '任务详情', '产品方案评估'], ['运行记录', '运行详情', '产品方案评估'], ['模板管理', '模板详情', '安全调查模板']]) {
    await sidebar.getByRole('button', { name: new RegExp(menu) }).click();
    await page.getByRole('button', { name: '卡片视图' }).click();
    await page.getByRole('listitem').filter({ hasText: selected }).click();
    await expect(page.getByRole('complementary', { name: label, exact: true })).toContainText(selected);
    await page.getByRole('button', { name: '列表视图' }).click();
    await expect(page.getByRole('row', { name: new RegExp(selected) })).toHaveAttribute('aria-current', 'true');
  }
});

test('desktop and intermediate widths keep filters, tables and details within the viewport', async ({ page }) => {
  mkdirSync(screenshots, { recursive: true });
  for (const width of [1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    for (const menu of ['我的任务', '运行记录', '模板管理']) {
      await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: new RegExp(menu) }).click();
      const list = page.locator('.workbench-list');
      expect((await list.boundingBox())!.width).toBeGreaterThanOrEqual(280);
      expect(await list.evaluate(el => el.scrollWidth)).toBeLessThanOrEqual(await list.evaluate(el => el.clientWidth) + 1);
      const filters = page.locator('.workbench-segmented');
      expect(await filters.evaluate(el => el.scrollWidth)).toBeLessThanOrEqual(await filters.evaluate(el => el.clientWidth) + 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /我的任务/ }).click();
  await expect(page.getByRole('region', { name: '我的任务工作台' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /我的任务/ })).toHaveClass(/selected/);
  await page.screenshot({ path: `${screenshots}/desktop-${test.info().project.name}.png` });
});

test('mobile task details, template editor and conversation remain usable without overflow', async ({ page }) => {
  mkdirSync(screenshots, { recursive: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('row', { name: /待配置的草稿/ }).click();
  const detail = page.getByRole('dialog', { name: '任务详情' });
  await expect(detail).toBeVisible();
  await expect.poll(async () => Math.round((await detail.boundingBox())!.x + (await detail.boundingBox())!.width)).toBe(390);
  await page.screenshot({ path: `${screenshots}/mobile-${test.info().project.name}.png` });
  await detail.getByRole('button', { name: '编辑流程', exact: true }).click();
  await page.getByRole('group', { name: '节点 资料收集', exact: true }).click();
  await expect(page.getByLabel('节点 Agent', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.getByRole('button', { name: '返回任务详情' }).click();
  if (await detail.isVisible()) await detail.getByRole('button', { name: '关闭任务详情' }).click();
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '对话', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '消息输入' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});
