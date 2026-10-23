/** @jest-environment jsdom */
// Profile: this instance's sign-in (GET/PUT /api/selfhost/profile). The default password is warned
// about; Save needs the current password and something changed, and both new passwords to match; the
// console restarts to take the change, and the page waits for it to answer before saying it is saved.
// A profile that cannot be read says so with Try again.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/components/hrui/Avatar', () => ({ MyPic: () => null, refreshOperator: jest.fn(async () => null) }));
jest.mock('@/components/hrui/Skel', () => ({ Skel: () => null, SkLine: () => null }));

import ProfilePage from './page';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let el: HTMLElement;
const fetchMock = jest.fn();
const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });
const save = () => document.getElementById('pfSave') as HTMLButtonElement;
const flush = async () => { for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); }); };
async function type(id: string, value: string) {
  const i = document.getElementById(id) as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(i, value); i.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function open() { await act(async () => { root.render(<ProfilePage />); }); await flush(); }

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(ok({ user: 'admin', gated: true, usingDefaultPassword: true }));
  global.fetch = fetchMock as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.useRealTimers(); });

test('the operator, the default password warned about, and Save waits for a change and the current password', async () => {
  await open();
  expect(el.querySelector('.pf-name')?.textContent).toBe('admin');
  expect(el.querySelector('.keywarn')?.textContent).toContain('You are using the default password.');
  expect(save().disabled).toBe(true);
  await type('pf-new', 'n3w-password');
  expect(document.getElementById('pf-confirm')).not.toBeNull();
  await type('pf-confirm', 'other');
  expect(document.getElementById('pfMismatch')?.textContent).toBe('Both passwords must match.');
  await type('pf-current', 'old');
  expect(save().disabled).toBe(true);
  await type('pf-confirm', 'n3w-password');
  expect(save().disabled).toBe(false);
});

test('Save sends the change, waits for the restarted console, then says it is saved', async () => {
  jest.useFakeTimers();
  await open();
  await type('pf-user', 'ops');
  await type('pf-current', 'old');
  fetchMock.mockImplementation(async (_u: string, init?: { method?: string; body?: string }) => (init?.method === 'PUT' ? ok({ ok: true }) : ok({ user: 'ops', gated: true, usingDefaultPassword: false })));
  await act(async () => { save().click(); });
  await flush();
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT');
  expect(put?.[0]).toBe('/api/selfhost/profile');
  expect(JSON.parse(put?.[1].body)).toEqual({ currentPassword: 'old', username: 'ops' });
  expect(el.querySelector('[role="status"]')?.textContent).toBe('Saved. Signing every other browser out.');
  await act(async () => { await jest.advanceTimersByTimeAsync(600); });
  await flush();
  expect(el.querySelector('[role="status"]')?.textContent).toBe('Saved.');
  expect(el.querySelector('.pf-name')?.textContent).toBe('ops');
});

test('a refusal is said in the server’s words', async () => {
  await open();
  await type('pf-user', 'ops');
  await type('pf-current', 'wrong');
  fetchMock.mockResolvedValueOnce(ok({ detail: 'Your current password is not right.' }, 403));
  await act(async () => { save().click(); });
  await flush();
  expect(el.querySelector('.kb-why')?.textContent).toBe('Your current password is not right.');
});

test('a profile that cannot be read says so, with Try again', async () => {
  fetchMock.mockResolvedValueOnce(ok({}, 503));
  await open();
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('Your profile could not be read just now.');
  await act(async () => { (el.querySelector('[role="alert"] button') as HTMLButtonElement).click(); });
  await flush();
  expect(el.querySelector('.pf-name')?.textContent).toBe('admin');
});
