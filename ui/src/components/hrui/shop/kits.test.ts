// The Shop's kit catalog reads (shop/kits). What this organization can run is read from the server or
// the read fails: never "nothing can run". A launched kit names what its setup really runs (the launch's
// own answer, or the catalog's), or nothing; never the suggestion in its place.
jest.mock('@/lib/chat', () => ({ authHeaders: () => ({}) }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => null }));
jest.mock('@/lib/workspace', () => ({ syncWorkspaceCookie: () => {} }));

import { harnessFetch } from '@/lib/hfetch';
import { fetchKitBases, launchKit, runtimeOf, type Kit } from './kits';

const fetchMock = harnessFetch as jest.Mock;
const KIT = (over: Partial<Kit> = {}): Kit => ({
  id: 'dashboard', title: 'Dashboard', tagline: '', description: '', icon: '', accent: '', route: '/kits/dashboard', iconUrl: '',
  launched: false, harnessId: null, skills: [], runningOn: null,
  choices: [{ base: 'claude-code', model: 'opus', baseLabel: 'Claude Code', available: true, recommended: true }],
  ...over,
});

beforeEach(() => fetchMock.mockReset());

describe('fetchKitBases', () => {
  it('is the server’s list', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ bases: [{ id: 'codex', label: 'Codex', models: [] }] }) });
    expect(await fetchKitBases()).toEqual([{ id: 'codex', label: 'Codex', models: [] }]);
  });
  it('throws when the read fails or answers no list', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 503, json: async () => ({}) });
    await expect(fetchKitBases()).rejects.toThrow('503');
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    await expect(fetchKitBases()).rejects.toThrow();
  });
});

describe('launchKit', () => {
  it('hands back what the setup runs on, from the launch’s own answer', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ harnessId: 'h1', route: '/kits/dashboard', created: true, harness: { base: 'codex', defaultModel: 'gpt-b' } }) });
    expect(await launchKit('dashboard', { base: 'codex', model: 'gpt-b' })).toEqual({ harnessId: 'h1', route: '/kits/dashboard', created: true, runningOn: { base: 'codex', model: 'gpt-b' } });
  });
  it('an answer without the setup names nothing it runs on', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ harnessId: 'h1', route: '', created: false }) });
    expect((await launchKit('dashboard')).runningOn).toBeNull();
  });
});

describe('runtimeOf', () => {
  it('a kit not launched shows the pairing it suggests', () => {
    expect(runtimeOf(KIT())).toEqual({ base: 'claude-code', label: 'Claude Code', model: 'opus', suggested: true });
  });
  it('a launched kit shows what it runs on, else nothing; never the suggestion', () => {
    expect(runtimeOf(KIT({ launched: true, runningOn: { base: 'codex', model: 'gpt-b' } }), [{ id: 'codex', label: 'Codex', models: [] }]))
      .toEqual({ base: 'codex', label: 'Codex', model: 'gpt-b', suggested: false });
    expect(runtimeOf(KIT({ launched: true, runningOn: null }))).toBeNull();
  });
});
