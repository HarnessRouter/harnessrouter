/** @jest-environment jsdom */
// "Who uses it" on Bring your own key is read from every workspace's setups. When the workspaces could
// not be listed the read is failed (the remove confirm then leaves the sentence out), never one
// workspace's setups read as everyone's, which made it say "No setup uses it right now."
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/workspace', () => ({ useWorkspace: jest.fn() }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn() }));
jest.mock('@/lib/chat', () => ({ authHeaders: () => ({}) }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org.x' }) }));
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }));
jest.mock('./toast', () => ({ toast: jest.fn() }));
jest.mock('./Sheet', () => ({ ConfirmSheet: () => null }));
jest.mock('./Skel', () => ({ Skel: () => null, SkRows: () => null, SkLine: () => null }));
jest.mock('./byok/KeyForm', () => ({ KeyForm: () => null }));

import { useWorkspace } from '@/lib/workspace';
import { harnessFetch } from '@/lib/hfetch';
import { listCustom } from '@/lib/harness';
import { useAllSetups } from './ByokPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });
let root: Root;
let el: HTMLElement;
let seen: ReturnType<typeof useAllSetups>;
function Probe() { seen = useAllSetups(); return null; }
async function mount() {
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<Probe />); });
  for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve(); });
}
beforeEach(() => { jest.clearAllMocks(); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('workspaces that could not be listed: failed, and no setups read without naming a workspace', async () => {
  (useWorkspace as jest.Mock).mockReturnValue({ workspaces: [], defaultId: '', loading: false });
  await mount();
  expect(seen).toBe('failed');
  expect(listCustom).not.toHaveBeenCalled();
  expect(harnessFetch).not.toHaveBeenCalled();
});

test('every workspace\'s setups, read by workspace', async () => {
  (useWorkspace as jest.Mock).mockReturnValue({ workspaces: [{ id: 'ws.def' }, { id: 'ws.pm' }], defaultId: 'ws.def', loading: false });
  (harnessFetch as jest.Mock).mockImplementation(async (url: string) => json({ harnesses: [{ name: url.includes('ws.pm') ? 'Photo' : 'Main', defaultModel: 'gpt-5' }] }));
  await mount();
  expect(seen).toEqual([{ name: 'Main', model: 'gpt-5' }, { name: 'Photo', model: 'gpt-5' }]);
});

test('a workspace whose read answers something other than its setups is a failed read, not "none"', async () => {
  (useWorkspace as jest.Mock).mockReturnValue({ workspaces: [{ id: 'ws.def' }], defaultId: 'ws.def', loading: false });
  (harnessFetch as jest.Mock).mockResolvedValue(json({ detail: 'ok' }));
  await mount();
  expect(seen).toBe('failed');
});
