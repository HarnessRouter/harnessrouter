/** @jest-environment jsdom */
// The Memories list, and New memory. Nothing connected leads to connecting (or finding the engines running here), in
// one sentence. A new memory takes a name and, if you like, a description; every engine is listed, the one chosen from
// them picked and marked Recommended with why, and any connected one can be picked. Each card names its engine, who
// uses it and when, where the service says, and shows its kept cover or its brick, reading nothing else for it. A
// refused connection says the engine's own words. Every figure on a card is the service's.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Provider } from '@/lib/memories';
import { allProviders, CAPS, memory, record, service } from './fixtures';

const push = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: jest.fn() }) }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => <a className={className} href={href}>{children}</a> }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => [{ id: 'chrn_a', name: 'Photo cut' }]), instructionFileLabel: () => 'AGENTS.md' }));
jest.mock('../setup/settingsModel', () => ({
  plain: (e: unknown, f: string) => (e instanceof Error && e.message ? e.message : f),
  plural: (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`,
}));

const drawCover = jest.fn();
jest.mock('./graph/coverShot', () => ({ drawCover: (...a: unknown[]) => drawCover(...a) }));

import { harnessFetch } from '@/lib/hfetch';
import { MemoriesPage } from './MemoriesPage';
import { toast } from '../toast';
import { listCustom } from '@/lib/harness';
import { memoryNowLine, replaceAsk } from './sheets';
import { coverGraphOf, coverSig, DRAW_VERSION } from './cover';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
const NONE = { mem0: false, graphiti: false, hindsight: false, reme: false };
const flush = async () => { for (let i = 0; i < 12; i++) await act(async () => { await Promise.resolve(); }); };
function backend(routes: Record<string, unknown>) {
  const s = service({ 'GET /v1/memories': { data: [] }, 'GET /v1/plugs': { plugs: [] }, ...routes });
  (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
  return s;
}
async function open() { await act(async () => { root.render(<MemoriesPage />); }); await flush(); }
const page = () => document.getElementById('hrui') as HTMLElement;
const button = (t: string) => Array.from(page().querySelectorAll('button')).find((b) => (b.textContent || '').trim() === t) as HTMLButtonElement | undefined;
async function press(t: string) {
  const b = button(t);
  if (!b) throw new Error(`no button ${t}: ${page().textContent}`);
  await act(async () => { b.click(); });
  await flush();
}
async function type(sel: string, v: string) {
  const i = page().querySelector(sel) as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(i.constructor.prototype, 'value')!.set!;
  await act(async () => { set.call(i, v); i.dispatchEvent(new Event('input', { bubbles: true })); });
}
beforeEach(() => {
  push.mockReset();
  localStorage.removeItem('hr.memories.view');
  window.history.replaceState(null, '', '/memories');
  el = document.createElement('div'); el.id = 'hrui';
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

const more = async (t: string) => {
  await press_(page().querySelector('.mm-top button[aria-label="More"]') as HTMLElement);
  await press_(Array.from(page().querySelectorAll('.mm-top .mm-mi')).find((b) => b.querySelector('b')?.textContent === t) as HTMLElement);
};
async function press_(b: HTMLElement | null | undefined) {
  if (!b) throw new Error(`nothing to press: ${page().textContent}`);
  await act(async () => { b.click(); });
  await flush();
}

describe('nothing connected', () => {
  test('the page explains in one sentence and leads to connecting, or to finding the engines running here', async () => {
    backend({ 'GET /v1/memories/providers': { data: allProviders(NONE) } });
    await open();
    expect(page().querySelector('.mm-empty-list h2')?.textContent).toBe('Connect a memory engine');
    expect(page().querySelectorAll('.mm-empty-list p')).toHaveLength(1);
    expect(button('New memory')).toBeUndefined();
    expect(button('Find engines')).toBeTruthy();
    await press('Connect an engine');
    const offered = Array.from(page().querySelectorAll('.mm-pv-o b')).map((b) => b.textContent);
    expect(offered).toEqual(['Mem0', 'Graphiti', 'Hindsight', 'ReMe']);
    expect(page().textContent).toContain('Plain Markdown files you can read and edit.');
    expect(page().querySelectorAll('.mm-pv-o .btn')).toHaveLength(4);
  });

  test('connecting sends the address and key, shows a refusal in the engine’s words, then goes on to New memory', async () => {
    let refuse = true;
    const s = backend({
      'GET /v1/memories/providers': () => ({ data: allProviders(refuse ? NONE : { ...NONE, graphiti: true }) }),
      'PUT /v1/plugs/graphiti': () => (refuse ? { $status: 422, error: { code: 'memory_invalid', message: 'That address did not answer.' } } : { type: 'graphiti' }),
    });
    await open();
    await press('Connect an engine');
    await act(async () => { (Array.from(page().querySelectorAll('.mm-pv-o')).find((o) => o.textContent?.includes('Graphiti'))!.querySelector('button') as HTMLButtonElement).click(); });
    await flush();
    // an address is required here
    expect((page().querySelector('.sheet button[type=submit]') as HTMLButtonElement).disabled).toBe(true);
    await type('#mmCnBase', 'https://g.example.com');
    await type('#mmCnKey', 'k1');
    await press('Connect');
    expect(s.sent('PUT', '/v1/plugs/graphiti')[0].body).toEqual({ enabled: true, config: { base_url: 'https://g.example.com' }, secrets: { api_key: 'k1' } });
    expect(page().querySelector('.sheet [role=alert]')?.textContent).toBe('That address did not answer.');
    refuse = false;
    await press('Connect');
    expect(page().querySelector('#mmCrT')?.textContent).toBe('New memory');
    expect(page().querySelector('.mm-engs [role=radio][aria-checked=true] b')?.textContent).toBe('Graphiti');
  });

  test('an engine that may go without an address needs a key then, and no key is sent when none is typed', async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: allProviders(NONE) },
      'PUT /v1/plugs/mem0': { type: 'mem0' },
    });
    await open();
    await press('Connect an engine');
    await act(async () => { (Array.from(page().querySelectorAll('.mm-pv-o')).find((o) => o.textContent?.includes('Mem0'))!.querySelector('button') as HTMLButtonElement).click(); });
    await flush();
    const go = () => page().querySelector('.sheet button[type=submit]') as HTMLButtonElement;
    expect(go().disabled).toBe(true);
    await type('#mmCnBase', 'https://m.example.com');
    expect(go().disabled).toBe(false);
    await press('Connect');
    expect(s.sent('PUT', '/v1/plugs/mem0')[0].body).toEqual({ enabled: true, config: { base_url: 'https://m.example.com' } });
  });

  test('Find engines asks the service to look, and says which it connected, from what it reads after', async () => {
    let found = false;
    const s = backend({
      'GET /v1/memories/providers': () => ({ data: allProviders(found ? { ...NONE, hindsight: true, reme: true } : NONE) }),
      // the service's own answer: one line per engine of the bundled stack
      'POST /v1/memory-services/discover': () => { found = true; return { object: 'list', data: [
        { engine: 'mem0', state: 'not_running', message: 'Mem0 isn\'t running here.' },
        { engine: 'graphiti', state: 'not_running', message: 'Graphiti isn\'t running here.' },
        { engine: 'hindsight', state: 'connected', message: 'Hindsight was found and connected.' },
        { engine: 'reme', state: 'connected', message: 'ReMe was found and connected.' },
      ] }; },
    });
    await open();
    await press('Find engines');
    expect(s.sent('POST', '/v1/memory-services/discover')).toHaveLength(1);
    expect(s.sent('POST', '/v1/memory-services/discover')[0].body).toBeUndefined();
    expect(toast).toHaveBeenCalledWith('Hindsight, ReMe connected.');
  });

  test('an engine running that needs its key, or one refused, is said in the service’s words', async () => {
    backend({
      'GET /v1/memories/providers': { data: allProviders(NONE) },
      'POST /v1/memory-services/discover': { object: 'list', data: [
        { engine: 'mem0', state: 'running', message: 'Mem0 is running. Connect it with deploy/memories/up.sh, which has its key.' },
        { engine: 'reme', state: 'refused', message: 'ReMe answers, but it can\'t read with a model: it has no working model key.' },
        { engine: 'hindsight', state: 'not_running', message: 'Hindsight isn\'t running here.' },
      ] },
    });
    await open();
    await press('Find engines');
    expect(toast).toHaveBeenCalledWith('Mem0 is running. Connect it with deploy/memories/up.sh, which has its key. '
      + 'ReMe answers, but it can\'t read with a model: it has no working model key.');
  });
});

describe('New memory: a name, a description if you like, and every engine, the one chosen for you picked', () => {
  const connected = { ...NONE, mem0: true, graphiti: true, hindsight: true };
  // the service's answers (GET /v1/memories/choose), by the name asked about: the console reads them, it never scores
  const PEOPLE = 'It serves people, so it keeps each person’s facts and preferences, separately per person.';
  const CHOICES: Record<string, { engine: string | null; scope: string; reason: string }> = {
    '': { engine: 'mem0', scope: 'per_user', reason: 'Nothing about it says otherwise, so it keeps each person’s facts and preferences, separately per person.' },
    'Customer preferences': { engine: 'mem0', scope: 'per_user', reason: PEOPLE },
    'Account research': { engine: 'graphiti', scope: 'shared', reason: 'It tracks people, things and how they relate over time.' },
    'Incident lessons': { engine: 'hindsight', scope: 'shared', reason: 'It learns from its own work, consolidating experience into lessons.' },
    Accounts: { engine: 'mem0', scope: 'per_user', reason: PEOPLE },
  };
  const asked = (c: { path: string }) => new URLSearchParams(c.path.split('?')[1] || '');
  const start = async (on: Record<string, boolean> = connected, choose: (name: string) => unknown = (n) => CHOICES[n] || CHOICES['']) => {
    const s = backend({
      'GET /v1/memories/providers': { data: allProviders(on) },
      'GET /v1/memories': { data: [memory()] },
      'GET /v1/memories/choose': (c: { path: string }) => choose(asked(c).get('name') || ''),
      'POST /v1/memories': (c: { body: { name: string; provider: string } }) => memory({ id: 'hmem_new', name: c.body.name, provider: c.body.provider }),
    });
    await open();
    await press('New memory');
    await rest();
    return s;
  };
  // typing rests before the service is asked again
  const rest = async () => { await act(async () => { await new Promise((r) => setTimeout(r, 350)); }); await flush(); };
  const rows = () => Array.from(page().querySelectorAll<HTMLButtonElement>('.mm-engs [role=radio]'));
  const row = (name: string) => rows().find((r) => r.querySelector('b')?.textContent === name) as HTMLButtonElement;
  const chosen = () => page().querySelector('.mm-engs [role=radio][aria-checked=true] b')?.textContent;
  const recommended = () => page().querySelector('.mm-engs .mm-eng-rec')?.closest('[role=radio]')?.querySelector('b')?.textContent;
  const pick = async (name: string) => { await act(async () => { row(name).click(); }); await flush(); };

  test('nothing to compare and nothing to lock: no Kept by, no Fixed once created', async () => {
    await start();
    expect(page().textContent).not.toContain('Kept by');
    expect(page().textContent).not.toContain('Fixed once created');
    expect(page().querySelector('.mm-sv-facts')).toBeNull();
    expect(page().querySelector('label[for=mmCrDesc]')?.textContent).toContain('optional');
  });

  test('every engine is listed at once, with what it keeps; one not running here is shown and can’t be picked', async () => {
    await start();
    expect(rows().map((r) => r.querySelector('b')?.textContent)).toEqual(['Mem0', 'Graphiti', 'Hindsight', 'ReMe']);
    expect(page().querySelector('[role=radiogroup]')?.getAttribute('aria-labelledby')).toBe('mmCrEng');
    expect(row('Graphiti').textContent).toContain('A graph of people, things and how they connect, tracked over time.');
    expect(row('ReMe').disabled).toBe(true);
    expect(row('ReMe').textContent).toContain('Not running here');
    expect(row('Mem0').textContent).not.toContain('Not running here');
    // nothing is folded away, and nothing asks for a click to see the others
    expect(button('Change')).toBeUndefined();
    expect(page().querySelector('.mm-eng [aria-expanded]')).toBeNull();
  });

  test('the one the service chooses is picked and marked Recommended, with why, and follows what is typed', async () => {
    const s = await start();
    expect(chosen()).toBe('Mem0');
    expect(recommended()).toBe('Mem0');
    await type('#mmCrName', 'Customer preferences');
    await type('#mmCrDesc', 'What each customer likes.');
    await rest();
    expect(chosen()).toBe('Mem0');
    expect(row('Mem0').querySelector('.mm-eng-why')?.textContent).toBe(PEOPLE);
    expect(page().querySelectorAll('.mm-eng-rec')).toHaveLength(1);
    const sent = s.sent('GET', '/v1/memories/choose');
    const last = sent[sent.length - 1];
    expect([asked(last).get('name'), asked(last).get('description')]).toEqual(['Customer preferences', 'What each customer likes.']);
    await type('#mmCrName', 'Account research');
    await type('#mmCrDesc', '');
    await rest();
    expect([chosen(), recommended()]).toEqual(['Graphiti', 'Graphiti']);
    await type('#mmCrName', 'Incident lessons');
    await rest();
    expect([chosen(), recommended()]).toEqual(['Hindsight', 'Hindsight']);
    // one question per pause in the typing, never one per key
    expect(s.sent('GET', '/v1/memories/choose').length).toBeLessThanOrEqual(5);
  });

  test('once the person picks one, the recommendation still says what it is but no longer moves the choice', async () => {
    const s = await start();
    await type('#mmCrName', 'Account research');
    await rest();
    expect(chosen()).toBe('Graphiti');
    await pick('Hindsight');
    expect(chosen()).toBe('Hindsight');
    await type('#mmCrName', 'Customer preferences');
    await rest();
    expect([chosen(), recommended()]).toEqual(['Hindsight', 'Mem0']);
    await press('Create');
    expect((s.sent('POST', '/v1/memories')[0].body as { provider: string }).provider).toBe('hindsight');
  });

  test('no engine answering here: the service says so in its words, and a connected one can still be picked', async () => {
    const s = await start({ ...NONE, mem0: true, graphiti: true }, () => ({ engine: null, scope: 'per_user', reason: 'No memory engine is running here; one command starts them: deploy/memories/up.sh' }));
    expect(chosen()).toBeUndefined();
    expect(recommended()).toBeUndefined();
    expect(page().querySelector('.mm-eng-none')?.textContent).toBe('No memory engine is running here; one command starts them: deploy/memories/up.sh');
    await type('#mmCrName', 'Accounts');
    expect(button('Create')?.disabled).toBe(true);
    await pick('Graphiti');
    expect(chosen()).toBe('Graphiti');
    await press('Create');
    expect((s.sent('POST', '/v1/memories')[0].body as { provider: string }).provider).toBe('graphiti');
  });

  test('a choice the service could not make is said, and asked again on Try again', async () => {
    let up = false;
    await start(connected, () => (up ? CHOICES.Accounts : { $status: 503, error: { message: 'Not now.' } }));
    expect(page().querySelector('.mm-eng .mm-err')?.textContent).toContain('The engine couldn’t be chosen just now.');
    expect(rows()).toHaveLength(4);
    up = true;
    await press('Try again');
    await rest();
    expect(chosen()).toBe('Mem0');
  });

  test('arrows move the choice along the engines that can be picked, and the choice is what gets created', async () => {
    const s = await start();
    await type('#mmCrName', 'Accounts');
    await rest();
    const group = page().querySelector('[role=radiogroup]') as HTMLElement;
    const key = async (k: string) => { await act(async () => { group.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true })); }); };
    await key('ArrowDown');
    expect(chosen()).toBe('Graphiti');
    await key('ArrowDown'); await key('ArrowDown');
    // ReMe isn't running here, so the choice goes round to Mem0
    expect(chosen()).toBe('Mem0');
    await key('ArrowUp');
    expect(chosen()).toBe('Hindsight');
    await press('Create');
    expect((s.sent('POST', '/v1/memories')[0].body as { provider: string }).provider).toBe('hindsight');
  });

  test('Create makes it with its name and description and opens its data, whatever the engine reads', async () => {
    const s = await start();
    await type('#mmCrName', 'Accounts');
    await type('#mmCrDesc', 'Who our customers are.');
    await press('Create');
    expect(s.sent('POST', '/v1/memories')[0].body).toEqual({ name: 'Accounts', description: 'Who our customers are.', provider: 'mem0' });
    expect(push).toHaveBeenCalledWith('/memories/hmem_new?tab=data');
  });

  test('none connected, with memories already here: nothing can be created, and the way to connect is there', async () => {
    backend({ 'GET /v1/memories/providers': { data: allProviders(NONE) }, 'GET /v1/memories': { data: [memory({ records: { count: null } })] } });
    await open();
    await press('New memory');
    await type('#mmCrName', 'Accounts');
    expect(button('Create')?.disabled).toBe(true);
    expect(rows().every((r) => r.disabled)).toBe(true);
    await press('Connect an engine');
    expect(page().querySelector('#mmCh')?.textContent).toBe('Connect a memory engine');
  });
});

describe('the cards', () => {
  test('no counts: the list is read without them, in the order it was last used, and a card names its engine', async () => {
    // Richard 11-06: the counts (memories, records, setups; a card's types, records and setups) made the list slow
    const s = backend({
      'GET /v1/memories/providers': { data: [CAPS.graphiti, CAPS.mem0] },
      'GET /v1/memories': { data: [memory(), memory({ id: 'hmem_2', name: 'Support', provider: 'mem0', records: { count: null }, description: '' })] },
      'GET /v1/memories/hmem_1/schema': { types: [{ name: 'Company' }, { name: 'Person' }], relations: [] },
    });
    await open();
    const [a, b] = Array.from(page().querySelectorAll('.mm-card'));
    expect(page().querySelectorAll('.mm-cs')).toHaveLength(0);
    expect(page().querySelector('.list-top')?.textContent).not.toMatch(/\d+ (memories|memory|records?)|used by/);
    expect(s.sent('GET', '/v1/memories').map((c) => c.path)).toEqual(['/v1/memories?counts=false&sort=recent']);
    expect(s.calls.filter((c) => c.path.includes('/grants'))).toEqual([]);
    expect(a.querySelector('.mm-cp')?.textContent).toBe('Graphiti');
    expect(b.querySelector('.mm-cd')?.textContent).toBe('No description yet.');
    expect(page().textContent).not.toContain('Kept by');
    // a service before 0.40 says nothing of who uses a memory: nothing is drawn of it
    expect(page().querySelector('.mm-ub')).toBeNull();
    expect(page().querySelector('.mm-sort')).toBeNull();
  });

  test('who uses each one, as chips, and when it was last used; the most recently used first', async () => {
    backend({
      'GET /v1/memories/providers': { data: [CAPS.mem0] },
      'GET /v1/memories': { data: [
        memory({ id: 'a', name: 'Older', provider: 'mem0', engine: 'mem0', used_by: [{ harness_id: 'chrn_a', name: 'Photo cut' }], last_used_at: '2026-11-01T00:00:00Z' }),
        memory({ id: 'b', name: 'Busy', provider: 'mem0', engine: 'mem0', used_by: [{ harness_id: 'chrn_a', name: 'Photo cut' }, { harness_id: 'chrn_b', name: 'Support bot' }, { harness_id: 'chrn_c', name: 'Sales' }], last_used_at: '2026-11-08T00:00:00Z' }),
        memory({ id: 'c', name: 'Idle', provider: 'mem0', engine: 'mem0', used_by: [], last_used_at: null }),
      ] },
    });
    await open();
    const cards = Array.from(page().querySelectorAll('.mm-card'));
    expect(cards.map((c) => c.querySelector('.mm-ct b')?.textContent)).toEqual(['Busy', 'Older', 'Idle']);
    expect(Array.from(cards[0].querySelectorAll('.mm-uc')).map((c) => c.textContent)).toEqual(['Photo cut', 'Support bot', '+1']);
    expect(cards[0].querySelector('.mm-cp')?.textContent).toMatch(/^Mem0 · Used .+ ago$/);
    expect(cards[2].querySelector('.mm-ub')?.textContent).toBe('Not used yet');
    expect(cards[2].querySelector('.mm-cp')?.textContent).toBe('Mem0');
    // Use in sits beside the card nothing uses, never inside its link
    const use = Array.from(page().querySelectorAll('.mm-cardw')).map((w) => !!w.querySelector(':scope > .mm-usein'));
    expect(use).toEqual([false, false, true]);
    // by name, a click away
    const sel = page().querySelector('.mm-sort select') as HTMLSelectElement;
    await act(async () => { sel.value = 'name'; sel.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(Array.from(page().querySelectorAll('.mm-card .mm-ct b')).map((b) => b.textContent)).toEqual(['Busy', 'Idle', 'Older']);
  });

  test('search narrows by name, description, engine or the setups that use it', async () => {
    backend({
      'GET /v1/memories/providers': { data: [CAPS.mem0, CAPS.graphiti] },
      'GET /v1/memories': { data: [
        memory({ id: 'a', name: 'Accounts', description: 'Who our customers are.', provider: 'graphiti', used_by: [] }),
        memory({ id: 'b', name: 'Prefs', description: '', provider: 'mem0', used_by: [{ harness_id: 'chrn_b', name: 'Support bot' }] }),
      ] },
    });
    await open();
    const names = () => Array.from(page().querySelectorAll('.mm-card .mm-ct b')).map((b) => b.textContent);
    await type('.mm-lfind input', 'customers');
    expect(names()).toEqual(['Accounts']);
    await type('.mm-lfind input', 'support bot');
    expect(names()).toEqual(['Prefs']);
    await type('.mm-lfind input', 'mem0');
    expect(names()).toEqual(['Prefs']);
    await type('.mm-lfind input', 'nothing like it');
    expect(page().textContent).toContain('No memory matches that.');
  });

  test('Use in gives a memory to a setup, which then remembers there', async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: [CAPS.mem0] },
      'GET /v1/memories': { data: [memory({ id: 'c', name: 'Idle', provider: 'mem0', engine: 'mem0', used_by: [] })] },
      'PUT /v1/harnesses/chrn_a/memory': { id: 'chrn_a', memory: { id: 'c', name: 'Idle', engine: 'mem0', scope: 'shared', reason: '' } },
    });
    await open();
    await press('Use in…');
    await press('Use here');
    expect(s.sent('PUT', '/v1/harnesses/chrn_a/memory')[0].body).toEqual({ memory: { id: 'c' } });
    expect(toast).toHaveBeenCalledWith('Photo cut remembers in Idle now.');
  });

  test('what Use in asks before it replaces: the memory by its name, or its own where it is named after the setup', () => {
    const own = (name: string) => ({ k: 'own' as const, id: 'hmem_x', name });
    expect(replaceAsk({ name: 'Busy', has: own('Busy') }, 'Idle')).toEqual({ title: 'Replace its own memory in Busy?',
      body: 'Busy remembers in its own memory now. From its next task it remembers in Idle instead. Its own memory is kept, with everything in it.' });
    expect(replaceAsk({ name: 'Busy', has: own('Support notes') }, 'Idle').title).toBe('Replace Support notes in Busy?');
    expect(replaceAsk({ name: 'Old', has: { k: 'count', n: 2 } }, 'Idle').body).toBe('Old uses 2 memories now. From its next task it remembers in Idle instead. They are kept, with everything in them.');
    expect(memoryNowLine(own('Busy'), 'c', 'Busy')).toBe('Remembers in its own memory');
  });

  test('Use in lists the setups in use first, each with the memory it has now; replacing one asks first (C6)', async () => {
    (listCustom as jest.Mock).mockResolvedValueOnce([
      { id: 'chrn_old', name: 'Old idle', createdAt: 1, memory: null, memory_reason: 'Turned off.' },
      { id: 'chrn_busy', name: 'Busy', createdAt: 2, memory: { id: 'hmem_x', name: 'Support notes', engine: 'mem0', scope: 'per_user', reason: '' } },
      { id: 'chrn_new', name: 'Newest', createdAt: 3 },
      { id: 'chrn_here', name: 'Already here', createdAt: 0, memory: { id: 'c', name: 'Idle', engine: 'mem0', scope: 'shared', reason: '' } },
    ]);
    const s = backend({
      'GET /v1/memories/providers': { data: [CAPS.mem0] },
      'GET /v1/memories': { data: [memory({ id: 'c', name: 'Idle', provider: 'mem0', engine: 'mem0', used_by: [] })] },
      'GET /v1/traces': { sessions: [{ session_id: 's1', harness_id: 'chrn_busy', status: 'completed', finished_at: 1762600000 }] },
      'PUT /v1/harnesses/chrn_busy/memory': { id: 'chrn_busy', memory: { id: 'c', name: 'Idle', engine: 'mem0', scope: 'shared', reason: '' } },
    });
    await open();
    await press('Use in…');
    const rows = Array.from(page().querySelectorAll('.mm-use-row')).map((r) => [r.querySelector('b')?.textContent, r.querySelector('.mm-use-n small')?.textContent || '', r.querySelector('button')?.textContent || r.querySelector('.mm-use-here')?.textContent]);
    expect(rows).toEqual([
      ['Busy', 'Remembers in Support notes', 'Use here'],
      ['Newest', '', 'Use here'],
      ['Old idle', 'No memory', 'Use here'],
      ['Already here', '', 'Remembers here'],
    ]);
    // one that has a memory of its own asks before it is replaced, in the console's own dialog
    await press_(page().querySelectorAll<HTMLElement>('.mm-use-row button')[0]);
    expect(page().querySelector('#mmUseRh')?.textContent).toBe('Replace Support notes in Busy?');
    expect(page().querySelector('#mmUseRp')?.textContent).toBe('Busy remembers in Support notes now. From its next task it remembers in Idle instead. Support notes is kept, with everything in it.');
    expect(s.sent('PUT', '/v1/harnesses/chrn_busy/memory')).toHaveLength(0);
    await press('Replace');
    expect(s.sent('PUT', '/v1/harnesses/chrn_busy/memory')[0].body).toEqual({ memory: { id: 'c' } });
    expect(toast).toHaveBeenCalledWith('Busy remembers in Idle now.');
  });

  test('connecting and finding engines are under More', async () => {
    backend({ 'GET /v1/memories/providers': { data: [CAPS.mem0] }, 'GET /v1/memories': { data: [memory({ provider: 'mem0' })] } });
    await open();
    expect(button('Connect an engine')).toBeUndefined();
    await more('Connect an engine');
    expect(page().querySelector('#mmCh')?.textContent).toBe('Connect a memory engine');
    // one connected already says Change, not Connect
    expect(Array.from(page().querySelectorAll('.mm-pv-o .btn')).map((b) => b.textContent)).toEqual(['Change']);
  });
});

describe('a card shows its picture', () => {
  const MADE = {
    types: [{ name: 'episode', description: 'e' }, { name: 'entity', description: 'n' }, { name: 'fact', description: 'f' }],
    relations: [{ name: 'about', from: 'fact', to: 'entity', description: 'a' }, { name: 'derived_from', from: 'fact', to: 'episode', description: 'o' }],
  };
  const graphiti = { ...CAPS.graphiti, schema: { ...CAPS.graphiti.schema, builtin: MADE } } as Provider;
  const factsOnly = { ...CAPS.mem0, schema: { mode: 'none', builtin: { types: [{ name: 'fact', description: 'f' }], relations: [] } } } as Provider;
  const PIC = new Blob([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], { type: 'image/png' });
  const made: Blob[] = [];
  beforeEach(() => {
    made.length = 0;
    let n = 0;
    Object.assign(URL, { createObjectURL: jest.fn((b: Blob) => { made.push(b); return `blob:cover/${++n}`; }), revokeObjectURL: jest.fn() });
  });
  const card = (n: string) => Array.from(page().querySelectorAll('.mm-card')).find((c) => c.textContent?.includes(n)) as Element;
  const reads = (s: { calls: { method: string; path: string }[] }) => s.calls.filter((c) => c.method === 'GET' && /\/(schema|records|grants)\b/.test(c.path));

  test('a card with a cover shows only the picture, read once by its version, and reads nothing else for it', async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: [graphiti] },
      'GET /v1/memories': { data: [memory({ id: 'hmem_1', name: 'Accounts', cover_at: 1762700000000, cover_sig: 'c1abc' })] },
      'GET /v1/memories/hmem_1/cover': PIC,
    });
    await open();
    const art = card('Accounts').querySelector('.mm-art') as Element;
    const img = art.querySelector('img.mm-cover') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('blob:cover/1');
    expect([img.alt, img.getAttribute('loading'), img.getAttribute('decoding')]).toEqual(['', 'lazy', 'async']);
    expect(art.querySelector('svg')).toBeNull();
    expect(s.sent('GET', '/v1/memories/hmem_1/cover').map((c) => c.path)).toEqual(['/v1/memories/hmem_1/cover?v=1762700000000']);
    expect(reads(s)).toEqual([]);
    expect(made).toEqual([PIC]);
  });

  test('a memory with no graph shows its brick from the agent stack, and reads nothing for it', async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: [factsOnly] },
      'GET /v1/memories': { data: [memory({ id: 'hmem_2', name: 'Brand facts', provider: 'mem0', builtin: factsOnly.schema!.builtin })] },
    });
    await open();
    const art = card('Brand facts').querySelector('.mm-art') as Element;
    expect(art.querySelector('.mm-brick svg.iso .bk.f-memory.built')).not.toBeNull();
    expect(art.querySelector('.mm-brick svg .iso-shadow')).not.toBeNull();
    expect(art.querySelector('img')).toBeNull();
    expect(art.textContent).toBe('');
    expect(s.calls.filter((c) => c.path.startsWith('/v1/memories/hmem_2'))).toEqual([]);
    // the list's row shows the same, small
    await press('List');
    expect(page().querySelector('.mm-row .mm-mini-box .mm-brick.mini .f-memory')).not.toBeNull();
  });

  test('a graph with no cover yet waits in a quiet shape of the same size, never the old drawing, and reads nothing at once', async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: [graphiti] },
      'GET /v1/memories': { data: [memory({ id: 'hmem_3', name: 'Research' })] },
    });
    await open();
    const art = card('Research').querySelector('.mm-art') as Element;
    expect(art.querySelector('.mm-cv-wait')).not.toBeNull();
    expect(art.querySelector('svg, img')).toBeNull();
    expect(reads(s)).toEqual([]);
  });
});

describe('a cover still missing is made once the page has settled', () => {
  jest.setTimeout(10000);
  const MADE = {
    types: [{ name: 'episode', description: 'e' }, { name: 'fact', description: 'f' }],
    relations: [{ name: 'derived_from', from: 'fact', to: 'episode', description: 'o' }],
  };
  const graphiti = { ...CAPS.graphiti, schema: { ...CAPS.graphiti.schema, builtin: MADE } } as Provider;
  const DRAWN = new Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' });
  beforeEach(() => {
    let n = 0;
    Object.assign(URL, { createObjectURL: jest.fn(() => `blob:drawn/${++n}`), revokeObjectURL: jest.fn() });
    Object.assign(window, { CanvasRenderingContext2D: function CanvasRenderingContext2D() { /* a canvas to draw on */ } });
    drawCover.mockReset();
    drawCover.mockResolvedValue(DRAWN);
  });
  afterEach(() => { delete (window as { CanvasRenderingContext2D?: unknown }).CanvasRenderingContext2D; });
  const settle = async () => { await act(async () => { await new Promise((r) => setTimeout(r, 1100)); }); await flush(); };

  test('drawn as the Schema tab draws it, one at a time, kept where the person may write, and shown', async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: [graphiti] },
      'GET /v1/memories': { data: [
        memory({ id: 'hmem_w', name: 'Writable' }),
        memory({ id: 'hmem_r', name: 'Read only', privileges: ['read'] }),
        // kept, and showing what the drawing would be now: nothing to do
        memory({ id: 'hmem_k', name: 'Kept', cover_at: 5, cover_sig: coverSig(coverGraphOf(null, graphiti)) }),
      ] },
      'GET /v1/memories/hmem_w/schema': { types: [{ name: 'Company', color: '#ec4899', icon: 'building', x: 10, y: 20 }], relations: [] },
      'GET /v1/memories/hmem_r/schema': { types: [], relations: [] },
      'GET /v1/memories/hmem_k/cover': new Blob(['x'], { type: 'image/png' }),
      'PUT /v1/memories/hmem_w/cover': { object: 'memory.cover', cover_at: 9, cover_sig: 'c1' },
    });
    let busy = 0, most = 0;
    drawCover.mockImplementation(async () => { busy += 1; most = Math.max(most, busy); await new Promise((r) => setTimeout(r, 30)); busy -= 1; return DRAWN; });
    await open();
    expect(drawCover).not.toHaveBeenCalled();
    await settle();
    await act(async () => { await new Promise((r) => setTimeout(r, 200)); }); await flush();
    expect(drawCover).toHaveBeenCalledTimes(2);
    expect(most).toBe(1);
    // the drawing is the schema with what the engine makes itself, as the tab draws it
    const g = drawCover.mock.calls[0][0] as { vertex_types: { label: string }[]; edge_types: { label: string }[] };
    expect(g.vertex_types.map((v) => v.label).sort()).toEqual(['Company', 'episode', 'fact']);
    const put = s.sent('PUT', '/v1/memories/hmem_w/cover');
    expect(put).toHaveLength(1);
    expect(put[0].body).toBe(DRAWN);
    expect(put[0].headers['content-type']).toBe('image/png');
    expect(put[0].headers['x-cover-sig']).toMatch(new RegExp(`^c${DRAW_VERSION}s_[0-9a-z]+$`));
    // read only: drawn for this visit, never kept
    expect(s.sent('PUT', '/v1/memories/hmem_r/cover')).toHaveLength(0);
    expect(s.sent('GET', '/v1/memories/hmem_k/schema')).toHaveLength(0);
    const src = (n: string) => (Array.from(page().querySelectorAll('.mm-card')).find((c) => c.textContent?.includes(n))?.querySelector('img') as HTMLImageElement | null)?.getAttribute('src');
    expect(src('Writable')).toMatch(/^blob:drawn\//);
    expect(src('Read only')).toMatch(/^blob:drawn\//);
  });

  test('a cover drawn before the drawing changed is made again in the same pass: from the list where it is what the provider makes, with one read where nothing says what it was, never one with a person’s own types', async () => {
    const now = coverSig(coverGraphOf(null, graphiti));
    const older = now.replace(`c${DRAW_VERSION}`, `c${DRAW_VERSION - 1}`);
    const s = backend({
      'GET /v1/memories/providers': { data: [graphiti] },
      'GET /v1/memories': { data: [
        memory({ id: 'hmem_b', name: 'Made by the engine', cover_at: 5, cover_sig: older }),
        memory({ id: 'hmem_u', name: 'Made before marks', cover_at: 5, cover_sig: 'c1abc123' }),
        memory({ id: 'hmem_s', name: 'Own types', cover_at: 5, cover_sig: `c${DRAW_VERSION - 1}s_abc` }),
        memory({ id: 'hmem_o', name: 'Someone else’s', cover_at: 5, cover_sig: older, privileges: ['read'] }),
      ] },
      'GET /v1/memories/hmem_u/schema': { types: [], relations: [] },
      'PUT /v1/memories/hmem_b/cover': { cover_at: 9 }, 'PUT /v1/memories/hmem_u/cover': { cover_at: 9 },
      ...Object.fromEntries(['hmem_b', 'hmem_u', 'hmem_s', 'hmem_o'].map((id) => [`GET /v1/memories/${id}/cover`, new Blob(['x'], { type: 'image/png' })])),
    });
    await open();
    await settle();
    await act(async () => { await new Promise((r) => setTimeout(r, 200)); }); await flush();
    expect(drawCover).toHaveBeenCalledTimes(2);
    expect(s.sent('PUT', '/v1/memories/hmem_b/cover')[0].headers['x-cover-sig']).toBe(now);
    expect(s.sent('PUT', '/v1/memories/hmem_u/cover')[0].headers['x-cover-sig']).toBe(now);
    // the only schema read: the cover that didn't say what it was
    expect(s.calls.filter((c) => c.path.endsWith('/schema')).map((c) => c.path)).toEqual(['/v1/memories/hmem_u/schema']);
    expect(s.sent('PUT', '/v1/memories/hmem_s/cover')).toHaveLength(0);
    expect(s.sent('PUT', '/v1/memories/hmem_o/cover')).toHaveLength(0);
    // until a new one comes, and after, the card shows a picture, never the wait
    expect(page().querySelectorAll('.mm-card .mm-cv-wait')).toHaveLength(0);
  });
});

describe('cards or a list', () => {
  test('List shows a row a memory, its name and description, and the choice is remembered', async () => {
    localStorage.removeItem('hr.memories.view');
    backend({
      'GET /v1/memories/providers': { data: [CAPS.graphiti, CAPS.mem0] },
      'GET /v1/memories': { data: [memory(), memory({ id: 'hmem_2', name: 'Support', provider: 'mem0', records: { count: null }, description: '' })] },
      'GET /v1/memories/hmem_1/schema': { types: [{ name: 'Company' }, { name: 'Person' }], relations: [] },
      'GET /v1/memories/hmem_1/grants': { data: [{ id: 'g1', memory_id: 'hmem_1', principal: 'member:chrn_a', privileges: ['read'], inherited: false }] },
    });
    await open();
    expect(page().querySelectorAll('.mm-card')).toHaveLength(2);
    await press('List');
    const rows = Array.from(page().querySelectorAll('.mm-row'));
    expect(rows).toHaveLength(2);
    const cells = (r: Element) => Array.from(r.children).slice(1).map((c) => c.textContent);
    expect(cells(rows[0])).toEqual(['What each brand wants.']);
    expect(cells(rows[1])).toEqual(['No description yet.']);
    expect(localStorage.getItem('hr.memories.view')).toBe('list');
    await press('Cards');
    expect(page().querySelectorAll('.mm-card')).toHaveLength(2);
    expect(localStorage.getItem('hr.memories.view')).toBe('cards');
  });
});
