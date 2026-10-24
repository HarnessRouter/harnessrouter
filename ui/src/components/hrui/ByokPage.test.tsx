/** @jest-environment jsdom */
// Bring your own key on this edition's routing document (GET/PUT /v1/admin/integrations). The rows are
// the server's catalog; a custom endpoint keeps its API format and its own model rows (a model id and
// the name on the wire; a wire-only row saves under the wire name; an empty row is left out), and the
// harnesses it can drive follow the format. Adding a key at the maker takes the models a gateway key
// was serving. Which key serves each model (chat and image apart) is changed one model at a time, Off
// included; a removed key leaves no route behind in either map. Media lists are reordered whole. A
// HarnessRouter API key comes from the hand-off and is saved once it lands.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => <a className={className} href={href}>{children}</a> }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/chat', () => ({ authHeaders: () => ({}) }));
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }));
const mockWs = { workspaces: [{ id: 'ws.def' }], defaultId: 'ws.def', loading: false };
jest.mock('@/lib/workspace', () => ({ useWorkspace: () => mockWs }));
jest.mock('@/lib/harness', () => ({
  gwHeaders: () => ({}),
  OOB: [{ id: 'pi', name: 'Pi', backend: 'pi' }, { id: 'codex', name: 'Codex', backend: 'codex' }, { id: 'claude-code', name: 'Claude Code', backend: 'claude' }],
}));
jest.mock('./toast', () => ({ toast: jest.fn() }));
jest.mock('./Skel', () => ({ Skel: () => null, SkRows: () => null, SkLine: () => null }));

import { harnessFetch } from '@/lib/hfetch';
import { toast } from './toast';
import { ByokPage, HANDOFF_POLL_MS } from './ByokPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const SECRET = '__secret__';
const CATALOG = [
  { id: 'harnessrouter', label: 'HarnessRouter API', base_url: 'https://hosted.example/v1', fields: [], secret: 'api_key', secret_label: 'API Key', models: [], backends: ['pi'] },
  { id: 'anthropic', label: 'Anthropic', base_url: 'https://api.anthropic.com/v1', fields: [], secret: 'api_key', secret_label: 'API Key', key_hint: 'sk-ant-…',
    models: [{ canonical: 'claude-sonnet', provider_id: 'claude-sonnet' }], backends: ['claude'] },
  { id: 'openrouter', label: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1', fields: [], secret: 'api_key', secret_label: 'API Key',
    models: [{ canonical: 'claude-sonnet', provider_id: 'anthropic/claude-sonnet' }, { canonical: 'gpt-x', provider_id: 'openai/gpt-x' }], backends: ['pi', 'codex'] },
  { id: 'custom', label: 'Custom', base_url: null, secret: 'api_key', secret_label: 'API key',
    fields: [{ key: 'api_format', label: 'API format' }, { key: 'base_url', label: 'Base URL' }, { key: 'full_url', label: 'Full URL' }],
    models: [], canonicals: ['catalog-model'], backends: ['pi', 'codex', 'claude'],
    format_backends: { openai: ['pi'], responses: ['codex'], anthropic: ['claude'] } },
];
type D = Record<string, unknown> & { integrations: Record<string, unknown>[] };
let doc: D;
let puts: Record<string, unknown>[];
let root: Root;
let el: HTMLElement;
const fetchMock = harnessFetch as jest.Mock;
const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });
const text = () => (document.body.textContent || '').replace(/\s+/g, ' ');
const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve(); }); };
const rowOf = (id: string) => document.querySelector(`[data-provider="${id}"]`) as HTMLElement;
async function click(label: string, scope: ParentNode = document) {
  const b = Array.from(scope.querySelectorAll('button')).find((x) => (x.textContent || '').trim() === label) as HTMLButtonElement | undefined;
  if (!b) throw new Error(`no button ${label}: ${text()}`);
  await act(async () => { b.click(); });
  await flush();
}
async function type(input: Element | null, value: string) {
  const i = input as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(i, value); i.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function choose(select: Element | null, value: string) {
  const s = select as HTMLSelectElement;
  await act(async () => { s.value = value; s.dispatchEvent(new Event('change', { bubbles: true })); });
  await flush();
}
const lastPut = () => puts[puts.length - 1];

beforeEach(() => {
  doc = { integrations: [], model_map: {}, image_model_map: {}, providers: ['anthropic', 'openrouter', 'custom'], catalog: CATALOG, media_chains: [], media_policy: {} };
  puts = [];
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (url: string, init?: { method?: string; body?: string }) => {
    if (url.startsWith('/api/harness/v1/harnesses')) return ok({ harnesses: [{ name: 'Support', defaultModel: 'claude-sonnet' }] });
    if (url === '/api/harness/v1/admin/integrations' && init?.method === 'PUT') { puts.push(JSON.parse(init.body || '{}')); return ok({}); }
    if (url === '/api/harness/v1/admin/integrations') return ok(doc);
    return ok({}, 404);
  });
  (toast as jest.Mock).mockClear();
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; jest.useRealTimers(); });

async function open() { await act(async () => { root.render(<ByokPage />); }); await flush(); }

it('reads the admin document and draws the server’s catalog, grouped, with nothing it cannot back', async () => {
  await open();
  expect(fetchMock.mock.calls.some(([u]) => u === '/api/harness/v1/admin/integrations')).toBe(true);
  expect(document.querySelector('[data-group="direct"] [data-provider="anthropic"]')).not.toBeNull();
  expect(document.querySelector('[data-group="gateway"] [data-provider="openrouter"]')).not.toBeNull();
  expect(document.querySelector('[data-group="custom"] [data-provider="custom"]')).not.toBeNull();
  expect(document.querySelector('#pvHosted [data-provider="harnessrouter"]')).not.toBeNull();
  expect(text()).not.toMatch(/balance|Microsoft sign-in|Sign in with Microsoft/i);
});

it('a custom endpoint saves its format, its endpoint and its own rows: arbitrary ids, wire-only rows, empty rows left out', async () => {
  await open();
  await click('Add endpoint', rowOf('custom'));
  await type(document.getElementById('pk-custom-label'), 'proxy');
  await type(document.getElementById('pk-custom-base_url'), 'https://llm.example/v1');
  await click('Add model', rowOf('custom'));
  const model = rowOf('custom').querySelector('input[aria-label="Model"]') as HTMLInputElement;
  expect(model.tagName).toBe('INPUT');
  expect(document.querySelector('#custom-model-ids option')?.getAttribute('value')).toBe('catalog-model');
  await type(model, 'gpt-4.1-mini');
  await click('Add model', rowOf('custom'));
  await type(rowOf('custom').querySelectorAll('input[aria-label="Name on the wire"]')[1], 'wire-only-model');
  await click('Add model', rowOf('custom'));
  await click('Create', rowOf('custom'));
  const put = lastPut() as { integrations: { name: string; provider: string; config: Record<string, string>; models: unknown[] }[] };
  expect(put.integrations[0]).toMatchObject({ name: 'proxy', provider: 'custom', config: { api_format: 'openai', base_url: 'https://llm.example/v1' } });
  expect(put.integrations[0].models).toEqual([
    { canonical: 'gpt-4.1-mini', provider_id: '' },
    { canonical: 'wire-only-model', provider_id: 'wire-only-model' },
  ]);
});

it('the harnesses a custom endpoint can drive follow its API format', async () => {
  await open();
  await click('Add endpoint', rowOf('custom'));
  expect(text()).toContain('Compatible harnesses: Pi.');
  await choose(document.getElementById('pk-custom-api_format'), 'responses');
  expect(text()).toContain('Compatible harnesses: Codex.');
  await choose(document.getElementById('pk-custom-api_format'), 'anthropic');
  expect(text()).toContain('Compatible harnesses: Claude Code.');
});

it('a key at the maker takes the models a gateway key was serving; nothing is saved without the key', async () => {
  doc.integrations = [{ name: 'or', provider: 'openrouter', config: { api_key: SECRET }, models: CATALOG[2].models }];
  doc.model_map = { 'claude-sonnet': 'or', 'gpt-x': 'or' };
  await open();
  await click('Add key', rowOf('anthropic'));
  await click('Create', rowOf('anthropic'));
  expect(puts).toHaveLength(0);
  expect(toast).toHaveBeenCalledWith('Paste your Anthropic API Key.');
  await type(document.getElementById('pk-anthropic-api_key'), 'sk-ant-123456789');
  await click('Create', rowOf('anthropic'));
  const put = lastPut() as { integrations: { name: string; config: Record<string, string> }[]; model_map: Record<string, string> };
  expect(put.integrations.map((i) => i.name)).toEqual(['or', 'default']);
  expect(put.integrations[1].config).toEqual({ api_key: 'sk-ant-123456789' });
  expect(put.model_map).toEqual({ 'claude-sonnet': 'default', 'gpt-x': 'or' });
  expect(put).not.toHaveProperty('image_model_map');
});

it('editing a key leaves a blank secret as it was (the sentinel goes back)', async () => {
  doc.integrations = [{ name: 'main', provider: 'anthropic', config: { api_key: SECRET }, models: CATALOG[1].models }];
  doc.model_map = { 'claude-sonnet': 'main' };
  await open();
  await click('Edit', rowOf('anthropic'));
  expect((document.getElementById('pk-anthropic-api_key') as HTMLInputElement).placeholder).toBe('Saved. Leave blank to keep it.');
  await click('Save', rowOf('anthropic'));
  const put = lastPut() as { integrations: { config: Record<string, string> }[] };
  expect(put.integrations[0].config.api_key).toBe(SECRET);
});

it('which key serves a model, chat and image apart, Off included', async () => {
  doc.integrations = [
    { name: 'main', provider: 'anthropic', config: { api_key: SECRET }, models: CATALOG[1].models },
    { name: 'or', provider: 'openrouter', config: { api_key: SECRET }, models: CATALOG[2].models, image_models: [{ canonical: 'img-1', provider_id: 'img-1' }] },
  ];
  doc.model_map = { 'claude-sonnet': 'main', 'gpt-x': 'or' };
  doc.image_model_map = { 'img-1': 'or' };
  await open();
  await choose(document.querySelector('#pvRoutes select[aria-label="Which key serves claude-sonnet"]'), 'or');
  expect(lastPut()).toEqual({ integrations: doc.integrations, model_map: { 'claude-sonnet': 'or', 'gpt-x': 'or' } });
  await choose(document.querySelector('#pvImageRoutes select[aria-label="Which key serves img-1"]'), '');
  expect(lastPut()).toEqual({ integrations: doc.integrations, image_model_map: { 'img-1': '' } });
  expect(toast).toHaveBeenLastCalledWith('img-1 is off: no key serves it.');
});

it('a removed key leaves no route behind, chat or image, and models switched off stay off', async () => {
  doc.integrations = [
    { name: 'main', provider: 'anthropic', config: { api_key: SECRET }, models: CATALOG[1].models },
    { name: 'or', provider: 'openrouter', config: { api_key: SECRET }, models: CATALOG[2].models, image_models: [{ canonical: 'img-1', provider_id: 'img-1' }] },
  ];
  doc.model_map = { 'claude-sonnet': 'main' };            // gpt-x switched off
  doc.image_model_map = { 'img-1': 'or' };
  await open();
  await click('Remove', rowOf('openrouter'));
  expect(text()).toContain('No setup uses it right now.');
  await act(async () => { (document.querySelector('.del-go') as HTMLButtonElement).click(); });
  await flush();
  const put = lastPut() as { integrations: { name: string }[]; model_map: Record<string, string>; image_model_map: Record<string, string> };
  expect(put.integrations.map((i) => i.name)).toEqual(['main']);
  expect(put.model_map).toEqual({ 'claude-sonnet': 'main', 'gpt-x': '' });
  expect(put.image_model_map).toEqual({});
});

it('a media list is reordered and switched whole, as the policy for its capability', async () => {
  doc.media_chains = [{ capability: 'text_to_video', unit: 'clip', candidates: [
    { model: 'vid-a', provider: 'fal', connected: true, off: false, seconds: 5 },
    { model: 'vid-b', provider: 'fal', connected: false, off: false, duration_ignored: true },
  ] }];
  await open();
  expect(text()).toContain('Video, from text');
  expect(text()).toContain('ignores the length you ask for');
  await click('Down', document.querySelector('[data-capability="text_to_video"]')!);
  expect(lastPut()).toEqual({ integrations: [], media_policy: { text_to_video: { order: ['vid-b', 'vid-a'], disabled: [] } } });
});

it('Get a key opens the hand-off, reads the code until the key is ready, and saves it as a connection', async () => {
  jest.useFakeTimers();
  const opened = jest.fn();
  Object.defineProperty(window, 'open', { value: opened, configurable: true });
  let ready = false;
  fetchMock.mockImplementation(async (url: string, init?: { method?: string; body?: string }) => {
    if (url.startsWith('/api/harness/v1/harnesses')) return ok({ harnesses: [] });
    if (url === '/api/harness/v1/admin/connect') return ok({ code: 'c1', url: 'https://hosted.example/connect/c1' });
    if (url === '/api/harness/v1/admin/connect/c1') return ready ? ok({ status: 'ready', api_key: 'hr-key-1', endpoint: 'https://hosted.example/v1', name: 'My account' }) : ok({}, 202);
    if (url === '/api/harness/v1/admin/integrations' && init?.method === 'PUT') { puts.push(JSON.parse(init.body || '{}')); return ok({}); }
    return ok(doc);
  });
  await open();
  await click('Get a key', rowOf('harnessrouter'));
  expect(opened).toHaveBeenCalledWith('https://hosted.example/connect/c1', '_blank', 'noopener');
  expect(rowOf('harnessrouter').querySelector('[role="status"] a')?.getAttribute('href')).toBe('https://hosted.example/connect/c1');
  await act(async () => { await jest.advanceTimersByTimeAsync(HANDOFF_POLL_MS); });
  expect(puts).toHaveLength(0);
  ready = true;
  await act(async () => { await jest.advanceTimersByTimeAsync(HANDOFF_POLL_MS); });
  const put = lastPut() as { integrations: { name: string; provider: string; config: Record<string, string> }[] };
  expect(put.integrations).toEqual([{ name: 'My account', provider: 'harnessrouter', models: [], config: { api_key: 'hr-key-1', base_url: 'https://hosted.example/v1' } }]);
});
