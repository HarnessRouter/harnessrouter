/** @jest-environment jsdom */
// Harness Studio's list reads its setups again when it is told one was made in this tab (SETUPS_EVENT, as
// start/build.ts tells it when a build lands while the person is on Studio). Told of a setup its rows
// already show, it reads nothing more.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  listCustom: jest.fn(), loadBases: jest.fn(async () => null), getHarnessPlugs: jest.fn(), readCustom: jest.fn(),
}));
jest.mock('@/lib/revamp-data', () => ({
  ...jest.requireActual('@/lib/revamp-data'),
  fetchHarnessTasks: jest.fn(async () => ({ sessions: [], cursor: '' })),
}));
jest.mock('@/lib/use-workspace-feed', () => ({ useWorkspaceFeed: () => ({ paused: false, reconnect: () => undefined }) }));

import { listCustom } from '@/lib/harness';
import { SETUPS_EVENT, useSetups, type SetupRow } from './setups';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const list = listCustom as jest.Mock;
const A = { id: 'chrn_a', name: 'Alpha', base: 'hermes', createdAt: 1 };
const B = { id: 'chrn_b', name: 'Greetings', base: 'hermes', createdAt: 2 };
let rows: SetupRow[] | null = null;
function Probe() { rows = useSetups().rows; return null; }

let root: Root;
let el: HTMLElement;
const settle = () => act(async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setTimeout(r, 0)); });
const tell = (detail?: { id: string }) => act(async () => { window.dispatchEvent(new CustomEvent(SETUPS_EVENT, { detail })); });
const names = () => (rows || []).map((r) => r.h.name).sort();

beforeEach(async () => {
  list.mockReset();
  list.mockResolvedValue([A]);
  rows = null;
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<Probe />); });
  await settle();
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('told of a harness it does not show, the list reads its harnesses again and shows it', async () => {
  expect(names()).toEqual(['Alpha']);
  list.mockResolvedValue([B, A]);
  await tell({ id: 'chrn_b' });
  await settle();
  expect(list).toHaveBeenCalledTimes(2);
  expect(names()).toEqual(['Alpha', 'Greetings']);
});

test('told of a harness it already shows, it reads nothing more; told of a change with no harness named, it reads again', async () => {
  await tell({ id: 'chrn_a' });
  await settle();
  expect(list).toHaveBeenCalledTimes(1);
  await tell();
  await settle();
  expect(list).toHaveBeenCalledTimes(2);
});
