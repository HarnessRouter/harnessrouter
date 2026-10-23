/** @jest-environment jsdom */
// Sign-in for this instance: one username and password posted to /api/selfhost/login, on the sign-in
// card. A field left empty is said under it and nothing is sent; a refusal is the server's own words;
// a sign-in that works goes to `next` only when it is a path on this site (GHSA-59mq-hx4p-fw48), else
// to Start. Nothing else is offered: no sign-up, no reset by email, no third-party sign-in.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { SelfHostLogin } from './SelfHostLogin';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let el: HTMLElement;
let assign: jest.Mock;
const fetchMock = jest.fn();
const text = () => (el.textContent || '').replace(/\s+/g, ' ');
async function type(id: string, value: string) {
  const i = document.getElementById(id) as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(i, value); i.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function submit() {
  await act(async () => { (document.getElementById('auGo') as HTMLButtonElement).click(); });
  for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve(); });
}
async function open(next: string) { await act(async () => { root.render(<SelfHostLogin next={next} go={assign} />); }); }

beforeEach(() => {
  fetchMock.mockReset();
  global.fetch = fetchMock as unknown as typeof fetch;
  assign = jest.fn();
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('the card has the instance’s two fields, and nothing a box without accounts cannot back', async () => {
  await open('/start');
  expect(document.getElementById('sh-user')?.getAttribute('autocomplete')).toBe('username');
  expect(document.getElementById('sh-pass')?.getAttribute('type')).toBe('password');
  expect(el.querySelector('#hrui .au-card h1')?.textContent).toBe('Sign in');
  expect(text()).not.toMatch(/Google|Microsoft|Create account|Forgot password|Sign up/i);
});

test('an empty field is said under it and nothing is sent', async () => {
  await open('/start');
  await submit();
  expect(document.getElementById('sh-userMsg')?.textContent).toBe('Enter your username.');
  await type('sh-user', 'admin');
  await submit();
  expect(document.getElementById('sh-passMsg')?.textContent).toBe('Enter your password.');
  expect(fetchMock).not.toHaveBeenCalled();
});

test('a refusal is the server’s own words, and the button can be pressed again', async () => {
  fetchMock.mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: 'Incorrect username or password.' }) });
  await open('/start');
  await type('sh-user', 'admin');
  await type('sh-pass', 'wrong');
  await submit();
  expect(fetchMock).toHaveBeenCalledWith('/api/selfhost/login', expect.objectContaining({ method: 'POST', body: JSON.stringify({ username: 'admin', password: 'wrong' }) }));
  expect(el.querySelector('.au-err')?.textContent).toBe('Incorrect username or password.');
  expect((document.getElementById('auGo') as HTMLButtonElement).disabled).toBe(false);
  expect(assign).not.toHaveBeenCalled();
});

test.each([
  ['/studio/chrn_1?test=s1', '/studio/chrn_1?test=s1'],
  ['https://evil.example/', '/start'],
  ['//evil.example', '/start'],
])('signed in, %j goes to %j', async (next, to) => {
  fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true }) });
  await open(next);
  await type('sh-user', 'admin');
  await type('sh-pass', 'right');
  await submit();
  expect(assign).toHaveBeenCalledWith(to);
});
