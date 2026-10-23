/** @jest-environment jsdom */
// A skill Claude Code loads is the CLI talking to its model, not the person (staging, 2026-10-19, the
// Videos kit on claude-opus-5): its Skill tool's body arrives as a user event marked isSynthetic, and the
// trace drew it as a second turn whose first row was "User: Base directory for this skill: /w...", with
// an "Idle · 0.0 s" gap splitting the one task in two. It starts no turn and draws no row; the Skill
// step stands for it, and the path it names is never shown. A real message from the person still opens
// the next turn.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/studio/traces/api', () => ({ tracesApi: { fullEvents: jest.fn(), manifest: jest.fn(), events: jest.fn() } }));
jest.mock('../setup/TaskThread', () => ({ Md: ({ text }: { text: string }) => <>{text}</>, prettyJson: () => null }));
jest.mock('@/lib/chat', () => ({ subscribeHarnessEvents: () => () => undefined }));

import { flatten } from '@/studio/traces/flatten';
import { TraceView, turnsOf, type TRow } from './TraceView';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
class RO { observe() {} disconnect() {} unobserve() {} }
Object.assign(globalThis, { ResizeObserver: RO });

const BODY = 'Base directory for this skill: /workspace/.claude/skills/video-storyboard\n\n# Storyboard\n\nPlan the shots first.';
// one Claude Code task: the person's request, the Skill call and its synthetic body, a media call, the answer
const task = (): Record<string, unknown>[] => [
  { type: 'user', message: { role: 'user', content: 'A 10-second video of a paper boat sailing down a rainy street, two shots.' }, _ts: 100 },
  { type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: "I'll read the storyboard skill first." }] }, _ts: 103 },
  { type: 'assistant', message: { role: 'assistant', content: [{ type: 'tool_use', id: 't1', name: 'Skill', input: { skill: 'video-storyboard' } }] }, _ts: 104 },
  { type: 'user', message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: 't1', content: 'Launching skill: video-storyboard' }] }, _ts: 104.5 },
  { type: 'user', message: { role: 'user', content: [{ type: 'text', text: BODY }] }, isSynthetic: true, _ts: 104.6 },
  { type: 'assistant', message: { role: 'assistant', content: [{ type: 'tool_use', id: 't2', name: 'mcp__media__list_capabilities', input: {} }] }, _ts: 106 },
  { type: 'user', message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: 't2', content: '{"video": []}' }] }, _ts: 106.5 },
  { type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: "Here's the plan, before anything is spent." }] }, _ts: 113 },
  { type: 'result', result: "Here's the plan, before anything is spent.", duration_ms: 18000, _ts: 118 },
];
// the person answers the plan: a real second turn
const followUp = (): Record<string, unknown>[] => [
  { type: 'user', message: { role: 'user', content: 'Go ahead with the cheaper route.' }, _ts: 200 },
  { type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: 'Rendering both shots.' }] }, _ts: 204 },
  { type: 'result', result: 'Rendering both shots.', duration_ms: 6000, _ts: 206 },
];

const rowsOf = (evs: Record<string, unknown>[]) => flatten(evs) as TRow[];

test("a skill's synthetic body is no row: one person message, and the Skill step stands for it", () => {
  const rows = rowsOf(task());
  expect(rows.filter((r) => r.kind === 'user').map((r) => r.text)).toEqual(['A 10-second video of a paper boat sailing down a rainy street, two shots.']);
  expect(rows.some((r) => (r.text || '').includes('Base directory'))).toBe(false);
  expect(rows.filter((r) => r.kind === 'tool').map((r) => r.label)).toEqual(['Skill', 'mcp__media__list_capabilities']);
});

test('the task stays one turn; a real message from the person opens the next', () => {
  expect(turnsOf(rowsOf(task()))).toHaveLength(1);
  expect(turnsOf(rowsOf([...task(), ...followUp()]))).toHaveLength(2);
});

describe('drawn', () => {
  let root: Root;
  let el: HTMLElement;
  beforeEach(() => { el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); });
  afterEach(() => { act(() => root.unmount()); el.remove(); });
  const body = () => (document.body.textContent || '').replace(/\s+/g, ' ');

  test('one turn with no path in it: no "Turn 2", no idle gap, no "Base directory"', () => {
    act(() => root.render(<TraceView sid="hsess1" rows={rowsOf(task())} failed={false} running={false} whole />));
    expect(body()).not.toContain('Base directory');
    expect(body()).not.toContain('Turn 2');
    expect(body()).not.toContain('Idle');
    expect(body()).toContain('Skill');
  });

  test("the person's follow-up is Turn 2", () => {
    act(() => root.render(<TraceView sid="hsess1" rows={rowsOf([...task(), ...followUp()])} failed={false} running={false} whole />));
    expect(body()).toContain('Turn 2');
    expect(body()).not.toContain('Base directory');
  });
});
