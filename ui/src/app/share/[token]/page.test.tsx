/** @jest-environment jsdom */
// The public share page: a conversation that could not be read is said, with Try again, never drawn
// as a conversation with nothing in it (the gateway answers a failed read with a 503).
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/app/revamp.css', () => ({}));
jest.mock('iconify-icon', () => ({}));
jest.mock('next/navigation', () => ({ useParams: () => ({ token: 'shr1' }) }));
jest.mock('react-markdown', () => ({ __esModule: true, default: ({ children }: { children: string }) => <p>{children}</p> }));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => null }));
jest.mock('@/components/FileTypeIcon', () => ({ FileTypeIcon: () => null }));

import SharePage from './page';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
const json = (status: number, body: unknown) => Promise.resolve({ ok: status < 400, status, json: async () => body } as Response);
const flush = async () => { for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); }); };
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('a conversation that could not be read says so, and Try again reads it again', async () => {
  let turnsAnswer = 503;
  global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta') ? json(200, { title: 'Pet Food' })
    : String(url).endsWith('/files') ? json(200, { files: [] })
    : turnsAnswer === 503 ? json(503, { error: { type: 'server_error', code: 'server_error' } })
    : json(200, { turns: [{ id: 'resp_1', user: 'Pet food', assistant: 'Done.' }] }))) as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<SharePage />); });
  await flush();
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('This conversation could not be loaded just now.');
  expect(el.textContent).not.toContain('No conversation content.');
  turnsAnswer = 200;
  await act(async () => { (Array.from(el.querySelectorAll('button')).find((b) => b.textContent === 'Try again') as HTMLButtonElement).click(); });
  await flush();
  expect(el.textContent).toContain('Done.');
  expect(el.querySelector('[role="alert"]')).toBeNull();
});

test('a conversation with no turns still says so plainly', async () => {
  global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta') ? json(200, { title: 'Pet Food' })
    : String(url).endsWith('/files') ? json(200, { files: [] })
    : json(200, { turns: [] }))) as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<SharePage />); });
  await flush();
  expect(el.textContent).toContain('No conversation content.');
  expect(el.querySelector('[role="alert"]')).toBeNull();
});

// Same rule, the artifacts read four lines above the turns read: a failed read is said, never drawn
// as a Task that produced nothing (the gateway answers 500 when the workspace tarball is truncated).
const alertWith = (text: string) => Array.from(el.querySelectorAll('[role="alert"]')).find((n) => n.textContent?.includes(text));

test('artifacts that could not be read say so, and are never drawn as a Task with none', async () => {
  global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta') ? json(200, { title: 'Pet Food' })
    : String(url).endsWith('/files') ? json(500, { detail: 'boom' })
    : json(200, { turns: [{ id: 'resp_1', user: 'Pet food', assistant: 'Done.' }] }))) as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<SharePage />); });
  await flush();
  expect(alertWith('The artifacts could not be loaded just now.')).toBeTruthy();
  expect(el.textContent).not.toContain('No artifacts in this Task.');
  expect(el.textContent).not.toContain('0 files');
});

test('a Task with no artifacts still says so plainly', async () => {
  global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta') ? json(200, { title: 'Pet Food' })
    : String(url).endsWith('/files') ? json(200, { files: [] })
    : json(200, { turns: [{ id: 'resp_1', user: 'Pet food', assistant: 'Done.' }] }))) as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<SharePage />); });
  await flush();
  expect(el.textContent).toContain('No artifacts in this Task.');
  expect(el.textContent).toContain('0 files');
  expect(alertWith('The artifacts could not be loaded just now.')).toBeUndefined();
});
