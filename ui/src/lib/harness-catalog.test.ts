/** @jest-environment jsdom */
// The harnesses a person can pick and the models each one runs are the server's (Richard 10-19: no
// fallbacks): before the catalog lands the console's copy of it (held to the gateway's catalog by the
// gateway's own tests) is drawn, but nothing in it can be sent until the server says a provider serves
// it; and a setup saved with no model of its own keeps none.

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org.a', member: { email: 'ana@example.com' } }) }));
jest.mock('@/lib/workspace', () => ({ workspaceHeaders: () => ({}), appendWorkspaceQuery: () => {} }));

import { harnessFetch } from '@/lib/hfetch';

const hf = harnessFetch as jest.MockedFunction<typeof harnessFetch>;
const json = (b: unknown, status = 200) => ({ ok: status < 400, status, json: async () => b, headers: new Headers({ 'content-type': 'application/json' }) }) as unknown as Response;
const MODELS = { backends: { hermes: { default: 'gpt-5.4', models: [{ id: 'gpt-5.4' }, { id: 'glm-5.3', available: false }] } } };
const BASES = { bases: [{ id: 'hermes', label: 'Hermes', backend: 'hermes', models: [] }] };

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
// each test gets the module fresh (its catalog and bases are cached for the tab), with the React it uses
type R = typeof import('react');
type RD = typeof import('react-dom/client');
let React!: R;
let RDC!: RD;
function fresh() {
  let mod!: typeof import('./harness');
  jest.isolateModules(() => {
    mod = jest.requireActual('./harness');
    React = jest.requireActual('react');
    RDC = jest.requireActual('react-dom/client');
  });
  return mod;
}
const act = (f: () => unknown) => React.act(f as () => Promise<void>);
const flush = async () => { for (let i = 0; i < 8; i++) await act(async () => { await Promise.resolve(); }); };

beforeEach(() => { hf.mockReset(); jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick'] }); });
afterEach(() => { jest.useRealTimers(); });

test('before the catalog lands the placeholder copy is drawn, and none of it can run yet', () => {
  const h = fresh();
  const hermes = h.oobById('hermes');
  expect(h.oobModels(hermes)).toEqual(hermes?.models);
  expect(h.oobDefaultModel(hermes)).toBe(hermes?.defaultModel);
  expect(h.modelAvailability('hermes', 'gpt-5.4')).toBe('unknown');
  expect(h.modelAvailable('hermes', 'gpt-5.4')).toBe(false);
});

test('once it lands, the models and the default are the server\'s', async () => {
  const h = fresh();
  hf.mockResolvedValueOnce(json(MODELS));
  await h.fetchModelCatalog();
  const hermes = h.oobById('hermes');
  expect(h.oobModels(hermes)).toEqual(['gpt-5.4', 'glm-5.3']);
  expect(h.oobDefaultModel(hermes)).toBe('gpt-5.4');
  expect(h.modelAvailability('hermes', 'glm-5.3')).toBe('no');
});

test('no harness is offered until the server lists it, and only the ones it lists', () => {
  const h = fresh();
  expect(h.offeredOob(null)).toEqual([]);
  expect(h.offeredOob({}).length).toBe(0);
  const one = h.offeredOob({ hermes: BASES.bases[0] as unknown as import('./harness').BaseInfo });
  expect(one.map((o) => o.id)).toEqual(['hermes']);
});

test('a setup saved with no model of its own keeps none, whatever the catalog says', async () => {
  const h = fresh();
  hf.mockResolvedValueOnce(json(MODELS));
  await h.fetchModelCatalog();
  hf.mockResolvedValueOnce(json({ id: 'chrn_1', name: 'Support', base: 'hermes', default_model: '' }));
  await h.createCustom({ name: 'Support', base: 'hermes', defaultModel: '' });
  const body = JSON.parse(String((hf.mock.calls[1][1] as RequestInit).body));
  expect(JSON.stringify(body)).toContain('"default_model":""');
});

test('a catalog that cannot be read is failed (after its retries), and Try again reads it again', async () => {
  const h = fresh();
  hf.mockImplementation(async () => json({ detail: 'down' }, 502));
  let got: import('./harness').Read<import('./harness').ModelCatalog> | null = null;
  const Probe = () => { got = h.useModelCatalogRead(); return null; };
  const root = RDC.createRoot(document.createElement('div'));
  await act(async () => { root.render(React.createElement(Probe)); });
  for (let i = 0; i < 4; i++) { await act(async () => { jest.advanceTimersByTime(6000); }); await flush(); }
  expect(got!.value).toBeNull();
  expect(got!.failed).toBe(true);
  // it answers now: Try again
  hf.mockImplementation(async () => json(MODELS));
  await act(async () => { got!.retry(); });
  await flush();
  expect(got!.failed).toBe(false);
  expect(got!.value?.hermes.default).toBe('gpt-5.4');
  act(() => root.unmount());
});

test('bases that cannot be read are failed (after their retries), never the console\'s own list', async () => {
  const h = fresh();
  hf.mockImplementation(async () => json({ detail: 'down' }, 503));
  let got: import('./harness').Read<Record<string, import('./harness').BaseInfo>> | null = null;
  const Probe = () => { got = h.useBasesRead(); return null; };
  const root = RDC.createRoot(document.createElement('div'));
  await act(async () => { root.render(React.createElement(Probe)); });
  for (let i = 0; i < 3; i++) { await act(async () => { jest.advanceTimersByTime(3000); }); await flush(); }
  expect(got!.value).toBeNull();
  expect(got!.failed).toBe(true);
  expect(h.offeredOob(got!.value)).toEqual([]);
  act(() => root.unmount());
});

test('a setup list answer without the list is a failed read, never "no setups"', async () => {
  const h = fresh();
  hf.mockResolvedValueOnce(json({ detail: 'ok' }));
  await expect(h.listCustom()).rejects.toThrow('Your setups could not be read just now.');
  hf.mockResolvedValueOnce(json({ harnesses: [] }));
  await expect(h.listCustom()).resolves.toEqual([]);
});
