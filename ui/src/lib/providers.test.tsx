/** @jest-environment jsdom */
// Which of the organization's keys serves each model: until the document is read, and when it cannot be
// read (after a few tries), the hook says the keys are not known, so no surface tells someone who has a
// key that a model runs on credit.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/chat', () => ({ authHeaders: () => ({}) }));

import { harnessFetch } from '@/lib/hfetch';
import { PROVIDERS_TRIES, useModelProviders, type ModelProviders } from './providers';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const fetchMock = harnessFetch as jest.Mock;
const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });
const DOC = { integrations: [{ name: 'mine', provider: 'anthropic' }], model_map: { 'claude-sonnet-4': 'mine' } };

let root: Root;
let el: HTMLElement;
let seen: ModelProviders;
function Probe() { seen = useModelProviders(); return null; }
async function mount() {
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<Probe />); });
}
const settle = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve(); }); };

beforeEach(() => { jest.useFakeTimers(); fetchMock.mockReset(); });
afterEach(() => { act(() => root.unmount()); el.remove(); jest.useRealTimers(); });

test('the document read: each model\'s key, and ready', async () => {
  fetchMock.mockResolvedValue(json(DOC));
  await mount();
  await settle();
  expect(seen.state).toBe('ready');
  expect(seen.connectionFor('claude-sonnet-4')).toEqual({ name: 'mine', provider: 'anthropic' });
  expect(seen.connectionFor('gpt-5')).toBeNull();
  expect(seen.hasConnections).toBe(true);
});

test('loading until it lands; a failed read is asked again, and a later answer is believed', async () => {
  fetchMock.mockResolvedValueOnce(json({ detail: 'down' }, 503)).mockResolvedValue(json(DOC));
  await mount();
  expect(seen.state).toBe('loading');
  await settle();
  expect(seen.state).toBe('loading');                 // retrying, still not known
  await act(async () => { jest.advanceTimersByTime(1000); });
  await settle();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(seen.state).toBe('ready');
});

test('reads that keep failing end as failed: the keys are not known, never "everything runs on credit" as an answer', async () => {
  fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ model_map: {} }) });   // not the document
  await mount();
  for (let i = 0; i < PROVIDERS_TRIES; i++) {
    await settle();
    await act(async () => { jest.advanceTimersByTime(10_000); });
  }
  await settle();
  expect(fetchMock).toHaveBeenCalledTimes(PROVIDERS_TRIES);
  expect(seen.state).toBe('failed');
  expect(seen.connectionFor('claude-sonnet-4')).toBeNull();
  expect(seen.hasConnections).toBe(false);
});
