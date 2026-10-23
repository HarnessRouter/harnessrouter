/** @jest-environment jsdom */
// An address with no page, said inside the console's frame, calmly, with the way back to Start (and, signed
// out, Sign in as well).
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
jest.mock('@/lib/auth', () => ({ hasActiveOrg: jest.fn(() => false) }));
jest.mock('@/lib/workspace', () => ({ WorkspaceProvider: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
jest.mock('@/components/hrui/Shell', () => ({
  HruiShell: ({ children, ownStyles }: { children: React.ReactNode; ownStyles?: boolean }) => <div id="hrui" className="shell" data-own={ownStyles ? '1' : ''}>{children}</div>,
}));
// the page itself, drawn at once (in the app it is loaded on demand)
jest.mock('@/components/hrui/NotFound', () => ({
  ConsoleNotFound: () => { const { NotFoundPage } = jest.requireActual('@/components/hrui/NotFoundPage'); return <NotFoundPage />; },
}));

import { hasActiveOrg } from '@/lib/auth';
import NotFound, { metadata } from './not-found';

const signIn = (on: boolean) => (hasActiveOrg as jest.Mock).mockReturnValue(on);

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let el: HTMLElement;
async function open() {
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<NotFound />); });
}
afterEach(() => { act(() => root.unmount()); el.remove(); signIn(false); });
const link = (label: string) => Array.from(el.querySelectorAll('a')).find((a) => a.textContent === label);

test('signed in: the heading and the line inside the console’s frame, drawn as its own page, and Start', async () => {
  signIn(true);
  await open();
  expect(el.querySelector('h1')?.textContent).toBe('This page isn’t here');
  expect(el.textContent).toContain('The link may be old, or the page was moved.');
  expect(el.querySelector('h1')?.closest('.shell')?.getAttribute('data-own')).toBe('1');
  const start = link('Back to Start');
  expect(start?.getAttribute('href')).toBe('/start');
  expect(start?.className).toContain('btn primary');
  expect(link('Sign in')).toBeUndefined();
});

test('signed out: the same, on the sign-in card, with Sign in as well', async () => {
  await open();
  expect(el.querySelector('.shell')).toBeNull();
  expect(el.querySelector('#hrui .au-card h1')?.textContent).toBe('This page isn’t here');
  expect(link('Back to Start')?.getAttribute('href')).toBe('/start');
  expect(link('Sign in')?.getAttribute('href')).toBe('/login');
});

test('its title, and no dash or internal word in what it says', async () => {
  expect(metadata.title).toBe('Page not found');
  for (const signedIn of [true, false]) {
    signIn(signedIn);
    await open();
    expect(el.textContent).not.toMatch(/[–—]| - /);
    act(() => root.unmount()); el.remove();
  }
  await open();
});
