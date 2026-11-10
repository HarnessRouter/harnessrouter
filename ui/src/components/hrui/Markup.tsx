'use client';
// Markup a drawing is built as (a brick, a tower, a page's picture), set as an element's inner HTML.
//
// React 19 sets innerHTML again whenever the object it is handed is a new one, and `{{ __html: x }}` written in place is
// new on every render. So every re-render replaced the whole drawing: a press that began on a brick and ended after a
// re-render fell on a node that was gone, and the browser drops such a click. Studio's cards are mostly picture and
// re-render many times a second while their figures load, so a card often needed a second click (Richard, 2026-11-06,
// on the open-source and hosted consoles). Here the object stays the same while the markup does, and the drawing stays.
import { useMemo, type CSSProperties } from 'react';

/** `dangerouslySetInnerHTML` for `markup`, the same object until the markup changes. */
export function useHtml(markup: string): { __html: string } {
  return useMemo(() => ({ __html: markup }), [markup]);
}

/** A decorative drawing from markup this console builds itself (never data). */
export function Markup({ html, as: Tag = 'span', className, style, id }: { html: string; as?: 'span' | 'div'; className?: string; style?: CSSProperties; id?: string }) {
  const inner = useHtml(html);
  return <Tag id={id} className={className} style={style} aria-hidden="true" dangerouslySetInnerHTML={inner} />;
}
