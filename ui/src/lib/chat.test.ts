// The conversation's transport (lib/chat): a task's record read either answers, says the task is gone
// (404), or THROWS (never an empty task in place of a failed read); a turn's own stream and a setup's
// live feed each end when nothing at all arrives for 45 s (the server writes a keepalive every 15 s),
// and the feed connects again with backoff, telling its listener each time it is up.
import type { BusMsg, BusState, StreamHandlers } from './chat';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org.a', member: { email: 'ana@example.com' } }) }));
jest.mock('@/lib/workspace', () => ({ workspaceHeaders: () => ({}) }));

import { harnessFetch } from '@/lib/hfetch';
import { loadSessionTurns, streamResponse, subscribeHarnessEvents, TurnsReadError, STREAM_IDLE_MS, BUS_BACKOFF_MAX_MS } from './chat';

const hf = harnessFetch as jest.MockedFunction<typeof harnessFetch>;
const enc = new TextEncoder();
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'content-type': 'application/json' } });

/** A gateway stream the test writes to, as the server would. */
function sse() {
  let ctl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(c) { ctl = c; } });
  return {
    res: new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
    send: (s: string) => ctl.enqueue(enc.encode(s)),
    hello: () => ctl.enqueue(enc.encode(': connected\n\n')),
    keepalive: () => ctl.enqueue(enc.encode(': keepalive\n\n')),
    data: (o: unknown) => ctl.enqueue(enc.encode(`data: ${JSON.stringify(o)}\n\n`)),
    end: () => ctl.close(),
  };
}
const tick = async (ms = 0) => { await jest.advanceTimersByTimeAsync(ms); };

beforeEach(() => { hf.mockReset(); });

describe('loadSessionTurns', () => {
  test('the record: its turns and the last response', async () => {
    hf.mockResolvedValueOnce(json({ turns: [{ id: 'r1', status: 'completed', user: 'hi', assistant: 'yo', tools: [], files: [] }], last_response_id: 'r1' }));
    await expect(loadSessionTurns('s1')).resolves.toEqual({
      turns: [{ id: 'r1', status: 'completed', user: 'hi', assistant: 'yo', tools: [], files: [] }], lastResponseId: 'r1' });
    expect(hf.mock.calls[0][0]).toBe('/api/harness/v1/sessions/s1/turns?limit=200');
  });

  test('a 404 is the one "nothing here" answer: the task is gone', async () => {
    hf.mockResolvedValueOnce(json({ detail: 'Not Found' }, 404));
    await expect(loadSessionTurns('s1')).resolves.toEqual({ turns: [], lastResponseId: null, missing: true });
  });

  test.each([
    ['a 5xx', () => json({ detail: 'store timeout' }, 503)],
    ['a body that is not JSON', () => new Response('<html>ok</html>', { status: 200 })],
    ['JSON that is not the turns', () => json({ detail: 'x' })],
  ])('%s throws, never an empty task', async (_, res) => {
    hf.mockResolvedValueOnce(res());
    await expect(loadSessionTurns('s1')).rejects.toBeInstanceOf(TurnsReadError);
  });

  test('the network failing throws', async () => {
    hf.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await expect(loadSessionTurns('s1')).rejects.toThrow('Failed to fetch');
  });

  test('a caller’s deadline goes with the request', async () => {
    hf.mockResolvedValueOnce(json({ turns: [], last_response_id: null }));
    const c = new AbortController();
    await loadSessionTurns('s1', c.signal);
    expect(hf.mock.calls[0][1]?.signal).toBe(c.signal);
  });
});

describe('a turn’s own stream', () => {
  beforeEach(() => { jest.useFakeTimers(); });
  afterEach(() => { jest.useRealTimers(); });

  test('silent for 45 s, not even a keepalive: the read ends without a terminal event, the response id kept', async () => {
    const s = sse();
    hf.mockResolvedValueOnce(s.res);
    const done = jest.fn();
    const h: StreamHandlers = { onDone: done, onTextDelta: jest.fn() };
    let out: string | null | undefined;
    void streamResponse({ input: 'hi' }, h).then((id) => { out = id; });
    await tick();
    s.data({ type: 'response.created', response: { id: 'resp_1', metadata: { session_id: 's1' } } });
    s.data({ type: 'response.output_text.delta', delta: 'Hel' });
    // the keepalives hold it open past the deadline
    for (let i = 0; i < 4; i++) { await tick(15_000); s.keepalive(); }
    await tick();
    expect(out).toBeUndefined();
    expect(h.onTextDelta).toHaveBeenCalledWith('Hel');
    await tick(STREAM_IDLE_MS - 1);
    expect(out).toBeUndefined();
    await tick(1);
    expect(out).toBe('resp_1');
    expect(done).not.toHaveBeenCalled();
  });

  test('a stream that ends normally returns at its end', async () => {
    const s = sse();
    hf.mockResolvedValueOnce(s.res);
    const done = jest.fn();
    let out: string | null | undefined;
    void streamResponse({ input: 'hi' }, { onDone: done }).then((id) => { out = id; });
    await tick();
    s.data({ type: 'response.created', response: { id: 'resp_2' } });
    s.data({ type: 'response.completed', response: { id: 'resp_2', status: 'completed' } });
    s.end();
    await tick();
    expect(out).toBe('resp_2');
    expect(done).toHaveBeenCalledWith('completed', expect.anything());
  });
});

describe('a setup’s live feed', () => {
  let random: jest.SpyInstance;
  beforeEach(() => { jest.useFakeTimers(); random = jest.spyOn(Math, 'random').mockReturnValue(0.5); });
  afterEach(() => { random.mockRestore(); jest.useRealTimers(); });

  function listen() {
    const msgs: BusMsg[] = [];
    const states: BusState[] = [];
    const stop = subscribeHarnessEvents('h1', (m) => msgs.push(m), (s) => states.push(s));
    return { msgs, states, stop };
  }

  test('up only once the server says it is connected; frames reach the listener', async () => {
    const s = sse();
    hf.mockResolvedValueOnce(s.res);
    const l = listen();
    await tick();
    expect(hf.mock.calls[0][0]).toBe('/api/harness/v1/harnesses/h1/events');
    expect(l.states).toEqual([]);
    s.hello();
    await tick();
    expect(l.states).toEqual(['up']);
    s.data({ session_id: 's1', response_id: 'r1', event: { type: 'response.output_text.delta', delta: 'x' } });
    await tick();
    expect(l.msgs).toEqual([{ session_id: 's1', response_id: 'r1', event: { type: 'response.output_text.delta', delta: 'x' } }]);
    l.stop();
  });

  test('silent for 45 s (no keepalive): dropped, connected again, and the listener hears it come up again', async () => {
    const a = sse(), b = sse();
    hf.mockResolvedValueOnce(a.res).mockResolvedValueOnce(b.res);
    const l = listen();
    await tick();
    a.hello();
    await tick();
    // keepalives every 15 s hold it
    for (let i = 0; i < 4; i++) { await tick(15_000); a.keepalive(); }
    await tick();
    expect(hf).toHaveBeenCalledTimes(1);
    await tick(STREAM_IDLE_MS);
    expect(l.states).toEqual(['up', 'down']);
    await tick(1000);                                   // the first backoff
    expect(hf).toHaveBeenCalledTimes(2);
    b.hello();
    await tick();
    expect(l.states).toEqual(['up', 'down', 'up']);
    l.stop();
  });

  test('a refused connect is tried again with a doubling backoff, at most 30 s apart', async () => {
    hf.mockImplementation(async () => json({ detail: 'busy' }, 503));
    const l = listen();
    await tick();
    expect(hf).toHaveBeenCalledTimes(1);
    await tick(1000); expect(hf).toHaveBeenCalledTimes(2);
    await tick(2000); expect(hf).toHaveBeenCalledTimes(3);
    await tick(4000); expect(hf).toHaveBeenCalledTimes(4);
    await tick(8000 + 16000 + BUS_BACKOFF_MAX_MS); expect(hf).toHaveBeenCalledTimes(7);
    await tick(BUS_BACKOFF_MAX_MS); expect(hf).toHaveBeenCalledTimes(8);
    expect(l.states).toEqual([]);                       // never up
    l.stop();
    await tick(BUS_BACKOFF_MAX_MS);
    expect(hf).toHaveBeenCalledTimes(8);
  });

  test('a connect that never answers is given up at the deadline and tried again', async () => {
    const signals: AbortSignal[] = [];
    hf.mockImplementation((_, init) => new Promise((_r, reject) => {
      const sig = init?.signal as AbortSignal;
      signals.push(sig);
      sig.addEventListener('abort', () => reject(new Error('aborted')));
    }));
    const l = listen();
    await tick(STREAM_IDLE_MS);
    expect(signals[0].aborted).toBe(true);
    await tick(1000);
    expect(hf).toHaveBeenCalledTimes(2);
    l.stop();
  });
});
