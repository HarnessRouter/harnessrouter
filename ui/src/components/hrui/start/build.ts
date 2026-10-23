'use client';
// A new setup being set up (docs/uxuidesign/console-91: buildAgent, then the build card at the top of
// its first task, backendShow / bsTop / buildSeq). Richard, 2026-10-19: the sheet closes as Save is
// pressed and the console opens the setup's page at once; its first task's conversation shows the
// work: "Setting up your harness" while the composer works, then the save card, each brick landing as
// the call that saves it answers, then the first request, waiting in that same conversation's box.
//
// The work outlives the sheet, so it is kept here, per tab, and the pages read it. Save records what
// was asked (startBuild) and opens the page of the setup being made; that page starts the work
// (resumeBuild), so no call is ever left in a page that is navigating away:
//   1. composing: the server builds the setup under this tab's key for it (start/compose.ts, POST
//      /v1/harnesses/builds): its builder reads what the setup should do and what the workspace has,
//      writes its configuration on one of the person's own models, then saves it itself; the page
//      shows each step as the server reports it, reading the build's record (GET
//      /v1/harnesses/builds/{key}) by long poll: the server answers as soon as the record stands
//      anywhere else than where the page last drew it, never on a timer of the page's own.
//      An unchanged demo with a recorded first run (start/replay.ts) is preset from its template
//      instead, and saved by the console (the server builds from a sentence, not a template). Shown on
//      /studio/new (start/BuildPage.tsx) while there is no setup yet;
//   2. saving: the server's saving step; for a demo preset, the setup is created (from here on it has
//      its id, and the setup's own page takes over, with the first test handed to it), then its
//      plugins are attached; each answer lands its brick on the card and on the Agent stack;
//   3. done: the first test is settled: its request waits in the box, ready to send (Richard,
//      2026-10-19: "Ready in the box"; nothing runs and no free request is used until the person sends
//      it). An unchanged demo's request waits there the same way, and sent as recorded it plays its
//      recorded run instead of running live (it reaches no server and takes nothing).
// A build the server says failed saved nothing, and nothing is saved in its place: the page says why
// (the server's reason, else "Your setup couldn't be built just now") with Try again, which reopens
// New setup with the sentence as it was written and starts a new build under a new key. The sentence
// is never saved as a setup's instructions (Richard, 2026-10-19). Nothing here is guessed: every state
// is an answer the server gave.
//
// The work is also kept for the tab (sessionStorage), step by step: what was asked, the configuration
// once composed, the name and time a create was sent under, the setup's id, the attaches. A full page
// load in the middle (a new console version turning the next navigation into a page load, a reload, a
// stale chunk reloading the page) loses the page's memory but not the work: the page of the setup
// being made picks it up where it stopped (resumeBuild), a create already sent is found by its name
// and time instead of being sent again, and the only place it ever lands is the setup's own Tasks
// (start/open.ts). Richard, 2026-10-19: a new account's tour was left on Harness Studio after Save,
// because the page that took over had nothing in memory and fell back to Studio.
//
// A build is the server's, by its key: a page load asks for it again by that key and picks it up
// wherever it is, and nothing about it is kept here but what was asked and, once saved, the setup.
// Richard, 2026-10-19 08:12Z: Save started the composer in the page it was leaving, the navigation
// became a page load (a new console version), the browser cancelled the call, the console saved its
// old fallback (his sentence as the instructions) and the page that loaded saved that, while the
// server's good answer arrived for nobody.
import { useEffect, useSyncExternalStore } from 'react';
import { createCustom, getCustom, listCustom, type CustomHarness } from '@/lib/harness';
import { setHarnessPlugs } from '@/lib/plugs';
import { getCurrentWorkspaceRef } from '@/lib/workspace';
import { track } from '@/lib/analytics';
import { toast } from '../toast';
import { seedSetup } from './seed';
import type { AssemblyState, Attach } from './Assembly';
import { handFirstTest } from './check';
import { BuildRefused, readServerBuild, standOf, startServerBuild, type BuildRecord, type BuildStep, type Chosen, type Composed } from './compose';
import { DEMOS } from './demos';
import { uniqName } from './names';
import { loadRecording, recordedMark, templateOf, type RecordedRun } from './replay';

export type BuildPhase = 'composing' | 'saving' | 'done' | 'failed';

export interface Build {
  /** this tab's own key for it (the address of /studio/new while it has no setup) */
  key: string;
  at: number;
  job: string;
  /** what the person chose: the agent harness and model (their names), or '' where Auto was left */
  pick: { baseName: string; model: string };
  phase: BuildPhase;
  /** how far the server's build has got, as it reports it ('' before its first answer, and for a demo preset) */
  step: BuildStep | '';
  /** the save card: what is being saved and how far each part has got (null while composing) */
  asm: AssemblyState | null;
  /** the setup, once created */
  id: string;
  /** the first test, once settled: its request, whether it runs now, whether a free request is left for it */
  first: { input: string; send: boolean; free: boolean } | null;
  /** an unchanged demo's recorded first run, played back when its request is sent */
  recording: RecordedRun | null;
  /** the first test's task, once it has one (a recorded run has none) */
  firstSid: string;
  /** an unchanged demo (its index in DEMOS), else null: Try again saves the demo again */
  demo: number | null;
  error: string;
}

/** What New setup asked for: plain values, so the work can be picked up after a page load. */
export interface BuildInput extends Chosen {
  job: string;
  pick: { baseName: string; model: string };
  /** an unchanged demo (its index in DEMOS), else null */
  demo: number | null;
  // base, model: the agent harness and model chosen (ids, or AUTO, which goes to the server as is: it
  // picks); baseName: the name of `base`, as this account offers it (a demo's template names its
  // agent harness with it)
}

/** Said where the setup would be, with Try again (BuildPage), when the server gives no reason */
export const NOT_BUILT = 'Your setup couldn’t be built just now.';
export const NOT_SAVED = 'Your setup couldn’t be saved just now.';
/** The setup exists but the rest of its save (its plugins, its recorded first run) did not answer */
export const NOT_FINISHED = 'Your setup couldn’t be finished just now.';

const builds = new Map<string, Build>();
/** the builds whose work is going on in this page */
const running = new Set<string>();
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
const sub = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
const hex = () => Math.random().toString(16).slice(2, 10);
/** No news of a build that is going on for this long (no answer): it is read once. Longer than the
 *  server's longest build (setup_builder STALE_S), past which a read settles it saved or failed. That
 *  read unanswered too: said, with Try again; a page load asks again by the key. */
const QUIET_MS = 210_000;
/** A long poll that failed is asked again after about this long, doubling, at most POLL_BACKOFF_MAX_MS. */
const POLL_BACKOFF_FIRST_MS = 2_000;
const POLL_BACKOFF_MAX_MS = 30_000;
/** A long poll answered at once with the record where it stood (a server that does not hold the read)
 *  is asked again no sooner than this, so the page never asks in a tight loop. */
const POLL_MIN_GAP_MS = 2_000;
/** How far a build has got, so an answer older than one already shown is not drawn over it */
const STEP_RANK: Record<string, number> = { reading: 0, writing: 1, saving: 2 };
const listOf = (xs: string[]) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const msOf = (t: number) => (t > 0 && t < 1e12 ? t * 1000 : t);

function set(key: string, fn: (b: Build) => Partial<Build>) {
  const b = builds.get(key);
  if (!b) return;
  builds.set(key, { ...b, ...fn(b) });
  emit();
}

// ── the work, kept for the tab ──────────────────────────────────────────────────────────────────
/** One build as kept: each step's answer, written as it comes. */
interface Kept {
  v: 1;
  key: string;
  at: number;
  input?: BuildInput;
  /** the configuration to save, once composed (or preset from the demo's recording) */
  cfg?: Composed;
  composed?: boolean;
  /** preset from the demo's recording: its first request plays the recording */
  preset?: boolean;
  /** a create was sent, under this name, at this time (ms) */
  name?: string;
  sentAt?: number;
  /** the setup, once created, and when its create answered */
  id?: string;
  savedAt?: number;
  /** each plugin's attach, once every attach has answered */
  plugins?: Record<string, Attach>;
  done?: boolean;
  error?: string;
}
const KEPT = 'hr.build:';
/** A build older than this is let go of (a tab kept open for days). */
const KEEP_MS = 24 * 3600_000;
/** A create sent before a page load: the setup it made was created at or after this long before it
 *  was sent (the server's clock and this one differ a little). */
const SENT_SKEW = 60_000;
type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem' | 'key' | 'length'>;
const tabStore = (): Store | null => { try { return globalThis.sessionStorage ?? null; } catch { return null; } };
// this page's own copy, so the work goes on where the tab keeps nothing (storage blocked or full)
const mem = new Map<string, Kept>();

function readKept(key: string): Kept | null {
  const m = mem.get(key);
  if (m) return m;
  try {
    const raw = tabStore()?.getItem(KEPT + key);
    if (!raw) return null;
    // kept by the console before 2026-10-19: the setup's id alone
    if (raw[0] !== '{') return { v: 1, key, at: 0, id: raw, done: true };
    const k = JSON.parse(raw) as Kept;
    return k && k.v === 1 ? { ...k, key } : null;
  } catch { return null; }
}
function keep(key: string, patch: Partial<Kept>): void {
  const next: Kept = { ...(readKept(key) || { at: Date.now() }), ...patch, v: 1, key };
  mem.set(key, next);
  const s = tabStore();
  try { s?.setItem(KEPT + key, JSON.stringify(next)); return; } catch { /* full: below */ }
  // a template's skills can be large: keep the rest (a page load then presets it again)
  try { s?.setItem(KEPT + key, JSON.stringify({ ...next, cfg: undefined })); } catch { /* the page's copy goes on */ }
}
function keptKeys(): string[] {
  const s = tabStore();
  const out: string[] = [];
  try { for (let i = 0; s && i < s.length; i++) { const k = s.key(i); if (k?.startsWith(KEPT)) out.push(k.slice(KEPT.length)); } } catch { /* none */ }
  return out;
}
function prune(now: number) {
  for (const k of keptKeys()) {
    const kept = readKept(k);
    if (!kept || now - (kept.at || 0) > KEEP_MS) { try { tabStore()?.removeItem(KEPT + k); } catch { /* left */ } mem.delete(k); }
  }
}

/** The configuration kept for this build, when it is one to save: composed (or preset), or already
 *  sent to be saved. A console before 2026-10-19 kept a stand-in when the composer gave nothing (the
 *  sentence as the instructions); one not yet sent is composed again. */
const keptCfg = (k: Kept | null): Composed | null => (k?.cfg && (k.composed || k.id || k.sentAt) ? k.cfg : null);

/** The build as the pages draw it, from what is kept. */
function fromKept(k: Kept): Build {
  const kc = keptCfg(k);
  const cfg = kc ? (k.name ? { ...kc, name: k.name } : kc) : null;
  return {
    key: k.key, at: k.at || Date.now(), job: k.input?.job || '', pick: k.input?.pick || { baseName: '', model: '' },
    phase: k.error ? 'failed' : k.done ? 'done' : k.id || cfg ? 'saving' : 'composing', step: '',
    asm: cfg ? { cfg, savedAt: k.savedAt ?? null, plugins: k.plugins || {}, done: !!k.done } : null,
    id: k.id || '', first: k.done && cfg ? readyInBox(cfg.exampleTask) : null,
    recording: null, firstSid: '', demo: k.input?.demo ?? null, error: k.error || '',
  };
}

/** The build at this key (the address of /studio/new). */
export function useBuild(key: string | null | undefined): Build | null {
  return useSyncExternalStore(sub, () => (key ? builds.get(key) || null : null), () => null);
}
/** This tab's build of this setup, if it was set up here. */
export function buildOf(id: string): Build | null {
  if (!id) return null;
  for (const b of builds.values()) if (b.id === id) return b;
  return null;
}
/** This tab's build of this setup; one a page load interrupted after the setup existed goes on. */
export function useBuildOf(id: string | null | undefined): Build | null {
  useEffect(() => { if (id) resumeBuildOf(id); }, [id]);
  return useSyncExternalStore(sub, () => buildOf(id || ''), () => null);
}
/** The first test of a setup built here has its task. */
export function noteFirstSid(id: string, sid: string): void {
  const b = buildOf(id);
  if (b && !b.firstSid) set(b.key, () => ({ firstSid: sid }));
}
/** Record a new setup to be set up; the page of the setup being made (start/BuildPage.tsx) starts the
 *  work (resumeBuild) and follows it by its key, then by its setup's id. Nothing is sent from here: the
 *  page that called this is about to be left, and a call left in it can be cut off by that navigation. */
export function startBuild(i: BuildInput): Build {
  const at = Date.now();
  const key = `b${at.toString(36)}${hex()}`;
  prune(at);
  keep(key, { at, input: i });
  const b = fromKept(readKept(key) as Kept);
  builds.set(key, b);
  emit();
  return b;
}

/** The build at this key, its work going on: this page's, or the tab's kept one picked up where it
 *  stopped (a page load in the middle of it); null when this tab has none (an old link, another tab's
 *  address). A build this page saw fail waits for Try again. */
export function resumeBuild(key: string | null | undefined): Build | null {
  if (!key) return null;
  let b = builds.get(key) || null;
  const k = readKept(key);
  if (!b) {
    if (!k) return null;
    b = fromKept(k);
    builds.set(key, b);
    emit();
  }
  if (k?.input && !k.done && !k.error && b.phase !== 'failed' && b.phase !== 'done') go(key);
  return b;
}
/** The rest of a save that failed after its setup existed, tried again (the setup's page's Try again). */
export function retryBuild(key: string): void {
  const b = builds.get(key);
  if (!b || b.phase !== 'failed' || running.has(key) || !readKept(key)?.input) return;
  set(key, (x) => ({ phase: x.id ? 'saving' : 'composing', error: '' }));
  go(key);
}

/** Whether the save of this setup, made in this tab, handed it a first request to send: true or false
 *  once the save has ended, null while it goes on or when this tab did not make it (the tour reads it:
 *  a save that handed none has no first test to wait for). */
export function handedFirst(id: string): boolean | null {
  if (!id) return null;
  const b = buildOf(id);
  if (b) return b.phase === 'done' ? !!b.first?.input.trim() : null;
  for (const k of keptKeys()) {
    const kept = readKept(k);
    if (kept?.id !== id) continue;
    const c = keptCfg(kept);
    return kept.done && c ? !!c.exampleTask.trim() : null;
  }
  return null;
}

/** A setup's page opened by a page load while its save was still attaching: the save goes on. */
export function resumeBuildOf(id: string): void {
  if (!id || buildOf(id)) return;
  for (const k of keptKeys()) {
    const kept = readKept(k);
    if (kept?.id === id && kept.input && !kept.done && !kept.error) { resumeBuild(k); return; }
  }
}

/** The first test of a setup just saved: ready in the box, never sent for the person (they read it,
 *  change it if they like, and send it; only then does it run, on a free request or the account, or,
 *  for an unchanged demo, its recorded run plays). */
const readyInBox = (input: string) => ({ input, send: false, free: false });

/** Run the work, once at a time in this page. Every step answers for itself; anything else that goes
 *  wrong (the recordings that could not be read, ...) is said, with Try again, and never ends as
 *  saved: before the setup exists on the page of the setup being made, after it on the setup's own
 *  page. Not kept: a page load, or Try again, goes on from the last step kept. */
function go(key: string) {
  if (running.has(key)) return;
  running.add(key);
  void run(key).catch(() => {
    set(key, () => ({ phase: 'failed', error: readKept(key)?.id ? NOT_FINISHED : NOT_BUILT }));
  }).finally(() => running.delete(key));
}

/** The work, from wherever it stopped: the configuration, the setup, its media tools and plugins. */
async function run(key: string) {
  const i = readKept(key)?.input;
  if (!i) return;
  // preset only where the person has what the recording ran on (the demo's harness and model, as
  // this account offers them) and this edition can add what it ran with (templateOf); otherwise the
  // demo is composed and runs live like any setup
  const loaded = await loadRecording(i.demo);
  const fits = i.demo != null && loaded && loaded.base === i.base && loaded.model === i.model ? loaded : null;
  const tpl = fits ? templateOf(i.demo as number, fits, i.baseName) : null;
  const rec = tpl ? fits : null;
  let k = readKept(key);
  let cfg = keptCfg(k);
  // the console saves a setup only from a demo's recording (its template); anything else the server builds
  if (!cfg && !rec) { await serve(key, i); return; }
  let preset = !!k?.preset && !!rec;
  if (!cfg) { cfg = tpl as Composed; preset = true; keep(key, { cfg, composed: true, preset }); }
  const c0 = cfg;
  set(key, (b) => ({ phase: 'saving', asm: b.asm || { cfg: c0, savedAt: null, plugins: {}, done: false } }));
  // a setup saved from a recording names it on its record, so its list always shows that first task
  const id = readKept(key)?.id || await create(key, i, c0, preset && rec ? recordedMark(rec) : undefined);
  if (!id) return;
  k = readKept(key);
  const savedAt = k?.savedAt || Date.now();
  if (!k?.savedAt) {
    // the setup's page takes over from here: its first request waits there, in the box
    handFirstTest(id, { input: c0.exampleTask, send: false, free: false });
    keep(key, { savedAt });
  }
  set(key, (b) => ({ id, phase: 'saving', asm: b.asm && { ...b.asm, savedAt, plugins: k?.plugins || Object.fromEntries(c0.plugins.map((p) => [p.id, 'now' as Attach])) } }));
  const failed = k?.plugins ? [] : await attach(key, id, c0);
  set(key, (b) => ({ phase: 'done', first: readyInBox(c0.exampleTask), recording: preset ? rec : null, asm: b.asm && { ...b.asm, done: true } }));
  keep(key, { done: true });
  if (k?.plugins) return;
  const lost = c0.plugins.filter((p) => failed.includes(p.id)).map((p) => p.name);
  const needTypes = c0.connectionsNeeded.map((p) => p.id);
  const name = buildOf(id)?.asm?.cfg.name || c0.name;
  if (lost.length) toast(`${listOf(lost)} ${lost.length > 1 ? 'weren’t' : 'wasn’t'} added. Add ${lost.length > 1 ? 'them' : 'it'} in the setup’s Settings.`);
  else if (needTypes.length) toast(`Connect ${listOf(c0.connectionsNeeded.map((p) => p.name))} in Add-ons so ${name} can use ${needTypes.length > 1 ? 'them' : 'it'}.`);
}

/** A build that saved nothing, said where the setup would be, with Try again. Not kept: a page load
 *  asks the server again by the key (a failed build reads failed again, with its reason). */
const fail = (key: string, reason: string) => set(key, () => ({ phase: 'failed', step: '', error: reason || NOT_BUILT }));

/** The server's build under this key, followed until it is saved or failed. */
async function serve(key: string, i: BuildInput): Promise<void> {
  const chosen: Chosen = { base: i.base, model: i.model, baseName: i.baseName };
  const workspace = getCurrentWorkspaceRef()?.id || '';
  let r: BuildRecord;
  try {
    // one key is one build: after a page load this hands back the same build and starts nothing
    r = await startServerBuild(key, i.job, chosen, workspace);
  } catch (e) {
    fail(key, e instanceof BuildRefused ? e.reason : '');
    return;
  }
  // a build the server has no record of (it restarted) is asked for again under the same key
  const end = await follow(key, r, async (after) => (await readServerBuild(key, chosen, after)) || startServerBuild(key, i.job, chosen, workspace));
  if (end instanceof BuildRefused) { fail(key, end.reason); return; }
  if (!end) { fail(key, ''); return; }
  if (end.status === 'failed' || !end.setupId) { fail(key, end.reason); return; }
  await savedByServer(key, end);
}

/** A build that is going on, followed until it is saved or failed. Its record is read by long poll:
 *  each read names where the record the page last drew stood (standOf), and the server answers as
 *  soon as it stands anywhere else, or after a while as it is; the next read is asked as each answers.
 *  Each answer is drawn, unless an answer already drawn is further on. A read that fails is asked
 *  again after about 2 s, doubling to 30 s. No answer at all for QUIET_MS: read once more, and that
 *  one unanswered too ends it. Resolves with the final record, the server's refusal, or null. */
function follow(key: string, first: BuildRecord, read: (after: string) => Promise<BuildRecord>): Promise<BuildRecord | BuildRefused | null> {
  return new Promise((resolve) => {
    let over = false, rank = -1, stand = '', backoff = 0;
    let quiet: ReturnType<typeof setTimeout> | undefined;
    let again: ReturnType<typeof setTimeout> | undefined;
    const end = (r: BuildRecord | BuildRefused | null) => {
      if (over) return;
      over = true;
      clearTimeout(quiet);
      clearTimeout(again);
      resolve(r);
    };
    const arm = () => { clearTimeout(quiet); quiet = setTimeout(() => void ask(true), QUIET_MS); };
    const take = (r: BuildRecord) => {
      if (over) return;
      if (r.status !== 'building') { end(r); return; }
      arm();
      stand = standOf(r);
      const n = STEP_RANK[r.step] ?? 0;
      if (n < rank) return;
      rank = n;
      set(key, (b) => ({ phase: r.step === 'saving' ? 'saving' : 'composing', step: r.step,
        asm: r.config ? { cfg: r.config, savedAt: null, plugins: {}, done: false } : b.asm }));
    };
    const ask = async (last = false) => {
      if (over) return;
      const was = stand, at = Date.now();
      try {
        take(await read(last ? '' : was));
        backoff = 0;
        if (over || last) return;
        // a read the server answered at once with the record where it stood is not asked again at once
        const gap = stand === was && Date.now() - at < POLL_MIN_GAP_MS ? POLL_MIN_GAP_MS : 0;
        clearTimeout(again);
        again = setTimeout(() => void ask(), gap);
      } catch (e) {
        if (e instanceof BuildRefused) { end(e); return; }
        if (last) { end(null); return; }
        backoff = backoff ? Math.min(POLL_BACKOFF_MAX_MS, backoff * 2) : POLL_BACKOFF_FIRST_MS;
        clearTimeout(again);
        again = setTimeout(() => void ask(), backoff);
      }
    };
    take(first);
    if (!over) void ask();
  });
}

/** The server saved the setup: its page takes over, with its example request in the box. */
async function savedByServer(key: string, r: BuildRecord): Promise<void> {
  const id = r.setupId, cfg = r.config, savedAt = Date.now();
  keep(key, { id, ...(cfg ? { cfg, composed: true } : {}), savedAt, plugins: r.attached, done: true });
  // the setup's page opens with it already here (start/seed.ts) when it can be read at once
  const h = await getCustom(id).catch(() => null);
  if (h) seedSetup(id, { h });
  handFirstTest(id, { input: cfg?.exampleTask || '', send: false, free: false });
  track('harness_created', { base: cfg?.base || '', model: cfg?.model || '', workspace_id: getCurrentWorkspaceRef()?.id || null, surface: 'new_setup', composed: true });
  set(key, () => ({ id, phase: 'done', step: '', first: readyInBox(cfg?.exampleTask || ''),
    asm: cfg ? { cfg, savedAt, plugins: r.attached, done: true } : null }));
  if (!cfg) return;
  const lost = cfg.plugins.filter((p) => r.attached[p.id] === 'off').map((p) => p.name);
  if (lost.length) toast(`${listOf(lost)} ${lost.length > 1 ? 'weren’t' : 'wasn’t'} added. Add ${lost.length > 1 ? 'them' : 'it'} in the setup’s Settings.`);
  else if (cfg.connectionsNeeded.length) {
    toast(`Connect ${listOf(cfg.connectionsNeeded.map((p) => p.name))} in Add-ons so ${cfg.name} can use ${cfg.connectionsNeeded.length > 1 ? 'them' : 'it'}.`);
  }
}

/** The setup's record, created once: a create sent before a page load is found by the name and time it
 *  was sent under, and only sent again when the server has no such setup. */
async function create(key: string, i: BuildInput, c0: Composed, source?: string): Promise<string | null> {
  try {
    const k = readKept(key);
    if (k?.name && k.sentAt) {
      const made = await findMade(k.name, k.sentAt);
      if (made) return landed(key, made);
    }
    const have = (await listCustom().catch(() => [] as CustomHarness[])).map((x) => x.name);
    const name = uniqName(i.demo != null ? DEMOS[i.demo].short : c0.name, have);
    if (name !== c0.name) set(key, (b) => ({ asm: b.asm && { ...b.asm, cfg: { ...b.asm.cfg, name } } }));
    keep(key, { name, sentAt: Date.now() });
    const c = await createCustom({ name, base: c0.base, defaultModel: c0.model, systemPrompt: c0.instructions,
      ...(c0.ownSkills?.length ? { skills: c0.ownSkills } : {}), ...(source ? { source } : {}) });
    track('harness_created', { base: c0.base, model: c0.model, harness_count_before: have.length, workspace_id: getCurrentWorkspaceRef()?.id || null, surface: 'new_setup', composed: !!readKept(key)?.composed });
    return landed(key, c);
  } catch {
    keep(key, { error: NOT_SAVED });
    set(key, () => ({ phase: 'failed', error: NOT_SAVED }));
    return null;
  }
}
function landed(key: string, c: CustomHarness): string {
  // the setup's page opens with it already here (start/seed.ts): no loading lines in the hand-off
  seedSetup(c.id, { h: c });
  keep(key, { id: c.id });
  return c.id;
}
/** The setup a create sent at `sentAt` under `name` made, when the server has it (read a few times:
 *  a create that has only just answered can take a moment to be listed). */
async function findMade(name: string, sentAt: number): Promise<CustomHarness | null> {
  for (let n = 0; n < 3; n++) {
    if (n) await sleep(1200);
    const xs = await listCustom().catch(() => null);
    const h = xs?.find((x) => x.name === name && msOf(x.createdAt || 0) >= sentAt - SENT_SKEW);
    if (h) return h;
  }
  return null;
}

/** Its plugins, each brick landing as its call answers; the ones that did not attach. (A demo's
 *  template brings no media tools on this edition: start/replay.ts SKIPPED_PLUGINS.) */
async function attach(key: string, id: string, c0: Composed): Promise<string[]> {
  const plugTypes = c0.plugins.map((p) => p.id);
  const needTypes = c0.connectionsNeeded.map((p) => p.id);
  const states: Record<string, Attach> = {};
  const mark = (ids: string[], v: Attach) => {
    ids.forEach((x) => { states[x] = v; });
    set(key, (b) => ({ asm: b.asm && { ...b.asm, plugins: { ...b.asm.plugins, ...Object.fromEntries(ids.map((x) => [x, v])) } } }));
  };
  const failed: string[] = [];
  // a plugin the job needs and the workspace has not connected is included too: it works once connected
  if (plugTypes.length || needTypes.length) {
    await setHarnessPlugs(id, [...plugTypes, ...needTypes]).then(() => mark(plugTypes, 'on')).catch(() => { mark(plugTypes, 'off'); failed.push(...plugTypes); });
  }
  keep(key, { plugins: states });
  return failed;
}
