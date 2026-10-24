/** @jest-environment jsdom */
// New setup on this edition, as the hosted console does it: Save starts a build of the setup (start/
// build.ts) with the sentence, the agent harness and the model as chosen (Auto goes as it is: the
// server picks), and opens the page of the setup being made; the sheet saves nothing itself and never
// saves the sentence as instructions. A sentence too short to say what it does is refused before
// anything starts. With no model key that runs a model, the line under the box says to connect one and
// Save waits; a harness chosen that no key runs a model on says where keys are added.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const mockRun: { models: Record<string, string[]> } = { models: { 'claude-code': ['claude-sonnet'], hermes: ['gpt-5.4'] } };
jest.mock('next/navigation', () => ({ useRouter: () => ({ prefetch: jest.fn(), push: jest.fn(), replace: jest.fn() }) }));
jest.mock('@/lib/harness', () => ({
  createCustom: jest.fn(), listCustom: jest.fn(),
  offeredOob: () => [{ id: 'claude-code', name: 'Claude Code' }, { id: 'hermes', name: 'Hermes' }],
  oobById: (id: string) => ({ id }),
  oobDefaultModel: () => 'claude-sonnet',
  useBasesRead: () => ({ value: { 'claude-code': {}, hermes: {} }, failed: false, retry: () => {} }),
  useModelCatalogRead: () => ({ value: { models: ['claude-sonnet'] }, failed: false, retry: () => {} }),
}));
jest.mock('@/lib/providers', () => ({ providerById: () => null, useModelProviders: () => ({ connectionFor: () => null, state: 'ready' }) }));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));
jest.mock('./Sheet', () => ({ Sheet: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
jest.mock('./toast', () => ({ toast: jest.fn() }));
jest.mock('./start/art', () => ({ nwArt: () => '' }));
jest.mock('./start/build', () => ({ startBuild: jest.fn(() => ({ key: 'bk1' })) }));
jest.mock('./start/open', () => ({ openNewSetup: jest.fn() }));
jest.mock('./start/compose', () => ({ AUTO: 'auto' }));
jest.mock('./start/demos', () => ({
  DEMOS: [{ from: 'Contract', to: 'risk review', short: 'Contract review', base: 'hermes', model: 'gpt-5.4', instr: 'Review this contract clause and list each risk.' }],
  baseName: (id: string) => (id === 'hermes' ? 'Hermes' : id === 'auto' ? 'auto' : 'Claude Code'),
  demoPick: () => ({ base: 'hermes', model: 'gpt-5.4' }), runnableModels: (b: string) => mockRun.models[b] || [],
}));
jest.mock('./start/Handoff', () => ({ Handoff: () => null }));

import { createCustom } from '@/lib/harness';
import { startBuild } from './start/build';
import { openNewSetup } from './start/open';
import { NewSetup } from './NewSetup';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let root: Root;
let el: HTMLElement;
const line = () => (el.querySelector('#nwCost')?.textContent || '').replace(/\s+/g, ' ').trim();
const save = () => el.querySelector('button[aria-label="Save setup"]') as HTMLButtonElement;
async function flush() { for (let i = 0; i < 4; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); }
async function open(pre: { job?: string; demo?: number }) {
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<NewSetup pre={pre} onClose={() => {}} />); });
  await flush();
}
beforeEach(() => {
  mockRun.models = { 'claude-code': ['claude-sonnet'], hermes: ['gpt-5.4'] };
  (startBuild as jest.Mock).mockClear(); (openNewSetup as jest.Mock).mockClear(); (createCustom as jest.Mock).mockReset();
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('Save starts a build with the sentence and Auto as it is, then opens the page of the setup being made', async () => {
  await open({ job: 'Answer support emails: look up the order, then draft a reply.' });
  expect(el.querySelector('#nwPicks')?.textContent).toContain('Auto');
  expect(save().disabled).toBe(false);
  await act(async () => { save().click(); });
  await flush();
  expect(startBuild).toHaveBeenCalledTimes(1);
  expect((startBuild as jest.Mock).mock.calls[0][0]).toMatchObject({
    job: 'Answer support emails: look up the order, then draft a reply.', base: 'auto', model: 'auto', demo: null,
    pick: { baseName: '', model: '' },
  });
  expect((openNewSetup as jest.Mock).mock.calls[0][1]).toEqual({ build: 'bk1' });
  // the sheet saves nothing itself: the build does, and never with the sentence as its instructions
  expect(createCustom).not.toHaveBeenCalled();
});

test('an unchanged demo starts on its own harness and model, and is built as that demo', async () => {
  await open({ demo: 0 });
  expect(el.querySelector('#nwPicks')?.textContent).toContain('Hermes');
  expect(el.querySelector('#nwPicks')?.textContent).toContain('gpt-5.4');
  await act(async () => { save().click(); });
  await flush();
  expect((startBuild as jest.Mock).mock.calls[0][0]).toMatchObject({ base: 'hermes', model: 'gpt-5.4', demo: 0, baseName: 'Hermes' });
  expect(el.querySelector('#nwBuild')).not.toBeNull();
});

test('a sentence too short to say what it does is refused before anything starts', async () => {
  await open({ job: 'Emails' });
  await act(async () => { save().click(); });
  await flush();
  expect(startBuild).not.toHaveBeenCalled();
  expect(line()).toBe('Write it as a sentence, e.g. Answer support emails in our tone.');
});

test('with no model key that runs a model, the line says to connect one and Save waits', async () => {
  mockRun.models = {};
  await open({ job: 'Review a contract and flag the risky clauses.' });
  expect(line()).toContain('Connect a model key to set up an agent harness.');
  expect((el.querySelector('#nwCost a') as HTMLAnchorElement).getAttribute('href')).toBe('/byok');
  expect(save().disabled).toBe(true);
  await act(async () => { save().click(); });
  expect(startBuild).not.toHaveBeenCalled();
});

test('a harness chosen that no key runs a model on says where keys are added, and Save waits', async () => {
  mockRun.models = { hermes: ['gpt-5.4'] };
  await open({ job: 'Review a contract and flag the risky clauses.' });
  const opener = el.querySelector('button[aria-haspopup="listbox"]') as HTMLButtonElement;
  await act(async () => { opener.click(); });
  await flush();
  const cc = Array.from(document.querySelectorAll('[role="option"]')).find((o) => o.textContent?.includes('Claude Code')) as HTMLButtonElement;
  await act(async () => { cc.click(); });
  await flush();
  expect(line()).toContain('None of your keys runs a model on Claude Code yet.');
  expect(save().disabled).toBe(true);
});

test('names nothing this edition does not have: no free requests, balance or request check', async () => {
  await open({ job: 'Review a contract and flag the risky clauses.' });
  expect(el.textContent).not.toMatch(/free request|balance|could not be checked/i);
});
