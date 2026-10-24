// Writing to a recorded first task continues it as a task of your own (the hosted console's fork):
// the recorded run is no task of the server's, so the first message written under it starts a new
// task whose input carries the recording itself: its request and its answer as the earlier messages,
// then the new message, with the files the run made (their kept copies under /demos, as data)
// attached, so "make the background white" has the image to work on. A server that takes earlier
// messages as the agent's history keeps them as the new task's first turn, marked imported (no cost,
// completed); only the new message runs. Nothing is ever read by the recording's own ids.
//
// A server without that (it would give the agent the new message alone, and read the thread back
// without the recorded part) must never get a fork: one is offered only where the server's discovery
// document says it takes input history (INPUT_HISTORY_FLAG); anywhere else, this edition's gateway
// included today, the recorded task stays read only, with Follow up (a new task of yours, run live).
// As a second guard, a fork's turns are read back, and one whose first turn is not imported keeps
// this browser on the read-only bar from then (asked again after a while, for an upgrade).
import { basesDoc } from '@/lib/harness';
import type { RecordedRun } from './replay';

/** The discovery flag that says the server takes earlier messages as a new task's history and keeps
 *  them as its imported first turn: `true` on GET /v1/bases, at its top or in its `capabilities`. */
export const INPUT_HISTORY_FLAG = 'input_history';

/** The server says it takes input history (the flag is true); false when it does not say so. */
export async function inputHistory(): Promise<boolean> {
  const d = await basesDoc().catch(() => null);
  if (!d) return false;
  const caps = d.capabilities && typeof d.capabilities === 'object' ? d.capabilities as Record<string, unknown> : {};
  return d[INPUT_HISTORY_FLAG] === true || caps[INPUT_HISTORY_FLAG] === true;
}

const fileParts = (fs: { name: string; dataUri: string }[]) => fs.map((f) => ({ type: 'input_file', filename: f.name, file_data: f.dataUri }));

/** The request's input for a fork of this recorded run: the recording's request,
 *  with the files the run made (so they come with the recorded part, the imported turn), its answer,
 *  then the new message with any file the person attached. Sent without previous_response_id or a
 *  session, which would make it a plain continuation. */
export function forkInput(run: RecordedRun, answer: string, text: string, runFiles: { name: string; dataUri: string }[],
  own: { name: string; dataUri: string }[] = []): unknown[] {
  return [
    { role: 'user', content: [{ type: 'input_text', text: run.request }, ...fileParts(runFiles)] },
    { role: 'assistant', content: answer },
    { role: 'user', content: [{ type: 'input_text', text }, ...fileParts(own)] },
  ];
}

const base = (p: string) => String(p || '').split('/').pop() || p;

/** The pauses before a recorded file's read is tried again after it fails; after the last, it failed. */
export const FILE_RETRY_MS = [500, 1500];
const sleep = (ms: number) => new Promise<void>((done) => { setTimeout(done, ms); });

/** Recorded files that could not be read, by name: the fork is not started without them. */
export class ForkFilesError extends Error {
  constructor(public names: string[]) { super(`The recorded files could not be read: ${names.join(', ')}`); this.name = 'ForkFilesError'; }
}

/** One kept copy, as data; throws when it cannot be read. */
async function readKept(f: RecordedRun['files'][number]): Promise<{ name: string; dataUri: string }> {
  const r = await fetch(f.src, { cache: 'force-cache' });
  if (!r.ok) throw new Error(String(r.status));
  const b = await r.blob();
  const dataUri = await new Promise<string>((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result || ''));
    fr.onerror = () => rej(fr.error);
    fr.readAsDataURL(b.type ? b : new Blob([b], { type: f.mime }));
  });
  return { name: base(f.name), dataUri };
}

/** The files the recorded run made, read from their kept copies as data, every one of them: a read
 *  that fails is tried again (FILE_RETRY_MS), and one that still fails throws ForkFilesError naming
 *  them all. A fork is never sent with some of its files left out. */
export async function forkFiles(run: RecordedRun): Promise<{ name: string; dataUri: string }[]> {
  const out = await Promise.allSettled(run.files.map(async (f) => {
    for (let i = 0; ; i++) {
      try { return await readKept(f); }
      catch (e) { if (i >= FILE_RETRY_MS.length) throw e; await sleep(FILE_RETRY_MS[i]); }
    }
  }));
  const lost = run.files.filter((_, i) => out[i].status === 'rejected').map((f) => base(f.name));
  if (lost.length) throw new ForkFilesError(lost);
  return out.map((o) => (o as PromiseFulfilledResult<{ name: string; dataUri: string }>).value);
}

// ── whether this environment's gateway keeps a fork whole ───────────────────────────────────────
const KEY = 'hr.fork.whole';
const RECHECK_MS = 6 * 3600_000;   // a server found without it is asked again after a while (an upgrade)

/** The fork's turns, read back: is its first turn the recording, imported? */
export function importedFirst(turns: unknown[]): boolean {
  const t = turns[0] as { imported?: unknown } | undefined;
  return !!t && t.imported === true;
}

/** Whether forks may be offered here: not when a fork here was read back without its imported turn
 *  (until RECHECK_MS has passed). */
export function forkOffered(): boolean {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || 'null') as { whole: boolean; at: number } | null;
    return !v || v.whole || Date.now() - v.at > RECHECK_MS;
  } catch { return true; }
}

/** What a fork's read back said. */
export function noteFork(whole: boolean): void {
  try { localStorage.setItem(KEY, JSON.stringify({ whole, at: Date.now() })); } catch { /* kept for this visit only */ }
}
