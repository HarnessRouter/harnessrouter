/** @jest-environment jsdom */
// New workspace: the create goes to this instance's gateway, the new workspace is current, and whatever the gateway
// refuses is said under the name in its own words (a plain sentence it gave), never a limit of ours and never a
// service's internal error.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/auth', () => ({ getSession: jest.fn() }));
jest.mock('./toast', () => ({ toast: jest.fn() }));

import { getSession } from '@/lib/auth';
import { useWorkspace, WorkspaceProvider } from '@/lib/workspace';
import { NewWorkspaceSheet } from './WorkspaceSheets';
import { toast } from './toast';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const fetchMock = jest.fn();
global.fetch = fetchMock as unknown as typeof fetch;
const res = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });
const LIST = { default_workspace_id: 'ws.def', workspaces: [{ id: 'ws.def', name: 'Default Workspace', role: 'member' }] };

let root: Root | null = null;
let el: HTMLElement;
let ctx: ReturnType<typeof useWorkspace>;
function Probe() { ctx = useWorkspace(); return null; }
const flush = async () => { for (let i = 0; i < 8; i++) await act(async () => { await Promise.resolve(); }); };
const btn = (t: string) => Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent === t) as HTMLButtonElement | undefined;

/** The provider (the real create, against the gateway's answer `post`) and the sheet. */
async function show(post: { ok: boolean; status: number; json: () => Promise<unknown> }) {
  let made: Record<string, unknown> | null = null;
  fetchMock.mockImplementation(async (_u: string, init?: { method?: string }) => {
    if (init?.method === 'POST') { if (post.ok) made = { ...(await post.json() as Record<string, unknown>), role: 'admin' }; return post; }
    // the list, with a workspace just made in it (its creator is its Admin)
    return res(200, { ...LIST, workspaces: [...LIST.workspaces, ...(made ? [made] : [])] });
  });
  el = document.createElement('div');
  document.body.appendChild(el);
  const r = createRoot(el);
  root = r;
  await act(async () => { r.render(<WorkspaceProvider><Probe /><NewWorkspaceSheet onClose={jest.fn()} /></WorkspaceProvider>); });
  await flush();
}
async function make(name: string) {
  const i = document.getElementById('nwName') as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(i, name); i.dispatchEvent(new Event('input', { bubbles: true })); });
  await act(async () => { btn('Create workspace')?.click(); });
  await flush();
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear(); sessionStorage.clear();
  (getSession as jest.Mock).mockReturnValue({ orgId: 'org.x', member: { id: 'member.dana' }, orgs: [{ id: 'org.x', owner_id: 'member.ann', role: 'member', personal: false }] });
});
afterEach(() => { if (root) { const r = root; act(() => r.unmount()); el.remove(); root = null; } document.body.innerHTML = ''; });

test('the create goes through: the gateway’s POST, the new workspace current, and its “is ready.” for the next page', async () => {
  await show(res(200, { id: 'ws.rocket', name: 'Rocket', description: '' }));
  await make('Rocket');
  expect(fetchMock).toHaveBeenCalledWith('/api/harness/v1/hr/workspaces', expect.objectContaining({ method: 'POST', body: JSON.stringify({ name: 'Rocket', description: '' }) }));
  expect(ctx.current.id).toBe('ws.rocket');
  expect(sessionStorage.getItem('hrui.toast.next')).toBe('Rocket is ready.');
  expect(document.body.querySelector('#nwWhy')).toBeNull();
});

test('a refusal says the gateway’s words under the name, and offers no plans', async () => {
  await show(res(403, { detail: 'A key held to one workspace does not make workspaces.' }));
  await make('Rocket');
  const why = document.getElementById('nwWhy') as HTMLElement;
  expect(why.getAttribute('role')).toBe('alert');
  expect(why.textContent).toBe('A key held to one workspace does not make workspaces.');
  expect(btn('See plans')).toBeUndefined();
  expect(toast).not.toHaveBeenCalled();
});

test('any other failure: one plain line, never what the service answered', async () => {
  await show(res(502, { detail: 'upstream unreachable: connect ECONNREFUSED' }));
  await make('Rocket');
  expect(document.getElementById('nwWhy')?.textContent).toBe('The workspace could not be created. Try again in a moment.');
  expect(document.body.textContent).not.toContain('ECONNREFUSED');
});

test('an empty name is marked, and nothing is sent', async () => {
  await show(res(200, { id: 'ws.x', name: 'X', description: '' }));
  await make('   ');
  expect(toast).toHaveBeenCalledWith('Give the workspace a name.');
  expect(fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === 'POST')).toBe(false);
});
