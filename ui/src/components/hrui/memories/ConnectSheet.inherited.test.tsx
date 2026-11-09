/** @jest-environment jsdom */
// Connecting an engine in a workspace that uses the instance's: the sheet says so, offers to connect one of the
// workspace's own, and never claims a key is kept here (the instance's key is not this workspace's to keep).
import { act } from 'react';
import { createRoot } from 'react-dom/client';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const plugs = jest.fn();
jest.mock('@/lib/memories', () => ({
  listProviderPlugs: () => plugs(), connectProvider: jest.fn(), agentMemoryOf: jest.fn(), chooseEngine: jest.fn(),
  createMemory: jest.fn(), setAgentMemory: jest.fn(), updateMemory: jest.fn(),
}));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => []) }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/workspace-feed', () => ({ lastTaskBySetup: jest.fn(async () => ({})) }));
jest.mock('../setup/settingsModel', () => ({ plain: (_e: unknown, s: string) => s }));
// eslint-disable-next-line import/first
import { ConnectSheet } from './sheets';

const open = async (row: Record<string, unknown>) => {
  plugs.mockResolvedValue([{ type: 'mem0', status: 'connected', config: { base_url: 'http://mem0:8000' }, secrets_set: ['api_key'], ...row }]);
  const host = document.createElement('div'); document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<ConnectSheet id="mem0" connected onClose={() => {}} onConnected={() => {}} />); });
  await act(async () => { await Promise.resolve(); });
  return { host: document.body, done: () => act(() => { root.unmount(); host.remove(); }) };
};

test("the instance's engine: said so, an empty form to connect one here, and no kept key claimed", async () => {
  const { host, done } = await open({ inherited: true, note: "This workspace uses this instance's Mem0 (inherited)." });
  expect(host.querySelector('.mm-inherited')?.textContent).toBe(
    "This workspace uses this instance's Mem0 (inherited). Connect one here to use it in this workspace instead.");
  expect(host.querySelector('#mmCn')?.textContent).toBe('Connect Mem0 for this workspace');
  expect((host.querySelector('#mmCnBase') as HTMLInputElement).value).toBe('');
  expect((host.querySelector('#mmCnKey') as HTMLInputElement).placeholder).toBe('');
  const submit = host.querySelector('button[type=submit]') as HTMLButtonElement;
  expect(submit.textContent).toBe('Connect');
  expect(submit.disabled).toBe(true);   // nothing of its own yet: a key or an address is needed first
  done();
});

test("the workspace's own: changed in place, its address shown and its key said to be kept", async () => {
  const { host, done } = await open({});
  expect(host.querySelector('.mm-inherited')).toBeNull();
  expect(host.querySelector('#mmCn')?.textContent).toBe('Change Mem0');
  expect((host.querySelector('#mmCnBase') as HTMLInputElement).value).toBe('http://mem0:8000');
  expect((host.querySelector('#mmCnKey') as HTMLInputElement).placeholder).toBe('Keep the key already saved');
  expect((host.querySelector('button[type=submit]') as HTMLButtonElement).textContent).toBe('Save');
  done();
});
