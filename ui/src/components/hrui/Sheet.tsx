'use client';
// The design's dialogs (docs/uxuidesign/console-79: `.scrim > .sheet`, renderSheet / closeSheet):
// a dimmed scrim over the page with one sheet in it, a bottom sheet on a phone (the stylesheet's
// media queries do that). Opening moves focus into the sheet (the given element, else its first
// field, else the sheet itself); Escape, the close button and a click on the scrim close it;
// closing gives focus back to what opened it. Tab stays inside the sheet while it is open.
//
// It renders into #hrui (the redesign's root), so the design's styles reach it wherever the page
// that opens it sits.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';

const X = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
);

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([type=hidden]):not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';
const FIELDS = 'input:not([type=hidden]):not([disabled]),textarea:not([disabled]),select:not([disabled])';

function visible(el: HTMLElement): boolean {
  return !!el.offsetParent && !el.closest('details:not([open])') && !el.hidden;
}

export interface SheetProps {
  onClose: () => void;
  /** id of the sheet's title (aria-labelledby) */
  labelledBy: string;
  describedBy?: string;
  /** classes beside `sheet`, e.g. "small-sheet", "small-sheet del-sheet", "sk-sheet" */
  className?: string;
  /** a confirm that asks before something is lost: role=alertdialog */
  alert?: boolean;
  /** what takes focus on open: an element, or 'dialog' for the sheet itself (a phone keeps its
   *  keyboard down); absent: the first field, else the sheet itself */
  initialFocus?: RefObject<HTMLElement | null> | 'dialog';
  /** while true, Escape and the scrim do not close it (a save in flight) */
  busy?: boolean;
  /** the first-run tour's mark for this sheet (`data-tour`), when a step lights it */
  tour?: string;
  children: ReactNode;
}

export function Sheet({ onClose, labelledBy, describedBy, className, alert, initialFocus, busy, tour, children }: SheetProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useLayoutEffect(() => {
    opener.current = (document.activeElement as HTMLElement | null) || null;
    setHost(document.getElementById('hrui') || document.body);
  }, []);

  // focus in once it is drawn; back to the opener when it goes
  useEffect(() => {
    if (!host) return;
    const d = ref.current;
    if (!d) return;
    const raf = requestAnimationFrame(() => {
      if (d.contains(document.activeElement)) return;
      const want = initialFocus && initialFocus !== 'dialog' ? initialFocus.current : null;
      if (want && d.contains(want)) { want.focus(); if (document.activeElement === want) return; }
      const f = initialFocus === 'dialog' ? undefined : Array.from(d.querySelectorAll<HTMLElement>(FIELDS)).find(visible);
      if (f) { f.focus(); if (document.activeElement === f) return; }
      d.focus({ preventScroll: true });
    });
    const back = opener.current;
    return () => {
      cancelAnimationFrame(raf);
      if (back && document.body.contains(back)) back.focus();
    };
  // focus moves once, when the sheet opens
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (busyRef.current) return;
        // An Escape inside a code editor is the editor's: it is the first half of the editor's own way out
        // (Escape, then Tab: CodeEditor), where Tab otherwise indents. Taken here, it closed the sheet and
        // lost the draft, and the keyboard had no way out of the editor but that (audit, 10-21). The next
        // Escape, from anywhere else in the sheet, closes it.
        if ((e.target as Element | null)?.closest?.('.cm-editor')) return;
        e.stopPropagation();
        close.current();
        return;
      }
      if (e.key !== 'Tab' || !ref.current) return;
      const all = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(visible);
      if (!all.length) { e.preventDefault(); return; }
      const first = all[0], last = all[all.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', key, true);
    return () => document.removeEventListener('keydown', key, true);
  }, []);

  if (!host) return null;
  return createPortal(
    <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget && !busyRef.current) close.current(); }}>
      <div ref={ref} className={`sheet${className ? ' ' + className : ''}`} role={alert ? 'alertdialog' : 'dialog'}
        aria-modal="true" aria-labelledby={labelledBy} aria-describedby={describedBy} tabIndex={-1} data-tour={tour}>
        {children}
      </div>
    </div>,
    host,
  );
}

/** The sheet's head: its title, an optional line under it, and the close button. */
export function SheetTop({ id, title, sub, onClose }: { id: string; title: ReactNode; sub?: ReactNode; onClose: () => void }) {
  return (
    <div className="sheet-top">
      <div>
        <h3 id={id}>{title}</h3>
        {sub ? <p className="sub">{sub}</p> : null}
      </div>
      <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>{X}</button>
    </div>
  );
}

/** A destructive confirm, as the design draws every one (`.del-sheet`): a title, what happens,
 *  Cancel and the red button. `refused`: the service's own answer that this person can't do it (who
 *  can, by role), said in the sheet in place of the red button, with Close. */
export function ConfirmSheet({ id, title, body, confirmLabel, onConfirm, onClose, busy, focusConfirm, refused }: {
  id: string; title: ReactNode; body: ReactNode; confirmLabel: string;
  onConfirm: () => void; onClose: () => void; busy?: boolean;
  /** the red button takes focus on open (the design does this where the action is the expected one) */
  focusConfirm?: boolean;
  refused?: string;
}) {
  const go = useRef<HTMLButtonElement | null>(null);
  const shut = useRef<HTMLButtonElement | null>(null);
  // the red button goes when the answer is a refusal: the focus moves to Close, never to the page
  useEffect(() => { if (refused) shut.current?.focus(); }, [refused]);
  return (
    <Sheet onClose={onClose} labelledBy={`${id}h`} describedBy={`${id}p`} className="small-sheet del-sheet" alert busy={busy}
      initialFocus={focusConfirm ? go : undefined}>
      <SheetTop id={`${id}h`} title={title} onClose={onClose} />
      <p className="del-p" id={`${id}p`}>{body}</p>
      {refused ? <p className="del-p del-refused" role="alert">{refused}</p> : null}
      <div className="del-act">
        <button ref={shut} type="button" className="btn" onClick={onClose} disabled={busy}>{refused ? 'Close' : 'Cancel'}</button>
        {refused ? null : <button ref={go} type="button" className="btn del-go" onClick={onConfirm} disabled={busy}>{confirmLabel}</button>}
      </div>
    </Sheet>
  );
}
