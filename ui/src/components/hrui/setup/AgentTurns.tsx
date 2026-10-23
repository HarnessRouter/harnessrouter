'use client';
// A conversation's turns drawn by reifyui/agent-chat, the way Claude Code draws them: prose in full,
// each run of work folded to one past-tense line that opens to every call (its input, its output),
// the agent's latest plan, and one live line while it works, with the harness's own mark moving.
// Shared by a task's conversation on its setup's page and every view of a task's turns. Content comes from the conversation store's
// messages (lib/conversation); the times come from each live turn's clock, so a turn read from the
// record shows no durations rather than invented ones. A surface can open some calls in a place of
// its own (TurnSteps: the task page opens a browser step in the browser card beside the conversation,
// the way a file card opens its file); every other call unfolds to its input and output.
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { AgentTurnView, turnFromMessage, motionFor, type OpenStep, type Turn, type TurnUser } from 'reifyui/agent-chat';
import { harnessLogoSrc } from '@/components/HarnessLogo';
import type { AsstMsg, Msg, UserMsg } from '@/lib/conversation';
import { limitStopWhy, SETUP_LIMITS } from '@/lib/limit-copy';
// reifyui/styles/agent-chat.css, scoped under #hrui so the redesign's reset does not undo it
import './agent-chat.scoped.css';
import './agent-turns.css';

/** The sentence for an incomplete turn, when the record knows why (the console's own wording). */
export function incompleteWhy(reason?: string, detail?: string): string {
  switch (reason) {
    // a runtime limit: which one, and the field in this setup's Settings that raises it
    case 'max_steps': case 'timeout': return limitStopWhy(reason, SETUP_LIMITS) || '';
    case 'interrupted': return 'Interrupted before it finished. No limit was hit.';
    default: return detail || '';
  }
}

/** The base harness's own mark and the motion chosen for it. */
export function harnessMark(base: string | null | undefined): { mark: ReactNode; motion: string } {
  const src = base ? harnessLogoSrc(base) : '';
  return { mark: src ? <img src={src} alt="" /> : undefined, motion: motionFor(base || '') };
}

/** One answer as the view draws it: its blocks, timed by its live clock. Once the turn has ended
 *  nothing in it is live: a clock whose stream dropped before the end still holds its last thought
 *  open, and that thought would read "Thinking" in motion under a finished answer. It reads done,
 *  with its duration only when both its ends were seen. */
export function viewTurn(asst: AsstMsg | null, user: TurnUser | null): Turn {
  const t = asst ? turnFromMessage(asst, asst.clock || null, user) : turnFromMessage({ status: 'done', blocks: [] }, null, user);
  if (t.status === 'running' || !t.items.some((x) => x.kind === 'thinking' && x.open)) return t;
  return { ...t, items: t.items.map((x) => (x.kind === 'thinking' && x.open ? { ...x, open: false } : x)) };
}

/** The calls a surface opens in its own place, per turn (the turn's number, as pairTurns counts):
 *  `openStep` answers a handler for each call it opens, `activeStep` is the call it shows now. */
export type TurnStepsOf = (turn: number) => { openStep?: OpenStep; activeStep?: string | null } | null;
export const TurnSteps = createContext<TurnStepsOf | null>(null);

type Pair = { user: UserMsg | null; asst: AsstMsg | null; turn: number };

/** Messages as turns: each answer with the message it answers. */
export function pairTurns(msgs: Msg[]): Pair[] {
  const out: Pair[] = [];
  let user: UserMsg | null = null;
  let n = 0;
  for (const m of msgs) {
    if (m.role === 'user') {
      if (user) out.push({ user, asst: null, turn: n++ });
      user = m;
    } else {
      out.push({ user, asst: m as AsstMsg, turn: n++ });
      user = null;
    }
  }
  if (user) out.push({ user, asst: null, turn: n });
  return out;
}

export function AgentTurns({ msgs, base, md, files, meta, actions, userLabel }: {
  msgs: Msg[];
  /** the setup's base harness id (its mark and motion) */
  base: string | null | undefined;
  /** markdown for the agent's prose */
  md: (text: string) => ReactNode;
  /** the files a turn produced, drawn by the surface (it owns their reads) */
  files?: (m: AsstMsg) => ReactNode;
  /** a line above an answer (the harness, the model it ran on) */
  meta?: (turn: number, m: AsstMsg) => ReactNode;
  /** under a finished answer */
  actions?: (turn: number, m: AsstMsg) => ReactNode;
  /** a caption inside the person's bubble: the same for every turn, or each turn's own */
  userLabel?: ReactNode | ((turn: number) => ReactNode);
}) {
  const { mark, motion } = useMemo(() => harnessMark(base), [base]);
  const stepsOf = useContext(TurnSteps);
  const pairs = pairTurns(msgs);
  return (
    <>
      {pairs.map(({ user, asst, turn }) => {
        const u: TurnUser | null = user ? { text: user.text, files: (user.attachments || []).map((a) => ({ name: a.name, src: a.dataUri })) } : null;
        const t = viewTurn(asst, u);
        const steps = asst && stepsOf ? stepsOf(turn) : null;
        return (
          <AgentTurnView key={turn} turn={t} renderMarkdown={md} mark={mark} motion={motion}
            openStep={steps?.openStep} activeStep={steps?.activeStep ?? null}
            userExtra={typeof userLabel === 'function' ? userLabel(turn) : userLabel}
            meta={asst && meta ? meta(turn, asst) : undefined}
            renderFiles={asst && files ? () => files(asst) : undefined}
            actions={asst && actions ? actions(turn, asst) : undefined}
            describeIncomplete={(i) => incompleteWhy(i.reason, i.detail)} />
        );
      })}
    </>
  );
}
