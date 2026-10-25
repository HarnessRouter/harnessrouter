/** @jest-environment jsdom */
// A setup's Tasks at every width: on a wide window the open task sits beside the list, and at 860 px
// and below the two take turns (hrui.css). A window narrowed from desktop width keeps the task it had
// open, whether it was picked from the list, opened by itself as the newest, or gone back to from
// Settings; a page that opens at a phone's width starts on the list, as before (#576).
import { act, createContext } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { TraceCard } from '@/lib/revamp-data';

// the address: what useSearchParams reads, and what the page's router.replace writes
let search = '';
const replace = jest.fn((href: string) => { search = href.includes('?') ? href.slice(href.indexOf('?') + 1) : ''; });
jest.mock('next/navigation', () => ({
  useParams: () => ({ id: 'h1' }),
  useRouter: () => ({ replace, push: jest.fn() }),
  useSearchParams: () => new URLSearchParams(search),
}));

const card = (sid: string, title: string, at: number): TraceCard => ({ session_id: sid, title, status: 'completed', finished_at: at } as TraceCard);
const CARDS = [card('t2', 'The newest task', 2000), card('t1', 'An older task', 1000)];
const mockList = {
  all: CARDS, byId: new Map(CARDS.map((c) => [c.session_id, c])), ready: true, failed: false, stale: false,
  more: false, reading: false, paused: false, pending: [],
  older: () => {}, refresh: () => {}, reconnect: () => {}, drop: () => {}, add: () => {},
};
jest.mock('@/components/hrui/setups', () => ({
  useSetup: () => ({
    row: { h: { id: 'h1', name: 'My setup', source: '', createdAt: 1 }, binding: null },
    cards: [], missing: false, failed: false, reload: () => {},
  }),
}));
jest.mock('@/components/hrui/setup/TaskRail', () => {
  const actual = jest.requireActual('@/components/hrui/setup/TaskRail');
  return {
    filterTasks: actual.filterTasks, NO_FILTER: actual.NO_FILTER,
    useTaskList: () => mockList,
    useLinkedTask: () => ({ failed: false, retry: () => {} }),
    TaskList: ({ onOpen }: { onOpen: (sid: string) => void }) => (
      <div className="tk-l">{CARDS.map((c) => <button key={c.session_id} type="button" id={`row-${c.session_id}`} onClick={() => onOpen(c.session_id)}>{c.title}</button>)}</div>
    ),
  };
});
jest.mock('@/components/hrui/setup/parts', () => ({
  useMedia: jest.requireActual('@/components/hrui/setup/parts').useMedia,
  useSideOff: () => [false, () => {}],
  AgentHead: ({ onTab }: { onTab: (t: 'tasks' | 'settings') => void }) => (
    <header><button type="button" id="tab-tasks" onClick={() => onTab('tasks')}>Tasks</button>
      <button type="button" id="tab-settings" onClick={() => onTab('settings')}>Settings</button></header>
  ),
  StackPanel: () => null,
}));
jest.mock('@/components/hrui/setup/Playground', () => ({ Playground: () => null }));
jest.mock('@/components/hrui/setup/SetupSettings', () => ({ SetupSettings: () => <div id="settings" /> }));
jest.mock('@/components/hrui/setup/settingsModel', () => ({ hasSettingsDraft: () => false, layerOf: () => undefined, useBrickNav: () => {} }));
jest.mock('@/components/hrui/SetUpApp', () => ({ SetUpApp: () => null }));
jest.mock('@/components/hrui/Skel', () => ({ Skel: () => null, SkLine: () => null, SkRows: () => null, SkThread: () => null }));
jest.mock('@/components/hrui/setup/TaskDetail', () => ({
  TaskHead: ({ card: c }: { card: TraceCard }) => <h1 id="task-title">{c.title}</h1>,
  RecordedHead: () => null, NewTaskHead: () => null,
}));
jest.mock('@/components/hrui/setup/TurnFiles', () => ({ FilesPanel: () => null }));
jest.mock('@/components/hrui/setup/PreviewGrip', () => ({ PreviewGrip: () => null, usePreviewWidth: () => ({ width: 480 }) }));
jest.mock('@/components/hrui/setup/BrowserSlot', () => ({
  BrowserControl: () => null, BrowserSlot: () => null, browserStepsOf: () => [], stepOf: () => null,
  useTaskBrowser: () => ({ pane: { open: false }, live: undefined, step: null, show: () => {}, close: () => {} }),
}));
jest.mock('@/components/hrui/setup/AgentTurns', () => ({ TurnSteps: createContext(null) }));
jest.mock('@/lib/conversation', () => ({ getPaneState: () => ({ open: false }), setPaneState: () => {}, useConvState: () => ({ msgs: [] }) }));
jest.mock('@/components/hrui/start/check', () => ({ takeFirstTest: () => null }));
jest.mock('@/components/hrui/start/build', () => ({ useBuildOf: () => null }));
jest.mock('@/components/hrui/start/seed', () => ({ seededSetup: () => null }));
jest.mock('@/components/hrui/start/buildStack', () => ({ useBuildStack: () => ({ r: null, now: null, drops: null }) }));
jest.mock('@/components/hrui/start/replay', () => ({ useRecordedRunState: () => ({ run: null, failed: false, retry: () => {} }) }));
jest.mock('@/components/hrui/toast', () => ({ toast: jest.fn() }));

import SetupPage from './page';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// a window whose width the test sets: every (max-width: N px) query answers it, and hears a change
// only when its answer flips, as a browser's does
let width = 1440;
const queries: { q: string; max: number; on: Set<() => void>; was: boolean }[] = [];
function matchMedia(q: string) {
  const max = Number(/max-width:\s*(\d+)px/.exec(q)?.[1] ?? Infinity);
  const entry = { q, max, on: new Set<() => void>(), was: width <= max };
  queries.push(entry);
  return {
    get matches() { return width <= max; }, media: q,
    addEventListener: (_: string, fn: () => void) => entry.on.add(fn),
    removeEventListener: (_: string, fn: () => void) => entry.on.delete(fn),
  };
}
async function resize(w: number) {
  width = w;
  await act(async () => {
    for (const e of queries) {
      const now = width <= e.max;
      if (now !== e.was) { e.was = now; e.on.forEach((fn) => fn()); }
    }
  });
}

let root: Root;
let el: HTMLElement;
const split = () => el.querySelector('.tk-split') as HTMLElement;
/** what a phone-width window shows: the open task, or the list (the 860 px rule is `.show-d`) */
const narrowShows = () => (split().classList.contains('show-d') ? 'task' : 'list');
async function open(at: number, address = '') {
  width = at; search = address;
  await act(async () => { root.render(<SetupPage />); });
  for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve(); });
}
const rerender = async () => { await act(async () => { root.render(<SetupPage />); }); };
const click = async (id: string) => { await act(async () => { (document.getElementById(id) as HTMLButtonElement).click(); }); await rerender(); };

beforeEach(() => {
  queries.length = 0; replace.mockClear();
  window.matchMedia = matchMedia as unknown as typeof window.matchMedia;
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('the newest task, opened by itself at desktop width, stays open as the window narrows to a phone’s', async () => {
  await open(1440);
  expect(document.getElementById('task-title')?.textContent).toBe('The newest task');
  await resize(1024);
  expect(narrowShows()).toBe('list');      // 1024 px is above the phone rule: both still show, nothing flips yet
  await resize(768);
  expect(narrowShows()).toBe('task');
  await resize(390);
  expect(narrowShows()).toBe('task');
  expect(document.getElementById('task-title')?.textContent).toBe('The newest task');
});

test('the task Settings went back to, named in the address, stays open as the window narrows', async () => {
  await open(1440, 'test=t1');
  await click('tab-settings');
  await click('tab-tasks');
  expect(search).toBe('test=t1');
  expect(document.getElementById('task-title')?.textContent).toBe('An older task');
  await resize(768);
  expect(narrowShows()).toBe('task');
  expect(document.getElementById('task-title')?.textContent).toBe('An older task');
});

test('a task picked from the list stays open as the window narrows, as it always did', async () => {
  await open(1440);
  await click('row-t1');
  await resize(390);
  expect(narrowShows()).toBe('task');
  expect(document.getElementById('task-title')?.textContent).toBe('An older task');
});

test('a page opened at a phone’s width starts on the list, and only a pick opens a task', async () => {
  await open(390);
  expect(narrowShows()).toBe('list');
  await resize(375);
  expect(narrowShows()).toBe('list');
  await click('row-t2');
  expect(narrowShows()).toBe('task');
});
