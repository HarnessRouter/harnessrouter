// The star count beside "Star us on GitHub": GitHub's, kept ten minutes. When GitHub does not answer once
// that time is up there is no number (502), never the remembered count served as current; the shell then
// shows no count.
export {};
const originalFetch = global.fetch;
let route: typeof import('./route');
beforeEach(() => { jest.resetModules(); jest.useFakeTimers(); route = require('./route'); global.fetch = jest.fn(); });
afterEach(() => { jest.useRealTimers(); });
afterAll(() => { global.fetch = originalFetch; });

const github = (stars: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify({ stargazers_count: stars }), { status }));

test('GitHub\'s count, and the same count within ten minutes without asking again', async () => {
  (fetch as jest.Mock).mockImplementation(() => github(1234));
  const a = await route.GET();
  expect(a.status).toBe(200);
  expect(await a.json()).toEqual({ stars: 1234, repo: 'HarnessRouter/harnessrouter' });
  jest.advanceTimersByTime(5 * 60 * 1000);
  const b = await route.GET();
  expect(await b.json()).toEqual({ stars: 1234, repo: 'HarnessRouter/harnessrouter' });
  expect(fetch).toHaveBeenCalledTimes(1);
});

test('GitHub not answering after the ten minutes: 502 and no number, never the old count', async () => {
  (fetch as jest.Mock).mockImplementation(() => github(1234));
  await route.GET();
  jest.advanceTimersByTime(11 * 60 * 1000);
  (fetch as jest.Mock).mockImplementation(() => github(null, 403));
  const r = await route.GET();
  expect(r.status).toBe(502);
  const body = await r.json();
  expect(body.stars).toBeUndefined();
  expect(body.stale).toBeUndefined();
});

test('no count ever read and GitHub down: 502', async () => {
  (fetch as jest.Mock).mockImplementation(() => Promise.reject(new TypeError('fetch failed')));
  const r = await route.GET();
  expect(r.status).toBe(502);
  expect((await r.json()).stars).toBeUndefined();
});
