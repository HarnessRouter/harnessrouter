/** @jest-environment jsdom */
// Installing a plugin package from a picked folder (issue #725): a plugin.json that is not valid JSON
// is refused before anything is saved, and the notice carries the parser's own message after the fixed
// sentence, so two different mistakes read differently. A valid one still installs.
// This file imports nothing new on purpose: it runs against the source before and after the fix.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { BaseInfo, CustomHarness } from '@/lib/harness';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  getCustom: jest.fn(), saveCustom: jest.fn(), getSkillFiles: jest.fn(), pluginSchemas: jest.fn(async () => []),
  getHarnessPlugs: jest.fn(async () => null), setHarnessPlugs: jest.fn(),
  useBases: jest.fn(), useModelCatalog: jest.fn(() => null), useRuntimeDefaults: jest.fn(() => null),
  useModelCatalogRead: jest.fn(() => ({ value: null, failed: false, retry: jest.fn() })),
  oobModels: jest.fn(() => []), oobDefaultModel: jest.fn(() => ''),
  modelAvailability: jest.fn((b: string, m: string) => jest.requireActual('@/lib/harness').modelAvailability(b, m)),
}));
jest.mock('@/lib/plugs', () => ({ listPlugs: jest.fn(async () => ({ workspace: 'ws', plugs: [] })), plugAttachments: jest.fn() }));
jest.mock('@/lib/cloud-upload', () => ({ statusOne: jest.fn(async () => ({ uploaded: false })), listTargets: jest.fn(), addTarget: jest.fn(), uploadOne: jest.fn() }));
jest.mock('@/lib/environments', () => ({ listEnvironments: jest.fn(async () => []) }));
jest.mock('@/lib/providers', () => ({ useModelProviders: () => ({ connectionFor: () => null }) }));
jest.mock('@/lib/workspace', () => ({
  ...jest.requireActual('@/lib/workspace'),
  useWorkspace: () => ({ current: { id: 'ws' }, defaultId: 'ws', loading: false }),
}));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));
// the folder's files as the reader hands them over: each picked File carries its text here
const mockText = new WeakMap<File, string>();
jest.mock('@/components/HarnessEditors', () => ({
  readSkillUpload: jest.fn(async (f: File, path: string) => ({ path, content: mockText.get(f) })),
}));
jest.mock('../bricks', () => ({ partIcon: () => '<svg></svg>' }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../Sheet', () => ({ ConfirmSheet: () => null, Sheet: ({ children }: { children: React.ReactNode }) => <div data-sheet="1">{children}</div>, SheetTop: () => null }));
jest.mock('../mcp/McpSheet', () => ({ McpSheet: () => null, authFor: jest.fn(), newMcpId: jest.fn() }));
jest.mock('../ext/AddPluginSheet', () => ({ AddPluginSheet: () => null }));
jest.mock('../ext/pluginParts', () => ({
  ...jest.requireActual('../ext/pluginParts'),
  Logo: ({ mark }: { mark?: { src: string } }) => (mark ? <img className="mark" src={mark.src} alt="" /> : null),
}));
jest.mock('./SkillSheet', () => ({ SkillSheet: () => null, skillDraft: jest.fn(), skillFiles: jest.fn(), skillSlug: (s: string) => s, splitSkillMd: () => null }));
jest.mock('./settingsSheets', () => ({ DeleteSetupSheet: () => null, EnvPickSheet: () => null, PackageSheet: () => null, DuplicateSheet: () => null }));

import * as harness from '@/lib/harness';
import { rowOf } from '../setups';
import { SetupSettings } from './SetupSettings';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const hx = harness as jest.Mocked<typeof harness>;
const said = (jest.requireMock('../toast') as { toast: jest.Mock }).toast;

const BASE = {
  id: 'hermes', label: 'Hermes', backend: 'hermes', status: 'ok', systemPrompt: '', defaultModel: 'deepseek-v4.1-flash', models: [],
  tools: [], builtinSkills: [], builtinSkillsEnumerable: true,
} as unknown as BaseInfo;
const setup = () => ({
  id: 'chrn_p1', name: 'Product images', base: 'hermes', defaultModel: 'deepseek-v4.1-flash', systemPrompt: 'Make product images.',
  skills: [], plugins: [], mcpServers: [], createdAt: 1,
}) as unknown as CustomHarness;

// What the parser itself says about a text, read here and never written into the test.
const NOT_JSON = 'Its plugin.json is not valid JSON.';
const parserSays = (text: string) => { try { JSON.parse(text); } catch (e) { return (e as Error).message; } throw new Error('valid JSON'); };
const refusal = (text: string) => `${NOT_JSON} ${parserSays(text)}`;
const TRUNCATED = '{"name": "x"';
const TRAILING_COMMA = '{"name": "x",}';

let root: Root;
let el: HTMLElement;
beforeEach(() => {
  hx.useBases.mockReturnValue({ hermes: BASE });
  hx.getCustom.mockResolvedValue(setup());
  hx.saveCustom.mockImplementation(async (h: CustomHarness) => h);
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

const flush = async () => { for (let i = 0; i < 10; i++) await act(async () => { await Promise.resolve(); }); };
async function settings() {
  const h = setup();
  await act(async () => { root.render(<SetupSettings r={rowOf(h, 'Hermes', [], false, null, BASE)} onSaved={() => {}} layer="caps" cap="plugin" onLayer={() => {}} />); });
  await flush();
}
/** Pick a folder holding one plugin.json, through the settings' own folder input. */
async function pick(manifest: string) {
  const input = el.querySelector('input[type=file][webkitdirectory]') as HTMLInputElement;
  expect(input).toBeTruthy();
  const file = new File([manifest], 'plugin.json', { type: 'application/json' });
  Object.defineProperty(file, 'webkitRelativePath', { value: 'pkg/plugin.json' });
  mockText.set(file, manifest);
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
  await flush();
}
const lastNotice = () => said.mock.calls[said.mock.calls.length - 1]?.[0];

test("a malformed plugin.json is refused with the parser's own message", async () => {
  await settings();
  await pick(TRUNCATED);
  expect(said).toHaveBeenCalledWith(refusal(TRUNCATED));
});

test('two different malformations give two different notices', async () => {
  await settings();
  await pick(TRUNCATED);
  const first = lastNotice();
  await pick(TRAILING_COMMA);
  const second = lastNotice();
  expect(first).toBe(refusal(TRUNCATED));
  expect(second).toBe(refusal(TRAILING_COMMA));
  expect(first).not.toBe(second);
});

test('a malformed plugin.json is never saved', async () => {
  await settings();
  await pick(TRUNCATED);
  await pick(TRAILING_COMMA);
  expect(hx.saveCustom).not.toHaveBeenCalled();
});

test('a valid plugin.json still installs', async () => {
  await settings();
  await pick('{"name":"demo-kit"}');
  expect(hx.saveCustom).toHaveBeenCalledTimes(1);
  const saved = hx.saveCustom.mock.calls[0][0];
  expect((saved.plugins || []).map((p) => p.name)).toEqual(['demo-kit']);
  expect(said).toHaveBeenCalledWith('demo-kit is installed.');
});
