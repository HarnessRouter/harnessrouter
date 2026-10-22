/** @jest-environment jsdom */
// A setup's Add plugin as a person uses it: every plugin the workspace has connected, with Include for
// this setup (the setup's binding, written at once through the caller); everything not connected yet as
// a grid whose Connect runs the Add-ons flow and then offers Include.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Plug } from '@/lib/plugs';

jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ member: { id: 'ada@example.com', email: 'ada@example.com' } }) }));
jest.mock('@/lib/plugs', () => ({
  listPlugs: jest.fn(), setPlug: jest.fn(), deletePlug: jest.fn(), plugTools: jest.fn(), plugAttachments: jest.fn(),
  microsoftStart: jest.fn(), microsoftComplete: jest.fn(), microsoftSignout: jest.fn(),
}));
jest.mock('../bricks', () => ({ partIcon: () => '<svg></svg>' }));
jest.mock('../toast', () => ({ toast: jest.fn() }));

import * as plugs from '@/lib/plugs';
import { AddPluginSheet, type Binding } from './AddPluginSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const m = plugs as jest.Mocked<typeof plugs>;

const P = (type: string, label: string, over: Partial<Plug> = {}): Plug => ({
  type, label, source: 'local', official: true, status: 'missing', config: {}, secrets_set: [],
  secrets_needed: type === 'browser' ? [] : ['token'], config_fields: type === 'browser' ? ['allow_domains', 'deny_domains'] : ['repo'],
  version: 0, tools: 2, ...over,
});

let catalog: Plug[];
let binding: Binding;
let onSet: jest.Mock;
let onChanged: jest.Mock;
let root: Root;
let el: HTMLElement;

const flush = async () => { for (let i = 0; i < 10; i++) await act(async () => { await Promise.resolve(); }); };
async function open() {
  await act(async () => {
    root.render(<AddPluginSheet workspace="ws" setup="Mail helper" binding={binding} busy={false} onSet={onSet} onChanged={onChanged} onClose={() => {}} />);
  });
  await flush();
}
const rows = () => Array.from(document.querySelectorAll('.pl-add .cap-row'));
const rowOf = (name: string) => rows().find((r) => r.querySelector('b')?.textContent === name) as HTMLElement;
const tileNames = () => Array.from(document.querySelectorAll('.pl-add .pl-tile .pl-top b')).map((b) => b.textContent);
const tog = (name: string) => rowOf(name).querySelector('.tog') as HTMLButtonElement;
async function click(b: HTMLElement) { await act(async () => { b.click(); }); await flush(); }

beforeEach(() => {
  jest.clearAllMocks();
  catalog = [
    P('browser', 'Browser'),
    P('github', 'GitHub', { status: 'connected', config: { repo: 'acme/app' }, secrets_set: ['token'] }),
    P('vercel', 'Vercel', { status: 'needs_auth' }),
  ];
  m.listPlugs.mockImplementation(async () => ({ workspace: 'ws', plugs: catalog }));
  m.setPlug.mockImplementation(async (type: string) => {
    const next = { ...(catalog.find((p) => p.type === type) as Plug), status: 'connected' as const };
    catalog = catalog.map((p) => (p.type === type ? next : p));
    return next;
  });
  binding = { plugs: ['github'] };
  onSet = jest.fn().mockResolvedValue(true);
  onChanged = jest.fn();
  document.body.innerHTML = '<div id="hrui"><div id="root"></div></div>';
  el = document.getElementById('root') as HTMLElement;
  root = createRoot(el);
});
afterEach(async () => { await act(async () => { root.unmount(); }); });

test('each connected plugin has its switch; flipping one writes the setup at once', async () => {
  await open();
  expect(rows().map((r) => r.querySelector('b')?.textContent)).toEqual(['GitHub', 'Vercel']);
  expect(tog('GitHub').getAttribute('aria-pressed')).toBe('true');
  expect(tog('GitHub').getAttribute('aria-label')).toBe('Include GitHub in Mail helper');
  expect(tog('Vercel').getAttribute('aria-pressed')).toBe('false');
  expect(rowOf('Vercel').querySelector('small.warn')?.textContent).toBe('Connect your account again to restore access.');
  expect(tileNames()).toEqual(['Browser']);
  expect(m.plugAttachments).not.toHaveBeenCalled();     // the sheet does not count who uses each

  await click(tog('Vercel'));
  expect(onSet).toHaveBeenLastCalledWith(['github', 'vercel']);
  await click(tog('GitHub'));
  expect(onSet).toHaveBeenLastCalledWith([]);
});

test('a plugin connected here moves up, offered to include', async () => {
  await open();
  await click(document.querySelector('[aria-label="Connect Browser"]') as HTMLButtonElement);
  expect(m.setPlug).toHaveBeenCalledWith('browser', { enabled: true });
  expect(onChanged).toHaveBeenCalled();
  expect(rowOf('Browser').textContent).toContain('Just connected. Include it in this setup?');
  expect(tileNames()).toEqual([]);
  await click(tog('Browser'));
  expect(onSet).toHaveBeenLastCalledWith(['github', 'browser']);
});
