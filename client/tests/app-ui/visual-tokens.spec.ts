import { test, expect, type Locator, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { taskFixture } from '../task-fixture';

type Rgb = [number, number, number, number];
const artifacts = '.artifacts/task-api';

const parseColor = (value: string): Rgb => {
  const match = value.match(/rgba?\(([^)]+)\)/);
  if (!match) throw new Error(`Unsupported color: ${value}`);
  const [red, green, blue, alpha = 1] = match[1].split(',').map(part => Number(part.trim()));
  return [red, green, blue, alpha];
};

const luminance = (color: Rgb) => {
  const [red, green, blue] = color.slice(0, 3).map(value => {
    const channel = value / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
};

const contrast = (foreground: Rgb, background: Rgb) => {
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort((left, right) => right - left);
  return (lighter + 0.05) / (darker + 0.05);
};

const effectiveColors = (locator: Locator) => locator.evaluate(element => {
  let background = 'rgba(0, 0, 0, 0)';
  let node: Element | null = element;
  while (node) {
    background = getComputedStyle(node).backgroundColor;
    if (background !== 'rgba(0, 0, 0, 0)' && background !== 'transparent') break;
    node = node.parentElement;
  }
  return { foreground: getComputedStyle(element).color, background };
});

const enterTaskWorkbench = async (page: Page) => {
  await taskFixture(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true }).click();
  await expect(page.getByRole('row', { name: /安全事件调查/ })).toBeVisible();
};

test('workbench uses the design-spec palette, font stack and readable text sizes', async ({ page }) => {
  await enterTaskWorkbench(page);

  const primary = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--hx-primary').trim());
  expect(primary.toLowerCase()).toBe('#2563eb');
  expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).toContain('Segoe UI Variable');

  const createButton = parseColor(await page.getByRole('button', { name: '新建任务', exact: true }).evaluate(element => getComputedStyle(element).backgroundColor));
  expect(createButton.slice(0, 3)).toEqual([37, 99, 235]);

  const sizes = await page.evaluate(() => {
    const read = (selector: string) => {
      const element = document.querySelector(selector);
      if (!element) throw new Error(`Missing ${selector}`);
      return Number.parseFloat(getComputedStyle(element).fontSize);
    };
    return {
      head: read('.workbench-table-head'),
      title: read('.table-title strong'),
      description: read('.table-copy small'),
      id: read('.table-title code'),
      status: read('.workbench-status'),
      detailMeta: read('.detail-section-head > span'),
      detailAction: read('.detail-section-head button'),
    };
  });
  expect(sizes.head).toBeGreaterThanOrEqual(10);
  expect(sizes.title).toBeGreaterThanOrEqual(12.5);
  expect(sizes.description).toBeGreaterThanOrEqual(11);
  expect(sizes.id).toBeGreaterThanOrEqual(10);
  expect(sizes.status).toBeGreaterThanOrEqual(10);
  expect(sizes.detailMeta).toBeGreaterThanOrEqual(10);
  expect(sizes.detailAction).toBeGreaterThanOrEqual(10);

  mkdirSync(artifacts, { recursive: true });
  await page.screenshot({ path: `${artifacts}/visual-tokens-light.png` });
});

test('workbench metadata meets AA contrast in light mode', async ({ page }) => {
  await enterTaskWorkbench(page);

  for (const selector of ['.workbench-table-head', '.table-title code', '.table-copy small', '.workbench-table-foot']) {
    const { foreground, background } = await effectiveColors(page.locator(selector).first());
    expect(contrast(parseColor(foreground), parseColor(background)), selector).toBeGreaterThanOrEqual(4.5);
  }
});

test('dark mode keeps workbench surfaces on dark tokens', async ({ page }) => {
  await enterTaskWorkbench(page);
  await page.getByRole('button', { name: '切换深色模式' }).click();
  await expect(page.locator('.app')).toHaveClass(/dark/);
  await page.waitForTimeout(250);

  const surfaces = await page.evaluate(() => {
    const read = (selector: string) => {
      const element = document.querySelector(selector);
      if (!element) throw new Error(`Missing ${selector}`);
      const style = getComputedStyle(element);
      return { background: style.backgroundColor, border: style.borderBottomColor };
    };
    return {
      head: read('.workbench-table-head'),
      foot: read('.workbench-table-foot'),
      row: read('.workbench-table-row'),
      rule: read('.detail-rule'),
    };
  });

  const refresh = page.locator('.workbench-toolbar .ant-btn').first();
  const refreshColors = await refresh.evaluate(element => {
    const style = getComputedStyle(element);
    return { foreground: style.color, background: style.backgroundColor };
  });
  expect(contrast(parseColor(refreshColors.foreground), parseColor(refreshColors.background))).toBeGreaterThanOrEqual(4.5);

  expect(luminance(parseColor(surfaces.head.background))).toBeLessThan(0.2);
  expect(luminance(parseColor(surfaces.foot.background))).toBeLessThan(0.2);
  expect(luminance(parseColor(surfaces.row.border))).toBeLessThan(0.3);
  expect(luminance(parseColor(surfaces.rule.background))).toBeLessThan(0.2);

  mkdirSync(artifacts, { recursive: true });
  await page.screenshot({ path: `${artifacts}/visual-tokens-dark.png` });
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /运行记录/ }).click();
  await expect(page.getByRole('complementary', { name: '运行详情' })).toBeVisible();
  expect(await page.locator('.run-trace-item > span').first().evaluate(element => element.getBoundingClientRect().width)).toBeGreaterThan(120);
  await page.screenshot({ path: `${artifacts}/visual-tokens-dark-runs.png` });
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /模板管理/ }).click();
  await expect(page.getByRole('complementary', { name: '模板详情' })).toBeVisible();
  await page.screenshot({ path: `${artifacts}/visual-tokens-dark-templates.png` });
});

test('keyboard focus uses the shared three-pixel ring', async ({ page }) => {
  await enterTaskWorkbench(page);

  const row = page.getByRole('row', { name: /安全事件调查/ });
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  while (!(await row.evaluate(element => element === document.activeElement))) await page.keyboard.press('Tab');
  const rowOutline = await row.evaluate(element => {
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: style.outlineWidth, color: style.outlineColor };
  });
  expect(rowOutline).toMatchObject({ style: 'solid', width: '3px', color: 'rgb(37, 99, 235)' });

  await page.getByRole('textbox', { name: '搜索任务' }).focus();
  const searchOutline = await page.locator('.workbench-search').evaluate(element => {
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: style.outlineWidth };
  });
  expect(searchOutline).toEqual({ style: 'solid', width: '3px' });
});

test('reduced motion disables transitions and live-workflow animation', async ({ page }) => {
  await enterTaskWorkbench(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });

  const motion = await page.evaluate(() => {
    const transition = document.createElement('div');
    transition.className = 'template-node';
    const spinner = document.createElement('div');
    spinner.className = 'workspace-spinner';
    document.body.append(transition, spinner);
    const result = {
      transitionSeconds: Number.parseFloat(getComputedStyle(transition).transitionDuration),
      spinnerAnimation: getComputedStyle(spinner).animationName,
    };
    transition.remove();
    spinner.remove();
    return result;
  });
  expect(motion.transitionSeconds).toBeLessThanOrEqual(0.01);
  expect(motion.spinnerAnimation).toBe('none');
});

test('mobile forms avoid zoom and primary touch targets meet the 34px floor', async ({ page }) => {
  await enterTaskWorkbench(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('region', { name: '我的任务工作台' })).toBeVisible();
  await expect(page.locator('.workbench-toolbar .ant-btn').first()).toBeEnabled();

  const inputSize = await page.getByRole('textbox', { name: '搜索任务' }).evaluate(element => Number.parseFloat(getComputedStyle(element).fontSize));
  expect(inputSize).toBeGreaterThanOrEqual(16);

  const sizes = await page.evaluate(() => {
    const button = (selector: string) => {
      const element = document.querySelector(selector);
      if (!element) throw new Error(`Missing ${selector}`);
      const box = element.getBoundingClientRect();
      return { width: box.width, height: box.height };
    };
    return {
      filter: button('.workbench-segmented button'),
      view: button('.workbench-view-toggle button'),
    };
  });
  expect(sizes.filter.height).toBeGreaterThanOrEqual(34);
  expect(sizes.view.height).toBeGreaterThanOrEqual(34);
  expect(sizes.view.width).toBeGreaterThanOrEqual(34);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  mkdirSync(artifacts, { recursive: true });
  await page.screenshot({ path: `${artifacts}/visual-tokens-mobile.png` });

  await page.locator('.workbench-toolbar').getByRole('button', { name: '新建任务', exact: true }).click();
  const form = page.getByRole('dialog', { name: '新建任务' });
  const formInputSize = await form.getByRole('textbox', { name: '任务名称', exact: true }).evaluate(element => Number.parseFloat(getComputedStyle(element).fontSize));
  expect(formInputSize).toBeGreaterThanOrEqual(16);
  await page.keyboard.press('Escape');
  await expect(form).toBeHidden();

  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '对话', exact: true }).click();
  const composer = page.getByRole('textbox', { name: '消息输入' });
  expect(await composer.evaluate(element => Number.parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16);
  const actionHeight = await page.locator('.composer-actions button:not(.ant-btn)').first().evaluate(element => element.getBoundingClientRect().height);
  expect(actionHeight).toBeGreaterThanOrEqual(34);
});
