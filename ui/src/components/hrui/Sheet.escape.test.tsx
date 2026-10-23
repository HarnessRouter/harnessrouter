/** @jest-environment jsdom */
// Escape and a code editor (audit, 2026-10-21): an Escape inside a code editor is the editor's, the first half of
// its own way out (Escape, then Tab), so it never closes the sheet and loses the draft; anywhere else in the sheet
// Escape closes it, and never while a save is in flight.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Sheet } from './Sheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve(); }); };
const esc = (target: Element) => act(() => { target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });

async function show(onClose: () => void, busy = false) {
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => {
    root.render(
      <Sheet onClose={onClose} labelledBy="t" busy={busy}>
        <h2 id="t">Edit skill</h2>
        <input aria-label="Name" />
        <div className="cm-editor"><div className="cm-content" contentEditable suppressContentEditableWarning tabIndex={0}>body</div></div>
      </Sheet>,
    );
  });
  await flush();
}
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; });

test('an Escape inside the code editor is left to the editor; the sheet stays open', async () => {
  const onClose = jest.fn();
  await show(onClose);
  await esc(document.querySelector('.cm-content') as Element);
  expect(onClose).not.toHaveBeenCalled();
});

test('an Escape anywhere else in the sheet closes it', async () => {
  const onClose = jest.fn();
  await show(onClose);
  await esc(document.querySelector('input[aria-label="Name"]') as Element);
  expect(onClose).toHaveBeenCalledTimes(1);
});

test('no Escape closes it while a save is in flight', async () => {
  const onClose = jest.fn();
  await show(onClose, true);
  await esc(document.querySelector('input[aria-label="Name"]') as Element);
  expect(onClose).not.toHaveBeenCalled();
});
