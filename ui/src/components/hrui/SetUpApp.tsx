'use client';
// "Connect your app" (the "Set up a starter app" design, 10-19: `hand-sheet use-sheet`; before it
// docs/uxuidesign/console-79 renderSheet0 and starterBody): the sheet a setup's "Connect your app"
// opens. Two steps, drawn as every coding-agent sheet draws them (start/Steps): copy the prompt and
// send it to your coding agent, and create an API key (start/KeyStep) for the app's backend.
//
// A setup launched from one of the kits whose app is in the starter-kit repository gets "Make <kit>
// yours", the repository's own steps for that app (start/prompts starterPrompt); any other setup gets
// "Connect your app": the coding agent adds the setup to the person's own app (promptText). Both name
// this setup. Nothing points a coding agent at a folder that does not exist.
//
// The sheet claims nothing it cannot read: the gateway's task cards do not say whether a task came
// from an app or from here, so it never says the app is connected. The app's tasks show in the
// setup's task list like every other task.
import { useRef, useState } from 'react';
import { Sheet } from './Sheet';
import type { SetupRow } from './setups';
import { useCopyConfirm } from './start/copy';
import { useWsKeys } from './start/keys';
import { KEY_BASE, KeyStep, keySlug, type MadeKey } from './start/KeyStep';
import { promptText, starterFolder, starterPrompt, type SetupRef } from './start/prompts';
import { PromptStep, type StepState } from './start/Steps';

const X = <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>;
const CHECK = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} aria-hidden="true"><path d="M5 12l5 5L20 7" /></svg>;

export function SetUpApp({ r, onClose, kit, kitTitle }: {
  r: SetupRow; onClose: () => void;
  /** the kit this setup runs, when the caller knows it (a kit's own page): its app is the starter */
  kit?: string;
  /** the kit's own name, for the starter prompt (else the setup's) */
  kitTitle?: string;
}) {
  const folder = starterFolder(kit);
  const starter = !!folder;
  const a: SetupRef = { id: r.h.id, name: r.h.name, harness: r.baseName, model: r.h.defaultModel || '', instr: (r.h.systemPrompt || '').trim() };
  const k = useWsKeys();
  const src = useRef<HTMLPreElement | null>(null);
  const keyEntry = useRef<HTMLElement | null>(null);
  const { copy, failed } = useCopyConfirm();
  // the prompt was copied in this sheet
  const [copied, setCopied] = useState(false);
  // the key made in this sheet, once copied (each time the sheet opens its step starts over)
  const [key, setKey] = useState<MadeKey | null>(null);
  const text = starter ? starterPrompt(a, folder, kitTitle || r.h.name) : promptText(a);
  const runs = r.baseName || 'its agent harness';

  const onCopy = () => copy(text, src, 'Copied. Paste it into your coding agent.', () => setCopied(true));
  const s1: StepState = copied ? 'built' : 'next';
  const done = copied && !!key;

  return (
    // the key step takes focus when it is the step at hand, as in the guides; otherwise the sheet
    // itself, so a phone keeps its keyboard down
    <Sheet onClose={onClose} labelledBy="sh" className="hand-sheet use-sheet" initialFocus={copied ? keyEntry : 'dialog'}>
      <div className="sheet-top">
        <div>
          <h3 id="sh">{starter ? `Make ${kitTitle || r.h.name} yours` : 'Connect your app'}</h3>
          <p className="sub">{starter
            ? `Your coding agent takes the kit’s app from GitHub and changes it. This instance keeps running ${runs} behind it.`
            : `Your coding agent adds ${r.h.name} to your app. This instance runs ${runs} behind it, and every task your app sends shows in its task list.`}</p>
        </div>
        <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>{X}</button>
      </div>
      <div className="hand">
        <ol className="hx">
          <PromptStep state={s1} text={text} preId="copySrc" preRef={src} copied={copied} failed={failed} onCopy={onCopy} />
          <KeyStep n={2} k={k} surface={starter ? 'set_up_kit' : 'set_up_app'} base={keySlug(r.h.name) || KEY_BASE}
            state={s1 === 'built' ? 'next' : 'empty'} onKey={setKey} entry={keyEntry} />
        </ol>
        <div className="hand-foot">
          {done ? <span className="grow ok-t">{CHECK}Ready for your coding agent</span> : <span className="grow" />}
          <button type="button" className="link-q" onClick={onClose}>{done ? 'Done' : 'Close'}</button>
        </div>
      </div>
    </Sheet>
  );
}
