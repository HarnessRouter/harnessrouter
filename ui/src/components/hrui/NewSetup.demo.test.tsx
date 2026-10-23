/** @jest-environment jsdom */
// New setup and a demo picked on Start (Richard, 2026-10-22: replay it, as the hosted console does,
// rather than spend tokens on it). Saved unchanged, on the harness and model its first request was
// recorded on, a demo is saved from that recording's template (the recording's pair, instructions and
// skills; not the hosted image tools) with the recording named on the setup (`source`), and nothing
// is handed over to run live: its first task is the recording, played as its page opens. A changed
// sentence, a demo on another pair, or one with no recording runs live as any setup does; recordings
// that cannot be read are said, and nothing is saved in their place. The recorded run is a fixture.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { RecordedRun } from './start/recorded';

const INSTR = 'Generate a product image for our store from a short brief: square, studio light, soft shadow, no text on the product.';
const mockPick: { base: string; model: string; runs: string[] } = { base: 'hermes', model: 'gpt-5.4', runs: ['gpt-5.4', 'glm-5.3'] };
jest.mock('next/navigation', () => ({ useRouter: () => ({ prefetch: jest.fn(), push: jest.fn(), replace: jest.fn() }) }));
jest.mock('@/lib/harness', () => ({
  createCustom: jest.fn(), listCustom: jest.fn(),
  offeredOob: () => [{ id: 'hermes', name: 'Hermes' }, { id: 'claude-code', name: 'Claude Code' }],
  oobById: (id: string) => ({ id }),
  oobDefaultModel: () => 'glm-5.3',
  useBasesRead: () => ({ value: { hermes: {}, 'claude-code': {} }, failed: false, retry: () => {} }),
  useModelCatalogRead: () => ({ value: { models: mockPick.runs }, failed: false, retry: () => {} }),
}));
jest.mock('@/lib/providers', () => ({ providerById: () => null, useModelProviders: () => ({ connectionFor: () => null, state: 'ready' }) }));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));
jest.mock('./Sheet', () => ({ Sheet: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
jest.mock('./toast', () => ({ toast: jest.fn() }));
jest.mock('./start/art', () => ({ nwArt: () => '' }));
jest.mock('./start/open', () => ({ openNewSetup: jest.fn() }));
jest.mock('./start/seed', () => ({ seedSetup: jest.fn(), setFirstTask: jest.fn(), setFirstReplay: jest.fn() }));
jest.mock('./start/demos', () => ({
  DEMOS: [{ from: 'Product brief', to: 'product image', short: 'Product images', base: 'hermes', model: 'gpt-5.4',
    instr: 'Generate a product image for our store from a short brief: square, studio light, soft shadow, no text on the product.' }],
  baseName: (id: string) => (id === 'hermes' ? 'Hermes' : 'Claude Code'), defaultBase: () => 'hermes',
  defaultModelOf: () => 'glm-5.3',
  demoPick: () => ({ base: mockPick.base, model: mockPick.model }), runnableModels: () => mockPick.runs,
}));
jest.mock('./start/Handoff', () => ({ Handoff: () => null }));
jest.mock('./start/replay', () => ({ ...jest.requireActual('./start/replay'), loadRecording: jest.fn() }));

import { createCustom, listCustom } from '@/lib/harness';
import { openNewSetup } from './start/open';
import { seedSetup, setFirstReplay, setFirstTask } from './start/seed';
import { loadRecording } from './start/replay';
import { NewSetup } from './NewSetup';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const RUN = {
  demo: 0, ranAt: 1792378362430, base: 'hermes', model: 'gpt-5.4', request: `${INSTR}\n\nA matte black ceramic mug with a bamboo lid.`,
  durMs: 105166, status: 'completed', events: [{ t: 0, ev: { type: 'response.created' } }], files: [],
  template: {
    demo: 0, name: 'Product images', base: 'hermes', model: 'gpt-5.4', instructions: INSTR,
    skills: [{ id: 'product-shot-style', name: 'Product shot style', body: 'Square.',
      skill: { name: 'product-shot-style', enabled: true, files: [{ path: 'SKILL.md', content: 'Square.' }] } }],
    plugins: [{ id: 'media', name: 'Image generation' }],
  },
} as unknown as RecordedRun;

const create = createCustom as jest.Mock;
const rec = loadRecording as jest.Mock;
let root: Root;
let el: HTMLElement;
const line = () => (el.querySelector('#nwCost')?.textContent || '').replace(/\s+/g, ' ').trim();
const save = () => el.querySelector('button[aria-label="Save setup"]') as HTMLButtonElement;
async function flush() { for (let i = 0; i < 4; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); }
async function open() {
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<NewSetup pre={{ demo: 0 }} onClose={() => {}} />); });
  await flush();
}
async function press() { await act(async () => { save().click(); }); await flush(); }
function type(text: string) {
  const ta = el.querySelector('#nwJob') as HTMLTextAreaElement;
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
  act(() => { set?.call(ta, text); ta.dispatchEvent(new Event('input', { bubbles: true })); });
}
beforeEach(() => {
  Object.assign(mockPick, { base: 'hermes', model: 'gpt-5.4', runs: ['gpt-5.4', 'glm-5.3'] });
  create.mockReset(); rec.mockReset();
  (listCustom as jest.Mock).mockResolvedValue([]);
  create.mockResolvedValue({ id: 'chrn_demo', name: 'Product images', source: 'demo:0@1792378362430' });
  rec.mockResolvedValue(RUN);
  [openNewSetup, seedSetup, setFirstTask, setFirstReplay].forEach((f) => (f as jest.Mock).mockClear());
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('an unchanged demo is saved from its recording, names it, and hands nothing over to run live', async () => {
  await open();
  await press();
  expect(rec).toHaveBeenCalledWith(0);
  expect(create).toHaveBeenCalledTimes(1);
  const body = create.mock.calls[0][0];
  expect(body).toMatchObject({
    name: 'Product images', base: 'hermes', baseLabel: 'Hermes', defaultModel: 'gpt-5.4', systemPrompt: INSTR,
    source: 'demo:0@1792378362430',
  });
  // the recording's own skills, saved under a fresh id; the hosted image tools are not added
  expect(body.skills).toEqual([{ id: expect.stringMatching(/^skl_[a-z0-9]+$/i), name: 'product-shot-style', enabled: true, files: [{ path: 'SKILL.md', content: 'Square.' }] }]);
  expect(body).not.toHaveProperty('plugins');
  expect(seedSetup).toHaveBeenCalledWith('chrn_demo', { h: { id: 'chrn_demo', name: 'Product images', source: 'demo:0@1792378362430' } });
  // its first task is the recording, played as its page opens: no live first task
  expect(setFirstReplay).toHaveBeenCalledWith('chrn_demo');
  expect(setFirstTask).not.toHaveBeenCalled();
  expect((openNewSetup as jest.Mock).mock.calls[0][1]).toEqual({ id: 'chrn_demo' });
});

test('a sentence the person changed runs live, and no recording is asked for', async () => {
  await open();
  type(`${INSTR} Use a warm grey background.`);
  create.mockResolvedValue({ id: 'chrn_own', name: 'Generate a product image' });
  await press();
  expect(rec).not.toHaveBeenCalled();
  const body = create.mock.calls[0][0];
  expect(body.systemPrompt).toBe(`${INSTR} Use a warm grey background.`);
  expect(body).not.toHaveProperty('source');
  expect(body).not.toHaveProperty('skills');
  expect(setFirstTask).toHaveBeenCalledWith('chrn_own', `${INSTR} Use a warm grey background.`);
  expect(setFirstReplay).not.toHaveBeenCalled();
});

test('a demo on a model other than its recording’s runs live: nothing is played that did not run there', async () => {
  // this instance cannot run the recording's model on its harness: the demo opens on another one
  Object.assign(mockPick, { model: '', runs: ['glm-5.3'] });
  await open();
  await press();
  const body = create.mock.calls[0][0];
  expect(body).toMatchObject({ name: 'Product images', base: 'hermes', defaultModel: 'glm-5.3', systemPrompt: INSTR });
  expect(body).not.toHaveProperty('source');
  expect(setFirstTask).toHaveBeenCalledWith('chrn_demo', INSTR);
  expect(setFirstReplay).not.toHaveBeenCalled();
});

test('a demo with no recording runs live as any setup does', async () => {
  rec.mockResolvedValue(null);
  await open();
  await press();
  expect(create.mock.calls[0][0]).not.toHaveProperty('source');
  expect(setFirstTask).toHaveBeenCalledWith('chrn_demo', INSTR);
  expect(setFirstReplay).not.toHaveBeenCalled();
});

test('recordings that cannot be read are said, nothing is saved in their place, and Save tries again', async () => {
  rec.mockRejectedValueOnce(new Error('Loading chunk 412 failed.'));
  await open();
  await press();
  expect(line()).toBe('The recorded demo run could not be read just now. Try again.');
  expect(create).not.toHaveBeenCalled();
  expect(setFirstTask).not.toHaveBeenCalled();
  expect(openNewSetup).not.toHaveBeenCalled();
  expect(save().disabled).toBe(false);
  await press();
  expect(create.mock.calls[0][0]).toMatchObject({ source: 'demo:0@1792378362430' });
  expect(setFirstReplay).toHaveBeenCalledWith('chrn_demo');
});
