'use client';
// The steps every coding-agent sheet is drawn as (docs/uxuidesign/console-79: handSheet's `hx` list;
// Richard's "Set up a starter app" design, 10-19: its step()): Connect your app, Make <kit> yours,
// Start in your codebase and Migrate an existing agent draw the same list. Each step is a brick, empty
// until the steps before it are done, outlined while it is the one at hand ("next"), built once it is
// done; then its number and title. A done step with a summary folds to it, keeping only the line
// under it the sheet asks for (the paste hint under "Copied"); a step with no summary keeps its body.
//
// Step 1 is the same in every sheet (PromptStep): the prompt in its well with Copy prompt, folding to
// "Copied · Copy again". The API key step is start/KeyStep.
import { useEffect, useRef, type ReactNode, type RefObject } from 'react';
import { partIcon } from '../bricks';
import { PasteHint, PromptCopy } from './PromptCopy';

export type StepState = 'empty' | 'next' | 'built';

export function HxStep({ n, state, title, sum, keep, children }: {
  n: number;
  state: StepState;
  title: ReactNode;
  /** what the step says once it is done, in place of its body */
  sum?: ReactNode;
  /** the line kept under a done step's title */
  keep?: ReactNode;
  children?: ReactNode;
}) {
  const folded = state === 'built' && !!sum;
  return (
    <li className={`hx-s ${state}`} aria-current={state === 'next' ? 'step' : undefined}>
      <span className="hx-b" aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon(state, 'backend') }} />
      <div className="hx-c">
        <div className="hx-t"><span className="hx-n">{n}</span><b>{title}</b>{folded ? <span className="hx-sum">{sum}</span> : null}</div>
        {folded ? (keep ? <div className="hx-d hx-keep">{keep}</div> : null)
          : children ? <div className="hx-d">{children}</div> : null}
      </div>
    </li>
  );
}

/** A step folds under the control that was pressed: once `on` turns true and focus fell to the page
 *  with that control, it goes to `to` (the summary's own link), so the keyboard stays in the sheet. */
export function useFocusOnFold(on: boolean, to: RefObject<HTMLElement | null>): void {
  const was = useRef(on);
  useEffect(() => {
    if (on && !was.current) {
      const a = document.activeElement;
      if (!a || a === document.body) to.current?.focus();
    }
    was.current = on;
  }, [on, to]);
}

/** Step 1 of every coding-agent sheet: the prompt, Copy prompt and where to paste it; once copied it
 *  folds to "Copied · Copy again" and keeps the paste hint. A copy the browser refused opens it again,
 *  so the prompt is there to select and copy by hand. A sheet that counts it done with no copy here
 *  (the app is already connected) folds it too: its link then says Copy prompt. */
export function PromptStep({ n = 1, state, text, preId, preRef, copied, failed, onCopy }: {
  n?: number;
  state: StepState;
  text: string;
  preId: string;
  preRef: RefObject<HTMLPreElement | null>;
  copied: boolean;
  failed: boolean;
  onCopy: () => void;
}) {
  const again = useRef<HTMLButtonElement | null>(null);
  useFocusOnFold(copied, again);
  const sum = failed ? null : (
    <>{copied ? 'Copied · ' : null}<button ref={again} type="button" className="link-q inl" onClick={onCopy}>{copied ? 'Copy again' : 'Copy prompt'}</button></>
  );
  return (
    <HxStep n={n} state={state} title="Copy the prompt and send it" sum={sum} keep={<PasteHint />}>
      <PromptCopy text={text} preId={preId} preRef={preRef} copied={copied} failed={failed} onCopy={onCopy} />
    </HxStep>
  );
}
