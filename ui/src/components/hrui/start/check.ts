'use client';
// New setup's first test, handed to the setup's Tasks: the request the build wrote as an end user would
// send it (start/compose.ts exampleTask), never the sentence the person wrote. It waits in the box,
// ready to send: nothing runs until the person sends it (Richard, 2026-10-19: "Ready in the box").
// (The hosted console's request check and free requests live beside this there; this edition has
// neither.)

/** The first test a new setup's Tasks open with (on New task): the request, whether it runs now (New
 *  setup hands none over that way), and whether it runs free (never, on this edition). Taken once.
 *  `setup` marks the one New setup handed over, as against a task run again as a test, which the page
 *  seeds the same way. */
export interface FirstTest { input: string; send: boolean; free: boolean; setup?: boolean }
type Handed = FirstTest & { at: number };
const pending = new Map<string, Handed>();
// kept for the tab too: the setup's page opened by a full page load (a new console version turning the
// navigation into one) still finds its first request (start/build.ts keeps the save the same way)
const HANDED = 'hr.first:';
const tabStore = (): Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null => { try { return globalThis.sessionStorage ?? null; } catch { return null; } };

export function handFirstTest(harnessId: string, t: FirstTest): void {
  const h = { ...t, at: Date.now() };
  pending.set(harnessId, h);
  try { tabStore()?.setItem(HANDED + harnessId, JSON.stringify(h)); } catch { /* this page's copy still works */ }
}

/** The first test waiting for this setup, once; one left more than a few minutes is dropped. It
 *  stays readable for a moment after it is taken, so a mount React makes twice reads the same one
 *  (the Playground puts it in the box once either way). */
export function takeFirstTest(harnessId: string): FirstTest | null {
  let t = pending.get(harnessId);
  if (!t) {
    try {
      const raw = tabStore()?.getItem(HANDED + harnessId);
      const k = raw ? JSON.parse(raw) as Handed : null;
      if (k && typeof k.input === 'string' && typeof k.at === 'number') { t = { input: k.input, send: !!k.send, free: !!k.free, at: k.at }; pending.set(harnessId, t); }
    } catch { /* none kept */ }
  }
  if (!t) return null;
  const was = t;
  setTimeout(() => {
    if (pending.get(harnessId) !== was) return;
    pending.delete(harnessId);
    try { tabStore()?.removeItem(HANDED + harnessId); } catch { /* left to expire */ }
  }, 1500);
  return Date.now() - t.at < 5 * 60_000 ? { input: t.input, send: t.send, free: t.free, setup: true } : null;
}
