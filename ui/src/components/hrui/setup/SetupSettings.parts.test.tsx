/** @jest-environment jsdom */
// A setup's plugins, skills and tools as a person sees them (Richard, 10-18): every place reads
// setupParts.ts and says which list it shows: the Capabilities tabs list everything, built-ins
// included; the Agent stack and the layers line beside it count only what a person added. Then what
// Settings shows when a read fails (no fallbacks), the Plugins tab's switches, and that it ends with Delete setup.
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { BaseInfo, CustomHarness, HarnessPlugin, Plug } from '@/lib/harness';

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
jest.mock('@/components/HarnessEditors', () => ({ readSkillUpload: jest.fn() }));
jest.mock('../bricks', () => ({ partIcon: () => '<svg></svg>' }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../Sheet', () => ({ ConfirmSheet: () => null, Sheet: ({ children }: { children: React.ReactNode }) => <div data-sheet="1">{children}</div>, SheetTop: () => null }));
jest.mock('../mcp/McpSheet', () => ({ McpSheet: () => null, authFor: jest.fn(), newMcpId: jest.fn() }));
const mockSheet = jest.fn();
jest.mock('../ext/AddPluginSheet', () => ({ AddPluginSheet: (p: unknown) => { mockSheet(p); return null; } }));
jest.mock('../ext/pluginParts', () => ({
  ...jest.requireActual('../ext/pluginParts'),
  Logo: ({ mark }: { mark?: { src: string } }) => (mark ? <img className="mark" src={mark.src} alt="" /> : null),
}));
jest.mock('./SkillSheet', () => ({ SkillSheet: () => null, skillDraft: jest.fn(), skillFiles: jest.fn(), skillSlug: (s: string) => s, splitSkillMd: () => null }));
jest.mock('./settingsSheets', () => ({ DeleteSetupSheet: () => null, EnvPickSheet: () => null, PackageSheet: () => null, DuplicateSheet: () => null }));

import * as harness from '@/lib/harness';
import { rowOf } from '../setups';
import { SetupSettings } from './SetupSettings';
import { StackPanel } from './parts';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const hx = harness as jest.Mocked<typeof harness>;
const plugsLib = jest.requireMock('@/lib/plugs') as { listPlugs: jest.Mock };
const cloudLib = jest.requireMock('@/lib/cloud-upload') as { statusOne: jest.Mock; listTargets: jest.Mock };
const envs = jest.requireMock('@/lib/environments') as { listEnvironments: jest.Mock };
const said = (jest.requireMock('../toast') as { toast: jest.Mock }).toast;

// Hermes with seven built-in tools and three built-in skills, on by default
const BASE = {
  id: 'hermes', label: 'Hermes', backend: 'hermes', status: 'ok', systemPrompt: '', defaultModel: 'deepseek-v4.1-flash', models: [],
  tools: ['terminal', 'read_file', 'write_file', 'patch', 'search_files', 'web_search', 'web_extract'].map((name) => ({ name })),
  builtinSkills: ['plan', 'research', 'write'].map((name) => ({ name, title: name, description: `${name} well`, defaultEnabled: true })),
  builtinSkillsEnumerable: true,
} as unknown as BaseInfo;
const PLUGS = { id: 'mcp.plugs', url: 'x', enabled: true };
const pkg = { name: 'brand-kit', enabled: true, files: [], manifest: { name: 'brand-kit', description: 'The brand’s colours and type' } } as unknown as HarnessPlugin;
const setup = (o: Partial<CustomHarness> = {}) => ({
  id: 'chrn_p2', name: 'Product images 2', base: 'hermes', defaultModel: 'deepseek-v4.1-flash', systemPrompt: 'Make product images.',
  skills: [], plugins: [pkg], mcpServers: [], createdAt: 1, ...o,
}) as unknown as CustomHarness;
const P = (type: string, label: string, status: Plug['status'] = 'connected'): Plug => ({
  type, label, source: 'platform', official: true, status, config: {}, secrets_set: [], secrets_needed: [], config_fields: [], version: 1, tools: 2,
});
const B = (p: string[]) => ({ id: 'chrn_p2', name: '', enabled: true, workspace: 'ws', plugs: p, status: {} });

let root: Root;
let el: HTMLElement;
beforeEach(() => {
  hx.useBases.mockReturnValue({ hermes: BASE });
  el = document.createElement('div');
  el.id = 'hrui';
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

const flush = async () => { for (let i = 0; i < 10; i++) await act(async () => { await Promise.resolve(); }); };
async function settings(h: CustomHarness, layer = 'caps', cap: string | undefined = 'plugin') {
  hx.getCustom.mockResolvedValue(h);
  await act(async () => { root.render(<SetupSettings r={rowOf(h, 'Hermes', [], false, null, BASE)} onSaved={() => {}} layer={layer} cap={cap} onLayer={() => {}} />); });
  await flush();
}
const tabs = () => Array.from(el.querySelectorAll('.cap-tabs [role=tab]')).map((t) => t.textContent);
const rows = () => Array.from(el.querySelectorAll('.cap-pane .cap-row:not([hidden])'));
const names = () => rows().map((r) => r.querySelector('b')?.textContent);
const stack = async (h: CustomHarness) => {
  await act(async () => { root.render(<StackPanel r={rowOf(h, 'Hermes', [], false, null, BASE)} off={false} onToggle={() => {}} />); });
};
const partSays = (k: string) => el.querySelector(`.part.built[data-tw=${k}] small`)?.textContent;
const railLine = () => Array.from(el.querySelectorAll('.ly-list .ly-n')).find((b) => b.querySelector('b')?.textContent === 'Capabilities')?.querySelector('small')?.textContent;
const button = (t: string) => Array.from(el.querySelectorAll('button')).find((b) => b.textContent === t) as HTMLButtonElement | undefined;

describe('a setup whose only plugin is a package installed on it', () => {
  test('the Plugins tab reads 1 and lists it, with its line and its switch on', async () => {
    await settings(setup());
    expect(tabs()).toEqual(['Plugins 1', 'Skills 3', 'Tools 7']);
    expect(names()).toEqual(['brand-kit']);
    expect(rows()[0].querySelector('small')?.textContent).toBe('The brand’s colours and type');
    expect(rows()[0].querySelector('[role=switch]')?.getAttribute('aria-checked')).toBe('true');
    // nothing connected in the workspace: said, with the way to connect one, never a dead end
    expect(el.textContent).toContain('No plugins are connected in this workspace yet.');
    expect(button('Connect a plugin')).toBeTruthy();
  });
  test('the layers list and the Agent stack count what was added', async () => {
    await settings(setup());
    expect(railLine()).toBe('1 plugin added');
    await stack(setup());
    expect(partSays('plugin')).toBe('1 added');
    expect(el.querySelector('.part.built[data-tw=plugin]')?.getAttribute('title')).toBe('brand-kit');
    expect(el.querySelector('.part.locked[data-partlock=skill]')?.getAttribute('aria-label')).toBe('Skill, none yet');
    expect(el.querySelector('.part.locked[data-partlock=mcp]')?.getAttribute('aria-label')).toBe('Tool, none yet');
  });
});

describe('built-ins in the tabs, only what was added in the picture', () => {
  test('a setup with only built-ins: the tabs list them, the stack and the line say nothing was added', async () => {
    const h = setup({ plugins: [] });
    await settings(h, 'caps', 'skill');
    expect(tabs()).toEqual(['Plugins 0', 'Skills 3', 'Tools 7']);
    expect(names()).toEqual(['plan', 'research', 'write']);
    expect(railLine()).toBe('Nothing added yet');
    await stack(h);
    expect(el.querySelectorAll('.part.built')).toHaveLength(0);
  });
  test('a built-in turned off and an own skill added: the tabs count what is on, the picture what was added', async () => {
    const h = setup({
      skills: [{ id: 'skl_x', name: 'research', enabled: false }, { id: 'skl_b', name: 'brand', enabled: true, files: [{ path: 'SKILL.md', content: '---\nname: brand\ndescription: Our look\n---\n' }] }],
      disabledTools: ['patch'],
    } as Partial<CustomHarness>);
    await settings(h, 'caps', 'skill');
    expect(tabs()).toEqual(['Plugins 1', 'Skills 3', 'Tools 6']);
    expect(rows().filter((r) => r.classList.contains('off')).map((r) => r.querySelector('b')?.textContent)).toEqual(['research']);
    expect(railLine()).toBe('1 plugin and 1 skill added');
  });
});

// Richard 10-19: every page stays simple. A layer says something about itself only where a person needs
// it, a control that can't be used is left out (never shown disabled), and an edge case shows only when
// it happens.
describe('only what a person needs', () => {
  test('only Capabilities says something about itself', async () => {
    for (const name of ['instructions', 'harness', 'runtime']) {
      await settings(setup(), name);
      expect(el.querySelector('.lg-desc')).toBeNull();
    }
    await settings(setup(), 'caps');
    expect(el.querySelector('.lg-desc')?.textContent).toBe('Plugin and skill changes apply right away.');
  });
  test('the instructions box is named for the file the agent harness reads', async () => {
    await settings(setup(), 'instructions');
    expect(el.querySelector('label[for=setMd]')?.textContent).toBe('AGENTS.md');
    await settings(setup({ base: 'claude-code' }), 'instructions');
    expect(el.querySelector('label[for=setMd]')?.textContent).toBe('CLAUDE.md');
  });
  test('an agent harness that takes no skills has no Skills tab, and its address opens the first tab there is', async () => {
    hx.useBases.mockReturnValue({ hermes: { ...BASE, takesSkills: false } as BaseInfo });
    await settings(setup(), 'caps', 'skill');
    expect(tabs()).toEqual(['Plugins 1', 'Tools 7']);
    expect(names()).toEqual(['brand-kit']);
  });
  test('a built-in tool says nothing unless turning it off only asks', async () => {
    hx.useBases.mockReturnValue({ hermes: { ...BASE, tools: [{ name: 'terminal' }, { name: 'web_search', enforcement: 'instruction' }] } as unknown as BaseInfo });
    await settings(setup(), 'caps', 'tool');
    expect(rows().map((r) => r.querySelector('small')?.textContent ?? null)).toEqual([null, 'Off asks the agent not to use it.']);
  });
  test('an agent harness that cannot open an environment has no Environment section, until one is set', async () => {
    hx.useBases.mockReturnValue({ hermes: { ...BASE, takesEnvironments: false } as BaseInfo });
    await settings(setup(), 'runtime');
    expect(Array.from(el.querySelectorAll('.lg-sub h3')).map((h) => h.textContent)).toEqual(['Environment variables', 'Request headers', 'Limits']);
    await settings(setup({ environment: 'env_old' } as Partial<CustomHarness>), 'runtime');
    expect(el.querySelector('.lg-sub h3')?.textContent).toBe('Environment');
    expect(el.textContent).toContain('Hermes can’t use an environment. Remove it, or every task on this setup is refused.');
  });
  test('the limits are steps and a timeout: no cost cap (nothing on this instance applies one), no reason codes', async () => {
    await settings(setup(), 'runtime');
    expect(el.querySelector('#setTurns')).not.toBeNull();
    expect(el.querySelector('#setMins')).not.toBeNull();
    expect(el.querySelector('#setCap')).toBeNull();
    expect(el.textContent).not.toMatch(/Max cost|plan|credit|max_steps/i);
    expect(el.textContent).not.toContain('Use a reference');   // the variables' hint comes with the first variable
  });
  test('a model with no provider is left out of the list, never listed disabled; the chosen one stays', async () => {
    const real = jest.requireActual('@/lib/harness') as typeof harness;
    const all = ['deepseek-v4.1-flash', 'glm-5.3', 'gpt-5.4', 'kimi-k2.7-code'];
    hx.oobModels.mockReturnValue(all);
    hx.modelAvailability.mockImplementation((_b, m) => (m === 'glm-5.3' ? 'no' : 'yes'));
    await settings(setup(), 'harness');
    const opts = Array.from(el.querySelectorAll<HTMLOptionElement>('#setModel option'));
    expect(opts.some((o) => o.disabled)).toBe(false);
    expect(opts.map((o) => o.value)).toEqual(['deepseek-v4.1-flash', 'gpt-5.4', 'kimi-k2.7-code']);
    hx.modelAvailability.mockImplementation(real.modelAvailability);
  });
});

// ── what Settings shows when a read fails or a choice was never made (Richard 10-19: no fallbacks) ──
describe('no fallbacks', () => {
  test('a setup with no model of its own keeps none: the harness default is its choice, never a model filled in', async () => {
    hx.oobModels.mockReturnValue(['glm-5.3', 'gpt-5.4']);
    (hx.oobDefaultModel as jest.Mock).mockReturnValue('gpt-5.4');
    hx.modelAvailability.mockImplementation(() => 'yes');
    await settings(setup({ defaultModel: '' }), 'harness');
    const sel = el.querySelector<HTMLSelectElement>('#setModel')!;
    expect(sel.value).toBe('');
    expect(sel.options[0].textContent).toBe('The harness default (gpt-5.4)');
    expect(Array.from(sel.options).map((o) => o.value)).toEqual(['', 'glm-5.3', 'gpt-5.4']);
    hx.modelAvailability.mockImplementation((b, m) => (jest.requireActual('@/lib/harness') as typeof harness).modelAvailability(b, m));
  });
  test('the models that could not be read are said, with Try again', async () => {
    const retry = jest.fn();
    hx.useModelCatalogRead.mockReturnValue({ value: null, failed: true, retry });
    await settings(setup(), 'harness');
    expect(el.textContent).toContain('The models could not be read just now.');
    await act(async () => { button('Try again')!.click(); });
    expect(retry).toHaveBeenCalled();
    expect(el.querySelector<HTMLSelectElement>('#setModel')!.value).toBe('deepseek-v4.1-flash');
    hx.useModelCatalogRead.mockReturnValue({ value: null, failed: false, retry: jest.fn() });
  });
  test('environments that could not be read never read as "Not found"', async () => {
    envs.listEnvironments.mockRejectedValueOnce(new Error('502'));
    await settings(setup({ environment: 'env_1' } as Partial<CustomHarness>), 'runtime');
    expect(el.textContent).toContain('Your environments could not be read just now.');
    expect(el.textContent).not.toContain('Not found');
    envs.listEnvironments.mockResolvedValueOnce([{ id: 'env_1', name: 'Python data', status: 'ready', description: '' }]);
    await act(async () => { button('Try again')!.click(); });
    await flush();
    expect(el.textContent).toContain('Python data');
  });
  test('workspace plugins that could not be read are said, never listed as not connected', async () => {
    plugsLib.listPlugs.mockRejectedValue(new Error('502'));
    hx.getHarnessPlugs.mockResolvedValueOnce(B(['github']));
    await settings(setup({ mcpServers: [PLUGS] } as Partial<CustomHarness>));
    await act(async () => { await new Promise((r) => setTimeout(r, 1100)); });   // the read's quiet second try
    await flush();
    expect(el.textContent).toContain('Your plugins could not be loaded just now.');
    expect(el.textContent).not.toContain('Not connected in this workspace');
    plugsLib.listPlugs.mockResolvedValue({ workspace: 'ws', plugs: [P('github', 'GitHub')] });
    await act(async () => { button('Try again')!.click(); });
    await flush();
    expect(el.textContent).not.toContain('could not be loaded');
    expect(names()).toContain('GitHub');
    plugsLib.listPlugs.mockResolvedValue({ workspace: 'ws', plugs: [] });
  });
});

// Richard, 10-21: the Plugins tab lists the workspace's connected plugins, each with a switch for this
// setup, included ones first; a flip writes the binding at once, and a refused write says so and goes
// back. Connecting another opens Add plugin at what can still be connected.
describe('the Plugins tab: the workspace’s connected plugins, a switch each', () => {
  const H = setup({ mcpServers: [PLUGS], plugins: [] } as unknown as Partial<CustomHarness>);
  async function open() {
    plugsLib.listPlugs.mockResolvedValue({ workspace: 'ws', plugs: [P('browser', 'Browser'), P('github', 'GitHub'), P('vercel', 'Vercel', 'missing')] });
    hx.getHarnessPlugs.mockResolvedValueOnce(B(['browser']));
    await settings(H);
  }
  const sw = (name: string) => rows().find((r) => r.querySelector('b')?.textContent === name)!.querySelector('[role=switch]') as HTMLButtonElement;
  afterEach(() => { plugsLib.listPlugs.mockResolvedValue({ workspace: 'ws', plugs: [] }); });

  test('lists them with their switches, included first', async () => {
    await open();
    expect(tabs()[0]).toBe('Plugins 1');
    expect(names()).toEqual(['Browser', 'GitHub']);
    expect(sw('Browser').getAttribute('aria-checked')).toBe('true');
    expect(sw('GitHub').getAttribute('aria-checked')).toBe('false');
  });
  test('a flip writes the binding at once, the switch busy while it saves', async () => {
    let answer: (v: ReturnType<typeof B>) => void = () => {};
    hx.setHarnessPlugs.mockImplementationOnce(() => new Promise((r) => { answer = r as (v: ReturnType<typeof B>) => void; }));
    await open();
    hx.getCustom.mockResolvedValue(H);
    await act(async () => { sw('GitHub').click(); });
    expect(hx.setHarnessPlugs).toHaveBeenCalledWith('chrn_p2', ['browser', 'github']);
    expect(sw('GitHub').getAttribute('aria-busy')).toBe('true');
    await act(async () => { answer(B(['browser', 'github'])); });
    await flush();
    expect(sw('GitHub').getAttribute('aria-busy')).toBeNull();
    expect(sw('GitHub').getAttribute('aria-checked')).toBe('true');
    expect(tabs()[0]).toBe('Plugins 2');
    expect(names()).toEqual(['Browser', 'GitHub']);      // it stays where it was
  });
  test('a refused write says so and the switch goes back', async () => {
    hx.setHarnessPlugs.mockRejectedValueOnce(new Error(''));
    await open();
    await act(async () => { sw('Browser').click(); });
    await flush();
    expect(said).toHaveBeenCalledWith('The plugins were not changed. Try again.');
    expect(sw('Browser').getAttribute('aria-checked')).toBe('true');
  });
  test('Connect another plugin opens Add plugin at what can still be connected', async () => {
    await open();
    mockSheet.mockClear();
    await act(async () => { button('Connect another plugin')!.click(); });
    await flush();
    expect(mockSheet.mock.calls[mockSheet.mock.calls.length - 1][0]).toMatchObject({ focus: 'available', setup: 'Product images 2', binding: { plugs: ['browser'] } });
  });
});

describe('Deploy to Cloud lives in the page bar, not here', () => {
  test('the settings end with Delete setup alone', async () => {
    await settings(setup(), 'harness');
    expect(el.querySelector('.lg-rows .ly-n.lg-up')).toBeNull();
    expect([...el.querySelectorAll('.lg-rows .lg-dz .ly-n')].map((b) => b.textContent)).toEqual(['Delete setup']);
    expect(el.textContent).not.toContain('Upload to cloud');
  });
});

// Every tablist moves with the arrow keys (tabKeys.ts): Capabilities' tabs, and the layers list, which is
// vertical, so Up and Down move it too.
describe('the arrow keys', () => {
  function Host({ h }: { h: CustomHarness }) {
    const [at, setAt] = useState<{ layer: string; cap?: string }>({ layer: 'caps', cap: 'plugin' });
    return <SetupSettings r={rowOf(h, 'Hermes', [], false, null, BASE)} onSaved={() => {}} layer={at.layer} cap={at.cap}
      onLayer={(layer, cap) => setAt({ layer, cap })} />;
  }
  const keyOn = async (t: Element, key: string) => {
    (t as HTMLElement).focus();
    await act(async () => { t.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })); });
    await flush();
  };
  const on = (sel: string) => el.querySelector(`${sel} [role=tab][aria-selected=true]`)?.textContent;
  test('ArrowRight opens the next Capabilities tab, and ArrowDown the next layer', async () => {
    const h = setup();
    hx.getCustom.mockResolvedValue(h);
    await act(async () => { root.render(<Host h={h} />); });
    await flush();
    expect(on('.cap-tabs')).toBe('Plugins 1');
    await keyOn(el.querySelector('.cap-tabs [role=tab][aria-selected=true]') as Element, 'ArrowRight');
    expect(on('.cap-tabs')).toBe('Skills 3');
    await keyOn(el.querySelector('.ly-list [role=tab][aria-selected=true]') as Element, 'ArrowDown');
    expect(on('.ly-list')).toContain('Environment & limits');
    expect(document.activeElement?.textContent).toContain('Environment & limits');
  });
});
