/** @jest-environment jsdom */
// A surface's own line after a turn (a branched task's "Continued from ..."): drawn right after the
// turn it was asked for, and nowhere else.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Msg } from '@/lib/conversation';

// Not `virtual`: the module is installed, and jest keeps its module ids across the files of one process. A file that
// ran earlier and loaded AgentTurns for real leaves an id this mock would miss, and the real view is drawn instead.
jest.mock('reifyui/agent-chat', () => ({
  AgentTurnView: ({ turn }: { turn: { user?: { text?: string } | null } }) => <div className="t">{turn.user?.text}</div>,
  turnFromMessage: (_m: unknown, _c: unknown, user: unknown) => ({ status: 'done', items: [], user }),
  motionFor: () => '',
}));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));
jest.mock('@/lib/limit-copy', () => ({ limitStopWhy: () => '', SETUP_LIMITS: {} }));
jest.mock('./agent-chat.scoped.css', () => ({}), { virtual: true });
jest.mock('./agent-turns.css', () => ({}), { virtual: true });

import { AgentTurns } from './AgentTurns';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const asst = { role: 'assistant', blocks: [], files: [], status: 'done' } as Msg;
const MSGS: Msg[] = [{ role: 'user', text: 'a' }, asst, { role: 'user', text: 'b' }, asst, { role: 'user', text: 'c' }, asst];

let root: Root;
let el: HTMLElement;
beforeEach(() => { el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('the line comes right after its turn, before the next', () => {
  act(() => { root.render(<AgentTurns msgs={MSGS} base="hermes" md={() => null} after={(t) => (t === 1 ? <p className="line" /> : null)} />); });
  expect([...el.children].map((c) => c.className || c.tagName)).toEqual(['t', 't', 'line', 't']);
});

test('without one, the turns are drawn as they were', () => {
  act(() => { root.render(<AgentTurns msgs={MSGS} base="hermes" md={() => null} />); });
  expect([...el.children].map((c) => c.className)).toEqual(['t', 't', 't']);
});
