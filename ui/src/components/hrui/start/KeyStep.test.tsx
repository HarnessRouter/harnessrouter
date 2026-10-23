/** @jest-environment jsdom */
// The API key step every coding-agent sheet has (Richard, 10-18: every sheet makes a new key; 10-19: in
// the "Set up a starter app" design's form). The name field is there at once with the next free name,
// Create beside it; the key shows once in the warning box with Copy key; once copied the step folds
// to the key's name and last four, with New key. A name that cannot be used is said under the field,
// never in a popup. A key the workspace already has is never offered or shown as done. Its mask is
// the last four of the key just made: nothing after the dots is made up.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('../toast', () => ({ toast: jest.fn() }));

import { toast } from '../toast';
import { KEY_TITLE, KeyStep, freeName, keySlug } from './KeyStep';
import { keyMask, type KeysState, type WsKey } from './keys';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const SECRET = 'sk-hr-' + '0'.repeat(60) + '9f3c';
const OLD: WsKey = { id: 'k.old', name: 'demo-key', tail: 'ab12' };
let root: Root;
let el: HTMLElement;
let create: jest.Mock;
let onKey: jest.Mock;
let writeText: jest.Mock;

let retry: jest.Mock;

function state(keys: WsKey[] | null, error = false): KeysState {
  const live = (keys || []).filter((x) => !x.revoked);
  return {
    keys, live: live[0] || null, error, retry, busy: false, create,
    nameProblem: (n: string) => (!n.trim() ? 'Name the key first, e.g. production.' : live.some((x) => (x.name || '').toLowerCase() === n.trim().toLowerCase()) ? `A key named ${n.trim()} already exists. Use another name.` : ''),
  };
}
async function show(keys: WsKey[] | null = [OLD], base = 'photo-edit', error = false) {
  await act(async () => { root.render(<ol className="hx"><KeyStep n={2} k={state(keys, error)} surface="set_up_app" base={base} state="next" onKey={onKey} /></ol>); });
}
const text = () => (el.textContent || '').replace(/\s+/g, ' ');
const input = () => el.querySelector('input') as HTMLInputElement | null;
const button = (label: string) => Array.from(el.querySelectorAll('button')).find((b) => (b.textContent || '').replace(/\s+/g, ' ').trim() === label) || null;
async function click(label: string) {
  const b = button(label);
  if (!b) throw new Error(`no button ${label}: ${text()}`);
  await act(async () => { b.click(); await new Promise((r) => setTimeout(r, 0)); });
}
async function type(value: string) {
  const i = input()!;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(i, value); i.dispatchEvent(new Event('input', { bubbles: true })); });
}
const fold = () => act(async () => { await new Promise((r) => setTimeout(r, 650)); });

beforeEach(() => {
  create = jest.fn(async () => ({ id: 'k.new', secret: SECRET }));
  retry = jest.fn();
  onKey = jest.fn();
  (toast as jest.Mock).mockClear();
  writeText = jest.fn(async () => undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

describe('keySlug', () => {
  it('is the setup’s name as a key name', () => {
    expect(keySlug('Photo edit')).toBe('photo-edit');
    expect(keySlug('  Support replies!! (v2) ')).toBe('support-replies-v2');
    expect(keySlug('Café · Menu')).toBe('café-menu');
    expect(keySlug('照片 编辑')).toBe('照片-编辑');
    expect(keySlug('!!!')).toBe('');
  });
  it('stays short and never ends in a hyphen', () => {
    const s = keySlug('A very long setup name that goes on and on past forty characters');
    expect(s.length).toBeLessThanOrEqual(40);
    expect(s).not.toMatch(/-$/);
  });
});

describe('freeName', () => {
  it('is the base, else the first of -2, -3 … no live key has', () => {
    expect(freeName('photo-edit', [OLD])).toBe('photo-edit');
    expect(freeName('photo-edit', [{ id: 'a', name: 'photo-edit' }])).toBe('photo-edit-2');
    expect(freeName('photo-edit', [{ id: 'a', name: 'Photo-Edit' }, { id: 'b', name: 'photo-edit-2' }])).toBe('photo-edit-3');
  });
  it('a revoked key frees its name, and an unread list takes none', () => {
    expect(freeName('photo-edit', [{ id: 'a', name: 'photo-edit', revoked: true }])).toBe('photo-edit');
    expect(freeName('photo-edit', null)).toBe('photo-edit');
  });
});

describe('keyMask', () => {
  it('is the dots and the last four', () => { expect(keyMask('dd27')).toBe('sk-hr-••••dd27'); });
  it('is nothing with no last four', () => { expect(keyMask(undefined)).toBe(''); expect(keyMask('  ')).toBe(''); });
});

describe('KeyStep', () => {
  it('opens at the name row with the next free name and Create, even when the workspace has a key', async () => {
    await show([OLD, { id: 'k.p', name: 'photo-edit', tail: 'aaaa' }]);
    expect(el.querySelector('.hx-t b')?.textContent).toBe(KEY_TITLE);
    expect(KEY_TITLE).toBe('Create an API key');
    expect(input()?.value).toBe('photo-edit-2');
    expect(input()?.placeholder).toBe('Key name, e.g. production');
    expect(button('Create')).not.toBeNull();
    expect(el.querySelector('li')?.className).toBe('hx-s next');
    expect(el.querySelector('.hx-d .keyrow input')).not.toBeNull();
    // no lead or warning paragraph, and nothing of a key made before
    expect(el.querySelector('p, .keywarn, h4')).toBeNull();
    expect(text()).not.toMatch(/demo-key|ab12|aaaa|can.t be shown again|reuse/i);
  });

  it('fills the name once the live list is read, and keeps what the person typed', async () => {
    await show(null);
    expect(input()?.value).toBe('photo-edit');
    await show([{ id: 'k.p', name: 'photo-edit' }]);
    expect(input()?.value).toBe('photo-edit-2');
    await type('laptop');
    await show([{ id: 'k.p', name: 'photo-edit' }, { id: 'k.q', name: 'photo-edit-2' }]);
    expect(input()?.value).toBe('laptop');
  });

  it('keys that could not be read: says so with Try again, and offers no name it cannot check', async () => {
    await show(null, 'photo-edit', true);
    const line = el.querySelector('.kb-why');
    expect(line?.getAttribute('role')).toBe('alert');
    expect(line?.textContent).toBe('Your keys could not be read just now. Try again');
    expect(input()).toBeNull();
    expect(button('Create')).toBeNull();
    await click('Try again');
    expect(retry).toHaveBeenCalledTimes(1);
    expect(create).not.toHaveBeenCalled();
    // once the list is read, the name row is back with the next free name
    await show([{ id: 'k.p', name: 'photo-edit' }]);
    expect(el.querySelector('.kb-why')).toBeNull();
    expect(input()?.value).toBe('photo-edit-2');
  });

  it('a key just made stays on screen even if the list read after it fails', async () => {
    await show();
    await click('Create');
    await show([OLD], 'photo-edit', true);
    expect(el.querySelector('.reveal code')?.textContent).toBe(SECRET);
    expect(button('Copy key')).not.toBeNull();
  });

  it('says a name that cannot be used under the field, and makes nothing', async () => {
    await show();
    await type('');
    await click('Create');
    expect(el.querySelector('.kb-why')?.textContent).toBe('Name the key first, e.g. production.');
    expect(el.querySelector('.kb-why')?.getAttribute('role')).toBe('alert');
    expect(input()?.getAttribute('aria-invalid')).toBe('true');
    expect(input()?.getAttribute('aria-describedby')).toBe(el.querySelector('.kb-why')?.id);
    await type('demo-key');
    expect(el.querySelector('.kb-why')).toBeNull();
    await click('Create');
    expect(el.querySelector('.kb-why')?.textContent).toBe('A key named demo-key already exists. Use another name.');
    expect(create).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });

  it('makes a new key and shows it once in the warning box, with Copy key', async () => {
    await show();
    await click('Create');
    expect(create).toHaveBeenCalledWith('photo-edit', 'set_up_app', expect.any(Function));
    const box = el.querySelector('.reveal');
    expect(box?.querySelector('b')?.textContent).toBe('Shown once. Paste it only into the secure prompt it opens.');
    const code = box?.querySelector('code');
    expect(code?.textContent).toBe(SECRET);
    expect(code?.classList.contains('ph-no-capture')).toBe(true);
    expect(button('Copy key')).not.toBeNull();
    expect(input()).toBeNull();
    // not done until it is copied
    expect(onKey).not.toHaveBeenCalled();
    expect(el.querySelector('li')?.className).toBe('hx-s next');
  });

  it('once copied, folds to the name and last four, with New key; the secret leaves the page', async () => {
    await show();
    await type('laptop');
    await click('Create');
    await click('Copy key');
    expect(writeText).toHaveBeenCalledWith(SECRET);
    expect(button('Copied')).not.toBeNull();
    await fold();
    expect(el.querySelector('li')?.className).toBe('hx-s built');
    expect(el.querySelector('.hx-sum')?.textContent?.replace(/\s+/g, ' ')).toBe('laptop · sk-hr-••••9f3cNew key');
    expect(text()).not.toContain(SECRET);
    expect(el.querySelector('code')).toBeNull();
    expect(onKey).toHaveBeenLastCalledWith({ id: 'k.new', name: 'laptop', tail: '9f3c' });
  });

  it('New key opens the name row again with the next free name', async () => {
    await show();
    await click('Create');
    await click('Copy key');
    await fold();
    // the list now has the key just made
    await show([{ id: 'k.new', name: 'photo-edit', tail: '9f3c' }, OLD]);
    await click('New key');
    expect(input()?.value).toBe('photo-edit-2');
    expect(el.querySelector('li')?.className).toBe('hx-s next');
    expect(onKey).toHaveBeenLastCalledWith(null);
  });

  it('a copy the browser refuses selects the key, and the person’s own copy of it counts', async () => {
    writeText.mockRejectedValueOnce(new Error('denied'));
    await show();
    await click('Create');
    await click('Copy key');
    expect(String(window.getSelection())).toBe(SECRET);
    expect(el.querySelector('li')?.className).toBe('hx-s next');
    await act(async () => { document.dispatchEvent(new Event('copy')); await new Promise((r) => setTimeout(r, 0)); });
    await fold();
    expect(onKey).toHaveBeenLastCalledWith({ id: 'k.new', name: 'photo-edit', tail: '9f3c' });
  });

  it('starts over each time it is drawn again: a key made before is not on screen or done', async () => {
    await show();
    await click('Create');
    await click('Copy key');
    await fold();
    act(() => root.unmount());
    root = createRoot(el);
    await show([{ id: 'k.new', name: 'photo-edit', tail: '9f3c' }, OLD]);
    expect(el.querySelector('li')?.className).toBe('hx-s next');
    expect(el.querySelector('.hx-sum')).toBeNull();
    expect(text()).not.toContain('9f3c');
    expect(input()?.value).toBe('photo-edit-2');
  });
});
