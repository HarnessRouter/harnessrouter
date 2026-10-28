'use client';
// A new setup's page before the setup exists (/studio/new?b=<key>; start/build.ts): New setup's sheet
// has closed and the console is on the setup's page at once (Richard, 2026-10-19), in the setup page's
// own frame (docs/uxuidesign/console-91: agentHead, tasksBody, newPane, the Agent stack). Its first
// task's conversation says what is happening, honestly: the step the server's build reports (reading
// what it should do, writing its instructions) with the time it has taken, then the save card at the
// top as the setup is saved. The
// moment the setup has its id, its own page takes over (the same frame, the same card), and the rest
// of the save and the first test go on there. Nothing is drawn that is not known: the name is "New
// setup" and the picks say Auto until the composer has answered.
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { AgentComposer, AgentConversation, WorkingIndicator } from 'reifyui/agent-chat';
import type { CustomHarness } from '@/lib/harness';
import { harnessLogoSrc } from '@/components/HarnessLogo';
import { rowOf } from '../setups';
import { BACK_IC, SETTINGS_IC, StackPanel, TASKS_IC, useSideOff } from '../setup/parts';
import { NewTaskHead } from '../setup/TaskDetail';
import { harnessMark } from '../setup/AgentTurns';
import { NewSetup } from '../NewSetup';
import { Assembly } from './Assembly';
import { resumeBuild, useBuild, type Build } from './build';
import type { BuildStep } from './compose';
import { openNewSetup } from './open';
// the chat's live line (reifyui/agent-chat), scoped under #hrui as a setup's tasks draw it
import '../setup/agent-chat.scoped.css';

/** The live line for each step of the server's build, as it reports it */
const STEP_LINE: Record<BuildStep, string> = {
  reading: 'Reading what it should do',
  writing: 'Writing its instructions',
  saving: 'Saving your setup',
};

const PLUS = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>;

/** The setup as far as it is known, for the Agent stack: its names (what the person chose, then what
 *  the composer gave) on the zones, and a tower with nothing on it yet. Nothing is saved before the
 *  setup exists: its bricks land on the setup's own page as each save answers (start/buildStack). */
function draftRow(b: Build) {
  const cfg = b.asm?.cfg;
  const empty = { id: '', name: '', base: '', baseLabel: '', defaultModel: '', systemPrompt: '', mcpServers: [], skills: [], createdAt: b.at } as unknown as CustomHarness;
  const row = rowOf(empty, '', [], false);
  return { ...row, baseName: cfg?.baseName || b.pick.baseName, h: { ...row.h, name: cfg?.name || 'New setup', defaultModel: cfg?.model || b.pick.model } };
}

export function BuildPage() {
  const router = useRouter();
  const key = useSearchParams().get('b');
  const b = useBuild(key);
  const [sideOff, toggleSide] = useSideOff();
  const [retry, setRetry] = useState(false);
  // this tab keeps nothing for this address (an old link, another tab's): said here, never sent elsewhere
  const [none, setNone] = useState(false);
  // Try again started another: its own page, with no sheet over it
  useEffect(() => { setRetry(false); setNone(false); }, [key]);
  // the work starts here, on the page that shows it, never in the page Save was pressed on (a call
  // left there is cut off when that navigation turns into a page load). When this page has no memory
  // of it (the page loaded in the middle of it: a new console version turned the navigation into a
  // page load, a reload, a stale chunk reloading it), the tab's kept work is picked up where it
  // stopped: a compose that never answered is asked again, a create already sent found rather than
  // sent again
  useEffect(() => { if (!resumeBuild(key)) setNone(true); }, [key]);
  // the setup exists: its own page goes on with the save and the first request, and nowhere else
  useEffect(() => { if (b?.id) openNewSetup(router, { id: b.id }); }, [b?.id, router]);
  if (!b) {
    return none ? (
      <div className="scroll"><div className="list-wrap">
        <p className="sub">Nothing is being set up here. <button type="button" className="link-q inl" onClick={() => setRetry(true)}>Set up an agent harness</button></p>
        {retry ? <NewSetup onClose={() => setRetry(false)} /> : null}
      </div></div>
    ) : null;
  }

  const cfg = b.asm?.cfg || null;
  const hn = cfg?.baseName || b.pick.baseName, md = cfg?.model || b.pick.model;
  const logo = cfg ? harnessLogoSrc(cfg.base) : '';
  const { mark, motion } = harnessMark(cfg?.base || '');
  const now = b.phase === 'composing' ? <><b>Setting up</b> · your harness</> : b.phase === 'saving' ? <><b>Saving</b> · your setup</> : null;
  return (
    <div className="tk-page">
      {/* the setup page's own bar (setup/parts AgentHead): Tasks · Settings at its right end with their icons, the same
          layout while it builds, never its own. The setup's actions join it once the setup exists, before the tabs */}
      <header className="ag-bar ag-rt">
        <div className="ag-lft">
          <Link className="ag-back" href="/studio" aria-label="Back to Harness Studio" title="Harness Studio">{BACK_IC}</Link>
          <div className="ag-ident">
            <div className="ag-l1"><h1 className="ag-name" title={cfg?.name || 'New setup'}>{cfg?.name || 'New setup'}</h1></div>
            <div className="ag-l2">
              {logo ? <img className="h-logo" src={logo} alt="" /> : null}<span className="ag-h">{hn || 'Auto'}</span>
              <span className="sep" aria-hidden="true">·</span><span className={md ? 'mono ag-m' : 'ag-m'}>{md || 'Auto'}</span>
            </div>
          </div>
        </div>
        {/* Settings opens once the setup exists: until then Tasks is the one tab in the Tab order and the arrows have nowhere to go */}
        <div className="tabs inline ag-tabs" role="tablist">
          <button type="button" role="tab" aria-selected tabIndex={0} className="on">{TASKS_IC}Tasks</button>
          <button type="button" role="tab" aria-selected={false} tabIndex={-1} disabled>{SETTINGS_IC}Settings</button>
        </div>
      </header>
      <div className="tk-split has-side show-d">
        <div className="tk-l">
          <div className="tk-bar"><button type="button" className="btn tk-newb on" disabled>{PLUS}New task</button><span className="grow" /></div>
          {/* as the setup's own page draws it before its first task, so the hand-off changes nothing */}
          <div className="tk-list"><div className="tk-empty">No tasks yet.</div></div>
        </div>
        <div className="tk-d">
          <NewTaskHead onBack={() => router.push('/studio')} />
          <div className="convo">
            <div className="agent-chat pg-on">
              {/* the same conversation the setup's page opens on (its first task, the box under it), so
                  the hand-off to it draws no new frame: the card's bricks land there, once */}
              <AgentConversation mode="pane" running={false} mark={mark} motion={motion}
                composer={b.phase === 'failed' ? null : (
                  <AgentComposer value={cfg?.exampleTask || ''} onChange={() => undefined} onSend={() => undefined} sendDisabled disabled
                    placeholder={`Send ${cfg?.name || 'it'} a task to test…`} ariaLabel={`Send ${cfg?.name || 'it'} a task to test`} labels={{ send: 'Run task' }} />
                )}>
                <div className="thread-inner" id="threadInner">
                  {b.phase === 'failed' ? (
                    <div className="bd-fail" role="alert">
                      <span>{b.error}</span>
                      <button type="button" className="btn small primary" onClick={() => setRetry(true)}>Try again</button>
                    </div>
                  ) : b.asm ? <Assembly s={b.id ? { ...b.asm, savedAt: null, plugins: {} } : b.asm} /> : (
                    <div className="bd-line"><WorkingIndicator start={b.at} label={b.step ? STEP_LINE[b.step] : 'Setting up your harness'} /></div>
                  )}
                </div>
              </AgentConversation>
            </div>
          </div>
        </div>
        <StackPanel r={draftRow(b)} off={sideOff} onToggle={toggleSide} now={now} />
      </div>
      {retry ? <NewSetup pre={b.demo != null ? { demo: b.demo } : { job: b.job }} onClose={() => setRetry(false)} /> : null}
    </div>
  );
}
