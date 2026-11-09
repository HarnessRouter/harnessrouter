/** @jest-environment jsdom */
// Saving is visible (the memories spec, C6): a finished turn whose record says it remembered something ends in
// "Remembered N things", linked to those records in the agent's memory. A turn that kept nothing, or a service that
// doesn't say (before 0.40), shows no such line.
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { CustomHarness, ModelCatalog } from '@/lib/harness';
import { service } from '../memories/fixtures';

const MSGS = [{ role: 'user', text: 'Hi, it is Dana. I prefer written steps.' }, { role: 'assistant', blocks: [], files: [], status: 'done' }];
jest.mock('@/lib/conversation', () => ({
  isInternalOutput: () => false,
  useHarnessBus: () => {},
  useConversationTurn: () => ({
    msgs: MSGS, busy: false, stopping: false, liveSessionId: 'hsess_1',
    send: () => Promise.resolve(true), stop: () => {}, setMsgs: () => {}, loadFailed: false, reload: () => {},
  }),
}));
jest.mock('@/lib/chat', () => ({ loadSessionTurns: jest.fn(async () => ({ turns: [] })) }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
const CAT: ModelCatalog = { hermes: { default: 'gpt-5.4', models: ['gpt-5.4'], unavailable: [] } } as unknown as ModelCatalog;
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  useModelCatalogRead: () => ({ value: CAT, failed: false, retry: jest.fn() }),
  oobModels: () => ['gpt-5.4'], oobDefaultModel: () => 'gpt-5.4', modelAvailability: () => 'yes',
}));
jest.mock('@/lib/providers', () => ({ providerById: () => null, useModelProviders: () => ({ connectionFor: () => null }) }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../Skel', () => ({ Skel: () => null, SkLine: () => null, SkThread: () => null }));
jest.mock('../start/prompts', () => ({ API_BASE: 'https://box.example/api/harness' }));
jest.mock('./TaskThread', () => ({ Md: () => null }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href, className }: { children: ReactNode; href: string; className?: string }) => <a href={href} className={className}>{children}</a> }));
// every answer's own line, as the conversation draws it under the answer
jest.mock('./AgentTurns', () => ({
  AgentTurns: ({ msgs, actions }: { msgs: { role: string }[]; actions: (t: number, m: unknown) => ReactNode }) => (
    <div>{msgs.filter((m) => m.role === 'assistant').map((m, i) => <div key={i} className="turn-foot">{actions(i, m)}</div>)}</div>
  ),
  harnessMark: () => ({ mark: null, motion: null }),
}));
jest.mock('./TurnFiles', () => ({ FileCards: () => null, filesOf: () => [] }));
jest.mock('../start/build', () => ({ useBuildOf: () => null, noteFirstSid: jest.fn(), retryBuild: jest.fn() }));
jest.mock('reifyui/agent-chat', () => ({
  AgentConversation: ({ children, composer }: { children?: ReactNode; composer?: ReactNode }) => <div>{children}{composer}</div>,
  AgentComposer: () => <div className="composer" />,
}), { virtual: true });

import { harnessFetch } from '@/lib/hfetch';
import { loadSessionTurns } from '@/lib/chat';
import { rowOf } from '../setups';
import { Playground } from './Playground';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const H = { id: 'chrn_t', name: 'Support', base: 'hermes', defaultModel: 'gpt-5.4', systemPrompt: '', mcpServers: [], skills: [], createdAt: 1 } as unknown as CustomHarness;
let root: Root; let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 12; i++) await act(async () => { await Promise.resolve(); }); };
beforeEach(() => { el = document.createElement('div'); el.id = 'hrui'; document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });
async function open(turn: object, harness: object) {
  (loadSessionTurns as jest.Mock).mockResolvedValue({ turns: [{ id: 'resp_1', ...turn }] });
  (harnessFetch as jest.Mock).mockImplementation(service({ 'GET /v1/harnesses/chrn_t': { id: 'chrn_t', ...harness } }).fetcher);
  await act(async () => {
    root.render(<Playground r={rowOf(H, 'Hermes', [], false)} onRan={() => {}} onBorn={() => {}} onPreview={() => {}} slot={{ key: 'k', resume: 'hsess_1' }} />);
  });
  await flush();
}
const OWN = { memory: { id: 'hmem_a', name: 'Support', engine: 'mem0', scope: 'per_user', reason: '' } };

test('a turn that remembered says how much, linked to the first record it kept in the agent’s memory', async () => {
  await open({ memory: { remembered: 3, records: ['r1', 'r2', 'r3'].map((id) => ({ id, memory_id: 'hmem_a' })) } }, OWN);
  const a = el.querySelector('.turn-foot .pg-mem') as HTMLAnchorElement;
  expect(a.textContent).toBe('Remembered 3 things');
  expect(a.getAttribute('href')).toBe('/memories/hmem_a?tab=data&record=r1');
});

test('a record kept in a person’s own memory opens on the agent’s memory, open in it there', async () => {
  await open({ memory: { remembered: 1, records: [{ id: 'r9', memory_id: 'hmem_dana' }] } }, OWN);
  const a = el.querySelector('.turn-foot .pg-mem') as HTMLAnchorElement;
  expect(a.textContent).toBe('Remembered 1 thing');
  expect(a.getAttribute('href')).toBe('/memories/hmem_a?tab=data&in=hmem_dana&record=r9');
});

test('a turn that searched its memory says how many things it recalled, beside what it remembered', async () => {
  const found = JSON.stringify({ results: [{ record: { id: 'f1', title: '', content: [{ type: 'text', text: 'User’s name is Dana' }] } }], abstain: false }, null, 1);
  const wrapped = `<untrusted_tool_result source="mcp__memories__memory_recall">\nThe following content was retrieved from an external source.\n\n${JSON.stringify({ result: found })}\n</untrusted_tool_result>`;
  MSGS[1] = { role: 'assistant', blocks: [{ kind: 'tools', reasoning: '', steps: [{ name: 'mcp__memories__memory_recall', args: '{"query":"Dana"}', result: wrapped }] }], files: [], status: 'done' } as never;
  try {
    await open({ memory: { remembered: 1, records: [{ id: 'r9', memory_id: 'hmem_a' }] } }, OWN);
    expect(Array.from(el.querySelectorAll('.turn-foot .pg-mem')).map((x) => x.textContent)).toEqual(['Recalled 1 thing', 'Remembered 1 thing']);
  } finally {
    MSGS[1] = { role: 'assistant', blocks: [], files: [], status: 'done' } as never;
  }
});

test('kept after the turn ended, in a person’s memory below the agent’s: the line comes when the agent’s memory says so', async () => {
  // the agent's memory is the one open here; a person's memory below it tells it that something changed, and nothing more
  const sources: FakeSource[] = [];
  class FakeSource {
    on: Record<string, (e: { data: string }) => void> = {};
    constructor(public url: string) { sources.push(this); }
    addEventListener(kind: string, f: (e: { data: string }) => void) { this.on[kind] = f; }
    close() { /* nothing open */ }
  }
  Object.assign(globalThis, { EventSource: FakeSource });
  try {
    await open({}, OWN);
    expect(el.querySelector('.pg-mem')).toBeNull();
    const es = sources.find((s) => s.url === '/api/harness/v1/memories/hmem_a/events');
    expect(es).toBeTruthy();
    (loadSessionTurns as jest.Mock).mockResolvedValue({ turns: [{ id: 'resp_1', memory: { remembered: 1, records: [{ id: 'r9', memory_id: 'hmem_dana' }] } }] });
    await act(async () => { es!.on['records.changed']({ data: JSON.stringify({ id: 4, type: 'records.changed', memory_id: 'hmem_a', record_ids: [], below: true }) }); });
    await act(async () => { await new Promise((r) => setTimeout(r, 900)); });
    await flush();
    expect(el.querySelector('.turn-foot .pg-mem')?.getAttribute('href')).toBe('/memories/hmem_a?tab=data&in=hmem_dana&record=r9');
  } finally {
    delete (globalThis as { EventSource?: unknown }).EventSource;
  }
});

test('nothing kept, or nothing said of it: no line', async () => {
  await open({ memory: { remembered: 0, records: [] } }, OWN);
  expect(el.querySelector('.pg-mem')).toBeNull();
  await act(async () => { root.unmount(); }); root = createRoot(el);
  await open({}, { name: 'Support' });
  expect(el.querySelector('.pg-mem')).toBeNull();
});

// ── a turn reopened from its record (the final walkthrough, 11-09: a reloaded turn lost "Recalled" and its time) ────
// The record as the gateway keeps it: each memory tool's output (its start), what the platform recalled as the turn
// began (memory.recalled_at_start), and when the turn began and ended (whole Unix seconds).
const { msgsFromTurns } = jest.requireActual('@/lib/conversation') as typeof import('@/lib/conversation');
const recalledText = (lines: string[]) => JSON.stringify({
  results: lines.map((text, i) => ({ record: { id: `r${i}`, memory_id: 'hmem_a', type: 'fact', title: '', content: [{ type: 'text', text }], version: 1, status: 'active' }, memory: { id: 'hmem_a', name: 'Support' }, score: 0.2, why: ['query'] })),
  parent: { id: 'hmem_a', name: 'Support' }, children: [], degraded: [], abstain: false,
}, null, 1);
// codex's CallToolResult, as runner _codex_tool_item hands it on (json.dumps)
const codexOut = (text: string) => `{"content": [{"type": "text", "text": ${JSON.stringify(text)}}], "structuredContent": null, "_meta": null}`;
const RECORD = (o: object = {}) => ({
  id: 'resp_1', status: 'completed', user: 'Which tea do I drink?', assistant: 'You drink genmaicha.', user_files: [], files: [],
  created_at: 1794199363, completed_at: 1794199375, ...o,
});
async function reopen(record: object) {
  const { msgs } = msgsFromTurns([record as never]);
  MSGS.splice(0, MSGS.length, ...(msgs as never[]));
  await open(record, OWN);
}
const restore = () => MSGS.splice(0, MSGS.length, { role: 'user', text: 'Hi, it is Dana. I prefer written steps.' }, { role: 'assistant', blocks: [], files: [], status: 'done' } as never);
const foot = () => Array.from(el.querySelectorAll('.turn-foot .agent-meta > span:not(.pg-acts), .turn-foot .agent-meta > a'))
  .map((x) => x.textContent).filter((x) => x !== '·');

test('reopened: a codex search kept on the record still says what it recalled, and the turn its time', async () => {
  try {
    await reopen(RECORD({ tools: [{ name: 'memories.memory_recall', arguments: '{"query": "tea"}', output: codexOut(recalledText(['User’s favourite tea is genmaicha', 'User likes sesame rice crackers with it'])) }] }));
    expect(foot()).toEqual(['Done in 12 s', 'Recalled 2 things']);
  } finally { restore(); }
});

test('reopened: a search whose output the record cut short says at least what came', async () => {
  const whole = codexOut(recalledText(['First fact.', 'Second fact.', 'Third fact, cut in the middle.']));
  try {
    await reopen(RECORD({ tools: [{ name: 'memories.memory_recall', arguments: '{}', output: whole.slice(0, whole.indexOf('cut in the')) }] }));
    expect(foot()).toEqual(['Done in 12 s', 'Recalled at least 2 things']);
  } finally { restore(); }
});

test('what the platform recalled as the turn began says Recalled, with no search to show for it', async () => {
  try {
    await reopen(RECORD({ tools: [], memory: { remembered: 0, records: [], pending: false, recalled_at_start: 2 } }));
    const line = el.querySelector('.turn-foot .pg-recalled');
    expect(line?.textContent).toBe('Recalled 2 things');
    expect(line?.getAttribute('title')).toBe('2 things recalled as the task began');
    expect(el.querySelectorAll('.turn-foot .pg-mem')).toHaveLength(1);
  } finally { restore(); }
});

test('with both, one line: the larger, never the sum, and the title says each', async () => {
  try {
    await reopen(RECORD({ tools: [{ name: 'memories.memory_recall', arguments: '{}', output: codexOut(recalledText(['Tea is genmaicha'])) }],
      memory: { remembered: 1, records: [{ id: 'k1', memory_id: 'hmem_a' }], recalled_at_start: 3 } }));
    expect(foot()).toEqual(['Done in 12 s', 'Recalled 3 things', 'Remembered 1 thing']);
    expect(el.querySelector('.turn-foot .pg-recalled')?.getAttribute('title')).toBe('3 things recalled as the task began; 1 thing found by its own searches');
  } finally { restore(); }
});

test('a record that says nothing of memory or time: just Done, no line', async () => {
  try {
    await reopen({ id: 'resp_1', status: 'completed', user: 'Hi', assistant: 'Hello', tools: [], files: [] });
    expect(foot()).toEqual(['Done']);
  } finally { restore(); }
});

test('a save that failed: the reason once, never "wasn’t kept" twice, and no guessed cause', async () => {
  await open({ memory: { remembered: 0, records: [], failed: true, reason: 'Mem0 did not answer: HTTP 500' } }, OWN);
  expect(el.querySelector('.pg-mem-failed')?.textContent).toBe("Couldn't remember this one: Mem0 did not answer: HTTP 500");
  await act(async () => { root.unmount(); }); root = createRoot(el);
  await open({ memory: { remembered: 0, records: [], failed: true, reason: "This conversation wasn't kept: Mem0 did not answer: HTTP 500." } }, OWN);
  expect(el.querySelector('.pg-mem-failed')?.textContent).toBe("Couldn't remember this one: Mem0 did not answer: HTTP 500");
  await act(async () => { root.unmount(); }); root = createRoot(el);
  await open({ memory: { failed: true } }, OWN);
  expect(el.querySelector('.pg-mem-failed')?.textContent).toBe("Couldn't remember this one");
});
