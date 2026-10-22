/** @jest-environment jsdom */
// The API Keys page (Richard 10-19: every page simple, a rare case said only when it happens). Create
// is the key step's own: the shared create call and name rule, a name that cannot be used said under
// the field (never a toast), and the secret shown once until Copy key turns to Copied, then folded
// away. A revoked key is not listed, and no standing line explains keys.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('./toast', () => ({ toast: jest.fn() }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org1', member: { email: 'ana@example.com' } }) }));
const mockWs = { current: { id: 'ws1', name: 'Default' }, defaultId: 'ws1' };
jest.mock('@/lib/workspace', () => ({ useWorkspace: () => mockWs }));
jest.mock('./bricks', () => ({ PagePic: () => null }));
jest.mock('./setups', () => ({ ago: () => '2 hours ago' }));
jest.mock('./start/keys', () => ({ ...jest.requireActual('./start/keys'), useWsKeys: jest.fn() }));

import { toast } from './toast';
import { harnessFetch } from '@/lib/hfetch';
import { useWsKeys } from './start/keys';
import { KeysPage } from './KeysPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const SECRET = 'sk-hr-' + '0'.repeat(60) + '9f3c';
let keys: Record<string, unknown>[];
let root: Root;
let el: HTMLElement;
let create: jest.Mock;
let writeText: jest.Mock;

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const text = () => (el.textContent || '').replace(/\s+/g, ' ');
const button = (label: string) => Array.from(el.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === label) || null;
async function flush() { await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); }
async function click(label: string) {
  const b = button(label);
  if (!b) throw new Error(`no button ${label}: ${text()}`);
  await act(async () => { b.click(); await new Promise((r) => setTimeout(r, 0)); });
}
async function type(value: string) {
  const i = el.querySelector('.keyname') as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(i, value); i.dispatchEvent(new Event('input', { bubbles: true })); });
}

beforeEach(() => {
  mockWs.current = { id: 'ws1', name: 'Default' };
  keys = [
    { id: 'k1', name: 'production', tail: 'ab12', workspace: 'ws1', created_at: 1_760_000_000, last_used: 1_760_100_000 },
    { id: 'k0', name: 'old', tail: 'zz99', workspace: 'ws1', created_at: 1_750_000_000, revoked: true },
  ];
  create = jest.fn(async () => ({ id: 'k2', secret: SECRET }));
  (useWsKeys as jest.Mock).mockReturnValue({
    keys: [], live: null, busy: false, create,
    nameProblem: (n: string) => (!n.trim() ? 'Name the key first, e.g. production.' : n.trim() === 'production' ? 'A key named production already exists. Use another name.' : ''),
  });
  (harnessFetch as jest.Mock).mockImplementation(async () => ok({ keys }));
  (toast as jest.Mock).mockClear();
  writeText = jest.fn(async () => undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

/** Revoke is in the key's Manage sheet: open it, then its Revoke key (the confirm sheet follows) */
async function manageRevoke() {
  const m = Array.from(document.body.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Manage');
  if (!m) throw new Error('no Manage');
  await act(async () => { m.click(); await new Promise((r) => setTimeout(r, 0)); });
  const r = Array.from(document.body.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Revoke key' && !b.closest('.del-sheet'));
  if (!r) throw new Error('no Revoke key');
  await act(async () => { r.click(); await new Promise((res) => setTimeout(res, 0)); });
}

async function open() { await act(async () => { root.render(<KeysPage />); }); await flush(); }

it('lists the live keys only, with no standing explainer', async () => {
  await open();
  const rows = Array.from(el.querySelectorAll('.rows .row'));
  expect(rows.map((r) => r.querySelector('b')?.textContent)).toEqual(['production']);
  expect(text()).not.toContain('Revoked');
  expect(el.querySelector('.list-top .sub')).toBeNull();
  expect(el.querySelector('.keywarn')).toBeNull();
  expect(el.querySelector('.keybox p')).toBeNull();
});

it('says a name that cannot be used under the field, never in a toast, and sends nothing', async () => {
  await open();
  await click('Create');
  expect(el.querySelector('.kb-why')?.textContent).toBe('Name the key first, e.g. production.');
  await type('production');
  expect(el.querySelector('.kb-why')).toBeNull();                // typing clears it
  await click('Create');
  expect(el.querySelector('.kb-why')?.textContent).toBe('A key named production already exists. Use another name.');
  expect(create).not.toHaveBeenCalled();
  expect(toast).not.toHaveBeenCalled();
});

it('makes the key with the shared call, shows it once, and Copy key turns to Copied before it folds away', async () => {
  await open();
  await type('staging');
  await click('Create');
  expect(create).toHaveBeenCalledWith('staging', 'keys', expect.any(Function));
  expect(el.querySelector('.reveal code')?.textContent).toBe(SECRET);
  expect(el.querySelector('.keyname')).toBeNull();               // the name row waits while the secret shows
  await click('Copy key');
  expect(writeText).toHaveBeenCalledWith(SECRET);
  expect(button('Copied')).toBeTruthy();
  await act(async () => { await new Promise((r) => setTimeout(r, 650)); });
  expect(el.querySelector('.reveal')).toBeNull();
  expect(text()).not.toContain(SECRET);
  expect(el.querySelector('.keyname')).toBeTruthy();
});

it('says a list that could not be read, with Try again', async () => {
  (harnessFetch as jest.Mock).mockImplementationOnce(async () => ({ ok: false, status: 503, json: async () => ({}) }));
  await open();
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('Your keys could not be read just now.');
  await click('Try again');
  await flush();
  expect(el.querySelector('[role="alert"]')).toBeNull();
  expect(el.querySelectorAll('.rows .row')).toHaveLength(1);
});

it('the key step’s own read failing is said too, and Try again reads it again (its name check runs on it)', async () => {
  const retry = jest.fn();
  (useWsKeys as jest.Mock).mockReturnValue({ keys: null, live: null, error: true, retry, busy: false, create, nameProblem: () => '' });
  await open();
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('Your keys could not be read just now.');
  const reads = (harnessFetch as jest.Mock).mock.calls.length;
  await click('Try again');
  expect(retry).toHaveBeenCalledTimes(1);
  // the page's own list was read fine: it is not read again
  expect((harnessFetch as jest.Mock).mock.calls.length).toBe(reads);
});

it('revokes after asking, in a short line', async () => {
  await open();
  await manageRevoke();
  expect(document.body.textContent).toContain('stops working right away in every workspace.');
  expect(document.body.textContent).not.toContain('Tasks sent with it are refused');
  (harnessFetch as jest.Mock).mockImplementation(async (_u: string, init?: { method?: string }) => {
    if (init?.method === 'DELETE') { keys = keys.map((x) => (x.id === 'k1' ? { ...x, revoked: true } : x)); return ok({}); }
    return ok({ keys });
  });
  await act(async () => { (document.querySelector('.del-go') as HTMLButtonElement).click(); });
  await flush();
  expect(toast).toHaveBeenCalledWith('production revoked.');
  expect(text()).toContain('No keys yet.');
});

const bodyText = () => (document.body.textContent || '').replace(/\s+/g, ' ');
async function clickAny(label: string) {
  const b = Array.from(document.body.querySelectorAll('button')).find((x) => (x.textContent || '').trim() === label);
  if (!b) throw new Error(`no button ${label}: ${bodyText()}`);
  await act(async () => { b.click(); await new Promise((r) => setTimeout(r, 0)); });
}
async function typeIn(input: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); });
}

it('renames a key in its Manage sheet (PATCH, the name only), and a name another key has is said under the field', async () => {
  keys.push({ id: 'k3', name: 'staging', tail: 'cd34', workspace: 'ws1', created_at: 1_759_000_000 });
  await open();
  await clickAny('Manage');
  const input = document.getElementById('kmName') as HTMLInputElement;
  expect(input.value).toBe('production');
  await typeIn(input, 'staging');
  await clickAny('Save name');
  expect(document.getElementById('kmWhy')?.textContent).toBe('A key named staging already exists. Use another name.');
  expect((harnessFetch as jest.Mock).mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false);
  await typeIn(input, 'prod-eu');
  await clickAny('Save name');
  const patch = (harnessFetch as jest.Mock).mock.calls.find(([, init]) => init?.method === 'PATCH');
  expect(patch?.[0]).toBe('/api/harness/v1/orgs/org1/keys/k1');
  expect(JSON.parse(patch?.[1].body)).toEqual({ name: 'prod-eu' });
  expect(toast).toHaveBeenCalledWith('Renamed to prod-eu.');
  expect(document.getElementById('kmName')).toBeNull();
});

it('rotates a secret: a new key with the same name and reach first, then the old one revoked; the new secret shows once', async () => {
  (harnessFetch as jest.Mock).mockClear();
  (harnessFetch as jest.Mock).mockImplementation(async (_u: string, init?: { method?: string }) => {
    if (init?.method === 'POST') return ok({ id: 'k9', key: SECRET });
    if (init?.method === 'DELETE') return ok({});
    return ok({ keys });
  });
  await open();
  await clickAny('Manage');
  await clickAny('Rotate secret');
  const calls = (harnessFetch as jest.Mock).mock.calls.filter(([, init]) => init?.method);
  expect(calls.map(([u, init]) => `${init.method} ${u}`)).toEqual(['POST /api/harness/v1/orgs/org1/keys', 'DELETE /api/harness/v1/orgs/org1/keys/k1']);
  expect(JSON.parse(calls[0][1].body)).toMatchObject({ name: 'production', workspace: 'ws1', workspace_default: true });
  expect(el.querySelector('.reveal code')?.textContent).toBe(SECRET);
  expect(el.querySelector('.reveal b')?.textContent).toContain('production has a new secret.');
});

it('outside the Default Workspace the create asks what the key reaches; Every workspace makes a key with no workspace', async () => {
  mockWs.current = { id: 'ws2', name: 'Team' };
  keys = [];
  await open();
  const reach = el.querySelector('#keyReach');
  expect(reach?.getAttribute('role')).toBe('radiogroup');
  expect(Array.from(reach!.querySelectorAll('button')).map((b) => b.textContent)).toEqual(['This workspace only', 'Every workspace']);
  await type('shared');
  await click('Every workspace');
  await click('Create');
  expect(create).toHaveBeenCalledWith('shared', 'keys', expect.any(Function), { everywhere: true });
});

it('in the Default Workspace nothing is asked: a key made there reaches every workspace', async () => {
  await open();
  expect(el.querySelector('#keyReach')).toBeNull();
  expect(el.querySelector('.rows .row .sub2')?.textContent).toContain('every workspace');
});
