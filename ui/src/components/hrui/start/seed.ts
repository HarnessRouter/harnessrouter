// A setup just made in this tab, handed to its page (setups.ts useSetup): the record the create answered
// with, kept in memory by the setup's id. The page a new setup opens on then draws its first frame with
// the setup already there, and reads it again from the server behind it, so the hand-off from New
// setup shows no loading in between. Only a page opened in this tab right after the create has one: a
// reload or a link opens cold, with its loading lines. The tab also notes which setups it made
// (madeHere), so the page of one never calls it missing while the server catches up with its create,
// even after a page load.
import type { CustomHarness } from '@/lib/harness';

export interface Seed { h: CustomHarness }
const seeds = new Map<string, Seed>();

const MADE = 'hr.made:';
/** How long after its create a setup made here is waited for, rather than called missing. */
const MADE_WAIT = 10 * 60_000;
const made = new Map<string, number>();
const tabStore = (): Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null => { try { return globalThis.sessionStorage ?? null; } catch { return null; } };

/** This tab has just made this setup (every create path says so as it opens the setup, start/open.ts). */
export function markMade(id: string, now = Date.now()): void {
  if (!id) return;
  made.set(id, now);
  try { tabStore()?.setItem(MADE + id, String(now)); } catch { /* this page's note still says so */ }
}
export function seedSetup(id: string, s: Seed): void {
  if (!id) return;
  seeds.set(id, s);
  markMade(id);
}
/** The setup this tab has just made, by its id, or null. */
export function seededSetup(id: string): Seed | null { return (id && seeds.get(id)) || null; }
/** This tab made this setup a moment ago: its page reads it again instead of calling it missing. */
export function madeHere(id: string, now = Date.now()): boolean {
  if (!id) return false;
  let at = made.get(id) || 0;
  if (!at) { try { at = Number(tabStore()?.getItem(MADE + id) || 0); } catch { at = 0; } }
  return at > 0 && now - at < MADE_WAIT;
}

// The task a setup was made with (New setup: the sentence the person sent there), for its page to run
// once as it opens. Kept in the tab too, so the page load that opens the setup still finds it; taking
// it forgets it, so a reload, a second tab or a return to the page never runs it again.
const FIRST = 'hr.first:';
const firsts = new Map<string, string>();
export function setFirstTask(id: string, text: string): void {
  if (!id || !text.trim()) return;
  firsts.set(id, text);
  try { tabStore()?.setItem(FIRST + id, text); } catch { /* this page's note still has it */ }
}
/** The first task waiting for this setup, without taking it ('' when none). */
export function peekFirstTask(id: string): string {
  if (!id) return '';
  let t = firsts.get(id) || '';
  if (!t) { try { t = tabStore()?.getItem(FIRST + id) || ''; } catch { t = ''; } }
  return t;
}
/** The first task waiting for this setup, taken: it is handed over once. */
export function takeFirstTask(id: string): string {
  const t = peekFirstTask(id);
  firsts.delete(id);
  try { tabStore()?.removeItem(FIRST + id); } catch { /* forgotten in this page */ }
  return t;
}


// A setup saved from a demo's recorded run (start/replay.ts) has no first task to run: its first task
// is that recording, which plays as its page opens, once, in proportion, as if it ran now. Kept in the
// tab like the first task, for the page load that opens the setup; taking it forgets it, so the page
// opened again shows the recorded task whole, at once, as it does when opened from the list.
const PLAY = 'hr.play:';
const plays = new Set<string>();
export function setFirstReplay(id: string): void {
  if (!id) return;
  plays.add(id);
  try { tabStore()?.setItem(PLAY + id, '1'); } catch { /* this page's note still has it */ }
}
/** This setup's recorded first task is to play now (true once): taking it forgets it. */
export function takeFirstReplay(id: string): boolean {
  if (!id) return false;
  let on = plays.has(id);
  if (!on) { try { on = tabStore()?.getItem(PLAY + id) === '1'; } catch { on = false; } }
  plays.delete(id);
  try { tabStore()?.removeItem(PLAY + id); } catch { /* forgotten in this page */ }
  return on;
}
