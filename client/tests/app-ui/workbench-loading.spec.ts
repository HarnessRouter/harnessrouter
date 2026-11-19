import { test, expect } from '@playwright/test';
import { taskFixture } from '../task-fixture';

test('run deep link stays readable when auxiliary lists fail and retry recovers the lists', async ({ page }) => {
  await taskFixture(page);
  let fail = true;
  for (const name of ['tasks', 'templates', 'runs']) await page.route(`**/api/hexa/${name}?*`, route => fail
    ? route.fulfill({ status: 404, json: { detail: 'Not Found' } }) : route.fallback());
  await page.goto('/runs/19');
  const detail = page.getByRole('complementary', { name: '运行详情', exact: true });
  await expect(detail).toContainText('Run #19');
  await expect(detail).toContainText('产品方案评估');
  await expect(detail).toContainText('已完成');
  await expect(page.getByRole('alert')).toContainText('运行记录列表接口不可用');
  fail = false;
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.getByRole('row', { name: /Run #19/ })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.reload();
  await expect(detail).toContainText('Run #19');
  await expect(detail).toContainText('产品方案评估');
});

test('task deep link remains readable and template outage is not reported as a missing task', async ({ page }) => {
  await taskFixture(page);
  await page.route('**/api/hexa/templates?*', route => route.fulfill({ status: 503, json: { detail: '模板服务暂时不可用' } }));
  await page.goto('/tasks/72');
  await expect(page.getByRole('complementary', { name: '任务详情', exact: true })).toContainText('产品方案评估');
  await expect(page.getByRole('alert')).toContainText('模板列表');
  await expect(page.getByRole('row', { name: /产品方案评估/ })).toBeVisible();
});
