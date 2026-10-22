/** @jest-environment jsdom */
// Setting a kit up offers only what this organization can run (Richard 10-19: a control that is not
// available is hidden, never shown disabled with why). The recommended pairing leads when it can run;
// else the first that can is chosen. When none can, that is said once, with where to fix it.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Kit } from './kits';

jest.mock('@/lib/harness', () => ({ testDatabase: jest.fn() }));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
jest.mock('./kits', () => ({ ...jest.requireActual('./kits'), launchKit: jest.fn(async () => ({ harnessId: 'h1', route: '/kits/x', created: true })) }));

import { testDatabase } from '@/lib/harness';
import { launchKit } from './kits';
import { LaunchSheet } from './LaunchSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const KIT = (choices: Kit['choices']): Kit => ({
  id: 'dashboard', title: 'Dashboard', tagline: '', description: '', icon: '', accent: '', route: '/kits/dashboard', iconUrl: '',
  launched: false, harnessId: null, skills: [], runningOn: null, choices,
});
const C = (base: string, model: string, available: boolean, recommended = false) => ({ base, model, baseLabel: base, available, recommended });

let root: Root;
let el: HTMLElement;
beforeEach(() => { el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); (launchKit as jest.Mock).mockClear(); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

async function open(kit: Kit) {
  await act(async () => { root.render(<LaunchSheet kit={kit} bases={[]} mode="try" onClose={jest.fn()} onDone={jest.fn()} />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
const options = () => Array.from(document.querySelectorAll('.ship-opts [role="radio"]'));

it('lists only what can run, and starts on the one that can when the recommended cannot', async () => {
  await open(KIT([C('claude-code', 'opus', false, true), C('codex', 'gpt', true)]));
  expect(options().map((o) => o.querySelector('small')?.textContent)).toEqual(['gpt']);
  expect(options()[0].getAttribute('aria-checked')).toBe('true');
  expect(document.body.textContent).not.toContain('Not connected');
  expect(document.querySelector('[role="dialog"] p.sub')).toBeNull();          // no line under the title
  await act(async () => { (Array.from(document.querySelectorAll('button')).find((b) => b.textContent === 'Try it') as HTMLButtonElement).click(); });
  expect(launchKit).toHaveBeenCalledWith('dashboard', expect.objectContaining({ base: 'codex', model: 'gpt' }));
});

it('offers only the agent harnesses and models something connected can run, when choosing another', async () => {
  const bases = [
    { id: 'claude-code', label: 'Claude Code', models: [{ id: 'opus', available: false }] },
    { id: 'codex', label: 'Codex', models: [{ id: 'gpt-a', available: true }, { id: 'gpt-b', available: false }] },
  ];
  await act(async () => { root.render(<LaunchSheet kit={KIT([C('codex', 'gpt-a', true, true)])} bases={bases} mode="try" onClose={jest.fn()} onDone={jest.fn()} />); });
  await act(async () => { (Array.from(document.querySelectorAll('button')).find((b) => b.textContent === 'Choose a different one') as HTMLButtonElement).click(); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  const opts = (sel: string) => Array.from((document.getElementById(sel) as HTMLSelectElement).options).map((o) => o.textContent);
  expect(opts('klBase')).toEqual(['Codex']);
  expect(opts('klModel')).toEqual(['gpt-a']);
});

it('says once when nothing can run it', async () => {
  await open(KIT([C('claude-code', 'opus', false, true)]));
  expect(options()).toHaveLength(0);
  expect(document.querySelector('.kl-warn')?.textContent).toContain('None of these can run yet.');
});

const click = async (label: string) => {
  const b = Array.from(document.querySelectorAll('button')).find((x) => x.textContent === label) as HTMLButtonElement | undefined;
  if (!b) throw new Error(`no button ${label}: ${document.body.textContent}`);
  await act(async () => { b.click(); await new Promise((r) => setTimeout(r, 0)); });
};

it('what can run, unread: says so where the choice is made, with Try again, and never that nothing can run', async () => {
  const retry = jest.fn();
  await act(async () => { root.render(<LaunchSheet kit={KIT([C('codex', 'gpt-a', true, true)])} bases={null} basesFailed onRetryBases={retry} mode="try" onClose={jest.fn()} onDone={jest.fn()} />); });
  await click('Choose a different one');
  const line = document.querySelector('[role="dialog"] [role="alert"]');
  expect(line?.textContent).toBe('The agent harnesses you can run could not be read just now. Try again');
  expect(document.getElementById('klBase')).toBeNull();
  expect(document.body.textContent).not.toContain('Nothing you have connected');
  await click('Try again');
  expect(retry).toHaveBeenCalledTimes(1);
  // read now: the choices are back
  await act(async () => { root.render(<LaunchSheet kit={KIT([C('codex', 'gpt-a', true, true)])} bases={[{ id: 'codex', label: 'Codex', models: [{ id: 'gpt-a', available: true }] }]} onRetryBases={retry} mode="try" onClose={jest.fn()} onDone={jest.fn()} />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  expect(document.querySelector('[role="dialog"] [role="alert"]')).toBeNull();
  expect(Array.from((document.getElementById('klBase') as HTMLSelectElement).options).map((o) => o.textContent)).toEqual(['Codex']);
});

it('while what can run is still being read, says nothing about it', async () => {
  await act(async () => { root.render(<LaunchSheet kit={KIT([C('codex', 'gpt-a', true, true)])} bases={null} mode="try" onClose={jest.fn()} onDone={jest.fn()} />); });
  await click('Choose a different one');
  expect(document.body.textContent).not.toContain('Nothing you have connected');
  // read, and nothing can: that is said
  await act(async () => { root.render(<LaunchSheet kit={KIT([C('codex', 'gpt-a', true, true)])} bases={[]} mode="try" onClose={jest.fn()} onDone={jest.fn()} />); });
  expect(document.body.textContent).toContain('Nothing you have connected can run an agent harness yet.');
});

it('a connection test that got no answer says it could not be checked, not that the string is wrong', async () => {
  const kit = { ...KIT([C('codex', 'gpt-a', true, true)]), database: { engines: ['postgres'] } };
  (testDatabase as jest.Mock).mockRejectedValueOnce(new Error('offline'));
  await open(kit);
  const input = document.getElementById('klDb') as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(input, 'postgresql://u:p@db.example.com:5432/x'); input.dispatchEvent(new Event('input', { bubbles: true })); });
  await click('Test connection');
  expect(document.querySelector('.kl-test [role="status"]')?.textContent).toBe('The connection could not be checked just now. Try again.');
  (testDatabase as jest.Mock).mockResolvedValueOnce({ ok: true, database: 'x', tableCount: 3 });
  await click('Test connection');
  expect(document.querySelector('.kl-test [role="status"]')?.textContent).toBe('Connected, x, 3 tables.');
});
