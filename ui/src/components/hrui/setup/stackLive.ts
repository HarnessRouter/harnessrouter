// The Agent stack while a task's turn runs on its setup's page (docs/uxuidesign/console-87: runningSet, brickStates,
// the "Running now" line). The design lights the layers a running task uses; here every brick follows
// the turn's own live events, read the way the thread's live line reads them (reifyui's liveState and
// describeTool), so the stack shows which layer is working at this moment. Nothing is timed or
// guessed: a brick is lit only while the event that names it is the turn's current one.
import { describeTool, liveState, turnFromMessage } from 'reifyui/agent-chat';
import type { AsstMsg } from '@/lib/conversation';
import { LAYERS, PARTS, SUBS, type BrickState, type Tower } from '../tower';

// The workspace plugins reach a harness through one server named `plugs`; each harness spells a
// server's tools its own way (mcp__plugs__x, plugs.x, mcp_plugs_x, plugs_x), so the server is a
// segment of the name.
const PLUGS = /(^|[_.:/-])plugs([_.:/-]|$)/i;
const FILE_KINDS = new Set(['read', 'write', 'edit', 'search', 'glob', 'list']);
const SANDBOX_KINDS = new Set(['shell', 'shell_output', 'web_search', 'web_fetch', 'browser', 'tool']);

/** The bricks one tool call works through: a workspace plugin's call is the Plugin brick, the
 *  setup's own MCP server's the Tool brick, a skill the Skill brick, a file tool Files, and the
 *  harness's other tools (a command, a web read) the Sandbox; those last two run in the Environment. */
export function toolLayers(name: string, args: unknown): string[] {
  if (PLUGS.test(name)) return ['plugin'];
  const k = describeTool(name, args).kind;
  if (k === 'mcp') return ['mcp'];
  if (k === 'skill') return ['skill'];
  if (FILE_KINDS.has(k)) return ['b-files', 'env'];
  if (SANDBOX_KINDS.has(k)) return ['b-sandbox', 'env'];
  if (k === 'agent' || k === 'think') return ['model'];
  return [];   // a plan update, a tool lookup: the harness's own bookkeeping
}

/** The bricks a running turn is working through now, from its message (null once it is over).
 *  `stopping`: a Stop was asked for and the turn is being cancelled. */
export function workingNow(m: AsstMsg | null | undefined, stopping = false): string[] | null {
  if (!m || m.status !== 'running') return null;
  const t = turnFromMessage(m, m.clock || null);
  const ls = liveState(t);
  if (!ls) return null;
  // the turn's run: its session, the orchestration that drives it, the harness, and the trace
  // recording each event
  const on = new Set<string>(['b-runtime', 'backend', 'b-sessions', 'b-orch']);
  // until the model has answered with anything (text or a call), it is reading its instructions
  if (!t.items.some((x) => x.kind === 'text' || x.kind === 'tool')) on.add('task');
  if (ls.phase === 'starting' || ls.phase === 'thinking') on.add('model');
  if (ls.phase === 'writing') { on.add('model'); on.add('b-stream'); }
  if (ls.phase === 'tool' && ls.tool) toolLayers(ls.tool.name, ls.tool.args).forEach((k) => on.add(k));
  // a call that just failed (the model is taking the error back), an error event, or a Stop
  const last = t.items[t.items.length - 1];
  if (stopping || t.error || (last && last.kind === 'tool' && last.status === 'failed')) on.add('b-errors');
  return [...on].sort();
}

/** The tower with its running bricks set from the live turn: a brick runs when it is part of the
 *  setup and the turn is working through it now; every other running brick is shown as set up.
 *  Instructions count as set up while a turn runs (the task given is what it follows: the design's
 *  builtMap takes a test in progress as the instructions). */
export function liveTower(t: Tower, working: string[]): Tower {
  const on = new Set(working), st: Record<string, BrickState> = { ...t.st };
  const keys = [...LAYERS.map((L) => L.key as string), ...SUBS.map((x) => x[0]), ...PARTS.map((x) => x[0] as string)];
  keys.forEach((k) => {
    const s = t.st[k] || 'empty';
    const built = s === 'built' || s === 'run' || (k === 'task' && s === 'next');
    st[k] = on.has(k) && built ? 'run' : s === 'run' ? 'built' : s;
  });
  return { ...t, st };
}

/** The "Running now" line: the layers at work, bottom first (the design's runNames). With `detail`
 *  (a live turn, read event by event) it goes on to the parts of HarnessRouter and the optional parts
 *  the current event is using; Sessions and Orchestration run for the whole turn, so the line
 *  names HarnessRouter for them. */
export function runningNames(t: Tower, detail = false): string[] {
  const st = t.st;
  const layers = LAYERS.filter((L) => st[L.key] === 'run').map((L) => L.name as string);
  if (!detail) return layers;
  const always = new Set(['b-sessions', 'b-orch']);
  return [
    ...layers,
    ...SUBS.filter(([k]) => st[k] === 'run' && !always.has(k)).map(([, n]) => n),
    ...PARTS.filter(([k]) => st[k] === 'run').map(([, n]) => n),
  ];
}
