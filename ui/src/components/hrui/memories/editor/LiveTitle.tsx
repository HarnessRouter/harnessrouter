'use client';
// A record's title as a shared line of text: each person's typing goes into the document as the difference it made,
// and what arrives moves this person's caret by what happened before it, so nobody's cursor jumps.
import { useEffect, useRef } from 'react';
import type * as Y from 'yjs';

function caretOf(el: HTMLElement): number | null {
  const s = window.getSelection();
  if (!s || !s.rangeCount || !el.contains(s.anchorNode)) return null;
  const r = s.getRangeAt(0).cloneRange();
  r.selectNodeContents(el);
  r.setEnd(s.anchorNode as Node, s.anchorOffset);
  return r.toString().length;
}

function putCaret(el: HTMLElement, at: number) {
  const s = window.getSelection();
  const n = el.firstChild;
  if (!s) return;
  const r = document.createRange();
  if (n) r.setStart(n, Math.min(at, n.textContent?.length ?? 0)); else r.setStart(el, 0);
  r.collapse(true);
  s.removeAllRanges();
  s.addRange(r);
}

export function LiveTitle({ text, readOnly, className, placeholder, onEnter }: {
  text: Y.Text; readOnly: boolean; className?: string; placeholder: string; onEnter?: () => void;
}) {
  const el = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => {
    const node = el.current;
    if (!node) return undefined;
    node.textContent = text.toString();
    const seen = (ev: Y.YTextEvent, tx: Y.Transaction) => {
      if (tx.local && tx.origin === 'title-input') return;
      let caret = caretOf(node);
      if (caret !== null) {
        let at = 0;
        for (const d of ev.delta) {
          if (d.retain) at += d.retain;
          else if (typeof d.insert === 'string') { if (at <= caret) caret += d.insert.length; at += d.insert.length; }
          else if (d.delete) { if (at < caret) caret -= Math.min(d.delete, caret - at); }
        }
      }
      node.textContent = text.toString();
      if (caret !== null) putCaret(node, caret);
    };
    text.observe(seen);
    return () => text.unobserve(seen);
  }, [text]);
  const input = () => {
    const next = (el.current?.textContent || '').replace(/\n/g, ' ');
    const cur = text.toString();
    if (next === cur) return;
    let s = 0;
    while (s < cur.length && s < next.length && cur[s] === next[s]) s += 1;
    let e = 0;
    while (e < cur.length - s && e < next.length - s && cur[cur.length - 1 - e] === next[next.length - 1 - e]) e += 1;
    text.doc?.transact(() => {
      if (cur.length - s - e) text.delete(s, cur.length - s - e);
      if (next.length - s - e) text.insert(s, next.slice(s, next.length - e));
    }, 'title-input');
  };
  return (
    <h1 ref={el} className={className} contentEditable={readOnly ? false : 'plaintext-only'} suppressContentEditableWarning spellCheck={false}
      role={readOnly ? undefined : 'textbox'} aria-label="Title" data-ph={readOnly ? undefined : placeholder} onInput={input}
      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); onEnter?.(); } }} />
  );
}
