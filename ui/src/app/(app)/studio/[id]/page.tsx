'use client';
// One setup (docs/uxuidesign/console-91, view `agent`: agentView, agentHead, tasksBody, newPane,
// taskPane, setSide, sideTog). One bar on top (back, name, Harness ID, Tasks · Settings, Set up the
// app); the rest of the window is work, every column starting with a 56 px bar on one hairline.
// Tasks: the task list, the open task (or New task), the Agent stack. Settings: the layers, the open
// layer, the Agent stack with that layer's brick lit. A test is a task: New task starts one, and every
// task of the setup takes follow-ups.
//
// The page opens on the newest task (a link to a task opens that one, and a setup just saved opens on
// New task, its first test's request waiting in the box: start/build.ts; a setup with none opens on New
// task, or on its recorded first task when it was saved from a demo's recorded run, start/replay.ts,
// drawn whole; a recording that could not be read is said, with Try again, never swapped for a live
// task). The open task is always one the list shows: filtering to Failed opens a failed one. On a
// phone the list and the open task take turns, with a back between; a wider window narrowed to a
// phone's width keeps the task it had open. The address carries the tab
// (?tab=settings), Settings' open layer (?layer=), Capabilities' tab (?cap=) and a task opened by its
// link or sent from here (?test=); an older link to the Tasks tab (?tab=tasks&task=) opens that task
// here.
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { useSetup } from '@/components/hrui/setups';
import type { TraceCard } from '@/lib/revamp-data';
import { AgentHead, StackPanel, useMedia, useSideOff, type SetupTab } from '@/components/hrui/setup/parts';
import { Playground, type Slot } from '@/components/hrui/setup/Playground';
import { SetupSettings } from '@/components/hrui/setup/SetupSettings';
import { hasSettingsDraft, layerOf, useBrickNav, type CapTab, type LayerKey } from '@/components/hrui/setup/settingsModel';
import { SetUpApp } from '@/components/hrui/SetUpApp';
import { Skel, SkLine, SkRows, SkThread } from '@/components/hrui/Skel';
import { filterTasks, NO_FILTER, TaskList, useLinkedTask, useTaskList, type TaskFilter } from '@/components/hrui/setup/TaskRail';
import { NewTaskHead, RecordedHead, TaskHead } from '@/components/hrui/setup/TaskDetail';
import { FilesPanel, type OpenFile } from '@/components/hrui/setup/TurnFiles';
import { PreviewGrip, usePreviewWidth } from '@/components/hrui/setup/PreviewGrip';
import { BrowserControl, BrowserSlot, browserStepsOf, stepOf, useTaskBrowser } from '@/components/hrui/setup/BrowserSlot';
import { TurnSteps, type TurnStepsOf } from '@/components/hrui/setup/AgentTurns';
import { getPaneState, setPaneState, useConvState } from '@/lib/conversation';
import { takeFirstTest, type FirstTest } from '@/components/hrui/start/check';
import { useBuildOf } from '@/components/hrui/start/build';
import { seededSetup } from '@/components/hrui/start/seed';
import { useBuildStack } from '@/components/hrui/start/buildStack';
import { useRecordedRunState } from '@/components/hrui/start/replay';
import { toast } from '@/components/hrui/toast';

const enc = encodeURIComponent;
// at and below this width the list and the open task take turns (hrui.css: the 860 px rules)
const PHONE_MAX = 860;

export default function SetupPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const rawTab = params.get('tab');
  const tab: SetupTab = rawTab === 'settings' ? 'settings' : 'tasks';
  const { row, cards, missing, failed, reload } = useSetup(id);
  // the demo run this setup was saved from, named on its own record (start/replay.ts): its first task,
  // always the list's oldest row (undefined while the recordings are read; a read that failed is said
  // below, never taken for "none")
  const rec = useRecordedRunState(row ? row.h.source : undefined);
  const recRun = rec.run;
  // the old Tasks tab's address (a task's link) and the old Playground's open here
  const linkTask = rawTab === 'tasks' ? params.get('task') : null;
  useEffect(() => {
    if (rawTab === 'tasks' || rawTab === 'playground') router.replace(`/studio/${enc(id)}${linkTask ? `?test=${enc(linkTask)}` : ''}`, { scroll: false });
  }, [rawTab, linkTask, router, id]);

  // the first test New setup handed this setup: the page opens on New task, its request in the box
  const [first] = useState<FirstTest | null>(() => takeFirstTest(id));
  // the task shown: one continued or shown (from the list, or ?test= in the address), or a new one;
  // null until the list says which (the newest)
  const [slot, setSlot] = useState<Slot | null>(() => {
    const t = params.get('test') || linkTask;
    if (t) return { key: t, resume: t };
    return first ? { key: 'n0', resume: null, first } : null;
  });
  const [testSid, setTestSid] = useState<string | null>(() => params.get('test') || linkTask);
  // on a phone: the open task shows instead of the list (picked from it, New task, or a link)
  const [picked, setPicked] = useState(() => !!(params.get('test') || linkTask || first));
  // a wide window shows the open task beside the list whether or not it was picked from it (the newest
  // one, opened by itself; the one Settings went back to), so a window narrowed into the phone layout
  // keeps that task instead of switching to the list. A window already that narrow as the page opens
  // is a phone's, and starts on the list as before
  const slotOpen = !!slot;
  useEffect(() => {
    if (!slotOpen) return;
    const mq = window.matchMedia(`(max-width: ${PHONE_MAX}px)`);
    const narrowed = () => { if (mq.matches) setPicked(true); };
    mq.addEventListener('change', narrowed);
    return () => mq.removeEventListener('change', narrowed);
  }, [slotOpen]);
  // when the task shown was opened: a new test's own entry in the list is one sent after it
  const slotAt = useRef(0);
  useEffect(() => { slotAt.current = Date.now(); }, [slot?.key]);
  // the tasks started on this page, continued here before their card is read
  const mine = useRef(new Set<string>());
  // a test was sent: the task list reads again (and shows the sent task at once)
  const [nudge, setNudge] = useState(0);
  // a setup this tab has just made (start/seed.ts) opens with its record and an empty list in hand
  const [fresh] = useState(() => !!seededSetup(id));
  const list = useTaskList(id, cards, nudge, { fresh });
  const [f, setF] = useState<TaskFilter>(NO_FILTER);
  const { shown } = useMemo(() => filterTasks(list, f), [list, f]);
  // a produced file open beside the conversation: every file of the task, and the one shown; docked
  // in the stack's column on a wide window, a drawer over the page below 1280 px
  const [preview, setPreview] = useState<{ files: OpenFile[]; key: string } | null>(null);
  const narrow = useMedia('(max-width: 1279px)');
  // the open task's browser (setup/BrowserSlot): the live card in the preview's place, popped when a
  // browser opens, opened from a browser step or the bar's Browser control. The place shows what was
  // opened last: a file takes it from the browser, a browser opening takes it from a file
  const tb = useTaskBrowser(id, testSid, () => setPreview(null));
  const browserShown = tb.pane.open && !preview;
  useEffect(() => { if (preview && getPaneState(id).open) setPaneState(id, { open: false, mode: 'docked' }); }, [preview, id]);
  const taskMsgs = useConvState(testSid || '').msgs;
  // docked, the preview's width is the viewer's to drag (PreviewGrip), measured against the split
  const splitRef = useRef<HTMLDivElement | null>(null);
  const pv = usePreviewWidth(splitRef, (!!preview || browserShown) && !narrow);
  const [sideOff, toggleSide] = useSideOff();

  const pgHref = (sid: string | null) => `/studio/${enc(id)}${sid ? `?test=${enc(sid)}` : ''}`;
  const openTest = (sid: string, card?: TraceCard | null) => {
    setPreview(null); setPicked(true);
    if (card) list.add(card);
    if (sid === testSid && slot) return;
    setSlot({ key: sid, resume: sid }); setTestSid(sid); router.replace(pgHref(sid), { scroll: false });
  };
  const newTest = () => {
    setPreview(null); setPicked(true);
    setSlot({ key: `n${Date.now()}`, resume: null }); setTestSid(null);
    router.replace(pgHref(null), { scroll: false });
    requestAnimationFrame(() => document.getElementById('input')?.focus());
  };
  // a new test's task, once it has one: kept in the address (a reload continues it), marked in the list
  const bornTest = (sid: string) => { mine.current.add(sid); setTestSid(sid); router.replace(pgHref(sid), { scroll: false }); };
  const onTab = (t: SetupTab) => {
    setPicked(false);
    router.replace(t === 'tasks' ? pgHref(testSid) : `/studio/${enc(id)}?tab=${t}`, { scroll: false });
  };
  // a link to a task (back and forward, the Tasks tab's old address) opens it, the page already being open
  const urlTest = params.get('test');
  useEffect(() => {
    if (tab !== 'tasks' || !urlTest || urlTest === testSid) return;
    setSlot({ key: urlTest, resume: urlTest }); setTestSid(urlTest); setPicked(true);
  // follows the address only; the page's own writes set testSid first
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, urlTest]);
  // no task asked for: once the list is read, the newest one it shows (its recorded first task when it
  // has no other, once that is read; New task when it has none; a list that could not be read is not
  // one with none)
  useEffect(() => {
    if (slot || !list.ready || !row) return;
    const top = shown[0];
    if (top) { setSlot({ key: top.session_id, resume: top.session_id }); setTestSid(top.session_id); return; }
    if (list.all.length || list.failed || recRun === undefined) return;
    setSlot(recRun ? { key: 'rec', resume: null, recorded: recRun } : { key: 'n0', resume: null });
  }, [slot, list.ready, list.failed, list.all.length, shown, row, recRun]);
  // the open task is always one the list shows: a filter that leaves it out opens its first task
  const fRef = useRef(f);
  useEffect(() => {
    if (fRef.current === f) return;
    fRef.current = f;
    if (!slot?.resume || !testSid || shown.some((c) => c.session_id === testSid)) return;
    setPreview(null);
    const top = shown[0];
    if (top) { setSlot({ key: top.session_id, resume: top.session_id }); setTestSid(top.session_id); router.replace(pgHref(top.session_id), { scroll: false }); }
    else { setSlot(null); setTestSid(null); router.replace(pgHref(null), { scroll: false }); }
  // when the filter changes only
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f]);
  // a task opened by its link that the list has not read (older than its pages): its own card, once;
  // a task of another setup, or one that is gone, lets go of the address; a read that failed says so
  // in the task's place, with Try again
  const linked = useLinkedTask(id, testSid, list, !!testSid && mine.current.has(testSid), () => {
    toast('That task is not in this setup.');
    newTest();
  });
  // Set up the app: the design's sheet, over whichever tab is open
  const [app, setApp] = useState(false);
  const onSetUpApp = () => setApp(true);
  // Settings' open layer is in the address too (?layer=), so a brick of the Agent stack opens it
  const layer = params.get('layer');
  const cap = params.get('cap');
  const onLayer = (k: LayerKey, c?: CapTab) => { setPicked(false); router.replace(`/studio/${enc(id)}?tab=settings&layer=${k}${c ? `&cap=${c}` : ''}`, { scroll: false }); };
  // the header's dot: edits in Settings not saved yet (they are kept while you look at another tab)
  const [dirty, setDirty] = useState(() => hasSettingsDraft(id));
  // the bricks the open test's running turn is working through now (null when none runs)
  const [working, setWorking] = useState<string[] | null>(null);
  // a setup just made here is still being saved (start/build.ts): the Agent stack follows its answers,
  // and the record is read again as the save ends
  const build = useBuildOf(id);
  const bstack = useBuildStack(row, build);
  const buildDone = build?.phase === 'done';
  useEffect(() => { if (buildDone) reload(); }, [buildDone, reload]);
  // the first request its save handed over, for an unchanged demo: the recorded run that plays when it is
  // sent (the setup's own, from its record; else its build's), waiting in the box until then
  const handed = !!slot && !slot.resume && !!slot.first?.setup;
  const handedRec = handed ? recRun || (buildDone ? build?.recording : null) || null : null;
  // the recorded first task while it plays: running, as a live run is, until it ends; once it has
  // begun, the handed request is that recorded task in the list
  const [replaying, setReplaying] = useState(false);
  const [played, setPlayed] = useState(false);
  // the recorded first task: the setup's own (from its record), or the one its save handed over once
  // it is sent; not listed while that request still waits in the box (the list shows New task)
  const recShown = handedRec && !played ? null : recRun || handedRec;
  // open while it is the task shown (opened from its row, or the handed request played)
  const recOn = (!!slot?.recorded || (!!handedRec && played)) && !testSid;
  const recRunning = recOn && replaying;
  const openRecorded = () => {
    if (!recShown || recOn) return;
    setPreview(null); setPicked(true);
    setSlot({ key: `rec${Date.now()}`, resume: null, recorded: recShown }); setTestSid(null); router.replace(pgHref(null), { scroll: false });
  };
  // when the setup was made (its record's createdAt, seconds or ms): the recorded row's time
  const madeAt = row ? (row.h.createdAt > 0 && row.h.createdAt < 1e12 ? row.h.createdAt * 1000 : row.h.createdAt) : 0;
  useBrickNav({ onLayer, onSetUpApp });

  if (failed && !row) {
    return (
      <div className="scroll"><div className="list-wrap">
        <p className="sub" role="alert">This setup could not be loaded just now. <button type="button" className="link-q inl" onClick={reload}>Try again</button></p>
      </div></div>
    );
  }
  if (missing) {
    return (
      <div className="scroll"><div className="list-wrap">
        <p className="sub">This setup is not in this workspace. <a className="link-q inl" href="/studio">Back to Harness Studio</a></p>
      </div></div>
    );
  }
  if (!row) {
    return (
      <div className="tk-page">
        <Skel label="Loading the setup" className="hrui-skel-contents">
          <header className="ag-bar" aria-hidden="true">
            <div className="ag-lft"><SkLine w={32} h={32} r={16} /><div style={{ display: 'grid', gap: 6 }}><SkLine w={180} h={20} /><SkLine w={240} h={10} /></div></div>
          </header>
        </Skel>
        <div className="tk-split" aria-hidden="true">
          <div className="tk-l"><div className="tk-bar"><SkLine w={112} h={32} r={16} /></div><div className="tk-list"><SkRows n={6} lead={false} /></div></div>
          <div className="tk-d"><div className="task-head tp-head"><div className="th-row"><SkLine w="40%" h={14} /></div></div><div className="thread"><SkThread /></div></div>
        </div>
      </div>
    );
  }
  const appSheet = app ? <SetUpApp r={row} onClose={() => { setApp(false); reload(); }} /> : null;
  const head = <AgentHead r={row} tab={tab} onTab={onTab} onSetUpApp={onSetUpApp} dirty={dirty} />;
  const stack = (focus?: LayerKey) => (
    <StackPanel r={bstack.r || row} live={tab === 'tasks' ? working : null} off={sideOff} onToggle={toggleSide} focus={focus}
      now={bstack.now} drops={bstack.drops} />
  );

  if (tab === 'settings') {
    return (
      <div className="tk-page">
        {head}
        <div className="set-split">
          <SetupSettings key={id} r={row} onSaved={reload} layer={layer} cap={cap} onLayer={onLayer} onDirty={setDirty}
            onNewTask={() => newTest()} />
          {stack(layerOf(layer))}
        </div>
        {appSheet}
      </div>
    );
  }

  // the open task's card: the list's, else (a test just sent, not listed yet) what was sent, from the
  // moment it was sent (before the task has its session, the new test's own entry)
  const openCard = testSid ? list.byId.get(testSid) || null : null;
  const sent = testSid ? (!openCard ? list.pending.find((p) => p.sid === testSid) : undefined)
    : slot && !slot.resume ? list.pending.find((p) => !p.sid && p.at >= slotAt.current) : undefined;
  const barCard: TraceCard | null = openCard
    || (sent ? { session_id: testSid || '', title: sent.title, status: 'running', finished_at: sent.at / 1000 } : null);
  const isNew = !!slot && !slot.resume && !barCard;
  // the task opened by its link could not be read: it says so in the task's place, and nothing else opens
  const linkFailed = linked.failed && !openCard;
  const gone = (sid: string) => {
    list.drop(sid);
    reload();
    if (sid !== testSid) return;
    const next = shown.find((c) => c.session_id !== sid);
    if (next) openTest(next.session_id, next); else newTest();
  };
  const docked = (!!preview || browserShown) && !narrow;
  // a browser step in the conversation opens the browser card, as a file card opens its file
  const turnSteps: TurnStepsOf = (turn) => ({
    openStep: (item, d) => (d.kind === 'browser' ? () => { setPreview(null); tb.show(stepOf(turn, item, d)); } : null),
    activeStep: browserShown && tb.step && tb.step.turn === turn ? tb.step.id : null,
  });
  // the bar's Browser control: the live browser, else the last step a closed one took, else its empty state
  const hasBrowser = !!row.binding?.plugs?.includes('browser');
  const toggleBrowser = () => {
    if (browserShown) { tb.close(); return; }
    setPreview(null);
    const past = tb.live?.open ? [] : browserStepsOf(taskMsgs);
    tb.show(past.length ? past[past.length - 1] : null);
  };
  return (
    <TurnSteps.Provider value={turnSteps}>
    {/* the preview's width is the page's (--pv-w), so the bar's tabs follow it as it is dragged */}
    <div className="tk-page" style={docked ? ({ '--pv-w': `${pv.width}px` } as CSSProperties) : undefined}>
      {head}
      <div ref={splitRef} className={`tk-split${docked ? ' previewing' : ' has-side'}${picked ? ' show-d' : ''}`}>
        <TaskList setupName={row.h.name} list={list} f={f} setF={setF} current={testSid} isNew={isNew && !recOn} newOpen={!!slot && !slot.resume && !recOn}
          recorded={recShown ? { title: recShown.request, at: madeAt, on: recOn, running: recRunning, onOpen: openRecorded } : null}
          recordedRetry={rec.failed ? rec.retry : undefined}
          onOpen={openTest} onNew={() => newTest()} onGone={gone} />
        <div className="tk-d">
          {!slot ? (
            list.ready ? (list.failed && !list.all.length ? (
              <div className="tk-none" role="alert">The tasks could not be read just now.{' '}
                <button type="button" className="link-q inl" onClick={list.refresh}>Try again</button></div>
            ) : rec.failed ? (
              <div className="tk-none" role="alert">This setup’s recorded first task could not be read just now.{' '}
                <button type="button" className="link-q inl" onClick={rec.retry}>Try again</button></div>
            ) : (
              <div className="tk-none"><b>No tasks match.</b></div>
            )) : (
              <Skel label="Opening the task"><div className="thread"><SkThread /></div></Skel>
            )
          ) : (
            <>
              {barCard ? (
                <TaskHead card={barCard}
                  browser={hasBrowser ? <BrowserControl shown={browserShown} live={tb.live} onToggle={toggleBrowser} /> : undefined}
                  onBack={() => setPicked(false)}
                  onStopped={() => { setTimeout(() => { list.refresh(); reload(); }, 1500); }} />
              ) : recOn && recShown ? (
                <RecordedHead title={recShown.request} running={recRunning} onBack={() => setPicked(false)} />
              ) : <NewTaskHead onBack={() => setPicked(false)} />}
              {linkFailed ? (
                <div className="tk-none" role="alert">This task could not be read just now.{' '}
                  <button type="button" className="link-q inl" onClick={linked.retry}>Try again</button></div>
              ) : null}
              <div className="convo" hidden={linkFailed}>
                <Playground r={row} onRan={() => { setNudge((n) => n + 1); reload(); }}
                  onPreview={(files, key) => setPreview({ files, key })} previewKey={preview?.key || null}
                  slot={slot} onBorn={bornTest} onLive={setWorking} onFollowUp={() => newTest()} handedRec={handedRec}
                  onReplay={(on) => { setReplaying(on); if (on) setPlayed(true); }}
                  taskTitle={barCard?.title?.trim() || undefined} />
              </div>
            </>
          )}
        </div>
        {docked && preview ? (
          // a file open takes the stack's column, as the original artifact view did, with a handle on
          // its edge to give it more room or less
          <>
            <PreviewGrip pv={pv} />
            <aside className="tk-preview" aria-label="File preview">
              <FilesPanel files={preview.files} active={preview.key} onSelect={(key) => setPreview((p) => (p ? { ...p, key } : p))} onClose={() => setPreview(null)} overlay={false} />
            </aside>
          </>
        ) : docked && browserShown ? (
          // the task's browser takes the same column, with the same handle
          <>
            <PreviewGrip pv={pv} />
            <BrowserSlot harnessId={id} sid={testSid} tb={tb} overlay={false} />
          </>
        ) : stack()}
      </div>
      {preview && narrow ? (
        <FilesPanel files={preview.files} active={preview.key} onSelect={(key) => setPreview((p) => (p ? { ...p, key } : p))} onClose={() => setPreview(null)} overlay />
      ) : null}
      {browserShown && narrow ? <BrowserSlot harnessId={id} sid={testSid} tb={tb} overlay /> : null}
      {appSheet}
    </div>
    </TurnSteps.Provider>
  );
}
