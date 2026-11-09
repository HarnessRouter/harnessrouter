/** @jest-environment jsdom */
// A standing instruction, set by a person in the console (0.40.4: agents can no longer set one). On a record that can
// stand, for a signed-in person who may write the memory, a switch writes `attributes.standing` through the record's
// update; a standing record says so; one an agent set says agents get it only as a note, with the way to make it the
// person's. Never on a conversation, nor on what an engine drew or kept itself, nor for someone who may only read.
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Memory, MemoryRecord, Provider } from '@/lib/memories';
import { CAPS, memory, record, service } from './fixtures';

let session: { member: Record<string, unknown> } | null = { member: { id: 'ada@example.com', email: 'ada@example.com' } };
const toast = jest.fn();
jest.mock('@/lib/auth', () => ({ getSession: () => session }));
jest.mock('@/lib/edition', () => ({ LOCAL_MEMBER: 'local@localhost' }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}) }));
jest.mock('react-markdown', () => ({ __esModule: true, default: ({ children }: { children: string }) => <p>{children}</p> }));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => undefined }));
jest.mock('next/dynamic', () => ({ __esModule: true, default: () => () => null }));
jest.mock('./editor/liveRecord', () => ({ useLiveRecord: () => ({ live: null, state: null }), useLiveText: () => '' }));
jest.mock('../setups', () => ({ ago: () => '2 d ago' }));
jest.mock('../toast', () => ({ toast: (m: string) => toast(m) }));
jest.mock('../setup/settingsModel', () => ({
  plain: (e: unknown, f: string) => (e instanceof Error && e.message ? e.message : f),
  plural: (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`,
}));

import { harnessFetch } from '@/lib/hfetch';
import { RecordDoc } from './RecordDoc';
import { canStand, standingOf } from './caps';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 10; i++) await act(async () => { await Promise.resolve(); }); };
const PERSON = { kind: 'member', id: 'ada@example.com', type: 'human' as const };
const AGENT = { kind: 'member', id: 'chrn_desk', type: 'agent' as const };
const note = (o: Partial<MemoryRecord> = {}) => record({ id: 'r1', type: 'note', title: 'Quote prices in euros', written_by: PERSON, ...o });

function backend() {
  const s = service({
    'PATCH /v1/memories/hmem_1/records/r1': (c: { body: { attributes?: Record<string, unknown> } }) =>
      note({ version: 2, attributes: { ...c.body.attributes }, written_by: PERSON }),
    'POST /v1/memories/hmem_1/records': (c: { body: { attributes?: Record<string, unknown>; title?: string } }) =>
      note({ id: 'r9', title: c.body.title, attributes: { ...c.body.attributes } }),
  });
  (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
  return s;
}
/** The record open as the page opens it: what a save answers is the record it shows next. */
function Host({ r0, m, p, onSaved }: { r0: MemoryRecord; m: Memory; p: Provider; onSaved?: (r: MemoryRecord) => void }) {
  const [r, setR] = useState(r0);
  return <RecordDoc memory={m} provider={p} record={r} schema={null} setups={null} links={0} folders={[]} onSaved={(x) => { setR(x); onSaved?.(x); }} onGone={() => {}} />;
}
async function draw(r: MemoryRecord, o: { m?: Partial<Memory>; p?: Provider; onSaved?: (r: MemoryRecord) => void } = {}) {
  const m = memory({ id: 'hmem_1', provider: 'graphiti', ...o.m });
  await act(async () => { root.render(<Host key={`${r.id}.${r.version}.${Math.random()}`} r0={r} m={m} p={o.p || CAPS.graphiti} onSaved={o.onSaved} />); });
  await flush();
}
const sw = () => el.querySelector('.mm-stand button.tog') as HTMLButtonElement | null;
const press = async (b: HTMLElement) => { await act(async () => { b.click(); }); await flush(); };
beforeEach(() => {
  session = { member: { id: 'ada@example.com', email: 'ada@example.com' } };
  el = document.createElement('div'); el.id = 'hrui'; document.body.appendChild(el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

test('a person who may write turns a record into a standing instruction, through the record’s own update', async () => {
  const s = backend();
  const saved = jest.fn();
  await draw(note(), { onSaved: saved });
  expect(el.querySelector('#mmStandL')?.textContent).toBe('Standing instruction');
  expect(el.querySelector('#mmStandH')?.textContent).toBe('Every agent that uses this memory gets it at the start of each task.');
  expect(sw()?.getAttribute('aria-pressed')).toBe('false');
  await press(sw() as HTMLElement);
  expect(s.sent('PATCH', '/v1/memories/hmem_1/records/r1').map((c) => c.body)).toEqual([{ attributes: { standing: true } }]);
  expect(saved).toHaveBeenCalledWith(expect.objectContaining({ attributes: { standing: true } }));
  expect(sw()?.getAttribute('aria-pressed')).toBe('true');
  // and off again, the same way
  await press(sw() as HTMLElement);
  expect(s.sent('PATCH', '/v1/memories/hmem_1/records/r1')[1].body).toEqual({ attributes: { standing: false } });
});

test('a standing record says so, and nothing raw about it is listed under Details', async () => {
  backend();
  await draw(note({ attributes: { standing: true } }));
  expect(el.querySelector('.mm-tags .mm-tag')?.textContent).toBe('Standing');
  expect(sw()?.getAttribute('aria-pressed')).toBe('true');
  expect(Array.from(el.querySelectorAll('.mm-props label')).map((l) => l.textContent)).not.toContain('standing');
});

test('without write, there is no switch: a reader sees the tag, and nothing to change', async () => {
  const s = backend();
  await draw(note({ attributes: { standing: true } }), { m: { privileges: ['read'] } });
  expect(sw()).toBeNull();
  expect(el.querySelector('.mm-stand')).toBeNull();
  expect(el.querySelector('.mm-tag')?.textContent).toBe('Standing');
  await draw(note(), { m: { privileges: ['read'] } });
  expect(el.querySelector('.mm-stand')).toBeNull();
  expect(s.calls).toEqual([]);
});

test('only a signed-in person gets the switch, never an agent', async () => {
  backend();
  session = null;
  await draw(note());
  expect(sw()).toBeNull();
  session = { member: { id: 'chrn_desk', type: 'agent' } };
  await draw(note({ version: 3 }));
  expect(sw()).toBeNull();
});

test('a conversation, and what an engine drew from one or kept itself, never get the switch', async () => {
  backend();
  const drawn = [
    note({ type: 'episode' }),
    note({ type: 'fact', references: [{ rel: 'derived_from', record_id: 'e1', available: true }] }),
    note({ type: 'entity', written_by: { kind: 'provider', id: 'graphiti' } }),
    note({ follows: { kind: 'file', name: 'Pricing.md' } }),
  ];
  for (const r of drawn) {
    await draw({ ...r, version: r.version + 1 });
    expect([r.type, sw()]).toEqual([r.type, null]);
    expect(canStand(r)).toBe(false);
  }
  // a person's record the service last revised on their behalf (a contradiction noted) can still stand
  expect(canStand(note({ written_by: { kind: 'provider', id: 'graphiti', on_behalf_of: 'member:ada@example.com' } }))).toBe(true);
  // nor on an engine that doesn't let a record be changed
  const fixed = { ...CAPS.graphiti, revise: false } as Provider;
  await draw(note({ version: 9 }), { p: fixed });
  expect(sw()).toBeNull();
});

test('one an agent set before 0.40.4 says agents get it as a note, and a person makes it theirs', async () => {
  const s = backend();
  await draw(note({ attributes: { standing: true }, written_by: AGENT }));
  expect(standingOf(note({ attributes: { standing: true }, written_by: AGENT }))).toBe('agent');
  expect(el.querySelector('.mm-tags')).toBeNull();
  expect(el.querySelector('.mm-stand.noted .mm-tag')?.textContent).toBe('Noted by an agent as standing');
  expect(el.querySelector('.mm-stand.noted small')?.textContent).toBe('An agent set this, so agents get it as a note, not as an instruction.');
  expect(sw()).toBeNull();
  await press(Array.from(el.querySelectorAll('.mm-stand button')).find((b) => b.textContent === 'Make it standing') as HTMLElement);
  expect(s.sent('PATCH', '/v1/memories/hmem_1/records/r1').map((c) => c.body)).toEqual([{ attributes: { standing: true } }]);
  expect(el.querySelector('.mm-tags .mm-tag')?.textContent).toBe('Standing');
  expect(toast).toHaveBeenCalledWith('Standing instruction set. Agents get it from their next task.');
  // someone who may only read sees the note, and no action
  await draw(note({ version: 5, attributes: { standing: true }, written_by: AGENT }), { m: { privileges: ['read'] } });
  expect(el.querySelector('.mm-stand.noted .mm-tag')?.textContent).toBe('Noted by an agent as standing');
  expect(el.querySelector('.mm-stand button')).toBeNull();
});

test('a refusal is said in the service’s words and the switch goes back', async () => {
  const s = service({ 'PATCH /v1/memories/hmem_1/records/r1': { $status: 403, error: { code: 'memory_forbidden', message: 'Only a person can set a standing instruction.' } } });
  (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
  await draw(note());
  await press(sw() as HTMLElement);
  expect(el.querySelector('.mm-err')?.textContent).toBe('Only a person can set a standing instruction.');
  expect(sw()?.getAttribute('aria-pressed')).toBe('false');
});

test('a new record gets the same switch, and is made standing when it is made', async () => {
  const s = backend();
  const fresh = record({ id: '', type: 'note', title: '', content: [], version: 0, written_by: { kind: 'member', id: '' } });
  await draw(fresh);
  await press(sw() as HTMLElement);
  expect(sw()?.getAttribute('aria-pressed')).toBe('true');
  // nothing is made until it has words
  expect(s.sent('POST', '/v1/memories/hmem_1/records')).toHaveLength(0);
  const title = el.querySelector('h1.mm-title') as HTMLElement;
  await act(async () => { title.textContent = 'Always answer in French'; title.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });
  await flush();
  expect(s.sent('POST', '/v1/memories/hmem_1/records')[0].body).toMatchObject({ title: 'Always answer in French', attributes: { standing: true } });
});

describe('a write made with an API key no person holds', () => {
  const KEY = { kind: 'x.service', id: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08' };
  const writtenBy = () => Array.from(el.querySelectorAll('.mm-props .mm-prow')).find((r) => r.querySelector('label')?.textContent === 'Written by')?.querySelector('.mm-pv')?.textContent;
  function keys(list: unknown) {
    const s = service({ 'GET /v1/orgs/org1/keys': list, 'PATCH /v1/memories/hmem_1/records/r1': (c: { body: { attributes?: Record<string, unknown> } }) => note({ version: 2, attributes: { ...c.body.attributes } }) });
    (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
    return s;
  }
  beforeEach(() => { session = { member: { id: 'ada@example.com' }, orgId: 'org1' } as never; });

  test('it is "An API key", by the name the keys list gives it, and never by its id', async () => {
    const s = keys({ keys: [{ id: KEY.id, name: 'production' }, { id: 'other', name: 'staging' }] });
    await draw(note({ written_by: KEY }));
    expect(writtenBy()).toBe('An API key (production) · 2 d ago');
    expect(el.textContent).not.toContain(KEY.id);
    expect(s.sent('GET', '/v1/orgs/org1/keys')).toHaveLength(1);
  });
  test('where the keys list can’t name it, it is "An API key", still never its id', async () => {
    keys({ $status: 403, error: { message: 'No.' } });
    await draw(note({ id: 'r2', written_by: { ...KEY, id: 'not-listed' } }));
    expect(writtenBy()).toBe('An API key · 2 d ago');
    expect(el.textContent).not.toContain('not-listed');
  });
  test('a standing record it set reads like an agent’s: a note to agents until a person makes it standing', async () => {
    const s = keys({ keys: [] });
    await draw(note({ attributes: { standing: true }, written_by: KEY }));
    expect(el.querySelector('.mm-stand.noted .mm-tag')?.textContent).toBe('Noted by an API key as standing');
    expect(el.querySelector('.mm-stand.noted small')?.textContent).toBe('An API key set this, so agents get it as a note, not as an instruction.');
    expect(el.querySelector('.mm-tags')).toBeNull();
    await press(Array.from(el.querySelectorAll('.mm-stand button')).find((b) => b.textContent === 'Make it standing') as HTMLElement);
    expect(s.sent('PATCH', '/v1/memories/hmem_1/records/r1').map((c) => c.body)).toEqual([{ attributes: { standing: true } }]);
    expect(el.querySelector('.mm-tags .mm-tag')?.textContent).toBe('Standing');
  });
  test('a key an agent holds for someone is an agent’s, as the service reads it', () => {
    expect(standingOf(note({ attributes: { standing: true }, written_by: { kind: 'member', id: 'ada@example.com', type: 'human', delegated: true } }))).toBe('agent');
    expect(standingOf(note({ attributes: { standing: true }, written_by: KEY }))).toBe('service');
  });
});
