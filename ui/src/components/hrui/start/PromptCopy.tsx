'use client';
// The copy block of every coding-agent sheet (Richard, 10-18: "直接 copy，不要 open 或者 open with，
// 把它 consistent"): the prompt in a grey well, then one row under it, where to paste it on the left
// and Copy prompt on the right. No sheet opens a coding agent with the prompt: each copies, the same
// way, in the same place. It is the body of step 1 (start/Steps PromptStep).
import type { RefObject } from 'react';
import { CODERS } from './prompts';

const FAILED = 'Couldn’t copy automatically. It’s selected: press Cmd or Ctrl + C.';

/** "Paste the prompt into Claude Code or Codex, in your terminal or the desktop app." */
export function PasteHint({ failed }: { failed?: boolean }) {
  return (
    <span className={`copy-hint lead${failed ? ' warn' : ''}`}>
      <span className="coder-pair" aria-hidden="true">{CODERS.map((c) => <img key={c.name} src={c.logo} alt="" />)}</span>
      <span>{failed ? FAILED : `Paste the prompt into ${CODERS.map((c) => c.name).join(' or ')}, in your terminal or the desktop app.`}</span>
    </span>
  );
}

export function PromptCopy({ text, preId, preRef, copied, failed, onCopy }: {
  text: string;
  preId: string;
  /** the well's text, which the copy selects when the browser will not copy */
  preRef: RefObject<HTMLPreElement | null>;
  copied: boolean;
  failed: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="code-wrap">
      <div className="code"><pre id={preId} ref={preRef}>{text}</pre></div>
      <div className="code-bar">
        <PasteHint failed={failed} />
        <button type="button" className={`btn small ${copied ? 'line' : 'primary'}`} onClick={onCopy}>{copied ? 'Copy again' : 'Copy prompt'}</button>
      </div>
    </div>
  );
}
