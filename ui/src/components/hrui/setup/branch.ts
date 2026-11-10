// Branching a task from one of its replies (Sessions 1.1, issue #477). A reply's Branch action opens a
// new conversation holding the task up to that reply; nothing exists on the server yet, because a
// session can only be branched by a turn (`branch: true` beside previous_response_id, with the new
// message as its input). So the conversation is a draft until its first message: leaving it costs
// nothing and leaves nothing behind, and the first message is the request that makes the branch.
import { harnessFetch } from '@/lib/hfetch';
import type { Msg } from '@/lib/conversation';

/** The capability a server reports when it branches. Optional in the protocol, so the action is
 *  offered only where the server says so. */
export const BRANCH_FLAG = 'session_branching';

/** The server says it branches sessions; false when it does not say so, or could not be read. Read
 *  from the protocol's own discovery document (GET /v1/uhp, Sessions 1.1), where a client must check
 *  it: GET /v1/bases, the console's other discovery read, repeats only some of the capabilities and
 *  does not carry this one (a real server showed no Branch at all when it was read from there). */
export async function sessionBranching(): Promise<boolean> {
  try {
    const r = await harnessFetch('/api/harness/v1/uhp');
    if (!r.ok) return false;
    const d = await r.json() as { capabilities?: Record<string, unknown> } | null;
    return d?.capabilities?.[BRANCH_FLAG] === true;
  } catch { return false; }
}

/** Which of a task's turns a branch can be made from, in order, as its turns say (`branchable`). A
 *  turn that does not say is not offered: the server refuses a branch from any reply it holds no branch
 *  point for (one from before branching, one whose files weren't kept, one that was deleted), and the
 *  turn is where it says which those are. */
export function branchableTurns(turns: { branchable?: boolean }[]): boolean[] {
  return turns.map((t) => t.branchable === true);
}

/** A branch not sent yet: what the new conversation shows, and what its first message branches from. */
export interface BranchDraft {
  /** the task it was branched from, and that task's title */
  from: string;
  title: string;
  /** the reply it goes on from */
  responseId: string;
  /** the conversation up to and including that reply */
  msgs: Msg[];
  /** the model each of those turns ran on, in order (the picker's rules and each reply's line read them) */
  models: string[];
  /** the model the reply ran on, which the new conversation starts on; '' for the setup's default */
  model: string;
}

/** The messages a branch from `reply` starts with, marked imported as the server will mark them. A
 *  question the reply ended on is left out: it stays the original task's to answer, and the server
 *  refuses an answer sent with a branch (Sessions 1.1). */
export function branchMsgs(msgs: Msg[], reply: Msg): Msg[] {
  const at = msgs.indexOf(reply);
  if (at < 0) return [];
  return msgs.slice(0, at + 1).map((m) => {
    if (m.role === 'user') return { ...m, imported: true as const };
    const { inputRequest: _asked, ...rest } = m;
    return { ...rest, imported: true as const };
  });
}

/** How many of a conversation's turns came with it. Every turn from the record has its answer, so
 *  the imported answers count the imported turns; the last of them is where the divider goes. */
export function importedTurnCount(msgs: Msg[]): number {
  return msgs.filter((m) => m.role === 'assistant' && m.imported).length;
}
