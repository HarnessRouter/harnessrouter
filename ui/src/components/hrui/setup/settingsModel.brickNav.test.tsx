/** @jest-environment jsdom */
// The setup page hears the Next bar's Connect your app (start/NextBar SET_UP_APP_EVENT) where it hears its
// Agent stack's bricks (useBrickNav), and opens its Connect your app sheet; once the page has gone, it no
// longer listens.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { useBrickNav } from './settingsModel';
import { SET_UP_APP_EVENT } from '../start/NextBar';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Page({ onSetUpApp }: { onSetUpApp: () => void }) {
  useBrickNav({ onLayer: () => {}, onSetUpApp });
  return null;
}

let root: Root;
let el: HTMLElement;
beforeEach(() => { el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { el.remove(); });

test('Connect your app from the Next bar opens the page’s sheet, and only while the page is there', () => {
  const onSetUpApp = jest.fn();
  act(() => root.render(<Page onSetUpApp={onSetUpApp} />));
  act(() => { window.dispatchEvent(new CustomEvent(SET_UP_APP_EVENT, { detail: { id: 'chrn_a' } })); });
  expect(onSetUpApp).toHaveBeenCalledTimes(1);
  act(() => root.unmount());
  window.dispatchEvent(new CustomEvent(SET_UP_APP_EVENT, { detail: { id: 'chrn_a' } }));
  expect(onSetUpApp).toHaveBeenCalledTimes(1);
});
