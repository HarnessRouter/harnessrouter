'use client';
// Escape closes the innermost thing open first. A sheet (Sheet.tsx) closes on Escape from a
// capture listener on the document; a part opened inside it (a manager under a settings row, a form,
// an inline confirm) registers here, and its listener, on the window in the capture phase, runs
// before the sheet's: the most recently opened part closes and the key goes no further. With none
// open, Escape reaches the sheet as before.
import { useEffect, useRef } from 'react';

const layers: { close: () => void }[] = [];
let listening = false;

function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape' || e.isComposing || !layers.length) return;
  e.stopPropagation();
  e.preventDefault();
  layers[layers.length - 1].close();
}

/** While `open`, Escape calls `close` (before anything opened earlier, and before the sheet). */
export function useEscapeLayer(open: boolean, close: () => void): void {
  const fn = useRef(close);
  fn.current = close;
  useEffect(() => {
    if (!open) return;
    const layer = { close: () => fn.current() };
    layers.push(layer);
    if (!listening) { window.addEventListener('keydown', onKey, true); listening = true; }
    return () => {
      const i = layers.indexOf(layer);
      if (i >= 0) layers.splice(i, 1);
      if (!layers.length && listening) { window.removeEventListener('keydown', onKey, true); listening = false; }
    };
  }, [open]);
}
