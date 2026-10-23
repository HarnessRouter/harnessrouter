/** @jest-environment jsdom */
// The browser in the redesigned task view (Richard 10-19: "Use Browser should open the browser's
// preview the way a file opens"). A browser step names what it did (never "Used the browser a tool"),
// a click on one opens the browser card beside the conversation the way a file card opens its file,
// a browser opening pops the card and its closing closes it, and a past step whose browser has closed
// shows what it recorded, never a stream that has stopped.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { describeTool, toolLine } from 'reifyui/agent-chat';

const harnessFetch = jest.fn();
jest.mock('@/lib/hfetch', () => ({ harnessFetch: (...a: unknown[]) => harnessFetch(...a) }));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));

import { getPaneState, setConvState, setPaneState, type AsstMsg, type Msg } from '@/lib/conversation';
import { AgentTurns, TurnSteps, type TurnStepsOf } from './AgentTurns';
import { BrowserSlot, browserStepsOf, resultText, shotOf, useTaskBrowser, type BrowserStep, type TaskBrowser } from './BrowserSlot';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
Object.assign(URL, { createObjectURL: () => 'blob:shot', revokeObjectURL: () => undefined });

const j = (o: unknown) => JSON.stringify(o);
const line = (name: string, args: unknown, st: 'running' | 'done' = 'done') => toolLine(describeTool(name, j(args)), st);

describe('a browser step names what it did', () => {
  test.each([
    ['browser_navigate', { url: 'https://duckduckgo.com/' }, 'Opened duckduckgo.com'],
    ['browser_click', { ref: 'e12' }, 'Clicked on the page'],
    ['browser_click', { selector: 'a.result__a' }, 'Clicked a link'],
    ['browser_type', { ref: 'e2', text: 'cats', submit: true }, 'Typed into a field'],
    ['browser_screenshot', {}, 'Took a screenshot'],
    ['browser_snapshot', {}, 'Read the page'],
    ['browser_extract_text', {}, 'Read the page’s text'],
    ['browser_get_url', {}, 'Checked the address'],
    ['browser_press_key', { key: 'Enter' }, 'Pressed Enter'],
    ['browser_scroll', { direction: 'down' }, 'Scrolled down'],
    ['browser_wait_for', { text: 'Results' }, 'Waited for “Results”'],
    ['browser_back', {}, 'Went back a page'],
    ['browser_list_tabs', {}, 'Listed the tabs'],
    ['browser_switch_tab', { index: 1 }, 'Switched tabs'],
    // the same tools as other harnesses name them, through the plugins server
    ['mcp__plugs__browser_click', { ref: 'e1' }, 'Clicked on the page'],
    ['plugs.browser_screenshot', {}, 'Took a screenshot'],
    ['plugs__browser_navigate', { url: 'https://www.bing.com/images/search?q=x' }, 'Opened www.bing.com/images/search'],
  ])('%s %j reads "%s"', (name, args, want) => {
    expect(line(name, args)).toBe(want);
  });

  test('never "a tool", running or done, and never what was typed', () => {
    for (const name of ['browser_click', 'browser_type', 'browser_screenshot', 'browser_snapshot', 'browser_hover', 'browser', 'browser_anything']) {
      for (const st of ['running', 'done'] as const) expect(line(name, { ref: 'e1' }, st)).not.toMatch(/a tool/);
    }
    for (const st of ['running', 'done'] as const) {
      expect(line('browser_type', { ref: 'e1', text: 'hunter2' }, st)).not.toMatch(/hunter2/);
      expect(line('computer', { action: 'type', text: 'hunter2' }, st)).not.toMatch(/hunter2/);
    }
    expect(line('browser_navigate', { url: 'https://www.bing.com/images/search' }, 'running')).toBe('Opening www.bing.com/images/search');
  });
});

// a finished turn that browsed: opened a page (its snapshot names e1), clicked e1, ran a command
const browsed = (): Msg[] => [
  { role: 'user', text: 'Find the about page' },
  { role: 'assistant', status: 'done', files: [], blocks: [{ kind: 'tools', reasoning: '', steps: [
    { name: 'browser_navigate', args: j({ url: 'https://duckduckgo.com/' }), result: 'Opened https://duckduckgo.com/ (DuckDuckGo)\n\ne1 link "About"', callId: 'c1' },
    { name: 'browser_click', args: j({ ref: 'e1' }), result: 'Clicked. Now at https://duckduckgo.com/about', callId: 'c2' },
    { name: 'Bash', args: j({ command: 'ls' }), result: 'a.txt', callId: 'c3' },
  ] }, { kind: 'text', text: 'Found it.' }] } as unknown as AsstMsg,
];

let root: Root;
let el: HTMLElement;
beforeEach(() => { el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); harnessFetch.mockReset(); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('a click on a browser step opens it, the way a file card opens its file; other calls still unfold', () => {
  const opened: { turn: number; id: string; name: string }[] = [];
  let active: string | null = null;
  const steps: TurnStepsOf = (turn) => ({
    openStep: (item, d) => (d.kind === 'browser' ? () => { opened.push({ turn, id: item.id, name: item.name }); active = item.id; } : null),
    activeStep: active,
  });
  const draw = () => act(() => root.render(<TurnSteps.Provider value={steps}><AgentTurns msgs={browsed()} base="pi" md={(t) => t} /></TurnSteps.Provider>));
  draw();
  // the run of work folds to one line; it opens to its calls
  act(() => { el.querySelector<HTMLButtonElement>('.uac-sum')!.click(); });
  const rows = () => [...el.querySelectorAll<HTMLElement>('.uac-step')];
  expect(rows().map((r) => r.textContent?.replace(/\s+/g, ' ').trim())).toEqual(['Opened duckduckgo.com', 'Clicked the “About” link', 'Ran ls']);
  act(() => { rows()[1].querySelector<HTMLButtonElement>('.uac-step-h')!.click(); });
  expect(opened).toEqual([{ turn: 0, id: 'c2', name: 'browser_click' }]);
  // it opened beside the conversation, not inline; its row is the one shown
  expect(el.querySelector('.uac-detail')).toBeNull();
  draw();
  expect(rows()[1].className).toMatch(/is-active/);
  expect(rows()[1].querySelector('.uac-step-h')!.getAttribute('aria-current')).toBe('true');
  // the command is not the browser's: it unfolds to its input and output as before
  const cmd = rows()[2].querySelector<HTMLButtonElement>('.uac-step-h')!;
  expect(cmd.getAttribute('aria-expanded')).toBe('false');
  act(() => { cmd.click(); });
  expect(el.querySelector('.uac-detail')).not.toBeNull();
  expect(opened).toHaveLength(1);
});

test('every browser step of a conversation, labelled as the thread labels it', () => {
  const s = browserStepsOf(browsed());
  expect(s.map((x) => [x.turn, x.id, x.label])).toEqual([[0, 'c1', 'Opened duckduckgo.com'], [0, 'c2', 'Clicked the “About” link']]);
});

test('a screenshot step keeps its picture: the plug\'s path for this task only, or the image the record kept', () => {
  const out = 'Screenshot of https://duckduckgo.com/ (DuckDuckGo)\nKept with the task\'s files as /v1/harnesses/chrn_1/servers/mcp.plugs/sessions/hsess_1/media/med_abc123';
  const step = { name: 'browser_screenshot', args: '{}', output: out };
  expect(shotOf(step, 'chrn_1', 'hsess_1')).toEqual({ path: '/v1/harnesses/chrn_1/servers/mcp.plugs/sessions/hsess_1/media/med_abc123' });
  expect(shotOf(step, 'chrn_1', 'hsess_other')).toBeNull();
  expect(shotOf({ ...step, name: 'browser_navigate' }, 'chrn_1', 'hsess_1')).toBeNull();
  expect(shotOf({ name: 'mcp__plugs__browser_screenshot', args: '{}', output: j([{ type: 'image', data: 'iVBORw0KGgo=', mimeType: 'image/png' }]) }, 'chrn_1', 'hsess_1'))
    .toEqual({ dataUri: 'data:image/png;base64,iVBORw0KGgo=' });
  expect(resultText(out)).toBe('Screenshot of https://duckduckgo.com/ (DuckDuckGo)');
});

// the hook on a page of its own: the card's place, as the task page holds it
let tb: TaskBrowser | null = null;
function Probe({ sid, onPop }: { sid: string | null; onPop: () => void }) { tb = useTaskBrowser('chrn_h', sid, onPop); return null; }
const browser = (open: boolean, epoch: number) => ({ open, control: 'agent' as const, lastCallAt: 0, lastTool: '', held: false, epoch });

test('a browser opening pops the card; closed by the person it stays closed for that browser; the browser closing closes it', async () => {
  harnessFetch.mockResolvedValue({ ok: true, json: async () => ({ open: false }) });
  setPaneState('chrn_h', { open: false, mode: 'docked', dismissed: {} });
  const onPop = jest.fn();
  await act(async () => root.render(<Probe sid="hsess_a" onPop={onPop} />));
  expect(getPaneState('chrn_h').open).toBe(false);
  act(() => setConvState('hsess_a', { browser: browser(true, 1) }));
  expect(getPaneState('chrn_h').open).toBe(true);
  expect(onPop).toHaveBeenCalledTimes(1);
  expect(tb!.popped).toBe(true);
  // the person closes it: this browser stays closed, the next one pops
  act(() => tb!.close());
  act(() => setConvState('hsess_a', { browser: { ...browser(true, 1), lastTool: 'click' } }));
  expect(getPaneState('chrn_h').open).toBe(false);
  act(() => setConvState('hsess_a', { browser: browser(true, 2) }));
  expect(getPaneState('chrn_h').open).toBe(true);
  // the browser closes: so does the card, with no stopped stream left standing
  act(() => setConvState('hsess_a', { browser: browser(false, 2) }));
  expect(getPaneState('chrn_h').open).toBe(false);
  // opened from a past step after that, it shows the step
  const step: BrowserStep = { turn: 0, id: 'c2', name: 'browser_click', args: j({ ref: 'e1' }), output: 'Clicked.', status: 'done', label: 'Clicked the “About” link' };
  act(() => tb!.show(step));
  expect(getPaneState('chrn_h').open).toBe(true);
  expect(tb!.step?.id).toBe('c2');
  expect(tb!.popped).toBe(false);
  // another task closes it
  await act(async () => root.render(<Probe sid="hsess_b" onPop={onPop} />));
  expect(getPaneState('chrn_h').open).toBe(false);
  expect(tb!.step).toBeNull();
});

test('a past step whose browser has closed shows what it recorded, never the stream', async () => {
  // the session's route says no browser is open; the screenshot reads with the sign-in
  harnessFetch.mockImplementation(async (url: string) => (String(url).includes('/media/')
    ? { ok: true, blob: async () => new Blob(['png']) }
    : { ok: true, json: async () => ({ session_id: 'hsess_1', open: false }) }));
  const step: BrowserStep = { turn: 0, id: 'c9', name: 'browser_screenshot', args: '{}', status: 'done', label: 'Took a screenshot',
    output: 'Screenshot of https://duckduckgo.com/ (DuckDuckGo)\nKept with the task\'s files as /v1/harnesses/chrn_1/servers/mcp.plugs/sessions/hsess_1/media/med_abc123' };
  const t: TaskBrowser = { live: browser(false, 1), busy: false, pane: { open: true, mode: 'docked', dismissed: {} }, step, popped: false, show: () => undefined, close: () => undefined };
  await act(async () => root.render(<BrowserSlot harnessId="chrn_1" sid="hsess_1" tb={t} overlay={false} />));
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  expect(el.querySelector('iframe')).toBeNull();
  expect(el.querySelector('.wbx-browser-status')?.textContent).toBe('Took a screenshot');
  const img = el.querySelector<HTMLImageElement>('.tk-brec-shot');
  expect(img?.getAttribute('src')).toBe('blob:shot');
  expect(harnessFetch).toHaveBeenCalledWith('/api/harness/v1/harnesses/chrn_1/servers/mcp.plugs/sessions/hsess_1/media/med_abc123', expect.anything());
  expect(el.textContent).toContain('This browser has closed.');
  expect(el.textContent).not.toContain('Here is what this step recorded');
  // the docked card sits in the preview's column; under 1280 px it is a drawer that Escape closes
  expect(el.querySelector('aside.tk-preview.tk-bslot')).not.toBeNull();
  const close = jest.fn();
  await act(async () => root.render(<BrowserSlot harnessId="chrn_1" sid="hsess_1" tb={{ ...t, close }} overlay />));
  expect(el.querySelector('[role="dialog"].tk-bdrawer')).not.toBeNull();
  act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); });
  expect(close).toHaveBeenCalled();
});
