'use client';
// The open task's conversation on a setup's Tasks tab (docs/uxuidesign/console-91: newPane, taskPane,
// leanComposer, pgOpts in the composer's bar, threadHtml): test the saved setup the way your app
// would call it. A test is a task: New task starts one, and every task of the setup takes follow-ups,
// whoever sent it. Its turns run through the one conversation machine (useConversationTurn), so
// sending, streaming, stopping and settling behave the same everywhere.
//
// The model can change inside a test: each message goes out with the model chosen at that moment
// (the request's `model`), and the next turn of the same task runs on it. The service keeps every
// model a task has run; the one switch it refuses is Codex running a -codex model in a task another
// model family has already used (its tools are not available there), and the picker says so for
// those models instead of letting the send fail. Each reply ends in one quiet line: the model when it
// is not the setup's own, how it ended and how long it took (when the record kept it), then three small
// actions (Richard 10-18): copy the reply as Markdown, copy its ID, and copy a request your own app can
// send to carry on the conversation from that reply. The conversation scrolls in its own column, the
// composer pinned at its foot.
//
// A setup saved from a demo's recorded run (start/replay.ts) has that run as its first task: it plays
// here through the same handlers a live turn goes through, sends nothing and spends nothing, says
// Recorded on its reply with the time it took when it ran, and is read, not continued. Under it, where
// the server takes earlier messages as a new task's history (start/fork.ts), the box takes a message
// that goes on as a task of your own; anywhere else a bar says it is a recorded task, with Follow up
// (a new task of yours, run live). It is never also sent as a live first task.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { isInternalOutput, useConversationTurn, useHarnessBus, type AsstMsg, type ChatTarget } from '@/lib/conversation';
import { replyMarkdown } from './replyMd';
import { loadSessionTurns } from '@/lib/chat';
import { modelAvailability, oobById, oobDefaultModel, oobModels, useModelCatalogRead } from '@/lib/harness';
import { providerById, useModelProviders } from '@/lib/providers';
import { toast } from '../toast';
import { Skel, SkLine, SkThread } from '../Skel';
import type { SetupRow } from '../setups';
import { API_BASE } from '../start/prompts';
import { peekFirstTask, takeFirstReplay, takeFirstTask } from '../start/seed';
import { recordedFile, replaySpeed, type RecordedRun } from '../start/replay';
import { forkFiles, forkInput, forkOffered, importedFirst, inputHistory, noteFork } from '../start/fork';
import { AgentConversation, AgentComposer } from 'reifyui/agent-chat';
import { AgentTurns, harnessMark } from './AgentTurns';
import { FileCards, filesOf, type OpenFile } from './TurnFiles';
import { workingNow } from './stackLive';
import { sec } from './fmt';
import { Md } from './TaskThread';
const MAX_FILE = 25 * 1024 * 1024;
const ACCEPT = 'image/jpeg,image/png,image/webp,image/gif,application/pdf,text/plain,text/markdown,text/csv,application/json,.md,.csv,.txt,.json,.pdf';

const CHEV = <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>;
const CHECK = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} aria-hidden="true"><path d="M5 12l5 5L20 7" /></svg>;
const COPY = <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h8" /></svg>;
const HASH = <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" aria-hidden="true"><path d="M4 9h16M4 15h16M10 3L8 21M16 3l-2 18" /></svg>;
const CODE = <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16" /></svg>;
/** where the next message goes in a copied request: plainly a placeholder, never sent as it is by mistake */
const NEXT_MSG = '<your next message>';


type Attach = { name: string; dataUri: string; size: number };

function readFile(f: File): Promise<Attach> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res({ name: f.name, dataUri: String(r.result || ''), size: f.size });
    r.onerror = () => rej(r.error);
    r.readAsDataURL(f);
  });
}

/** One test: the composer, then its thread once sent. A new test mounts a fresh one. */
function Test({ r, model, defaultModel, headerValues, onRan, onBorn, pgOpts, resume, onSeen, onPreview, previewKey, onLive, taskTitle, recording, onFollowUp, onReplay }: {
  r: SetupRow; model: string; defaultModel: string; headerValues: Record<string, string>;
  /** the open task's title, as its bar shows it (a reply's Download all names its zip after it) */
  taskTitle?: string;
  onRan: () => void; onBorn: (sid: string) => void;
  /** the model (and headers) picker, drawn in the composer's bar */
  pgOpts: () => React.ReactNode;
  /** a past test to continue (its session), else a new one */
  resume: string | null;
  /** open a produced file in the preview beside the conversation (every file of the test, the one clicked) */
  onPreview: (files: OpenFile[], key: string) => void;
  previewKey: string | null;
  /** the models this test has run, oldest first (from its record when continued, then each send) */
  onSeen: (models: string[], resumed: boolean) => void;
  /** the bricks this test's turn is working through now (null when none runs), for the Agent stack */
  onLive?: (working: string[] | null) => void;
  /** the setup's recorded first task (start/replay.ts): played back here, never sent */
  recording?: RecordedRun | null;
  /** a recorded task's Follow up: a new task of yours, run live */
  onFollowUp?: () => void;
  /** a recorded run is playing here (true) or has ended (false): its row and head show it running */
  onReplay?: (playing: boolean) => void;
}) {
  const oob = oobById(r.h.base);
  const [sid, setSid] = useState<string | null>(resume);
  // the model each turn ran on, in order: read from a continued test's record, then each message sent
  const [turnModels, setTurnModels] = useState<string[]>([]);
  // each turn's response ID, as the record has it (read with the record, and again as a turn ends)
  const [turnIds, setTurnIds] = useState<string[]>([]);
  const seenRef = useRef(onSeen);
  seenRef.current = onSeen;
  const fromRecord = useRef(false);
  useEffect(() => {
    if (!resume) return;
    let alive = true, t: ReturnType<typeof setTimeout> | undefined;
    // a read that fails says nothing of the turns: read again, 2 s, 4 s, ... (the next message needs no
    // answer from it: one sent with no model goes on with the task's last model, server side)
    const read = (n: number) => loadSessionTurns(resume).then(({ turns }) => {
      if (!alive) return;
      fromRecord.current = true;
      // the model each turn asked for; where the record does not carry it, the one it was served on,
      // without its provider ("openai/gpt-6.1-sol")
      setTurnModels(turns.map((t) => {
        const x = t as { _model?: string; served_model?: string | null };
        return String(x._model || (x.served_model ? x.served_model.split('/').pop() : '') || '');
      }));
      setTurnIds(turns.map((x) => String(x.id || '')));
    }).catch(() => { if (alive) t = setTimeout(() => void read(n + 1), Math.min(30_000, 2000 * 2 ** n)); });
    void read(0);
    return () => { alive = false; if (t) clearTimeout(t); };
  }, [resume]);
  // the page hears which models this test has run (the picker's Codex rule reads them)
  useEffect(() => { seenRef.current(turnModels, fromRecord.current); fromRecord.current = false; }, [turnModels]);
  const [input, setInput] = useState('');
  const [att, setAtt] = useState<Attach | null>(null);
  const ta = useRef<HTMLTextAreaElement | null>(null);
  // this conversation is a recorded run, played back (whole at once, or in proportion as it ran): it
  // is read, not continued
  const [replayed, setReplayed] = useState(false);
  const [whole, setWhole] = useState(false);
  // written to, a recorded run goes on as a task of your own (start/fork.ts): from then on it is live
  const [forked, setForked] = useState(false);
  const forking = useRef(false);
  // offered only where the server says it takes input history, and no fork here read back half
  const [offerFork, setOfferFork] = useState(false);
  useEffect(() => {
    if (!recording) return;
    let alive = true;
    void inputHistory().then((ok) => { if (alive) setOfferFork(ok && forkOffered()); });
    return () => { alive = false; };
  }, [recording]);
  const recorded = replayed && !forked;
  const target: ChatTarget = { name: r.h.name, backend: oob?.backend ?? null, model, baseId: oob?.id, runtime: oob?.name, defaultModel };
  const conv = useConversationTurn({
    harnessId: r.h.id, sessionId: resume, target, onRan,
    onSession: (s) => { setSid(s); onBorn(s); },
    onRefused: (text, files) => { setInput(text); setAtt(files[0] ? { ...files[0], size: 0 } : null); },
    onSendStart: () => { setInput(''); setAtt(null); },
    extraHeaders: () => headerValues,
  });
  // While a test runs, the harness's live feed is open too: the test's own stream renders its turn,
  // and if that stream drops (a network blink, a restart) the feed carries the rest of it live
  // instead of the turn standing still until the record settles it.
  // (a recorded run reaches no server: nothing to hear)
  useHarnessBus(conv.busy && !recorded ? r.h.id : '');
  // The Agent stack beside the test follows its turn: the layers the current event works through,
  // told to the page only when they change (the stream's deltas leave them as they are).
  const lastAsst = [...conv.msgs].reverse().find((m): m is AsstMsg => m.role === 'assistant');
  // (a recorded run drawn whole at once is not running: it is drawn as it ended)
  const working = conv.busy && !(recorded && whole) ? workingNow(lastAsst, conv.stopping) : null;
  const workSig = working ? working.join(' ') : '';
  const liveRef = useRef(onLive);
  liveRef.current = onLive;
  useEffect(() => { liveRef.current?.(workSig ? workSig.split(' ') : null); }, [workSig]);
  useEffect(() => () => liveRef.current?.(null), []);
  // a turn sent here has ended: its response ID is in the record now
  const wasBusy = useRef(false);
  useEffect(() => {
    const was = wasBusy.current;
    wasBusy.current = conv.busy;
    const live = sid || conv.liveSessionId;
    if (!was || conv.busy || !live) return undefined;
    let alive = true, t: ReturnType<typeof setTimeout> | undefined;
    // a read that fails keeps the IDs already read, and is read again shortly (at most three more times)
    const read = (n: number) => loadSessionTurns(live).then(({ turns }) => { if (alive) setTurnIds(turns.map((x) => String(x.id || ''))); })
      .catch(() => { if (alive && n < 3) t = setTimeout(() => void read(n + 1), 1000 * 2 ** n); });
    void read(0);
    return () => { alive = false; if (t) clearTimeout(t); };
  }, [conv.busy, sid, conv.liveSessionId]);
  const started = conv.msgs.length > 0 || !!resume || !!recording;
  // a recorded run plays as a live one runs: the page's row and head say it is running until it ends
  const playing = recorded && conv.busy && !whole;
  const replayRef = useRef(onReplay);
  replayRef.current = onReplay;
  useEffect(() => { replayRef.current?.(playing); }, [playing]);
  useEffect(() => () => replayRef.current?.(false), []);
  // a task opened from the list shows its latest turn, as a chat does: the conversation's own
  // scroller goes to its end once the record has drawn
  const chatRef = useRef<HTMLDivElement | null>(null);
  const atEnd = useRef(false);
  useEffect(() => {
    if (!resume || atEnd.current || conv.msgs.length === 0) return;
    atEnd.current = true;
    requestAnimationFrame(() => { const sc = chatRef.current?.querySelector<HTMLElement>('.uac-scroll'); if (sc) sc.scrollTop = sc.scrollHeight; });
  }, [resume, conv.msgs.length]);
  const mixed = new Set(turnModels.filter(Boolean)).size > 1;
  const opening = !!resume && conv.msgs.length === 0;
  /** a message goes out on the model chosen now; the turn is recorded with it once it is taken */
  const sendNow = (text: string, files: { name: string; dataUri: string }[]) => {
    const m = model;
    void conv.send(text, files).then((took) => {
      if (!took) return;
      setTurnModels((xs) => [...xs, m]);
    });
  };
  // THE TASK THE SETUP WAS MADE WITH runs as its page opens (New setup: the sentence the person sent is
  // what they asked to see run), once, on the model chosen there, as soon as that model is known to run.
  // One no provider serves now leaves it in the box instead, to send once another model is chosen.
  const avail = modelAvailability(target.backend, model);
  // A recorded first task is never also sent live: it has no first task to run.
  useEffect(() => {
    if (recording || resume || conv.msgs.length || conv.busy || conv.loadFailed || avail === 'unknown' || !peekFirstTask(r.h.id)) return;
    const text = takeFirstTask(r.h.id);
    if (avail === 'no') setInput(text);
    else sendNow(text, []);
    // sendNow is this render's; the hand-off happens once, when the conditions above first hold
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resume, conv.msgs.length, conv.busy, conv.loadFailed, avail, r.h.id]);
  // A setup's recorded first run, played back here: it reaches no server and takes nothing. In order
  // and in proportion, at most REPLAY_MAX_MS long, when New setup has just saved it (start/seed.ts
  // takeFirstReplay); opened from the list, or again, whole at once.
  const autoPlayed = useRef(false);
  const play = (all: boolean) => {
    if (!recording) return;
    autoPlayed.current = true;
    setReplayed(true); setWhole(all); setInput('');
    const speed = all ? 0 : 1 / replaySpeed(recording);
    conv.replay(recording.request, recording.events.map((e) => ({ t: e.t * speed, ev: e.ev })), (f) => recordedFile(recording, f), recording.durMs * speed);
  };
  useEffect(() => {
    if (!recording || autoPlayed.current) return;
    play(!takeFirstReplay(r.h.id));
    // play is this render's; a recording plays once, as the task opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recording, r.h.id]);
  // a task whose record could not be read takes no message: it would go on from an unknown point
  const canSend = !conv.busy && !conv.loadFailed && (input.trim() || att) && modelAvailability(target.backend, model) !== 'no';
  // the recorded run, finished and offered as a conversation like any other (start/fork.ts): the first
  // message written under it starts a task of yours carrying the recording as its earlier messages
  const forkable = recorded && !!recording && offerFork;
  const fork = async () => {
    const text = input.trim();
    if (!text || !recording || forking.current) return;
    forking.current = true;
    const answer = conv.msgs.filter((x): x is AsstMsg => x.role === 'assistant')
      .map((a) => a.blocks.filter((b) => b.kind === 'text' && !b.error).map((b) => (b.kind === 'text' ? b.text : '')).join('\n\n')).join('\n\n');
    // the run's own files go with its request (the imported turn); a file the person attached goes
    // with their message, as always
    const own = att ? [{ name: att.name, dataUri: att.dataUri }] : [];
    // the run's files that cannot be read (after their own retries) stop the fork: nothing is sent
    // without them, and the message stays in the box
    let runFiles: Awaited<ReturnType<typeof forkFiles>>;
    try { runFiles = await forkFiles(recording); }
    catch { forking.current = false; toast('The recorded files could not be read just now. Try again.'); return; }
    const m = model;
    setForked(true);
    // from here the recorded run is this task's imported first turn: quoted, never the agent's own
    conv.setMsgs((ms) => ms.map((x) => ({ ...x, imported: true as const })));
    const took = await conv.send(text, own, { input: forkInput(recording, answer, text, runFiles, own) });
    forking.current = false;
    if (!took) { setForked(false); conv.setMsgs((ms) => ms.map(({ imported: _i, ...x }) => x)); return; }
    setTurnModels([recording.model, m]);
  };
  // a fork's first turn, read back once it has ended: kept whole (the recording imported as its first
  // turn), or not, which keeps the recorded task read only in this browser from then on
  const forkRead = useRef(false);
  useEffect(() => {
    const live = sid || conv.liveSessionId;
    if (!forked || conv.busy || !live || forkRead.current) return;
    forkRead.current = true;
    loadSessionTurns(live).then(({ turns }) => noteFork(importedFirst(turns))).catch(() => { /* asked again on the next fork */ });
  }, [forked, conv.busy, sid, conv.liveSessionId]);
  const send = () => {
    if (!canSend) return;
    if (forkable) { void fork(); return; }
    // a file alone goes as it is: no words are put in the person's mouth
    sendNow(input.trim(), att ? [{ name: att.name, dataUri: att.dataUri }] : []);
  };
  const pick = async (f: File | undefined) => {
    if (!f) return;
    if (f.size > MAX_FILE) { toast('That file is over 25 MB. Choose a smaller one.'); return; }
    try { setAtt(await readFile(f)); } catch { toast('That file could not be read. Try another.'); }
  };
  // a request your own app can send to carry on this conversation from a reply: the reply's ID as
  // previous_response_id and a placeholder for the next message; the reply's model when it is not the
  // setup's own, the setup's ID, the test's headers with placeholders for their values, and the app's
  // own key, named and never filled in
  const copyNext = async (turnIndex: number, rid: string) => {
    const body: Record<string, unknown> = { input: NEXT_MSG, previous_response_id: rid };
    const tm = turnModels[turnIndex] || model;
    if (tm && tm !== defaultModel) body.model = tm;
    body.metadata = { harness_id: r.h.id };
    const hdrs = Object.keys(headerValues).filter((k) => headerValues[k]).map((k) => `  -H "${k}: <value>" \\\n`).join('');
    const text = `curl ${API_BASE}/v1/responses \\\n  -H "Authorization: Bearer $HR_API_KEY" \\\n  -H "Content-Type: application/json" \\\n${hdrs}  -d '${JSON.stringify(body, null, 2).replace(/'/g, "'\\''")}'`;
    try { await navigator.clipboard.writeText(text); toast('Copied'); } catch { toast('Text selected. Press Cmd or Ctrl + C.'); }
  };

  // the composer (leanComposer): the box, attach, the model in its bar, send. A recorded run where this
  // server cannot continue one has a bar in its place: what it is, and Follow up (a task of yours)
  const composer = (ph: string) => (recorded && !offerFork ? (
    <div className="readonly"><span>Recorded task</span>
      {onFollowUp ? <button type="button" className="btn small" onClick={onFollowUp}>Follow up</button> : null}
    </div>
  ) : (
    <AgentComposer value={input} onChange={setInput} onSend={send} onStop={playing ? undefined : () => conv.stop()}
      running={conv.busy} stopping={conv.stopping} sendDisabled={!canSend}
      placeholder={ph} runningPlaceholder="Working on it. Write your next message here."
      ariaLabel={ph.replace(/…$/, '')} inputId="input" inputRef={ta}
      attachments={att ? [{ name: att.name, src: att.dataUri }] : []} onRemoveAttachment={() => setAtt(null)}
      onAttachFiles={(fl) => void pick(fl[0])} accept={ACCEPT} left={pgOpts()}
      labels={{ send: 'Run task' }} />
  ));
  const { mark, motion } = harnessMark(r.h.base);
  const asked = conv.msgs.filter((m) => m.role === 'user').length;
  // what this task made, for the links a reply makes to its own files (TaskThread Md)
  const produced = useMemo(() => conv.msgs.flatMap((m) => (m.role === 'assistant' ? m.files.map((f) => f.filename) : [])), [conv.msgs]);
  const liveSid = sid || conv.liveSessionId || undefined;
  const md = (text: string) => <Md text={text} sid={liveSid} harnessId={r.h.id} produced={produced} />;
  const copyRid = async (id: string) => { try { await navigator.clipboard.writeText(id); toast('Copied'); } catch { toast('Text selected. Press Cmd or Ctrl + C.'); } };
  const copyReply = async (text: string) => {
    try { await navigator.clipboard.writeText(text); toast('Copied'); } catch { toast('Couldn’t copy automatically. Try again.'); }
  };
  /** a reply's one quiet line, after it (agentMeta, am-foot): the model when it is not the setup's own
   *  (every reply's, once the test has run on more than one), how it ended, and its actions */
  const foot = (t: number, m: AsstMsg) => {
    const tm = turnModels[t] || (t >= turnModels.length ? model : '');
    const note = tm && (tm !== defaultModel || mixed) ? tm : '';
    // how long it took: the turn's own clock when this page watched it, else what the record kept. A
    // turn that did not finish says so in its own outcome line above (stopped, incomplete, failed)
    const c = m.clock;
    const ms = c && c.startedAt != null && c.endedAt != null ? c.endedAt - c.startedAt : m.elapsed != null ? m.elapsed * 1000 : null;
    // a recorded run says the time it took when it ran, however fast it is played
    const rec0 = replayed && t === 0 && !!recording;
    const took = rec0 && recording ? recording.durMs : ms;
    const end = m.status === 'done' ? (took != null && took >= 0 ? `Done in ${sec(took)}` : 'Done') : '';
    const rid = turnIds[t] || '';
    const bits: React.ReactNode[] = [];
    if (rec0) bits.push(<span key="rec" className="replay-tag">Recorded</span>);
    if (note) bits.push(<span key="m">{r.baseName} · <span className="mono">{note}</span></span>);
    if (end) bits.push(<span key="e">{end}</span>);
    // its actions, after the words, once it has finished: the reply itself as Markdown (the one most
    // people want, first), its ID, and a request that carries on from it (not on a recorded run,
    // which no server holds)
    const acts: React.ReactNode[] = [];
    const asMd = m.status !== 'running' ? replyMarkdown(m.blocks, m.files.filter((f) => !isInternalOutput(f.filename))) : '';
    if (asMd) {
      acts.push(<button key="md" type="button" className="icon-btn xs" aria-label="Copy reply"
        title="Copy this reply as Markdown" onClick={() => void copyReply(asMd)}>{COPY}</button>);
    }
    if (rid) {
      acts.push(<button key="r" type="button" className="icon-btn xs" aria-label="Copy response ID"
        title="Copy response ID" onClick={() => void copyRid(rid)}>{HASH}</button>);
      if (!rec0 && m.status !== 'running') {
        acts.push(<button key="c" type="button" className="icon-btn xs" aria-label="Copy a request that continues this conversation"
          title="Copy a request that continues from here" onClick={() => void copyNext(t, rid)}>{CODE}</button>);
      }
    }
    return (
      <span className="agent-meta pg-turn-meta">
        {bits.flatMap((b, i) => (i ? [<span key={`s${i}`} aria-hidden="true">·</span>, b] : [b]))}
        {acts.length ? <span className="pg-acts">{acts}</span> : null}
      </span>
    );
  };

  return (
    <div ref={chatRef} className={`agent-chat${started ? ' pg-on' : ''}`}>
      {!started ? (
        <div className="tk-newp">
          <div className="ac-hero">{composer(`Send ${r.h.name} a task to test…`)}</div>
        </div>
      ) : opening && conv.loadFailed ? (
        // the task's record could not be read: said, with Try again; nothing is drawn as if it were empty
        <div className="thread-inner pg-opening">
          <div className="empty-list ld-fail" role="alert">This task could not be read just now.{' '}
            <button type="button" className="link-q inl" onClick={conv.reload}>Try again</button></div>
        </div>
      ) : opening ? (
        <Skel label="Opening the task" className="thread-inner pg-opening"><SkThread /></Skel>
      ) : (
        <AgentConversation mode="pane" running={conv.busy} mark={mark} motion={motion} followKey={asked}
          composer={composer(conv.msgs.length ? 'Follow up…' : `Send ${r.h.name} a task to test…`)}>
          <div className="thread-inner" id="threadInner">
            <AgentTurns msgs={conv.msgs} base={r.h.base} md={md}
              files={(m) => (m.status === 'running' ? null : <FileCards files={m.files || []} active={previewKey} onOpen={(k) => onPreview(filesOf(conv.msgs), k)} zipName={taskTitle || r.h.name} />)}
              actions={foot} />
          </div>
        </AgentConversation>
      )}
    </div>
  );
}

/** Codex runs a -codex model only in a task no other model family has used (the service refuses the
 *  switch in words, measured 2026-09-05: such a model runs without its tools there). */
const codexFamily = (m: string) => (/-codex$/i.test(m.trim()) ? 'codex' : 'gpt');
function codexBlocked(backend: string | null | undefined, seen: string[], m: string): boolean {
  if (backend !== 'codex' || codexFamily(m) !== 'codex') return false;
  return seen.some((x) => x && codexFamily(x) !== 'codex');
}

export interface Slot {
  /** a new key mounts a fresh test */
  key: string;
  /** a past test to continue (its session), or null for a new one */
  resume: string | null;
  /** the setup's recorded first task (start/replay.ts): played back, read only */
  recorded?: RecordedRun | null;
}

export function Playground({ r, onRan, slot, onBorn, onPreview, previewKey = null, onLive, taskTitle, onFollowUp, onReplay }: {
  r: SetupRow; onRan: () => void;
  /** a recorded first task's Follow up: a new task, run live */
  onFollowUp?: () => void;
  /** the recorded first task is playing (true) or has ended (false) */
  onReplay?: (playing: boolean) => void;
  /** the open task's title, as its bar shows it */
  taskTitle?: string;
  /** the task shown: a past one to continue, or a new one */
  slot: Slot;
  /** a new test got its task (the page keeps it in the address and marks it in the list) */
  onBorn: (sid: string) => void;
  /** a produced file was opened: the page shows it beside the conversation */
  onPreview: (files: OpenFile[], key: string) => void;
  previewKey?: string | null;
  /** the bricks the open test's turn is working through now, or null: the page's Agent stack lights them */
  onLive?: (working: string[] | null) => void;
}) {
  const catalog = useModelCatalogRead();   // the server's model list: the picker offers nothing else
  const cat = catalog.value;
  const providers = useModelProviders();
  const oob = oobById(r.h.base);
  // the setup's own model; '' when it has none: a message sent with no model runs on the setup's
  // default, or, in a task that has run, on its last model (the server decides; nothing is guessed here)
  const defaultModel = r.h.defaultModel || '';
  const harnessDefault = oobDefaultModel(oob);
  // the setup's own model (or its default), then every model its base runs that a provider serves now;
  // null until the catalog has landed (before it, every model reads as unknown)
  const models = useMemo<string[] | null>(() => {
    if (!cat) return null;
    const runs = oobModels(oob).filter((m) => modelAvailability(oob?.backend, m) === 'yes');
    const own = r.h.defaultModel ? (modelAvailability(oob?.backend, r.h.defaultModel) !== 'no' ? [r.h.defaultModel] : []) : [''];
    return [...own, ...runs.filter((m) => !own.includes(m))];
  }, [cat, oob, r.h.defaultModel]);
  // a past task goes on with no model named (its last one, server side) until its record says which
  const [model, setModel] = useState(slot.resume ? '' : defaultModel);
  // a new task starts on the setup's own model; a past one on the model it last ran (onSeen)
  const slotKey = useRef(slot.key);
  useEffect(() => {
    if (slotKey.current === slot.key) return;
    slotKey.current = slot.key;
    setModel(slot.resume ? '' : defaultModel);
  }, [slot.key, slot.resume, defaultModel]);
  const [seen, setSeen] = useState<string[]>([]);
  const [started, setStarted] = useState(false);
  const [pop, setPop] = useState<'model' | 'headers' | null>(null);
  const [q, setQ] = useState('');
  const [hv, setHv] = useState<Record<string, string>>({});
  const declared = (r.h.additionalHeaders || []).filter(Boolean);
  const nset = declared.filter((h) => (hv[h] || '').trim()).length;
  const optsRef = useRef<HTMLDivElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);
  const pkRef = useRef<HTMLButtonElement | null>(null);
  const hdRef = useRef<HTMLButtonElement | null>(null);
  const [pos, setPos] = useState<CSSProperties | null>(null);
  useEffect(() => {
    if (!pop) return;
    const down = (e: MouseEvent) => { const t = e.target as Node; if (!optsRef.current?.contains(t) && !popRef.current?.contains(t)) setPop(null); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { const b = pop === 'headers' ? hdRef.current : pkRef.current; setPop(null); b?.focus(); } };
    document.addEventListener('mousedown', down); document.addEventListener('keydown', key);
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key); };
  }, [pop]);
  // the list is fixed to the window (it must not be cut by the conversation's scroll): it sits under
  // its pill, or over it when the window has no room below (the composer at the foot of a task)
  const place = useCallback(() => {
    const b = pop === 'headers' ? hdRef.current : pkRef.current;
    if (!b || !pop) { setPos(null); return; }
    const rc = b.getBoundingClientRect(), vw = window.innerWidth, vh = window.innerHeight;
    const w = Math.min(pop === 'headers' ? 400 : 360, vw - 24), left = Math.min(Math.max(12, rc.left), vw - w - 12);
    const below = vh - rc.bottom - 16, above = rc.top - 16, up = below < 260 && above > below;
    const mh = Math.max(180, Math.min(pop === 'headers' ? 440 : 380, up ? above : below));
    setPos(up ? { left, width: w, maxHeight: mh, top: 'auto', bottom: vh - rc.top + 6 } : { left, width: w, maxHeight: mh, bottom: 'auto', top: rc.bottom + 6 });
  }, [pop]);
  useLayoutEffect(() => { place(); }, [place]);
  useEffect(() => {
    if (!pop) return;
    window.addEventListener('resize', place); window.addEventListener('scroll', place, true);
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); };
  }, [pop, place]);
  // a past test opens on the model it last ran
  const onSeen = useCallback((ms: string[], resumed: boolean) => {
    setSeen(ms);
    setStarted(ms.length > 0);
    const last = [...ms].reverse().find(Boolean);
    if (resumed && last) setModel(last);
  }, []);

  const keyOf = (m: string) => { const c = providers.connectionFor(m); return c ? (providerById(c.provider)?.name || c.provider) : ''; };
  // what the pill and the list call a model; '' is the setup's default, or a past task's own last model
  const nameOf = (m: string) => m || (slot.resume ? 'Same model' : `Setup default${harnessDefault ? ` (${harnessDefault})` : ''}`);
  const cantRun = !!model && modelAvailability(oob?.backend, model) === 'no';
  const shown = (models || []).filter((m) => nameOf(m).toLowerCase().includes(q.trim().toLowerCase()));
  const choose = (m: string) => { if (codexBlocked(oob?.backend, seen, m)) return; setModel(m); setPop(null); setQ(''); pkRef.current?.focus(); };
  const forWhat = started ? 'Model for your next message' : 'Model for this test';
  // the composer's bar holds the model, as in Claude Code (pgOpts in the bar)
  const pgOpts = () => (
    <div className="pg-opts in-bar" ref={optsRef}>
      <button ref={pkRef} type="button" className={`nw-pk${pop === 'model' ? ' on' : ''}`} aria-haspopup="listbox" aria-expanded={pop === 'model'}
        title={cantRun ? `${model} cannot run right now. Choose another model.` : forWhat} aria-label={`${forWhat}: ${nameOf(model)}${cantRun ? ', cannot run right now' : ''}`}
        onClick={() => setPop(pop === 'model' ? null : 'model')}><b className={model ? 'mono' : undefined}>{nameOf(model)}</b>{cantRun ? <small className="warn">can’t run now</small> : null}{CHEV}</button>
      {declared.length
        ? <button ref={hdRef} type="button" className={`nw-pk${pop === 'headers' ? ' on' : ''}`} aria-haspopup="dialog" aria-expanded={pop === 'headers'}
            title="Header values for this test" onClick={() => setPop(pop === 'headers' ? null : 'headers')}><span>Headers</span><b>{nset} of {declared.length}</b>{CHEV}</button>
        : null}
    </div>
  );
  const headersPop = pop === 'headers' && pos ? (
    <div ref={popRef} className="nw-pop pg-pop pl-dd pl-fly pg-hdr pg-hdr-fly" role="dialog" aria-label="Header values for this test" style={pos}>
      <p className="nw-popn">For this test only. Not saved.</p>
      {declared.map((h) => (
        <label key={h} className="pg-hf"><span className="mono">{h}</span>
          <input className="set-in" placeholder="Value" value={hv[h] || ''} autoComplete="off" spellCheck={false} onChange={(e) => setHv({ ...hv, [h]: e.target.value })} />
        </label>
      ))}
      <div className="pg-hdr-f"><button type="button" className="btn small" onClick={() => { setPop(null); hdRef.current?.focus(); }}>Done</button></div>
    </div>
  ) : null;
  const modelPop = pop === 'model' && pos ? (
    <div ref={popRef} className="nw-pop pg-pop pl-dd pl-fly pg-mpop" role="listbox" aria-label={forWhat} style={pos}>
      {models === null && catalog.failed ? (
        <div className="dd-empty" role="alert">The models could not be read just now. <button type="button" className="link-q inl" onClick={catalog.retry}>Try again</button></div>
      ) : models === null ? (
        <Skel label="Reading the models"><div className="pg-msk">{[60, 72, 54, 66].map((w, i) => <SkLine key={i} w={`${w}%`} h={12} style={{ margin: '10px 8px' }} />)}</div></Skel>
      ) : (
        <>
          <div className="dd-s"><input className="dd-q" autoFocus placeholder={`Search ${models.filter(Boolean).length} models on ${r.baseName}`} autoComplete="off" spellCheck={false} aria-label="Search models"
            value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { const f = shown.find((m) => !codexBlocked(oob?.backend, seen, m)); if (e.key === 'Enter' && f) choose(f); }} /></div>
          {shown.length ? shown.map((m) => {
            const no = codexBlocked(oob?.backend, seen, m);
            return (
              <button key={m} type="button" className={`nw-opt dd-o${m === model ? ' sel' : ''}${no ? ' pg-no' : ''}`} role="option" aria-selected={m === model} aria-disabled={no || undefined}
                title={no ? `Codex runs ${m} only in a task no other model has used. Start a new task for it.` : undefined} onClick={() => choose(m)}>
                <span className="chk">{m === model ? CHECK : null}</span><b className={m ? 'mono' : undefined}>{nameOf(m)}</b>
                {no ? <small>new task only</small> : m && m === defaultModel ? <small>default</small> : m && keyOf(m) ? <small>your {keyOf(m)} key</small> : null}
              </button>
            );
          }) : <div className="dd-empty">{models.filter(Boolean).length ? 'No model matches.' : `No model of ${r.baseName} can run right now.`}</div>}
        </>
      )}
    </div>
  ) : null;

  return (
    <>
      <Test key={slot.key} r={r} model={model} defaultModel={defaultModel} headerValues={hv} onRan={onRan}
        onBorn={(sid) => { onBorn(sid); onRan(); }} pgOpts={pgOpts}
        resume={slot.resume} onSeen={onSeen} onPreview={onPreview} previewKey={previewKey} onLive={onLive} taskTitle={taskTitle}
        recording={slot.recorded || null} onFollowUp={onFollowUp} onReplay={onReplay} />
      {modelPop}
      {headersPop}
    </>
  );
}
