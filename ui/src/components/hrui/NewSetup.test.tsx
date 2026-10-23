/** @jest-environment jsdom */
// New setup on this edition: Save makes the setup at once (POST /v1/harnesses through createCustom),
// named from the lead of its sentence and kept apart from the workspace's other names, with the
// sentence as its instructions and the harness and model chosen; then its page opens on its Tasks with
// the saved record handed to it. A sentence too short to say what it does is refused before anything
// is sent, a save that fails says so and opens nothing, and a harness no key can run a model on says
// where keys are added rather than offering a Save that cannot work.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const mockRun: { models: string[] } = { models: ['claude-sonnet'] };
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
jest.mock('./start/open', () => ({ openNewSetup: jest.fn() }));
jest.mock('./start/seed', () => ({ seedSetup: jest.fn(), setFirstTask: jest.fn() }));
jest.mock('./start/demos', () => ({
  DEMOS: [{ from: 'Contract', to: 'risk review', short: 'Contract review', base: 'hermes', model: 'claude-sonnet', instr: 'Review this contract clause and list each risk.' }],
  baseName: (id: string) => (id === 'hermes' ? 'Hermes' : 'Claude Code'), defaultBase: () => 'claude-code',
  defaultModelOf: () => (mockRun.models.includes('claude-sonnet') ? 'claude-sonnet' : ''),
  demoPick: () => ({ base: 'hermes', model: 'claude-sonnet' }), runnableModels: () => mockRun.models,
}));
jest.mock('./start/Handoff', () => ({ Handoff: () => null }));

import { createCustom, listCustom } from '@/lib/harness';
import { openNewSetup } from './start/open';
import { seedSetup, setFirstTask } from './start/seed';
import { NewSetup } from './NewSetup';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const create = createCustom as jest.Mock;
const list = listCustom as jest.Mock;
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
  mockRun.models = ['claude-sonnet'];
  create.mockReset(); list.mockReset();
  list.mockResolvedValue([{ id: 'h0', name: 'Answer support emails' }]);
  (openNewSetup as jest.Mock).mockClear(); (seedSetup as jest.Mock).mockClear(); (setFirstTask as jest.Mock).mockClear();
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('Save makes the setup at once: named from its sentence, kept apart, the sentence its instructions and its first task; then its page opens', async () => {
  create.mockResolvedValue({ id: 'chrn_new', name: 'Answer support emails 2' });
  await open({ job: 'Answer support emails: look up the order, then draft a reply.' });
  expect(save().disabled).toBe(false);
  await act(async () => { save().click(); });
  await flush();
  expect(create).toHaveBeenCalledTimes(1);
  expect(create.mock.calls[0][0]).toEqual({
    name: 'Answer support emails 2', base: 'claude-code', baseLabel: 'Claude Code', defaultModel: 'claude-sonnet',
    systemPrompt: 'Answer support emails: look up the order, then draft a reply.',
  });
  expect(seedSetup).toHaveBeenCalledWith('chrn_new', { h: { id: 'chrn_new', name: 'Answer support emails 2' } });
  // what the person sent runs as the setup's first task as its page opens (Richard 10-22)
  expect(setFirstTask).toHaveBeenCalledWith('chrn_new', 'Answer support emails: look up the order, then draft a reply.');
  expect((openNewSetup as jest.Mock).mock.calls[0][1]).toEqual({ id: 'chrn_new' });
});

test('an unchanged demo saves under its own name, on its own harness and model', async () => {
  create.mockResolvedValue({ id: 'chrn_demo', name: 'Contract review' });
  await open({ demo: 0 });
  await act(async () => { save().click(); });
  await flush();
  expect(create.mock.calls[0][0]).toMatchObject({ name: 'Contract review', base: 'hermes', defaultModel: 'claude-sonnet' });
  expect(el.querySelector('#nwBuild')).not.toBeNull();
});

test('a sentence too short to say what it does is refused before anything is sent', async () => {
  await open({ job: 'Emails' });
  await act(async () => { save().click(); });
  await flush();
  expect(create).not.toHaveBeenCalled();
  expect(line()).toBe('Write it as a sentence, e.g. Answer support emails in our tone.');
});

test('a save that fails says so, opens nothing, and can be sent again', async () => {
  create.mockRejectedValueOnce(new Error('503'));
  await open({ job: 'Review a contract and flag the risky clauses.' });
  await act(async () => { save().click(); });
  await flush();
  expect(line()).toBe('The setup could not be saved just now. Try again.');
  expect(openNewSetup).not.toHaveBeenCalled();
  expect(setFirstTask).not.toHaveBeenCalled();     // nothing to run: nothing was made
  expect(save().disabled).toBe(false);
  create.mockResolvedValueOnce({ id: 'chrn_2', name: 'Review a contract and flag' });
  await act(async () => { save().click(); });
  await flush();
  expect((openNewSetup as jest.Mock).mock.calls[0][1]).toEqual({ id: 'chrn_2' });
});

test('a harness no key runs a model on says where keys are added, and Save waits', async () => {
  mockRun.models = [];
  await open({ job: 'Review a contract and flag the risky clauses.' });
  expect(line()).toContain('None of your keys runs a model on Claude Code yet.');
  expect((el.querySelector('#nwCost a') as HTMLAnchorElement).getAttribute('href')).toBe('/byok');
  expect(save().disabled).toBe(true);
});

test('names nothing it cannot back: no free requests, balance or Auto', async () => {
  await open({ job: 'Review a contract and flag the risky clauses.' });
  expect(el.textContent).not.toMatch(/free request|balance|Auto/);
});
