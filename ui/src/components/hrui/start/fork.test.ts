// A recorded first task, written to, goes on as a task of your own: the request's input carries the
// recording as the earlier messages, then the new message with the run's files. Only where the server
// says it takes input history: anywhere else (this edition's gateway today) none is offered, and the
// recorded task keeps its read-only bar. The run here is a test fixture: no page ever shows one.
const mockDoc: { doc: Record<string, unknown> | null } = { doc: null };
jest.mock('@/lib/harness', () => ({ basesDoc: async () => mockDoc.doc }));

import { FILE_RETRY_MS, forkFiles, ForkFilesError, forkInput, forkOffered, importedFirst, inputHistory, INPUT_HISTORY_FLAG } from './fork';
import type { RecordedRun } from './replay';

const RUN = { request: 'Make a product image of a mug.', files: [] } as unknown as RecordedRun;

describe('a fork of a recorded run', () => {
  test('its input: the recorded request and answer, then the new message with the files', () => {
    const inp = forkInput(RUN, 'Done. Best image: mug-v3.png', 'Make the background pure white.',
      [{ name: 'mug-v3.png', dataUri: 'data:image/png;base64,AAAA' }], [{ name: 'brand.pdf', dataUri: 'data:application/pdf;base64,BBBB' }]);
    expect(inp).toEqual([
      { role: 'user', content: [
        { type: 'input_text', text: 'Make a product image of a mug.' },
        { type: 'input_file', filename: 'mug-v3.png', file_data: 'data:image/png;base64,AAAA' },
      ] },
      { role: 'assistant', content: 'Done. Best image: mug-v3.png' },
      { role: 'user', content: [
        { type: 'input_text', text: 'Make the background pure white.' },
        { type: 'input_file', filename: 'brand.pdf', file_data: 'data:application/pdf;base64,BBBB' },
      ] },
    ]);
  });
  test('kept whole only when its first turn reads back imported', () => {
    expect(importedFirst([{ imported: true }, {}])).toBe(true);
    expect(importedFirst([{ user: 'Make a product image of a mug.' }])).toBe(false);
    expect(importedFirst([])).toBe(false);
  });
  test('the read-back guard: nothing has said otherwise (no browser storage here)', () => {
    expect(forkOffered()).toBe(true);
  });
  test('the discovery flag is one name', () => {
    expect(INPUT_HISTORY_FLAG).toBe('input_history');
  });
});

describe('whether a fork is offered', () => {
  test('only where the bases document says the server takes input history', async () => {
    mockDoc.doc = { object: 'list', bases: [] };                       // a server that does not say so
    expect(await inputHistory()).toBe(false);
    mockDoc.doc = null;                                               // one whose document could not be read
    expect(await inputHistory()).toBe(false);
    mockDoc.doc = { bases: [], capabilities: { input_history: 'yes' } };   // only true is a yes
    expect(await inputHistory()).toBe(false);
    mockDoc.doc = { bases: [], capabilities: { input_history: true } };
    expect(await inputHistory()).toBe(true);
    mockDoc.doc = { bases: [], input_history: true };
    expect(await inputHistory()).toBe(true);
  });
});


describe('the recorded files a fork carries', () => {
  const FILES = { request: 'x', files: [
    { name: 'out/mug-v3.png', mime: 'image/png', bytes: 3, src: '/demos/product/mug-v3.png' },
    { name: 'brief.txt', mime: 'text/plain', bytes: 2, src: '/demos/product/brief.txt' },
  ] } as unknown as RecordedRun;
  const realFetch = globalThis.fetch;
  let answers: Record<string, (() => Promise<Response>)[]>;
  beforeAll(() => {
    // the browser's FileReader, as far as a fork uses it
    class FR {
      result: string | null = null; error: Error | null = null;
      onload: (() => void) | null = null; onerror: (() => void) | null = null;
      readAsDataURL(b: Blob) { void b.arrayBuffer().then((buf) => { this.result = `data:${b.type};base64,${Buffer.from(buf).toString('base64')}`; this.onload?.(); }); }
    }
    Object.assign(globalThis, { FileReader: FR });
  });
  beforeEach(() => {
    jest.useFakeTimers();
    answers = {};
    globalThis.fetch = jest.fn(async (src: string) => {
      const next = answers[src]?.shift();
      return next ? next() : new Response(new Blob(['ok'], { type: 'text/plain' }));
    }) as unknown as typeof fetch;
  });
  afterEach(() => { jest.useRealTimers(); globalThis.fetch = realFetch; });
  const down = () => Promise.resolve(new Response('', { status: 503 }));
  const offline = () => Promise.reject(new TypeError('Failed to fetch'));

  test('every file, as data, by its own name', async () => {
    const out = await forkFiles(FILES);
    expect(out).toEqual([{ name: 'mug-v3.png', dataUri: 'data:text/plain;base64,b2s=' }, { name: 'brief.txt', dataUri: 'data:text/plain;base64,b2s=' }]);
  });

  test('a read that fails is tried again, and the file comes', async () => {
    answers['/demos/product/mug-v3.png'] = [down, offline];
    const p = forkFiles(FILES);
    await jest.advanceTimersByTimeAsync(FILE_RETRY_MS.reduce((a, b) => a + b, 0));
    expect((await p).map((f) => f.name)).toEqual(['mug-v3.png', 'brief.txt']);
  });

  test('a file that still cannot be read fails the fork, naming it; none is left out silently', async () => {
    answers['/demos/product/mug-v3.png'] = [down, down, down, down];
    const p = forkFiles(FILES);
    const seen = p.then(() => null, (e: unknown) => e);
    await jest.advanceTimersByTimeAsync(FILE_RETRY_MS.reduce((a, b) => a + b, 0));
    const e = await seen;
    expect(e).toBeInstanceOf(ForkFilesError);
    expect((e as ForkFilesError).names).toEqual(['mug-v3.png']);
  });
});
