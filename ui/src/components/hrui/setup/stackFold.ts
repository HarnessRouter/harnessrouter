// Whether a setup page's Agent stack is open or folded (Richard, 2026-10-18: "the Agent stack's
// open/closed state is remembered in localStorage, and the first time a person comes in it is
// open"). One choice per viewer, kept in this browser: the same on Tasks and Settings and on every
// setup. Under 1280 px the stack opens over the work instead of beside it, so there it starts
// folded whatever was kept; its toggle opens it for the visit, and that never overwrites the choice
// made at desktop width.

/** The viewer's choice, in this browser: 'open' or 'closed'. */
export const STACK_KEY = 'hrui.stack';
/** At and below this width the open stack lies over the work (hrui.css: the 1279 px rules). */
export const OVERLAY_MAX = 1279;

export type Fold = 'open' | 'closed';
type Store = Pick<Storage, 'getItem' | 'setItem'>;

/** The kept choice, or null when there is none (or the browser keeps nothing: private windows,
 *  blocked storage). */
export function readFold(store: Store | null | undefined): Fold | null {
  try {
    const v = store?.getItem(STACK_KEY);
    return v === 'open' || v === 'closed' ? v : null;
  } catch { return null; }
}

/** Keep a choice; a browser that keeps nothing keeps it for this visit only. */
export function writeFold(store: Store | null | undefined, v: Fold): void {
  try { store?.setItem(STACK_KEY, v); } catch { /* kept in the page for this visit */ }
}

/** Folded or open: under the overlay width folded unless opened there this visit; else the kept
 *  choice, open when there is none. */
export function stackOff(kept: Fold | null, narrow: boolean, openedNarrow: boolean): boolean {
  if (narrow) return !openedNarrow;
  return kept === 'closed';
}

/** What a press of the toggle changes: at desktop width the kept choice; under the overlay width
 *  only this visit's opening (`keep` null: nothing is written). */
export function toggled(kept: Fold | null, narrow: boolean, openedNarrow: boolean): { keep: Fold | null; openedNarrow: boolean } {
  if (narrow) return { keep: null, openedNarrow: !openedNarrow };
  return { keep: stackOff(kept, false, false) ? 'open' : 'closed', openedNarrow };
}
