/** @jest-environment jsdom */
// A key create the gateway refuses: its own sentence, naming who can by role, goes to the
// caller to say under its name field (keyRefusal reads it from the gateway's error body); with no caller to
// say it, it is the toast. Anything that is not a refusal (a 5xx, a body that is not the gateway's) keeps
// the one line "The key could not be created. Try again." and never shows what the service answered.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org1', member: { email: 'dana@example.com' } }) }));
jest.mock('@/lib/workspace', () => ({ useWorkspace: () => ({ current: { id: 'ws2', name: 'PhotoMagic' }, defaultId: 'ws1' }) }));
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }));
jest.mock('@/lib/settle', () => ({ readSettled: (read: (s: AbortSignal) => Promise<unknown>) => read(new AbortController().signal) }));
jest.mock('../toast', () => ({ toast: jest.fn() }));

import { harnessFetch } from '@/lib/hfetch';
import { toast } from '../toast';
import { keyRefusal, useWsKeys, type KeysState } from './keys';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const FORBIDDEN = "You don't have access to this workspace. Ask its admin to add you.";
const fetchMock = harnessFetch as jest.Mock;
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const gw = (status: number, message: string) => ({ ok: false, status, json: async () => ({ error: { message }, detail: message }) });
let root: Root;
let el: HTMLElement;
let state: KeysState;
function Probe() { state = useWsKeys(); return null; }
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

beforeEach(async () => {
  fetchMock.mockReset();
  (toast as jest.Mock).mockClear();
  fetchMock.mockResolvedValue(ok({ keys: [] }));
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<Probe />); });
  await flush();
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

describe('keyRefusal', () => {
  it('reads the gateway’s sentence from a 403 or a 409, its error message first, then its detail', () => {
    expect(keyRefusal(403, { error: { message: FORBIDDEN }, detail: 'older words' })).toBe(FORBIDDEN);
    expect(keyRefusal(403, { detail: 'An API key is made in your own name.' })).toBe('An API key is made in your own name.');
    expect(keyRefusal(409, { error: { message: 'This workspace is archived. Unarchive it to keep working here.' } }))
      .toBe('This workspace is archived. Unarchive it to keep working here.');
  });
  it('gives nothing for anything that is not a refusal written for a person', () => {
    expect(keyRefusal(503, { error: { message: 'Your role in this organization could not be checked just now.' } })).toBe('');
    expect(keyRefusal(401, { detail: 'invalid session token' })).toBe('');
    expect(keyRefusal(422, { detail: [{ loc: ['body', 'name'], msg: 'x' }] })).toBe('');
    expect(keyRefusal(403, null)).toBe('');
    expect(keyRefusal(403, 'Forbidden')).toBe('');
    expect(keyRefusal(403, { detail: '   ' })).toBe('');
  });
});

it('a refused create hands the gateway’s sentence to the caller, toasts nothing and makes no key', async () => {
  fetchMock.mockResolvedValueOnce(gw(403, FORBIDDEN));
  const said = jest.fn();
  let r: unknown = 'unset';
  await act(async () => { r = await state.create('ci', 'keys', said); });
  expect(r).toBeNull();
  expect(said).toHaveBeenCalledWith(FORBIDDEN);
  expect(toast).not.toHaveBeenCalled();
  expect(state.busy).toBe(false);
});

it('with no caller to say it, the refusal is the toast', async () => {
  fetchMock.mockResolvedValueOnce(gw(403, FORBIDDEN));
  await act(async () => { await state.create('ci', 'keys'); });
  expect(toast).toHaveBeenCalledWith(FORBIDDEN);
});

it('a failure that is not a refusal keeps its own line and never hands the caller the service’s words', async () => {
  fetchMock.mockResolvedValueOnce({ ok: false, status: 502, json: async () => ({ detail: 'harness-gateway unreachable: reset' }) });
  const said = jest.fn();
  await act(async () => { await state.create('ci', 'keys', said); });
  expect(said).not.toHaveBeenCalled();
  expect(toast).toHaveBeenCalledWith('The key could not be created. Try again.');
});
