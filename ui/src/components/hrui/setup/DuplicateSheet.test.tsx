/** @jest-environment jsdom */
// Duplicate harness, in the sheet: Save sends the copy the harness's own MCP servers and its variables beside what it
// already sent, says before Save which server stays with the original, and says it again once saved. Until 0.41.14
// the sheet sent neither and told the person to add them again by hand.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { CustomHarness } from '@/lib/harness';

jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  createCustom: jest.fn(async (input: { name: string }) => ({ ...input, id: 'chrn_copy' })),
  getSkillFiles: jest.fn(async () => []),
  getPluginFiles: jest.fn(async () => []),
  setHarnessPlugs: jest.fn(async () => null),
  offeredOob: () => [{ id: 'dsh', name: 'DeepSeek Harness', backend: 'dsh', status: 'ready' }],
  oobModels: () => [],
  oobDefaultModel: () => '',
  useModelCatalogRead: () => ({ value: null, failed: false, retry: () => {} }),
}));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../Sheet', () => ({
  Sheet: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetTop: ({ title, sub }: { title: React.ReactNode; sub?: React.ReactNode }) => <header><h2>{title}</h2><p>{sub}</p></header>,
}));
let mockN = 0;
jest.mock('../mcp/McpSheet', () => ({ newMcpId: () => `mcp.new${++mockN}` }));

import * as harness from '@/lib/harness';
import { toast } from '../toast';
import { DuplicateSheet } from './settingsSheets';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const hx = harness as jest.Mocked<typeof harness>;

const ORIGINAL = {
  id: 'chrn_orig', name: 'notes-agent', base: 'dsh', baseLabel: 'DeepSeek Harness', defaultModel: '',
  systemPrompt: 'Answer from my notes.', skills: [], plugins: [], createdAt: 1,
  mcpServers: [
    { id: 'mcp.a1b2c3d4', name: 'notes', url: 'https://notes.example/mcp', auth: '$headers.X-Notes-Key', enabled: true },
    { id: 'mcp.database', name: 'orders-db', url: 'https://box.example/v1/mcp/database', auth: 'vault:harness-hosted-chrn-orig-mcp-database', enabled: true },
    { id: 'mcp.memories', name: 'memories', url: 'https://box.example/v1/mcp/memories', auth: 'vault:harness-hosted-chrn-orig-mcp-memories', enabled: true },
  ],
  disabledTools: ['skill'], maxStep: 40, timeoutSeconds: 600, reasoningEffort: 'low',
  additionalHeaders: ['X-Notes-Key'], env: { NOTES_KEY: '$headers.X-Notes-Key' },
} as unknown as CustomHarness;
const BASES = { dsh: { takesSkills: true, takesEnvironments: true } } as never;

let root: Root;
let el: HTMLElement;
beforeEach(() => { mockN = 0; el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

async function open(h: CustomHarness) {
  const done = jest.fn();
  await act(async () => { root.render(<DuplicateSheet h={h} bases={BASES} plugs={null} onClose={() => {}} onDone={done} />); });
  return done;
}
async function save() {
  const btn = Array.from(el.querySelectorAll('button')).find((b) => b.textContent === 'Save harness');
  if (!btn) throw new Error('no Save harness button');
  await act(async () => { btn.click(); });
  for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); });
}

test('Save sends the copy its own MCP servers under new ids and its variables, with what it sent before', async () => {
  const done = await open(ORIGINAL);
  await save();
  expect(hx.createCustom).toHaveBeenCalledTimes(1);
  expect(hx.createCustom.mock.calls[0][0]).toEqual(expect.objectContaining({
    name: 'notes-agent copy', base: 'dsh', systemPrompt: 'Answer from my notes.',
    mcpServers: [{ id: 'mcp.new1', name: 'notes', url: 'https://notes.example/mcp', auth: '$headers.X-Notes-Key', enabled: true }],
    env: { NOTES_KEY: '$headers.X-Notes-Key' },
    disabledTools: ['skill'], maxStep: 40, timeoutSeconds: 600, reasoningEffort: 'low', additionalHeaders: ['X-Notes-Key'],
  }));
  expect(done).toHaveBeenCalledTimes(1);
});

test('a server tied to the original is named before Save and in the saved message', async () => {
  await open(ORIGINAL);
  expect(el.textContent).toContain('orders-db is tied to this harness, so the copy won’t have it.');
  expect(el.textContent).not.toContain('are not copied');
  await save();
  expect(toast).toHaveBeenCalledWith('Saved as notes-agent copy. orders-db is tied to the original, so the copy doesn’t have it.');
});

test('a harness with nothing tied to it says nothing more than that it was saved', async () => {
  await open({ ...ORIGINAL, mcpServers: [ORIGINAL.mcpServers[0]] } as CustomHarness);
  expect(el.textContent).not.toContain('tied to');
  await save();
  expect(toast).toHaveBeenCalledWith('Saved as notes-agent copy');
});

test('the sheet says the copy keeps its tools', async () => {
  await open(ORIGINAL);
  expect(el.textContent).toContain('Same skills, tools, plugins and instructions, new Harness ID.');
});
