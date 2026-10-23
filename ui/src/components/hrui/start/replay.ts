// A demo's first request, played back instead of run again (Richard, 2026-10-22: like the hosted
// console, replay the recorded steps so a demo spends no tokens). An unchanged demo, on the harness
// and model its recording ran on, is saved as a real setup in the workspace from its template
// (start/recorded.ts: the instructions and skills the recording ran on); everything sent to it later
// runs live. Only its first request is not run again: the real run recorded for it (each stream event
// with its offset from the request) plays in the setup's first task through the same handlers a live
// turn goes through (useConversationTurn.replay), on its own timeline, so it reads the same. It costs
// nothing and makes no task. Nothing is ever read by the recording's own ids: the turn comes from the
// recording alone, and the files it made are its kept copies (public/demos). A demo with no
// recording runs live, as any other setup does: nothing is ever played that did not run. The
// recordings are read only when a demo is saved or a setup saved from one opens (a dynamic import),
// so no page carries them otherwise. An import that fails is asked for again (IMPORT_RETRY_MS); one
// that still fails throws, and is never taken for "no recording": the demo is not saved to run live
// in its place, and a saved demo's recorded first task is said to be unreadable, with Try again.
import { useEffect, useState } from 'react';
import type { CustomHarness } from '@/lib/harness';
import type { RespFile } from '@/lib/chat';
import { DEMOS } from './demos';
import type { RecordedRun } from './recorded';

export type { RecordedRun } from './recorded';

/** The longest a recording takes to play (compressed, with an honest label): every step in order and
 *  in proportion, sped up so a long run plays in this time; a shorter one plays at the pace it ran.
 *  "Done in" always says the time it took when it ran. */
export const REPLAY_MAX_MS = 15_000;
/** How much faster than it ran a recording plays (1: as it ran). */
export const replaySpeed = (run: RecordedRun) => Math.max(1, run.durMs / REPLAY_MAX_MS);

const usable = (r: RecordedRun | undefined | null): r is RecordedRun =>
  !!r && Array.isArray(r.events) && r.events.length > 0 && !!r.request && !!r.template;

/** The pauses before the recordings' import is asked for again after it fails (a chunk that did not
 *  load); after the last, the read fails. */
export const IMPORT_RETRY_MS = [1000, 3000];
const sleep = (ms: number) => new Promise<void>((done) => { setTimeout(done, ms); });

let loaded: Promise<RecordedRun[]> | null = null;
async function importRecordings(): Promise<RecordedRun[]> {
  for (let i = 0; ; i++) {
    try { return (await import('./recorded')).RECORDED.filter(usable); }
    catch (e) { if (i >= IMPORT_RETRY_MS.length) throw e; await sleep(IMPORT_RETRY_MS[i]); }
  }
}
/** Every usable recording; throws when they could not be read (the next call tries again). */
const recordings = () => (loaded ||= importRecordings().catch((e) => { loaded = null; throw e; }));

/** The recorded first run of this demo, or null when it has none (it then runs live). Throws when the
 *  recordings could not be read: that is not "none". */
export async function loadRecording(demo: number | null | undefined, runs?: RecordedRun[]): Promise<RecordedRun | null> {
  if (demo == null) return null;
  const all = runs ? runs.filter(usable) : await recordings();
  return all.find((r) => r.demo === demo) || null;
}

// ── which recording a setup was saved from ──────────────────────────────────────────────────────
// A setup saved from a demo's recording carries it on its own record, in `source` (stored on create,
// returned with the setup, never changed by a later save): "demo:<its index>@<when the run was
// recorded>". Its task list shows that recorded first task, the oldest, for as long as the setup
// exists; one whose run is no longer kept shows none (nothing is played that is not the run it was
// saved from).

/** The marker a setup saved from this recording carries. */
export const recordedMark = (run: RecordedRun) => `demo:${run.demo}@${run.ranAt}`;

/** Which demo run a setup's `source` names, or null when it names none. */
export function markOf(source: string | undefined | null): { demo: number; ranAt: number } | null {
  const m = /^demo:(\d+)@(\d+)$/.exec(String(source || ''));
  return m ? { demo: Number(m[1]), ranAt: Number(m[2]) } : null;
}

/** The recorded run this marker names, from these runs, or null. */
export function runOfMark(source: string | undefined | null, runs: RecordedRun[]): RecordedRun | null {
  const k = markOf(source);
  return k ? runs.find((r) => r.demo === k.demo && r.ranAt === k.ranAt) || null : null;
}

/** The recorded run a setup was saved from, read from its record: `run` is undefined while the
 *  recordings are read (and while they could not be), null when it was saved from none (or its run is
 *  no longer kept). `failed`: they could not be read, which the page says with Try again (`retry`). */
export function useRecordedRunState(source: string | undefined | null): { run: RecordedRun | null | undefined; failed: boolean; retry: () => void } {
  const src = String(source || '');
  const marked = !!markOf(src);
  // what was read, for the source it was read for: a source that has just arrived (the setup's record
  // read after the page opened) is undefined until its own read answers, never the last one's answer
  const [got, setGot] = useState<{ src: string; run: RecordedRun | null } | null>(null);
  const [failed, setFailed] = useState(false);
  const [again, setAgain] = useState(0);
  useEffect(() => {
    setFailed(false);
    if (!marked) return;
    let alive = true;
    recordings().then((all) => { if (alive) setGot({ src, run: runOfMark(src, all) }); }, () => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [marked, src, again]);
  const run = !marked ? null : got && got.src === src ? got.run : undefined;
  return { run, failed: marked && failed && run === undefined, retry: () => setAgain((n) => n + 1) };
}

/** useRecordedRunState's run alone: undefined while read, and while the read has failed (never null,
 *  "saved from none", in its place). */
export function useRecordedRun(source: string | undefined | null): RecordedRun | null | undefined {
  return useRecordedRunState(source).run;
}

const tail = (p: string) => String(p || '').split('/').pop() || '';

/** A file the recorded run reports, as its own kept copy (matched by file name); null when the
 *  recording kept none, so nothing is shown that cannot be opened. */
export function recordedFile(run: RecordedRun, f: RespFile): RespFile | null {
  const n = tail(f.filename);
  const kept = run.files.find((x) => tail(x.name) === n || tail(x.src) === n);
  return kept ? { ...f, url: kept.src } : null;
}

const skillId = () => 'skl_' + (globalThis.crypto?.randomUUID?.() || `${Date.now()}${Math.random()}`).replace(/[^a-z0-9]/gi, '');

/** The plugins of a recording's template that a setup here is saved without: the image generation
 *  tools ('media') are the hosted service's own, and on this edition the agent harness makes the
 *  image itself (a live run here produced the product image without them). */
export const SKIPPED_PLUGINS = ['media'];

/** What a setup saved from a demo's recording is made with (createCustom): the name it saves as, the
 *  agent harness and model the recording ran on, its instructions, and its own skills (the entries
 *  the recorded setup stored, saved under fresh ids). */
export interface DemoSetup {
  name: string; base: string; model: string; instructions: string;
  skills: CustomHarness['skills'];
}

/** A demo's setup, as its recording ran on it; null when the recording ran on a plugin this edition
 *  cannot add (anything but SKIPPED_PLUGINS), so the setup it plays in would not be the one it ran
 *  on: that demo runs live. */
export function templateOf(demo: number, run: RecordedRun): DemoSetup | null {
  const t = run.template;
  if ((t.plugins || []).some((p) => p && p.id && !SKIPPED_PLUGINS.includes(p.id))) return null;
  const skills = (t.skills || []).filter((s) => s && s.id && s.skill);
  return {
    name: t.name || DEMOS[demo].short, base: run.base, model: run.model,
    instructions: t.instructions || DEMOS[demo].instr,
    skills: skills.map((s): CustomHarness['skills'][number] => ({ ...s.skill, id: skillId(), enabled: s.skill.enabled !== false })),
  };
}
