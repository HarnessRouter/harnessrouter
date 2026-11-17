/** @jest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({ 'x-test': 'operator' }) }));

import { harnessFetch } from '@/lib/hfetch';
import { RunnersPage } from './RunnersPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const runner = (over: Record<string, unknown> = {}) => ({
  name: 'runner-1', url: 'http://runner-1:8081', static: false, alive: true, ready: true,
  accepting: true, phase: 'ready', draining: false, active: 0, capacity: 4, sessions: 1,
  backends: ['codex'], installed_backends: ['codex'], version: 'test', last_heartbeat: 1760000000,
  ...over,
});
const response = (body: unknown, ok = true) => ({ ok, status: ok ? 200 : 503, json: async () => body });
let root: Root;
let el: HTMLElement;
let confirmMock: jest.Mock;
const text = () => (el.textContent || '').replace(/\s+/g, ' ');
const button = (label: string) => Array.from(el.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === label);
async function flush() { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); }); }
async function open() { await act(async () => { root.render(<RunnersPage />); }); await flush(); }
async function click(label: string) {
  const b = button(label);
  if (!b) throw new Error(`missing button ${label}: ${text()}`);
  await act(async () => { b.click(); await new Promise((resolve) => setTimeout(resolve, 0)); });
}
async function setValue(node: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { setter.call(node, value); node.dispatchEvent(new Event('input', { bubbles: true })); });
}

beforeEach(() => {
  (harnessFetch as jest.Mock).mockReset().mockResolvedValue(response({ runners: [runner()] }));
  confirmMock = jest.fn(() => true);
  Object.defineProperty(window, 'confirm', { configurable: true, value: confirmMock });
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

it('loads runner health and does not call a non-ready runner normal', async () => {
  (harnessFetch as jest.Mock).mockResolvedValue(response({ runners: [runner({ accepting: false, phase: 'starting' })] }));
  await open();
  expect(text()).toContain('runner-1');
  expect(text()).toContain('启动中');
  expect(text()).toContain('否');
  expect(el.querySelector('.runner-phase.is-ready')).toBeNull();
});

it('registers a dynamic runner with the entered capacity', async () => {
  (harnessFetch as jest.Mock)
    .mockResolvedValueOnce(response({ runners: [] }))
    .mockResolvedValueOnce(response({ ok: true }))
    .mockResolvedValueOnce(response({ runners: [runner({ name: 'runner-2' })] }));
  await open();
  const inputs = el.querySelectorAll('input');
  await setValue(inputs[0] as HTMLInputElement, 'runner-2');
  await setValue(inputs[1] as HTMLInputElement, 'http://runner-2:8081');
  await setValue(inputs[2] as HTMLInputElement, '8');
  await click('注册');
  const [, init] = (harnessFetch as jest.Mock).mock.calls[1];
  expect(init.method).toBe('POST');
  expect(JSON.parse(init.body)).toEqual({ name: 'runner-2', url: 'http://runner-2:8081', capacity: 8 });
  expect(text()).toContain('runner-2');
});

it('drains and deregisters only after confirmation', async () => {
  (harnessFetch as jest.Mock)
    .mockResolvedValueOnce(response({ runners: [runner({ draining: true })] }))
    .mockResolvedValueOnce(response({ ok: true }))
    .mockResolvedValueOnce(response({ runners: [runner({ draining: false })] }))
    .mockResolvedValueOnce(response({ ok: true }))
    .mockResolvedValueOnce(response({ runners: [runner({ draining: true })] }))
    .mockResolvedValueOnce(response({ ok: true }))
    .mockResolvedValueOnce(response({ runners: [] }));
  await open();
  await click('恢复接单');
  expect(JSON.parse((harnessFetch as jest.Mock).mock.calls[1][1].body)).toMatchObject({ name: 'runner-1', draining: false, capacity: 4 });
  await click('排空');
  expect(JSON.parse((harnessFetch as jest.Mock).mock.calls[3][1].body)).toMatchObject({ name: 'runner-1', draining: true, capacity: 4 });
  await click('注销');
  expect(confirmMock).toHaveBeenCalledWith(expect.stringContaining('runner-1'));
  expect(JSON.parse((harnessFetch as jest.Mock).mock.calls[5][1].body)).toEqual({ name: 'runner-1' });
});

it('shows router failures as an alert', async () => {
  (harnessFetch as jest.Mock).mockResolvedValue(response({ detail: 'router offline' }, false));
  await open();
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('router offline');
});
