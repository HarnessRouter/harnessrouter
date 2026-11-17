/** @jest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({ 'x-test': 'operator' }) }));
jest.mock('./toast', () => ({ toast: jest.fn() }));

import { harnessFetch } from '@/lib/hfetch';
import { toast } from './toast';
import { UhpConnectionsPage } from './UhpConnectionsPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const SECRET = '__secret__';
let root: Root;
let el: HTMLElement;
let confirmMock: jest.Mock;

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const fail = (status: number, detail = '') => ({ ok: false, status, json: async () => ({ detail }) });
const connection = (over: Record<string, unknown> = {}) => ({
  id: 'uhpc_1', name: 'browser', kind: 'external_uhp', base_url: 'http://runtime:8421',
  config: { api_key: SECRET }, uhp: { version: '2026-10-19', capabilities: { streaming: true } },
  harnesses: [{ id: 'harn_1', remote_id: 'browser/page-1', name: 'Browser', enabled: true }], ...over,
});
const text = () => (el.textContent || '').replace(/\s+/g, ' ');
const button = (label: string) => Array.from(el.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === label);
const input = (label: string) => el.querySelector(`label:has(> input[placeholder="${label}"]) input`) as HTMLInputElement;
async function flush() { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); }); }
async function open() { await act(async () => { root.render(<UhpConnectionsPage />); }); await flush(); }
async function click(label: string) {
  const b = button(label);
  if (!b) throw new Error(`missing button ${label}: ${text()}`);
  await act(async () => { b.click(); await new Promise((resolve) => setTimeout(resolve, 0)); });
}
async function setValue(node: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => {
    setter.call(node, value);
    node.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

beforeEach(() => {
  (harnessFetch as jest.Mock).mockReset().mockResolvedValue(ok({ connections: [connection()] }));
  (toast as jest.Mock).mockClear();
  confirmMock = jest.fn(() => true);
  Object.defineProperty(window, 'confirm', { configurable: true, value: confirmMock });
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

it('loads connections, keeps the secret redacted, and shows remote harness ids', async () => {
  await open();
  expect(text()).toContain('browser');
  expect(text()).toContain('Browser');
  expect(text()).toContain('harn_1');
  expect(text()).not.toContain('test-runtime-secret');
  expect(el.querySelector('input[type="password"]')).toBeTruthy();
});

it('shows health details and refreshes a failed connection with a manual check', async () => {
  (harnessFetch as jest.Mock)
    .mockResolvedValueOnce(ok({ connections: [connection({ health: {
      status: 'unreachable', last_checked_at: 1794800000, last_success_at: 1794799900,
      latency_ms: 34, fresh_until: 9999999999, last_error: '无法连接 UHP 服务。',
    } })] }))
    .mockResolvedValueOnce(ok({ connection: connection({ health: {
      status: 'healthy', last_checked_at: 1794800001, latency_ms: 12,
      fresh_until: 9999999999, last_error: '',
    } }) }));
  await open();
  expect(text()).toContain('无法连接');
  expect(text()).toContain('最近检查');
  expect(text()).toContain('34 ms');
  await click('立即检查');
  expect((harnessFetch as jest.Mock).mock.calls[1][0]).toBe('/api/harness/v1/admin/uhp-connections/browser/check');
  expect(text()).toContain('连接正常');
  expect(text()).toContain('12 ms');
  expect(text()).not.toContain('无法连接 UHP 服务。');
});

it('saves an entered connection and clears the secret field after success', async () => {
  (harnessFetch as jest.Mock)
    .mockResolvedValueOnce(ok({ connections: [] }))
    .mockResolvedValueOnce(ok({ connection: connection({ name: 'xred', base_url: 'http://xred:8421', health: { status: 'healthy' } }) }));
  await open();
  await setValue(input('Browser Runtime'), 'xred');
  await setValue(input('http://xred:8421'), 'http://xred:8421');
  await setValue(input('输入密钥；更新已有连接可留空'), 'runtime-secret');
  await click('测试并保存');
  const [, init] = (harnessFetch as jest.Mock).mock.calls[1];
  expect(init.method).toBe('PUT');
  expect(JSON.parse(init.body)).toEqual({ name: 'xred', base_url: 'http://xred:8421', api_key: 'runtime-secret' });
  expect(text()).toContain('xred');
  expect((el.querySelector('input[type="password"]') as HTMLInputElement).value).toBe('');
  expect(toast).toHaveBeenCalledWith('UHP 连接已保存，Harness 已同步。');
});

it('uses the redacted sentinel when updating an existing connection without a new key', async () => {
  (harnessFetch as jest.Mock)
    .mockResolvedValueOnce(ok({ connections: [connection()] }))
    .mockResolvedValueOnce(ok({ connection: connection({ base_url: 'http://runtime-new:8421' }) }));
  await open();
  await setValue(input('Browser Runtime'), 'browser');
  await setValue(input('http://xred:8421'), 'http://runtime-new:8421');
  await click('测试并保存');
  const [, init] = (harnessFetch as jest.Mock).mock.calls[1];
  expect(JSON.parse(init.body).api_key).toBe(SECRET);
});

it('confirms and deletes a connection, and reports read failures', async () => {
  (harnessFetch as jest.Mock)
    .mockResolvedValueOnce(ok({ connections: [connection()] }))
    .mockResolvedValueOnce(ok({}));
  await open();
  await click('删除');
  expect(confirmMock).toHaveBeenCalledWith('删除 UHP 连接“browser”？');
  expect((harnessFetch as jest.Mock).mock.calls[1][1].method).toBe('DELETE');
  expect(text()).not.toContain('Browser');

  (harnessFetch as jest.Mock).mockReset().mockResolvedValue(fail(503));
  await act(async () => { root.unmount(); el.innerHTML = ''; root = createRoot(el); root.render(<UhpConnectionsPage />); });
  await flush();
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('暂时无法读取 UHP 连接。');
});
