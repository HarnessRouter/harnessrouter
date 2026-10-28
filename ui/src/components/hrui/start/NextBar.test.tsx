/** @jest-environment jsdom */
// The Next card under a new setup's first test (Richard, 2026-10-19: the "nx2" design). Your app (a
// brick still to build) and the setup by its own name (a built brick) at the two ends, the task going
// over and the result coming back between them, Connect your app under the wires. Its button opens the
// setup page's Connect your app sheet.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { NextBar, SET_UP_APP_EVENT } from './NextBar';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let root: Root;
let host: HTMLElement;

function show(name: string, id = 'chrn_a') {
  act(() => root.render(<NextBar id={id} name={name} />));
  return host.querySelector<HTMLElement>('.bs-next') as HTMLElement;
}

beforeEach(() => {
  host = document.createElement('div');
  host.id = 'hrui';
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('the Next card', () => {
  test('your app at the left, the setup by its own name at the right, task over and result back between', () => {
    const card = show('Product images');
    expect(card.classList.contains('nx2')).toBe(true);
    expect(card.querySelector('.bs-nk')?.textContent).toBe('Next');
    const [app, setup] = Array.from(card.querySelectorAll<HTMLElement>('.nx-end'));
    expect(app.querySelector('b')?.textContent).toBe('Your app');
    expect(app.querySelector('span')?.textContent).toBe('Built by your coding agent');
    expect(setup.querySelector('b')?.textContent).toBe('Product images');
    expect(setup.querySelector('span')?.textContent).toBe('Runs every task in HarnessRouter');
    // the bricks in their states: your app still to build, the setup built
    expect(app.querySelector('svg.iso.nx-b .bk.next')).not.toBeNull();
    expect(setup.querySelector('svg.iso.nx-b .bk.built')).not.toBeNull();
    expect(card.querySelectorAll('.bk .su')).toHaveLength(8);
    // the wires: the task goes over, the result comes back
    expect(card.querySelector('.nx-wire .go')?.textContent).toBe('task');
    expect(card.querySelector('.nx-wire .back')?.textContent).toBe('result');
    expect(card.querySelector('.nx-mid button')?.textContent).toBe('Connect your app');
    // no dash anywhere in its words, and this edition is not the hosted service
    expect(card.textContent).not.toMatch(/[-–—]/);
    expect(card.textContent).not.toContain('Cloud');
    expect(card.querySelector('[data-tour]')).toBeNull();
  });

  test('a screen reader hears the flow in one sentence, then the button', () => {
    const card = show('Product images');
    const flow = card.querySelector('.nx-flow') as HTMLElement;
    expect(flow.getAttribute('role')).toBe('group');
    expect(flow.getAttribute('aria-label')).toBe('Your app, built by your coding agent, sends each task to Product images. It runs in HarnessRouter and the result comes back.');
    card.querySelectorAll('.nx-end, .nx-wire').forEach((e) => expect(e.getAttribute('aria-hidden')).toBe('true'));
    // the button is never inside a picture, where it would be hidden with the picture's contents
    const btn = card.querySelector('button') as HTMLButtonElement;
    expect(btn.closest('[role="img"], [aria-hidden="true"]')).toBeNull();
  });

  test('a long name is the setup’s own, whole in the sentence and the tooltip', () => {
    const long = 'Quarterly supplier invoice reconciliation for every regional office';
    const card = show(long);
    const b = card.querySelector('.nx-setup b') as HTMLElement;
    expect(b.textContent).toBe(long);
    expect(b.getAttribute('title')).toBe(long);
    expect(card.querySelector('.nx-flow')?.getAttribute('aria-label')).toContain(`sends each task to ${long}.`);
  });

  test('Connect your app asks the setup’s page for its Connect your app sheet', () => {
    const heard = jest.fn();
    const on = (e: Event) => heard((e as CustomEvent).detail);
    window.addEventListener(SET_UP_APP_EVENT, on);
    try {
      const card = show('Product images', 'chrn_7');
      act(() => (card.querySelector('.nx-mid button') as HTMLButtonElement).click());
      expect(heard).toHaveBeenCalledTimes(1);
      expect(heard).toHaveBeenCalledWith({ id: 'chrn_7' });
    } finally {
      window.removeEventListener(SET_UP_APP_EVENT, on);
    }
  });
});
