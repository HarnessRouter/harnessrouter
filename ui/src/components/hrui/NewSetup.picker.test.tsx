/** @jest-environment jsdom */
// New setup's agent harness list (audit 10-21: at 390 a long name was cut): a harness's name is its own
// element, whole (it wraps rather than being cut), with its logo beside it and nothing else in it.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('next/navigation', () => ({ useRouter: () => ({ prefetch: jest.fn(), push: jest.fn(), replace: jest.fn() }) }));
jest.mock('@/lib/harness', () => ({
  createCustom: jest.fn(), listCustom: jest.fn(async () => []),
  offeredOob: () => [{ id: 'claude-code', name: 'Claude Code' }, { id: 'qoder', name: 'Qoder Cloud Agent' }],
  oobById: (id: string) => ({ id }),
  oobDefaultModel: () => 'claude-sonnet',
  useBasesRead: () => ({ value: { 'claude-code': { takesSkills: true }, qoder: {} }, failed: false, retry: () => {} }),
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
  DEMOS: [], baseName: (id: string) => (id === 'qoder' ? 'Qoder Cloud Agent' : 'Claude Code'), defaultBase: () => 'claude-code',
  defaultModelOf: () => 'claude-sonnet', demoPick: () => ({ base: 'claude-code', model: 'claude-sonnet' }), runnableModels: () => ['claude-sonnet'],
}));
jest.mock('./start/Handoff', () => ({ Handoff: () => null }));

import { createCustom } from '@/lib/harness';
import { NewSetup } from './NewSetup';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let el: HTMLElement;
async function flush() { for (let i = 0; i < 4; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); }
beforeEach(async () => {
  (createCustom as jest.Mock).mockReset();
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<NewSetup pre={{ job: '' }} onClose={() => {}} />); });
  await flush();
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('each harness: its name whole in its own element, and the one chosen marked', async () => {
  const opener = el.querySelector('button[aria-haspopup="listbox"]') as HTMLButtonElement;
  await act(async () => { opener.click(); });
  await flush();
  const opts = Array.from(document.querySelectorAll('[role="listbox"] [role="option"]')) as HTMLButtonElement[];
  expect(opts.map((o) => o.querySelector('.dd-hn')?.textContent)).toEqual(['Claude Code', 'Qoder Cloud Agent']);
  expect(opts.map((o) => o.getAttribute('aria-selected'))).toEqual(['true', 'false']);
  expect(document.querySelector('[role="listbox"] .h-pre')).toBeNull();
  expect(document.body.textContent).not.toContain('Auto');
});
