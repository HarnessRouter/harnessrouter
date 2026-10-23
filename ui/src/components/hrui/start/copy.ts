'use client';
// Copying a prompt or a line, as the design does it (copyConfirm / copyFrom): the clipboard when
// the browser allows it; otherwise the text is selected, the person is told to press Cmd or Ctrl + C,
// and their own copy of that selection counts as done.
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { toast } from '../toast';

/** What to select when the browser will not copy: an element, or a ref to one that may only be drawn
 *  once the failure is shown (a folded step opens again to show its text). */
type Target = HTMLElement | null | RefObject<HTMLElement | null>;
const node = (t: Target): HTMLElement | null => (t && 'current' in t ? t.current : t);

function selectNode(n: HTMLElement | null): void {
  if (!n) return;
  const r = document.createRange(); r.selectNodeContents(n);
  const w = window.getSelection(); w?.removeAllRanges(); w?.addRange(r);
}

/** Copy a short text (a line, a key): on failure select its element and say how to copy it. */
export async function copyFrom(text: string, el: HTMLElement | null, msg = 'Copied'): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); toast(msg); return true; }
  catch { selectNode(el); toast('Text selected. Press Cmd or Ctrl + C.'); return false; }
}

/** Copy something whose copying is a step (a prompt, a new key): `ok` runs once it is on the
 *  clipboard, whether the browser put it there or the person did after it was selected for them.
 *  `failed` says the automatic copy did not happen, for the hint beside the button. */
export function useCopyConfirm(): { copy: (text: string, el: Target, msg: string, ok: () => void) => void; failed: boolean } {
  const [failed, setFailed] = useState(false);
  const wait = useRef<{ el: Target; msg: string; ok: () => void } | null>(null);
  useEffect(() => {
    const onCopy = () => {
      const w = wait.current; if (!w) return;
      const n = node(w.el), sel = window.getSelection();
      if (!n || !sel || !sel.rangeCount || !String(sel).trim() || !n.contains(sel.getRangeAt(0).commonAncestorContainer)) return;
      wait.current = null;
      setTimeout(() => { setFailed(false); toast(w.msg); w.ok(); }, 0);
    };
    document.addEventListener('copy', onCopy);
    return () => document.removeEventListener('copy', onCopy);
  }, []);
  const copy = useCallback((text: string, el: Target, msg: string, ok: () => void) => {
    const fail = () => {
      wait.current = { el, msg, ok };
      setFailed(true);
      // the text may be drawn only now that the failure shows it
      if (node(el)) selectNode(node(el)); else requestAnimationFrame(() => selectNode(node(el)));
      toast('Couldn’t copy automatically. Press Cmd or Ctrl + C.');
    };
    try {
      navigator.clipboard.writeText(text).then(() => { wait.current = null; setFailed(false); toast(msg); ok(); }, fail);
    } catch { fail(); }
  }, []);
  return { copy, failed };
}
