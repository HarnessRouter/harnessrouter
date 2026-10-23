'use client';
// The handle between the open task's conversation and its file's preview (studio/[id], where the
// preview is docked from 1280 px; below that it is a drawer over the page and has no handle).
// Richard 10-18: "like before", as the workbench's preview had it (TaskChat useHResize, UI Core's
// PaneResizer): drag it with a pointer (mouse, pen or touch), or focus it and press the arrow keys
// (24 px a press, 96 px with Shift); a double-click puts the preview back at its first width. Both
// sides keep room: the preview at least PREVIEW_MIN, the conversation at least CONVO_MIN. The width
// is this viewer's own, kept in this browser; a window too narrow for it shows what fits there and
// keeps the wider width for a wider window.
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import './preview-grip.css';

const KEY = 'hrui.tk.preview.w';
export const PREVIEW_DEFAULT = 620;
export const PREVIEW_MIN = 320;
/** the task list's column beside them (the docked layout's first column, preview-grip.css) */
const LIST_W = 300;
/** the conversation: room for its composer and a column you can read */
export const CONVO_MIN = 380;

/** The widest the preview may be in a split `room` px wide (0: not measured yet, no limit). */
export function previewMax(room: number): number {
  return room > 0 ? Math.max(PREVIEW_MIN, room - LIST_W - CONVO_MIN) : Infinity;
}

/** The preview's width for the one wanted, in a split `room` px wide. */
export function fitPreview(want: number, room: number): number {
  const w = Number.isFinite(want) && want > 0 ? want : PREVIEW_DEFAULT;
  return Math.round(Math.min(previewMax(room), Math.max(PREVIEW_MIN, w)));
}

function readKept(): number {
  try {
    const n = parseInt(window.localStorage.getItem(KEY) || '', 10);
    return Number.isFinite(n) && n > 0 ? n : PREVIEW_DEFAULT;
  } catch { return PREVIEW_DEFAULT; }
}
function keep(w: number | null): void {
  try {
    if (w == null) window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, String(w));
  } catch { /* not kept: the width lasts this visit */ }
}

const useIsoLayout = typeof window === 'undefined' ? useEffect : useLayoutEffect;

export interface PreviewWidth { width: number; room: number; setWant: (w: number) => void }

/** The docked preview's width, measured against the split it sits in while it is docked (`on`). */
export function usePreviewWidth(split: RefObject<HTMLElement | null>, on: boolean): PreviewWidth {
  const [want, setWant] = useState(PREVIEW_DEFAULT);
  // read after the page is drawn: the server that drew it first has no storage
  useEffect(() => { setWant(readKept()); }, []);
  const [room, setRoom] = useState(0);
  useIsoLayout(() => {
    const el = split.current;
    if (!on || !el) return undefined;
    const read = () => setRoom(el.clientWidth);
    read();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, [on, split]);
  return { width: fitPreview(want, room), room, setWant };
}

export function PreviewGrip({ pv }: { pv: PreviewWidth }) {
  const { width, room, setWant } = pv;
  const drag = useRef<{ x: number; w: number } | null>(null);
  const last = useRef(width);
  last.current = width;
  const [on, setOn] = useState(false);
  const to = (w: number, save: boolean) => {
    const v = fitPreview(w, room);
    last.current = v;
    setWant(v);
    if (save) keep(v);
  };
  const end = () => {
    if (!drag.current) return;
    drag.current = null;
    setOn(false);
    document.body.classList.remove('hr-pv-resizing');
    keep(last.current);
  };
  useEffect(() => () => { document.body.classList.remove('hr-pv-resizing'); }, []);
  const max = previewMax(room);
  return (
    <div className={`tk-pv-grip${on ? ' on' : ''}`} role="separator" aria-orientation="vertical" tabIndex={0}
      aria-label="Resize the preview" title="Drag to resize. Double-click to reset."
      aria-valuenow={width} aria-valuemin={PREVIEW_MIN} aria-valuemax={Number.isFinite(max) ? max : undefined}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        drag.current = { x: e.clientX, w: width };
        setOn(true);
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* the moves still reach it while over it */ }
        // while it drags, a preview's frame cannot take the pointer and no text is selected
        document.body.classList.add('hr-pv-resizing');
      }}
      // the handle is on the preview's left edge: dragging left widens the preview
      onPointerMove={(e) => { const d = drag.current; if (d) to(d.w - (e.clientX - d.x), false); }}
      onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end}
      onDoubleClick={() => { last.current = fitPreview(PREVIEW_DEFAULT, room); setWant(PREVIEW_DEFAULT); keep(null); }}
      onKeyDown={(e) => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        const step = e.shiftKey ? 96 : 24;
        to(width + (e.key === 'ArrowLeft' ? step : -step), true);
      }} />
  );
}
