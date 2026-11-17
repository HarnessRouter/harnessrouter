import { test, expect } from '@playwright/test';

test('real login form, expiry, relogin and failed logout preserve the correct session and draft', async ({ page }) => {
  let authenticated = false, failLogout = true;
  const sent: string[] = [];
  await page.route('**/api/hexa/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path.endsWith('/auth/login')) {
      const body = request.postDataJSON();
      expect(body.username).toBe('admin');
      if (body.password !== 'correct-password') return route.fulfill({ status: 401, json: { detail: '用户名或密码错误。' } });
      authenticated = true;
      return route.fulfill({ json: { authenticated: true, username: 'admin' } });
    }
    if (path.endsWith('/auth/logout')) {
      if (failLogout) return route.fulfill({ status: 503, json: { detail: '暂时无法退出，请重试。' } });
      authenticated = false;
      return route.fulfill({ json: { authenticated: false } });
    }
    if (!authenticated) return route.fulfill({ status: 401, json: { detail: '需要先登录。' } });
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { authenticated: true, username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'a1', name: '真实助手' }] } });
    if (path.endsWith('/messages')) sent.push(path);
    return route.fulfill({ json: { agents: [], conversations: [], workspaces: [], selected_id: null } });
  });
  await page.goto('/');
  const login = page.getByRole('dialog', { name: '登录 Hexa', exact: true });
  await login.getByLabel('密码', { exact: true }).fill('wrong-password');
  await login.getByRole('button', { name: '登录', exact: true }).click();
  await expect(login.getByRole('alert')).toContainText('用户名或密码错误');
  await login.getByLabel('密码', { exact: true }).fill('correct-password');
  await login.getByRole('button', { name: '登录', exact: true }).click();
  await expect(login).toBeHidden();
  await page.getByRole('textbox', { name: '消息输入' }).fill('过期后保留的草稿');
  await page.reload();
  await expect(page.getByRole('button', { name: '用户菜单：admin', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '智能体', exact: true }).click();
  await expect(page.getByRole('heading', { name: '真实助手' })).toBeVisible();
  authenticated = false;
  await page.getByRole('button', { name: '刷新列表', exact: true }).click();
  await expect(login).toBeVisible();
  await expect(page.getByRole('heading', { name: '真实助手' })).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: '消息输入' })).toBeDisabled();
  await login.getByLabel('密码', { exact: true }).fill('correct-password');
  await login.getByRole('button', { name: '登录', exact: true }).click();
  await expect(login).toBeHidden();
  await expect(page.getByRole('textbox', { name: '消息输入' })).toHaveValue('过期后保留的草稿');
  expect(sent).toEqual([]);
  await page.getByRole('button', { name: '用户菜单：admin', exact: true }).click();
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('暂时无法退出');
  await expect(page.getByRole('button', { name: '用户菜单：admin', exact: true })).toBeVisible();
  failLogout = false;
  await page.getByRole('button', { name: '用户菜单：admin', exact: true }).click();
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(login).toBeVisible();
  await page.reload();
  await expect(login).toBeVisible();
});
