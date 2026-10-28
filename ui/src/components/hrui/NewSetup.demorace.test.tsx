/** @jest-environment jsdom */
// A demo picked on a fresh Start opens the sheet before the server's harness list has landed (as on the hosted console: the
// first demo picked opened on Auto and kept it, so it was saved composed and renamed on another harness). Once the list is
// in, the sheet takes the demo's own pair and saves it as the demo.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const mockBases: { value: Record<string, unknown> | null } = { value: null };
const mockRuns: { models: string[] } = { models: ['claude-sonnet'] };
jest.mock('next/navigation', () => ({ useRouter: () => ({ prefetch: jest.fn(), push: jest.fn(), replace: jest.fn() }) }));
jest.mock('@/lib/harness', () => ({
  gw: jest.fn(),
  offeredOob: (b: Record<string, unknown> | null) => (b ? [{ id: 'claude-code', name: 'Claude Code' }] : []),
  oobById: (id: string) => ({ id }),
  oobDefaultModel: () => 'claude-sonnet',
  useBasesRead: () => ({ value: mockBases.value, failed: false, retry: () => {} }),
  useModelCatalogRead: () => ({ value: { models: ['claude-sonnet'] }, failed: false, retry: () => {} }),
}));
jest.mock('@/lib/providers', () => ({ providerById: () => null, useModelProviders: () => ({ connectionFor: () => null, state: 'ready' }) }));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));
jest.mock('./Sheet', () => ({ Sheet: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
jest.mock('./toast', () => ({ toast: jest.fn() }));
jest.mock('./start/art', () => ({ nwArt: () => '' }));
jest.mock('./start/build', () => ({ startBuild: jest.fn(() => ({ key: 'b1' })) }));
jest.mock('./start/open', () => ({ openNewSetup: jest.fn() }));
jest.mock('./start/compose', () => ({ AUTO: 'auto' }));
jest.mock('./start/demos', () => ({
  DEMOS: [{ from: 'Contract', to: 'risk review', short: 'Contract review', instr: 'Review a contract and list the clauses that carry risk, please.', base: 'claude-code', model: 'claude-sonnet' }],
  baseName: () => 'Claude Code',
  demoPick: (_i: number, b: Record<string, unknown> | null) => (b ? { base: 'claude-code', model: mockRuns.models.includes('claude-sonnet') ? 'claude-sonnet' : '' } : { base: '', model: '' }),
  runnableModels: () => ['claude-sonnet'],
}));
jest.mock('./start/Handoff', () => ({ Handoff: () => null }));

import { NewSetup } from './NewSetup';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let el: HTMLElement;
async function flush() { for (let i = 0; i < 4; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); }
const picks = () => Array.from(el.querySelectorAll('.nw-pk b')).map((b) => (b.textContent || '').trim());
beforeEach(() => { mockBases.value = null; mockRuns.models = ['claude-sonnet']; el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('a demo opened before the harness list lands takes its own pair once it does, and saves as the demo', async () => {
  await act(async () => { root.render(<NewSetup pre={{ demo: 0 }} onClose={() => {}} />); });
  await flush();
  expect(picks()[0]).toBe('Auto');                                     // nothing to pick from yet
  mockBases.value = { 'claude-code': { takesSkills: true } };
  await act(async () => { root.render(<NewSetup pre={{ demo: 0 }} onClose={() => {}} />); });
  await flush();
  expect(picks()).toEqual(['Claude Code', 'claude-sonnet']);
  expect(el.querySelector('button.send')?.id).toBe('nwBuild');           // saved as the demo, not composed
});

test('a demo whose model could not run yet when the sheet settled on Auto takes it once it can', async () => {
  mockBases.value = { 'claude-code': { takesSkills: true } };
  mockRuns.models = [];                                                   // the model's availability has not landed
  await act(async () => { root.render(<NewSetup pre={{ demo: 0 }} onClose={() => {}} />); });
  await flush();
  expect(picks()).toEqual(['Claude Code', 'Auto']);
  mockRuns.models = ['claude-sonnet'];
  await act(async () => { root.render(<NewSetup pre={{ demo: 0 }} onClose={() => {}} />); });
  await flush();
  expect(picks()).toEqual(['Claude Code', 'claude-sonnet']);
  expect(el.querySelector('button.send')?.id).toBe('nwBuild');
});
