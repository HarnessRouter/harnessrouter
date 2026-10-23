/** @jest-environment jsdom */
// The switcher's list, read from this instance's gateway through the API proxy: until the list answers
// the current workspace is not known (no placeholder "Default Workspace" stands in for it); a list that
// cannot be read is `failed` (the frame shows an error, never a guess), a list read before in the tab
// still stands, and a chosen workspace gone from the list moves to Default, named.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/auth', () => ({ getSession: jest.fn() }));

import { getSession } from '@/lib/auth';
import { getCurrentWorkspaceRef, useWorkspace, WorkspaceProvider } from './workspace';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const fetchMock = jest.fn();
global.fetch = fetchMock as unknown as typeof fetch;
// jsdom has no Response: the provider reads only ok, status and json()
const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });
const LIST = { default_workspace_id: 'ws.def', workspaces: [{ id: 'ws.def', name: 'Default Workspace' }, { id: 'ws.pm', name: 'PhotoMagic' }] };

let root: Root;
let el: HTMLElement;
let seen: ReturnType<typeof useWorkspace>;
function Probe() { seen = useWorkspace(); return null; }

async function mount() {
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<WorkspaceProvider><Probe /></WorkspaceProvider>); });
}
const settle = async (ms = 0) => {
  for (let i = 0; i < 6; i++) {
    await act(async () => { await Promise.resolve(); });
    if (ms) act(() => { jest.advanceTimersByTime(ms); });
  }
};

beforeEach(() => {
  jest.useFakeTimers();
  localStorage.clear();
  fetchMock.mockReset();
  (getSession as jest.Mock).mockReturnValue({ orgId: 'org.x', member: { id: 'member.ann' } });
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.useRealTimers(); });

test('until the list answers the current workspace is not known, and no placeholder name stands in', async () => {
  let answer: (v: unknown) => void = () => {};
  fetchMock.mockImplementation(() => new Promise((res) => { answer = res; }));
  await mount();
  expect(seen.known).toBe(false);
  expect(seen.current).toEqual({ id: '', name: '', description: '', site: '' });
  expect(seen.workspaces).toEqual([]);
  expect(seen.failed).toBe(false);
  expect(seen.loading).toBe(true);
  await act(async () => { answer(json(LIST)); });
  await settle();
  expect(seen.known).toBe(true);
  expect(seen.current.id).toBe('ws.def');
});

test('a list that cannot be read is failed, and nothing stands in for it as an answer', async () => {
  fetchMock.mockResolvedValue(json({ detail: 'down' }, 503));
  await mount();
  await settle();
  expect(seen.failed).toBe(true);
  expect(seen.loading).toBe(false);
  expect(seen.known).toBe(false);
  expect(seen.current.name).toBe('');
  expect(seen.workspaces).toEqual([]);
  // nothing is saved to a workspace that is not known, and no "saved" is said
  await expect(seen.update({ name: 'X' })).rejects.toThrow('Your workspaces could not be read just now.');
  expect(fetchMock).toHaveBeenCalledTimes(1);
  // read again and answered: no longer failed
  fetchMock.mockResolvedValue(json(LIST));
  await act(async () => { await seen.refresh(); });
  expect(seen.failed).toBe(false);
  expect(seen.workspaces.map((w) => w.id)).toEqual(['ws.def', 'ws.pm']);
  // a later failure keeps the list the server answered
  fetchMock.mockResolvedValue(json({ detail: 'down' }, 503));
  await act(async () => { await seen.refresh(); });
  expect(seen.failed).toBe(false);
  expect(seen.workspaces.map((w) => w.id)).toEqual(['ws.def', 'ws.pm']);
});

test('an answer that is not the list, or that does not name its Default Workspace, is a failed read', async () => {
  for (const body of [null, { workspaces: [{ id: 'ws.pm', name: 'PhotoMagic' }] },
                      { default_workspace_id: 'ws.def' }, { default_workspace_id: 'ws.def', workspaces: [{ id: 'ws.pm', name: 'PhotoMagic' }] }]) {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(json(body));
    await mount();
    await settle();
    expect(seen.failed).toBe(true);
    expect(seen.known).toBe(false);
    expect(seen.workspaces).toEqual([]);
    act(() => root.unmount()); el.remove();
  }
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => { throw new SyntaxError('not JSON'); } });
  await mount();
  await settle();
  expect(seen.failed).toBe(true);
});

test('a workspace just made is current at once, from the server\'s answer to the create, while the list catches up', async () => {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => (init?.method === 'POST'
    ? json({ id: 'ws.new', name: 'Rocket' }) : json(LIST)));
  await mount();
  await settle();
  expect(seen.current.id).toBe('ws.def');
  // the list lags the create: the new workspace is still current, from the server's answer to the create
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => (init?.method === 'POST'
    ? json({ id: 'ws.new', name: 'Rocket' }) : json({ detail: 'down' }, 503)));
  let made: Promise<unknown> = Promise.resolve();
  act(() => { made = seen.create('Rocket'); });
  await settle();
  expect(seen.current).toMatchObject({ id: 'ws.new', name: 'Rocket' });
  expect(seen.known).toBe(true);
  await act(async () => { await made; });
  expect(getCurrentWorkspaceRef()).toEqual({ id: 'ws.new', isDefault: false, name: 'Rocket' });
});

test('a chosen workspace gone from the list falls back to Default and is named', async () => {
  localStorage.setItem('hr.workspace.current.org.x', JSON.stringify({ id: 'ws.gone', def: false, name: 'Studio Two' }));
  fetchMock.mockImplementation(async () => json(LIST));
  await mount();
  await settle(1300);
  expect(seen.current.id).toBe('ws.def');
  expect(seen.lost).toEqual({ name: 'Studio Two' });
  expect(getCurrentWorkspaceRef()).toEqual({ id: 'ws.def', isDefault: true, name: 'Default Workspace' });
  act(() => seen.clearLost());
  expect(seen.lost).toBeNull();
});

test('a choice stored before names were kept is named on the next read, and a present one is not lost', async () => {
  localStorage.setItem('hr.workspace.current.org.x', JSON.stringify({ id: 'ws.pm', def: false }));
  fetchMock.mockImplementation(async () => json(LIST));
  await mount();
  await settle();
  expect(seen.current.id).toBe('ws.pm');
  expect(seen.lost).toBeNull();
  expect(getCurrentWorkspaceRef()).toEqual({ id: 'ws.pm', isDefault: false, name: 'PhotoMagic' });
});

test('the list and a create go to this instance\'s own gateway, through the API proxy', async () => {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => (init?.method === 'POST'
    ? json({ id: 'ws.new', name: 'Rocket' }) : json(LIST)));
  await mount();
  await settle();
  act(() => { void seen.create('Rocket'); });
  await settle();
  const urls = fetchMock.mock.calls.map((c) => String(c[0]));
  expect(urls.length).toBeGreaterThan(1);
  for (const u of urls) expect(u).toBe('/api/harness/v1/hr/workspaces');
});
