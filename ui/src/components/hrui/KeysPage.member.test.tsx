/** @jest-environment jsdom */
// The API Keys page as a Member meets it: who may make or revoke a key is the gateway's
// (backend/harness_gateway/app.py, mint_key and _revoke_allowed), and the key list carries no answer per
// key. So a Revoke the gateway refuses says its own sentence, naming who can by role, in the revoke sheet
// in place of the red button (never "could not be revoked. Try again."), and a create it refuses says why
// under the name field. A failure that is not a refusal keeps its own line.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('./toast', () => ({ toast: jest.fn() }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org1', member: { email: 'dana@example.com' } }) }));
jest.mock('@/lib/workspace', () => ({ useWorkspace: () => ({ current: { id: 'ws1', name: 'Default' }, defaultId: 'ws1' }) }));
jest.mock('./bricks', () => ({ PagePic: () => null }));
jest.mock('./setups', () => ({ ago: () => '2 hours ago' }));
jest.mock('./start/keys', () => ({ ...jest.requireActual('./start/keys'), useWsKeys: jest.fn() }));

import { toast } from './toast';
import { harnessFetch } from '@/lib/hfetch';
import { useWsKeys } from './start/keys';
import { KeysPage } from './KeysPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// the gateway's own sentences (app.py KEY_REVOKE_REFUSED, KEY_WIDE_REFUSED), in its error body
const REVOKE_NO = 'Only the person who made this key, or the owner or an Admin of your organization, can revoke it.';
const WIDE_NO = 'Only the owner or an Admin of your organization can create an organization key. Create a key for a workspace you use, or ask the owner or an Admin of your organization.';
const refusal = (status: number, message: string) => ({ ok: false, status, json: async () => ({ error: { type: 'permission_error', code: 'not_org_admin', message }, detail: message }) });
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });

let root: Root;
let el: HTMLElement;
let create: jest.Mock;
const keys = [{ id: 'k1', name: 'ana-prod', tail: 'ab12', workspace: 'ws1', member: 'ana@example.com', created_at: 1_760_000_000 }];
const all = () => (document.body.textContent || '').replace(/\s+/g, ' ');
const button = (label: string) => Array.from(document.body.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === label) || null;
async function flush() { await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); }
async function click(label: string) {
  const b = button(label);
  if (!b) throw new Error(`no button ${label}: ${all()}`);
  await act(async () => { b.click(); await new Promise((r) => setTimeout(r, 0)); });
}
async function type(value: string) {
  const i = el.querySelector('.keyname') as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(i, value); i.dispatchEvent(new Event('input', { bubbles: true })); });
}
function deletes(answer: unknown) {
  (harnessFetch as jest.Mock).mockImplementation(async (_u: string, init?: { method?: string }) => (init?.method === 'DELETE' ? answer : ok({ keys })));
}

beforeEach(() => {
  create = jest.fn(async () => ({ id: 'k2', secret: 'sk-hr-x' }));
  (useWsKeys as jest.Mock).mockReturnValue({ keys: [], live: null, busy: false, create, nameProblem: (n: string) => (n.trim() ? '' : 'Name the key first, e.g. production.') });
  (harnessFetch as jest.Mock).mockImplementation(async () => ok({ keys }));
  (toast as jest.Mock).mockClear();
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; });

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

it('a Revoke the gateway refuses says who can revoke it, in the sheet, with Close in place of the red button', async () => {
  await open();
  await manageRevoke();
  deletes(refusal(403, REVOKE_NO));
  await act(async () => { (document.querySelector('.del-go') as HTMLButtonElement).click(); });
  await flush();
  expect(document.querySelector('.del-refused')?.textContent).toBe(REVOKE_NO);
  expect(document.querySelector('.del-refused')?.getAttribute('role')).toBe('alert');
  expect(document.querySelector('.del-go')).toBeNull();
  expect(document.activeElement?.textContent).toBe('Close');
  expect(toast).not.toHaveBeenCalled();
  expect(all()).not.toContain('could not be revoked');
  // closing it leaves the key listed, and the next Revoke asks afresh
  await click('Close');
  expect(document.querySelector('.del-sheet')).toBeNull();
  expect(el.querySelectorAll('.rows .row')).toHaveLength(1);
  await manageRevoke();
  expect(document.querySelector('.del-refused')).toBeNull();
  expect(document.querySelector('.del-go')).toBeTruthy();
});

it('a Revoke that fails without a refusal keeps its own line, and the red button stays to try again', async () => {
  await open();
  await manageRevoke();
  deletes({ ok: false, status: 503, json: async () => ({ detail: 'harness-gateway unreachable: x' }) });
  await act(async () => { (document.querySelector('.del-go') as HTMLButtonElement).click(); });
  await flush();
  expect(toast).toHaveBeenCalledWith('The key could not be revoked. Try again.');
  expect(document.querySelector('.del-refused')).toBeNull();
  expect(document.querySelector('.del-go')).toBeTruthy();
  expect(all()).not.toContain('harness-gateway');
});

it('a create the gateway refuses says why under the name field, never in a toast', async () => {
  create.mockImplementation(async (_n: string, _s: string, onRefused?: (why: string) => void) => { onRefused?.(WIDE_NO); return null; });
  await open();
  await type('everywhere');
  await click('Create');
  expect(el.querySelector('.kb-why')?.textContent).toBe(WIDE_NO);
  expect((el.querySelector('.keyname') as HTMLInputElement).getAttribute('aria-invalid')).toBe('true');
  expect(el.querySelector('.reveal')).toBeNull();
  expect(toast).not.toHaveBeenCalled();
  await type('everywhere2');
  expect(el.querySelector('.kb-why')).toBeNull();               // typing clears it, as it does a name problem
});
