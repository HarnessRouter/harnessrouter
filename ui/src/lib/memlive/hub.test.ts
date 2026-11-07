/** @jest-environment node */
// The heart of editing together: people's typing reaches the memory once, in the pauses, and what an agent writes
// through the API reaches everyone who has the record open, without either overwriting the other. The gateway is
// faked at the wire, so what's checked is what would really be sent.
import * as Y from 'yjs';
import { BODY, normal, readBody, TITLE, writeBody } from './convert';
import { hub, Refused, type Who } from './hub';
import { mergeText, mergeTitle } from './merge';

const who: Who = { headers: { 'x-harness-internal': 'k' }, member: 'ada' };
const CLIENT = 901;

interface Sent { method: string; path: string; body?: Record<string, unknown>; match?: string }
let sent: Sent[]; let record: Record<string, unknown>; let privileges: string[];
let patchAnswer: (b: Record<string, unknown>) => { status: number; body: unknown };
let tellGateway: (frame: string) => void;
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

function fakeGateway() {
  (globalThis as { fetch: unknown }).fetch = jest.fn(async (url: string, init: { method: string; body?: string }) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    const body = init.body ? JSON.parse(init.body) : undefined;
    sent.push({ method: init.method, path, body, match: (init as { headers?: Record<string, string> }).headers?.['if-match'] });
    if (path.includes('/events')) {
      const stream = new ReadableStream<Uint8Array>({ start(c) { tellGateway = (f) => c.enqueue(new TextEncoder().encode(f)); } });
      return new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } });
    }
    if (init.method === 'GET' && /\/records\//.test(path)) return json(200, record);
    if (init.method === 'GET') return json(200, { privileges });
    if (init.method === 'PATCH') { const a = patchAnswer(body); return json(a.status, a.body); }
    return json(404, {});
  });
}

let told: { event: string; data: Record<string, unknown> }[];
let seq = 0;
async function join(rid = `r${++seq}`) {
  told = [];
  const c = `conn-${rid}-aaaa`;
  const leave = await hub.join('m1', rid, c, who, (event, data) => { if (event) told.push({ event, data: data as Record<string, unknown> }); }, () => {});
  const hello = told.find((t) => t.event === 'hello')!.data;
  const doc = new Y.Doc();
  doc.clientID = CLIENT;
  Y.applyUpdate(doc, new Uint8Array(Buffer.from(String(hello.state), 'base64')));
  return { rid, c, leave, doc, hello };
}
const typeInto = (j: { rid: string; c: string; doc: Y.Doc }, change: (d: Y.Doc) => void) => {
  const sv = Y.encodeStateVector(j.doc);
  change(j.doc);
  hub.update('m1', j.rid, j.c, Y.encodeStateAsUpdate(j.doc, sv));
};
/** What a browser holding this copy now reads, after everything the server told it. */
const received = (j: { doc: Y.Doc }) => {
  for (const t of told) if (t.event === 'u') Y.applyUpdate(j.doc, new Uint8Array(Buffer.from(String(t.data.u), 'base64')));
  return { title: j.doc.getText(TITLE).toString(), body: readBody(j.doc) };
};
const patches = () => sent.filter((s) => s.method === 'PATCH');
const agent = { kind: 'member', id: 'chrn_a', type: 'agent' };
const tick = (ms: number) => jest.advanceTimersByTimeAsync(ms);
const event = (d: object) => tellGateway(`id: ${++seq}\nevent: x\ndata: ${JSON.stringify(d)}\n\n`);

beforeEach(() => {
  jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] });
  sent = []; privileges = ['read', 'write'];
  record = { id: 'x', version: 1, status: 'active', title: 'Acme', content: [{ type: 'text', text: 'First paragraph.\n\nSecond paragraph.' }], written_by: { kind: 'member', id: 'ada' } };
  patchAnswer = (b) => {
    record = { ...record, ...(b.title !== undefined ? { title: b.title } : {}), ...(b.content !== undefined ? { content: b.content } : {}), version: Number(record.version) + 1 };
    return { status: 200, body: record };
  };
  fakeGateway();
});
afterEach(() => { jest.useRealTimers(); });

describe('text and document', () => {
  test('a record opens as its title and its text, under the editor’s schema', async () => {
    const j = await join();
    expect(j.doc.getText(TITLE).toString()).toBe('Acme');
    expect(readBody(j.doc)).toBe('First paragraph.\n\nSecond paragraph.');
    expect(j.hello.canWrite).toBe(true);
    j.leave();
  });
  test('formatting survives the round trip and compares as the same text', () => {
    const md = '# Heading\n\nSome **bold** and *italic* and `code`.\n\n- one\n- two\n\n```js\nconst a = 1;\n```';
    const doc = new Y.Doc();
    writeBody(doc, md, 'x');
    expect(normal(readBody(doc))).toBe(normal(md));
    expect(normal(normal(md))).toBe(normal(md));
  });
  test('turning a body into a new text changes only what differs', () => {
    const doc = new Y.Doc();
    writeBody(doc, 'One.\n\nTwo.\n\nThree.', 'x');
    const frag = doc.getXmlFragment(BODY);
    const first = frag.get(0), last = frag.get(2);
    writeBody(doc, 'One.\n\nTwo, changed.\n\nThree.', 'x');
    expect(frag.get(0)).toBe(first);
    expect(frag.get(2)).toBe(last);
    expect(readBody(doc)).toBe('One.\n\nTwo, changed.\n\nThree.');
  });
});

describe('what people type reaches the memory', () => {
  test('once, in a pause, as what changed and nothing else', async () => {
    const j = await join();
    typeInto(j, (d) => { d.getText(TITLE).insert(4, ' Corp'); });
    await tick(500);
    typeInto(j, (d) => { d.getText(TITLE).insert(9, 'oration'); });
    await tick(1000);
    expect(patches()).toHaveLength(0);
    await tick(600);
    expect(patches()).toHaveLength(1);
    expect(patches()[0].body).toEqual({ title: 'Acme Corporation' });
    expect(told.some((t) => t.event === 'saved' && t.data.version === 2)).toBe(true);
    j.leave();
  });
  test('someone who never pauses is still saved', async () => {
    const j = await join();
    for (let i = 0; i < 14; i += 1) {
      typeInto(j, (d) => { d.getText(TITLE).insert(0, 'x'); });
      await tick(1000);
    }
    expect(patches().length).toBeGreaterThanOrEqual(1);
    j.leave();
  });
  test('opening and closing a record writes nothing', async () => {
    const j = await join();
    await tick(3000);
    j.leave();
    await tick(3000);
    expect(patches()).toHaveLength(0);
  });
  test('what a person typed is saved when they leave, without waiting for the pause', async () => {
    const j = await join();
    typeInto(j, (d) => { d.getText(TITLE).insert(4, '!'); });
    j.leave();
    await tick(10);
    expect(patches()).toHaveLength(1);
  });
  test('a person’s edit reaches everyone else and isn’t sent back to them', async () => {
    const a = await join();
    const rid = a.rid;
    const bTold: string[] = [];
    const bLeave = await hub.join('m1', rid, 'conn-b-aaaaaaaa', who, (e) => { if (e) bTold.push(e); }, () => {});
    told.length = 0;
    typeInto(a, (d) => { d.getText(TITLE).insert(0, 'Z'); });
    expect(bTold).toContain('u');
    expect(told.filter((t) => t.event === 'u')).toHaveLength(0);
    a.leave(); bLeave();
  });
  test('a provider’s refusal is said once, and not tried again', async () => {
    const j = await join();
    patchAnswer = () => ({ status: 422, body: { error: { message: 'A title is one line.' } } });
    typeInto(j, (d) => { d.getText(TITLE).insert(0, 'Z'); });
    await tick(2000);
    expect(told.find((t) => t.event === 'refused')?.data.message).toBe('A title is one line.');
    const n = patches().length;
    await tick(60_000);
    expect(patches()).toHaveLength(n);
    j.leave();
  });
  test('a provider that’s down is tried again, and the page knows', async () => {
    const j = await join();
    let down = true;
    const up = patchAnswer;
    patchAnswer = (b) => (down ? { status: 503, body: {} } : up(b));
    typeInto(j, (d) => { d.getText(TITLE).insert(0, 'Z'); });
    await tick(2000);
    expect(told.some((t) => t.event === 'unsaved')).toBe(true);
    down = false;
    await tick(10_000);
    expect(told.some((t) => t.event === 'saved' && t.data.version === 2)).toBe(true);
    expect(record.title).toBe('ZAcme');
    j.leave();
  });
  test('someone who may only read can’t change it, whatever they send', async () => {
    privileges = ['read'];
    const j = await join();
    expect(j.hello.canWrite).toBe(false);
    expect(() => typeInto(j, (d) => { d.getText(TITLE).insert(0, 'Z'); })).toThrow(Refused);
    await tick(3000);
    expect(patches()).toHaveLength(0);
    j.leave();
  });
  test('someone who may not read it doesn’t get in', async () => {
    privileges = [];
    await expect(join()).rejects.toThrow(Refused);
  });
});

describe('what an agent writes reaches whoever has it open', () => {
  const wrote = async (j: { rid: string }, change: object) => {
    record = { ...record, ...change, version: Number(record.version) + 1, written_by: agent };
    event({ type: 'record.revised', record_id: j.rid, version: record.version, written_by: agent });
    await tick(5);
  };
  test('it arrives in the document, as an edit, and isn’t written back', async () => {
    const j = await join();
    await tick(5);
    await wrote(j, { content: [{ type: 'text', text: 'First paragraph.\n\nSecond paragraph, from the agent.' }] });
    expect(received(j).body).toBe('First paragraph.\n\nSecond paragraph, from the agent.');
    await tick(5000);
    expect(patches()).toHaveLength(0);
    expect(told.some((t) => t.event === 'saved' && t.data.version === 2)).toBe(true);
    j.leave();
  });
  test('the agent stands in the document for a moment, at what it changed', async () => {
    const j = await join();
    await tick(5);
    await wrote(j, { title: 'Acme, renamed' });
    expect(received(j).title).toBe('Acme, renamed');
    expect(told.filter((t) => t.event === 'a').length).toBeGreaterThan(0);
    j.leave();
  });
  test('a person’s unsaved typing elsewhere survives it, and both reach the memory', async () => {
    const j = await join();
    await tick(5);
    typeInto(j, (d) => { writeBody(d, 'First paragraph, typed by a person.\n\nSecond paragraph.', 'p'); });
    await wrote(j, { content: [{ type: 'text', text: 'First paragraph.\n\nSecond paragraph, from the agent.' }] });
    expect(received(j).body).toBe('First paragraph, typed by a person.\n\nSecond paragraph, from the agent.');
    await tick(3000);
    const c = patches().pop()?.body?.content as { text: string }[];
    expect(c[0].text).toBe('First paragraph, typed by a person.\n\nSecond paragraph, from the agent.');
    j.leave();
  });
  test('both changing the same paragraph keeps both, for a person to settle', async () => {
    const j = await join();
    await tick(5);
    typeInto(j, (d) => { writeBody(d, 'First paragraph, the person’s.\n\nSecond paragraph.', 'p'); });
    await wrote(j, { content: [{ type: 'text', text: 'First paragraph, the agent’s.\n\nSecond paragraph.' }] });
    const body = received(j).body;
    expect(body).toContain('the person’s');
    expect(body).toContain('the agent’s');
    expect(body).toContain('Second paragraph.');
    j.leave();
  });
  test('a write that crossed another is told so by the service: the two are merged and saved together', async () => {
    const j = await join();
    await tick(5);
    expect(record.version).toBe(1);
    typeInto(j, (d) => { writeBody(d, 'First paragraph, typed by a person.\n\nSecond paragraph.', 'p'); });
    // the agent's write lands at the provider first; its event is still on its way when this console's save goes
    const up = patchAnswer;
    patchAnswer = (b) => {
      if (Number(b.__seen) === 0) return up(b);
      if (record.version === 1) {
        record = { ...record, content: [{ type: 'text', text: 'First paragraph.\n\nSecond paragraph, from the agent.' }], version: 2, written_by: agent };
        return { status: 412, body: { error: { code: 'memory_version_moved', message: 'moved' } } };
      }
      return up(b);
    };
    await tick(2000);
    expect(patches()[0].match).toBe('1');
    await tick(2000);
    const last = patches().pop()!;
    expect(last.match).toBe('2');
    expect((last.body?.content as { text: string }[])[0].text).toBe('First paragraph, typed by a person.\n\nSecond paragraph, from the agent.');
    expect(received(j).body).toBe('First paragraph, typed by a person.\n\nSecond paragraph, from the agent.');
    j.leave();
  });
  test('this console’s own save, told back to it, changes nothing', async () => {
    const j = await join();
    await tick(5);
    typeInto(j, (d) => { d.getText(TITLE).insert(4, '!'); });
    await tick(2000);
    told.length = 0;
    event({ type: 'record.revised', record_id: j.rid, version: 2, written_by: { kind: 'member', id: 'ada', type: 'human' } });
    await tick(5);
    expect(told.filter((t) => t.event === 'u')).toHaveLength(0);
    await tick(3000);
    expect(patches()).toHaveLength(1);
    j.leave();
  });
  test('a provider that keeps its own wording: the page comes to say what it holds, without a loop', async () => {
    const j = await join();
    await tick(5);
    patchAnswer = (b) => {
      record = { ...record, ...b, title: String(b.title).toUpperCase(), version: Number(record.version) + 1 };
      return { status: 200, body: record };
    };
    typeInto(j, (d) => { d.getText(TITLE).insert(4, ' corp'); });
    await tick(2000);
    expect(received(j).title).toBe('ACME CORP');
    await tick(10_000);
    expect(patches()).toHaveLength(1);
    j.leave();
  });
  test('forgotten while open: the page is told, and nothing more is saved', async () => {
    const j = await join();
    await tick(5);
    record = { ...record, status: 'forgotten' };
    event({ type: 'record.forgotten', record_id: j.rid });
    await tick(5);
    expect(told.some((t) => t.event === 'gone')).toBe(true);
    expect(() => typeInto(j, (d) => { d.getText(TITLE).insert(0, 'Z'); })).toThrow(Refused);
    await tick(3000);
    expect(patches()).toHaveLength(0);
    j.leave();
  });
  test('an event about another record leaves this one alone', async () => {
    const j = await join();
    await tick(5);
    const reads = sent.filter((s) => s.method === 'GET' && s.path.includes(`/records/${j.rid}`)).length;
    event({ type: 'record.revised', record_id: 'someone-else', version: 9 });
    await tick(5);
    expect(sent.filter((s) => s.method === 'GET' && s.path.includes(`/records/${j.rid}`))).toHaveLength(reads);
    j.leave();
  });
  test('a job that finished or a reader told to catch up reads again', async () => {
    const j = await join();
    await tick(5);
    record = { ...record, title: 'After the job', version: 5 };
    event({ type: 'records.changed', record_ids: [] });
    await tick(5);
    expect(received(j).title).toBe('After the job');
    j.leave();
  });
});

describe('merging', () => {
  test('what only one side touched is kept', () => {
    expect(mergeText('a!\n\nb', 'a\n\nb', 'a\n\nb?')).toBe('a!\n\nb?');
    expect(mergeText('a', 'a', 'b')).toBe('b');
    expect(mergeText('b', 'a', 'a')).toBe('b');
  });
  test('the same paragraph changed on both sides keeps both', () => {
    const m = mergeText('a1\n\nb', 'a\n\nb', 'a2\n\nb');
    expect(m).toContain('a1'); expect(m).toContain('a2'); expect(m).toContain('b');
  });
  test('a title is one line: a person’s unsaved change stands', () => {
    expect(mergeTitle('mine', 'old', 'theirs')).toBe('mine');
    expect(mergeTitle('old', 'old', 'theirs')).toBe('theirs');
  });
});
