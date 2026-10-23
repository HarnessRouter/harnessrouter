/** @jest-environment jsdom */
// Every coding-agent sheet is one experience (Richard, 10-18; 10-19: his "Set up a starter app" design):
// Connect your app, Make <kit> yours, Start in your codebase and Migrate an existing agent draw the same
// step list, with the same copy step (Copy prompt on the right of the row under the prompt, no link
// that opens Claude Code or Codex) and the same key step (the name row at once, a new key made in the
// current workspace and shown once; each time the sheet opens it starts over). None offers to reuse a
// key the app already has. Set up the app is two steps and claims nothing it cannot read (the task cards
// do not say a task came from an app); no number it did not read is shown.
import { act, type ReactElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/lib/harness', () => ({ listCustom: jest.fn(async () => []) }));
jest.mock('@/lib/revamp-data', () => ({ RUNNING: new Set(['running', 'queued', 'in_progress']) }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: jest.fn(() => ({ orgId: 'org.t', member: { email: 'me@example.com' } })) }));
jest.mock('@/lib/workspace', () => ({ useWorkspace: jest.fn(() => ({ current: { id: 'ws.test', name: 'Test Workspace' }, defaultId: 'ws.default' })) }));
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../setups', () => ({ newestTasks: jest.fn(async () => ({ sessions: [], cursor: '' })) }));

import { harnessFetch } from '@/lib/hfetch';
import type { SetupRow } from '../setups';
import { SetUpApp } from '../SetUpApp';
import { Handoff } from './Handoff';
import { KEY_TITLE } from './KeyStep';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const SECRET = 'sk-hr-' + '1'.repeat(60) + '3e80';
const ROW = {
  h: { id: 'chrn_0123456789', name: 'Support replies', defaultModel: 'gpt-5.4', systemPrompt: 'Answer customer questions.' },
  baseName: 'Hermes',
} as unknown as SetupRow;
const noop = () => {};
const SHEETS: [string, () => ReactElement, string][] = [
  ['Connect your app', () => <SetUpApp r={ROW} onClose={noop} />, 'support-replies'],
  ['Make Super Mario yours', () => <SetUpApp r={ROW} kit="mario" kitTitle="Super Mario" onClose={noop} />, 'support-replies'],
  ['Start in your codebase', () => <Handoff kind="new" onClose={noop} />, 'app-backend'],
  ['Migrate an existing agent', () => <Handoff kind="move" onClose={noop} />, 'app-backend'],
];

let root: Root;
let el: HTMLElement;
let keys: { id: string; name: string; tail?: string; workspace?: string; revoked?: boolean }[];
const fetchMock = harnessFetch as jest.Mock;
const body = () => (document.body.textContent || '').replace(/\s+/g, ' ');
const button = (label: string) => Array.from(document.body.querySelectorAll('button')).find((b) => (b.textContent || '').replace(/\s+/g, ' ').trim() === label) || null;
const keyName = () => document.querySelector('.hx .keyrow input') as HTMLInputElement | null;
const steps = () => Array.from(document.querySelectorAll('[role="dialog"] ol.hx > li.hx-s'));
const stepOf = (title: string) => steps().find((s) => s.querySelector('.hx-t b')?.textContent === title) || null;
async function click(label: string) {
  const b = button(label);
  if (!b) throw new Error(`no button ${label}: ${body()}`);
  await act(async () => { b.click(); await new Promise((r) => setTimeout(r, 0)); });
}
async function type(input: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function draw(sheet: () => ReactElement) {
  await act(async () => { root.render(sheet()); await new Promise((r) => setTimeout(r, 0)); });
}
const fold = () => act(async () => { await new Promise((r) => setTimeout(r, 650)); });

beforeEach(() => {
  keys = [{ id: 'k.old', name: 'demo-key', tail: 'ab12', workspace: 'ws.test' }];
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (_url: string, init?: { method?: string; body?: string }) => {
    if (init?.method === 'POST') {
      keys = [{ id: 'k.new', name: JSON.parse(init.body || '{}').name, tail: '3e80', workspace: 'ws.test' }, ...keys];
      return { ok: true, status: 200, json: async () => ({ id: 'k.new', key: SECRET }) };
    }
    return { ok: true, status: 200, json: async () => ({ keys }) };
  });
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: jest.fn(async () => undefined) }, configurable: true });
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; });

describe.each(SHEETS)('%s', (title, sheet, base) => {
  it('is the design’s sheet: its steps, the shared copy step and the shared key step, and no link that opens a coding agent', async () => {
    await draw(sheet);
    const d = document.querySelector('[role="dialog"]');
    expect(d?.querySelector('h3')?.textContent).toBe(title);
    expect(d?.classList.contains('hand-sheet')).toBe(true);
    expect(d?.classList.contains('use-sheet')).toBe(true);
    // the same list: step 1 the copy step, then the key step under the same title
    expect(steps()[0].querySelector('.hx-t b')?.textContent).toBe('Copy the prompt and send it');
    expect(steps().filter((s) => s.querySelector('.hx-t b')?.textContent === KEY_TITLE)).toHaveLength(1);
    expect(steps()[0].querySelector('.hx-n')?.textContent).toBe('1');
    expect(steps()[0].className).toBe('hx-s next');
    // the copy block: the prompt in its well, then Copy prompt at the end of the row under it
    const bar = document.querySelector('.code-wrap .code-bar');
    expect(bar?.lastElementChild?.textContent).toBe('Copy prompt');
    expect(document.querySelectorAll('.code-wrap')).toHaveLength(1);
    // the key step: the name row at once, with the sheet's own next free name
    expect(keyName()?.value).toBe(base);
    expect(button('Create')).not.toBeNull();
    expect(button('Create API key')).toBeNull();
    expect(document.querySelector('.keybox, .keywarn')).toBeNull();
    // no way to open a coding agent with the prompt, and nothing that keeps an old key
    expect(document.querySelector('a[href^="claude:"], a[href^="codex:"], a.coder, .coders')).toBeNull();
    expect(body()).not.toMatch(/Or open in|Open in Claude Code|Open in Codex/);
    expect(body()).not.toMatch(/demo-key|ab12|No new key needed|Need a separate key|can.t be shown again|Create a key to copy/);
    expect(document.querySelector('pre')?.textContent).not.toMatch(/Do not create a new key|reuse the same HR_API_KEY|sk-hr-/i);
    // one prompt: no tabs for raw requests, no banner about another setup
    expect(document.querySelector('[role="tablist"], .langs, .sib')).toBeNull();
    expect(body()).not.toMatch(/Prefer the code|Use a coding agent instead|already talks to HarnessRouter|Copy code/);
    // no estimate of how long anything takes
    expect(body()).not.toMatch(/\d+\s*[–-]\s*\d+\s*min/);
  });

  it('copying folds step 1 to Copied · Copy again, and keeps the paste hint', async () => {
    await draw(sheet);
    await click('Copy prompt');
    expect(steps()[0].className).toBe('hx-s built');
    expect(steps()[0].querySelector('.hx-sum')?.textContent).toBe('Copied · Copy again');
    expect(steps()[0].querySelector('.hx-keep')?.textContent).toContain('Paste the prompt into Claude Code or Codex');
    expect(document.querySelector('pre')).toBeNull();
  });

  it('makes a new key in this workspace each time it opens, shown once', async () => {
    keys.push({ id: 'k.same', name: base, workspace: 'ws.test' });
    await draw(sheet);
    expect(keyName()?.value).toBe(`${base}-2`);
    await type(keyName()!, 'laptop');
    await click('Create');
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(post?.[0]).toBe('/api/harness/v1/orgs/org.t/keys');
    expect(JSON.parse(post?.[1].body)).toMatchObject({ name: 'laptop', workspace: 'ws.test', workspace_name: 'Test Workspace' });
    const secret = document.querySelector('.hx .reveal code');
    expect(secret?.textContent).toBe(SECRET);
    expect(secret?.classList.contains('ph-no-capture')).toBe(true);
    await click('Copy key');
    await fold();
    expect(stepOf(KEY_TITLE)?.querySelector('.hx-sum')?.textContent).toBe('laptop · sk-hr-••••3e80New key');
    expect(body()).not.toContain(SECRET);

    // closed and opened again: the step starts over, and the key made before is not on screen or done
    act(() => root.unmount());
    root = createRoot(el);
    await draw(sheet);
    expect(body()).not.toContain(SECRET);
    expect(stepOf(KEY_TITLE)?.querySelector('.hx-sum')).toBeNull();
    expect(keyName()).not.toBeNull();
  });
});

describe('Set up the app', () => {
  it('says who builds and what runs behind it, true for each prompt, and names no hosted service', async () => {
    await draw(SHEETS[0][1]);
    expect(document.querySelector('.sub')?.textContent).toBe('Your coding agent adds Support replies to your app. This instance runs Hermes behind it, and every task your app sends shows in its task list.');
    act(() => root.unmount());
    root = createRoot(el);
    await draw(SHEETS[1][1]);
    expect(document.querySelector('.sub')?.textContent).toBe('Your coding agent takes the kit’s app from GitHub and changes it. This instance keeps running Hermes behind it.');
    expect(body()).not.toContain('HarnessRouter Cloud');
  });

  it('claims nothing it cannot read: two steps, and once the prompt is copied and a key made it is ready for the coding agent', async () => {
    await draw(SHEETS[0][1]);
    expect(steps()).toHaveLength(2);
    await click('Copy prompt');
    await click('Create');
    await click('Copy key');
    await fold();
    expect(document.querySelector('.hand-foot')?.textContent).toBe('Ready for your coding agentDone');
    expect(body()).not.toMatch(/Connected|Started|No task/);
  });
});
