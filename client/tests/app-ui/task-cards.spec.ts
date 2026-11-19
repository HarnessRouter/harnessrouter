import { test, expect, type Page } from '@playwright/test';
import { taskFixture } from '../task-fixture';

async function enterCards(page: Page) {
  await page.goto('/');
  const taskEntry = page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true });
  await expect(taskEntry).toBeVisible();
  await taskEntry.click();
  await page.getByRole('button', { name: '卡片视图' }).click();
  await expect(page.getByRole('listitem').first()).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
});

test('card view keeps every card body inside its card when columns collapse to one', async ({ page }) => {
  await taskFixture(page);
  await enterCards(page);
  for (const width of [1440, 1280, 1024, 900, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const cards = page.getByRole('listitem');
    for (let index = 0; index < await cards.count(); index++) {
      const geometry = await cards.nth(index).evaluate(card => {
        const body = card.querySelector('.workbench-card-body')!.getBoundingClientRect();
        const visual = card.querySelector('.workbench-card-visual')!.getBoundingClientRect();
        const rect = card.getBoundingClientRect();
        return {
          cardBottom: rect.bottom,
          bodyBottom: body.bottom,
          bodyTop: body.top,
          visualBottom: visual.bottom,
          scrollHeight: card.scrollHeight,
          clientHeight: card.clientHeight,
          height: rect.height,
        };
      });
      expect(geometry.bodyTop).toBeGreaterThanOrEqual(geometry.visualBottom - 1);
      expect(geometry.bodyBottom).toBeLessThanOrEqual(geometry.cardBottom + 1);
      expect(geometry.scrollHeight).toBeLessThanOrEqual(geometry.clientHeight + 1);
      expect(geometry.height).toBeGreaterThan(180);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }
});

test('thumbnails fit the card visual and keep nodes readable in narrow columns', async ({ page }) => {
  await taskFixture(page);
  await enterCards(page);
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const boxes = await page.getByRole('listitem').evaluateAll(cards => cards.map(card => {
      const visual = card.querySelector('.workbench-card-visual')!.getBoundingClientRect();
      const svg = card.querySelector('.flow-thumb-box')?.ownerSVGElement?.getBoundingClientRect();
      const nodes = Array.from(card.querySelectorAll('.flow-thumb-box')).map(node => node.getBoundingClientRect().width);
      return { visual, svg, nodes };
    }));
    for (const box of boxes) {
      expect(box.svg).toBeTruthy();
      expect(box.svg!.left).toBeGreaterThanOrEqual(box.visual.left - 1);
      expect(box.svg!.right).toBeLessThanOrEqual(box.visual.right + 1);
      expect(box.svg!.top).toBeGreaterThanOrEqual(box.visual.top - 1);
      expect(box.svg!.bottom).toBeLessThanOrEqual(box.visual.bottom + 1);
      expect(Math.min(...box.nodes)).toBeGreaterThanOrEqual(40);
    }
  }
});

test('workflow thumbnails and run graphs expose status tones and live animations', async ({ page }) => {
  const fixture = await taskFixture(page);
  fixture.runs[0].nodes = [
    { ...fixture.runs[0].nodes[0], status: 'succeeded' },
    { ...fixture.runs[0].nodes[1], status: 'running', finished_at: null },
    { ...fixture.runs[0].nodes[2], status: 'queued' },
  ];
  await enterCards(page);
  const first = page.getByRole('listitem').first();
  await expect(first.locator('.flow-thumb-node.succeeded')).toHaveCount(1);
  await expect(first.locator('.flow-thumb-node.running')).toHaveCount(1);
  await expect(first.locator('.flow-thumb-node.queued')).toHaveCount(1);
  await expect(first.locator('.flow-thumb-edge.active')).toHaveCount(1);
  await expect(first.locator('.flow-thumb-edge.ready')).toHaveCount(1);
  expect(await first.locator('.flow-thumb-node.running').evaluate(node => getComputedStyle(node.querySelector('.flow-thumb-box')!).animationName)).not.toBe('none');
  expect(await first.locator('.flow-thumb-edge.active').first().evaluate(edge => getComputedStyle(edge).animationName)).not.toBe('none');

  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect(await first.locator('.flow-thumb-node.running').evaluate(node => getComputedStyle(node.querySelector('.flow-thumb-box')!).animationName)).toBe('none');
  expect(await first.locator('.flow-thumb-edge.active').first().evaluate(edge => getComputedStyle(edge).animationName)).toBe('none');
});

test('run graph highlights succeeded, running and failed nodes with animated edges', async ({ page }) => {
  const fixture = await taskFixture(page);
  fixture.runs[0].nodes = [
    { ...fixture.runs[0].nodes[0], status: 'succeeded' },
    { ...fixture.runs[0].nodes[1], status: 'running', finished_at: null },
    { ...fixture.runs[0].nodes[2], status: 'queued' },
  ];
  await page.goto('/');
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '任务', exact: true }).click();
  await page.getByRole('navigation', { name: '任务菜单' }).getByRole('button', { name: /运行记录/ }).click();
  await page.getByRole('row', { name: /安全事件调查/ }).click();
  await page.getByRole('button', { name: '打开流程图' }).click();
  const graph = page.getByRole('main', { name: '运行流程图' });
  await expect(graph.locator('.run-graph-node.running')).toHaveCount(1);
  await expect(graph.locator('.run-graph-node.succeeded')).toHaveCount(1);
  await expect(graph.locator('.run-graph-edge.active')).toHaveCount(1);
  await expect(graph.locator('.run-graph-edge.ready')).toHaveCount(1);
  expect(await graph.locator('.run-graph-node.running').evaluate(node => getComputedStyle(node).animationName)).not.toBe('none');
  expect(await graph.locator('.run-graph-edge.active').first().evaluate(edge => getComputedStyle(edge).animationName)).not.toBe('none');
});
