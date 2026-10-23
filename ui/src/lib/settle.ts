// A read a page waits on always ends. When a service behind a read stalls (a store that holds a
// request open without answering), a read with no end leaves its page on its skeleton forever, and
// nothing fails, so nothing says so. readSettled gives a read an end.
//
// A read gets one quiet second try. The first try is cancelled when it fails or has no answer after
// FIRST_TRY_MS; after a short pause it is asked once more. The read rejects when the second try fails
// too, or when READ_MS have passed since it began, whichever comes first, so the page can show its
// error and Try again within about 15 seconds.

export const READ_MS = 15_000;
export const FIRST_TRY_MS = 10_000;
const PAUSE_MS = 1_000;

/** A try that had no answer in time (its request is cancelled too). */
export class ReadTimeout extends Error {
  constructor() { super('The read had no answer in time.'); this.name = 'ReadTimeout'; }
}

/** One try with an end: `read` gets a signal that aborts at `ms`, and the promise rejects at `ms`
 *  whether or not the read heeds the signal (a body that stalls after its headers). */
export function withDeadline<T>(read: (signal: AbortSignal) => Promise<T>, ms: number): Promise<T> {
  const ctl = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<never>((_, reject) => {
    timer = setTimeout(() => { const e = new ReadTimeout(); ctl.abort(e); reject(e); }, ms);
  });
  const work = Promise.resolve().then(() => read(ctl.signal));
  work.catch(() => { /* a try cancelled at its deadline rejects after the race is decided */ });
  return Promise.race([work, late]).finally(() => clearTimeout(timer));
}

const sleep = (ms: number) => new Promise<void>((done) => { setTimeout(done, ms); });

/** A read that always settles: see the head of this file. */
export async function readSettled<T>(read: (signal: AbortSignal) => Promise<T>,
  { within = READ_MS, firstTry = FIRST_TRY_MS, pause = PAUSE_MS }: { within?: number; firstTry?: number; pause?: number } = {}): Promise<T> {
  const end = Date.now() + within;
  try {
    return await withDeadline(read, Math.min(firstTry, within));
  } catch (e) {
    if (end - Date.now() - pause <= 0) throw e;
    await sleep(pause);
    const left = end - Date.now();
    if (left <= 0) throw e;
    return withDeadline(read, left);
  }
}
