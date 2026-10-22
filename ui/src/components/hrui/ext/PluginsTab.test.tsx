/** @jest-environment jsdom */
// Add-ons › Plugins as a person uses it: what the workspace has connected, a row each with the setups
// that include it; every other plugin as a tile to connect; one sheet per plugin to connect it, change
// it, sign each person in with Microsoft, keep the browser's sites, or remove it. The server is
// lib/plugs, answered here with the shapes the gateway sends (GET /v1/plugs, PUT and DELETE
// /v1/plugs/{type}, its tools and attachments, Microsoft's sign-in).
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Plug } from '@/lib/plugs';

jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ member: { id: 'ada@example.com', email: 'ada@example.com' } }) }));
jest.mock('@/lib/plugs', () => ({
  listPlugs: jest.fn(), setPlug: jest.fn(), deletePlug: jest.fn(), plugTools: jest.fn(), plugAttachments: jest.fn(),
  microsoftStart: jest.fn(), microsoftComplete: jest.fn(), microsoftSignout: jest.fn(),
}));
jest.mock('../bricks', () => ({ partIcon: () => '<svg></svg>' }));
jest.mock('../toast', () => ({ toast: jest.fn() }));

import * as plugs from '@/lib/plugs';
import { toast } from '../toast';
import { usePlugins, PluginsTab, signInReturn } from './PluginsTab';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const m = plugs as jest.Mocked<typeof plugs>;
const say = toast as jest.Mock;

// each type as the gateway's _PLUG_FORMS describes it
const FORMS: Record<string, [string, string[], string[]]> = {
  browser: ['Browser', [], ['allow_domains', 'deny_domains']],
  github: ['GitHub', ['token'], ['repo', 'owner', 'default_branch']],
  vercel: ['Vercel', ['token'], ['project', 'project_id', 'team_id']],
  insforge: ['InsForge', ['api_key'], ['project', 'project_id', 'url', 'region']],
  microsoft365: ['Microsoft 365', ['client_secret'], ['tenant_id', 'client_id', 'mode']],
};
const P = (type: string, over: Partial<Plug> = {}): Plug => ({
  type, label: FORMS[type][0], source: type === 'browser' ? 'platform' : 'local', official: true, status: 'missing',
  config: {}, secrets_set: [], secrets_needed: FORMS[type][1], config_fields: FORMS[type][2], version: 0, tools: 3, ...over,
});

let catalog: Plug[];
function serve(list: Plug[]) {
  catalog = list;
  m.listPlugs.mockImplementation(async () => ({ workspace: 'ws', plugs: catalog }));
  m.plugAttachments.mockImplementation(async (type: string) => ({
    harnesses: 2, attached: type === 'github' ? 1 : 0, harness_list: type === 'github' ? [{ id: 'h1', name: 'Mail helper' }] : [],
  }));
  m.plugTools.mockImplementation(async (type: string) => ({ type, label: type, tools: [{ name: `${type}_read`, description: 'Reads it', risk: 'read' }] }));
  m.setPlug.mockImplementation(async (type: string, body: { enabled: boolean; config?: Record<string, unknown>; secrets?: Record<string, string> }) => {
    const had = catalog.find((p) => p.type === type) as Plug;
    const next: Plug = { ...had, status: body.enabled ? 'connected' : 'disabled', config: { ...had.config, ...(body.config || {}) },
      secrets_set: [...new Set([...had.secrets_set, ...Object.keys(body.secrets || {})])], version: had.version + 1 };
    catalog = catalog.map((p) => (p.type === type ? next : p));
    return next;
  });
  m.deletePlug.mockImplementation(async (type: string) => {
    catalog = catalog.map((p) => (p.type === type ? P(type) : p));
    return { type, workspace: 'ws', removed: true };
  });
}

let root: Root;
let el: HTMLDivElement;
function Page() {
  const d = usePlugins('ws');
  return <><span id="tabcount">{d.connectedCount ?? ''}</span><PluginsTab data={d} workspace="ws" /></>;
}
const flush = async () => { for (let i = 0; i < 10; i++) await act(async () => { await Promise.resolve(); }); };
const section = (h: string) => el.querySelector(`#${h}`)?.closest('section') as HTMLElement | null;
const connectedNames = () => Array.from(section('pl-con-h')?.querySelectorAll('.row b') || []).map((b) => b.textContent);
const tileNames = () => Array.from(el.querySelectorAll('.pl-tile .pl-top b')).map((b) => b.textContent);
const tile = (name: string) => Array.from(el.querySelectorAll('.pl-tile')).find((t) => t.querySelector('.pl-top b')?.textContent === name) as HTMLElement;
const row = (name: string) => Array.from(el.querySelectorAll('.row')).find((r) => r.querySelector('b')?.textContent === name) as HTMLElement;
const button = (text: string, within: ParentNode = document) =>
  Array.from(within.querySelectorAll('button')).find((b) => b.textContent === text) as HTMLButtonElement;
const sheet = () => document.querySelector('.pl-sheet') as HTMLElement | null;
const input = (id: string) => document.getElementById(id) as HTMLInputElement;
async function type(target: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(target, value); target.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function click(b: HTMLElement) { await act(async () => { b.click(); }); await flush(); }
async function open() { await act(async () => { root.render(<Page />); }); await flush(); }

beforeEach(() => {
  jest.clearAllMocks();
  window.history.replaceState(null, '', '/extensions');
  document.body.innerHTML = '<div id="hrui"></div>';
  el = document.getElementById('hrui') as HTMLDivElement;
  root = createRoot(el);
});
afterEach(async () => { await act(async () => { root.unmount(); }); });

test('what is connected or waiting is a row with the setups that include it; the rest are tiles', async () => {
  serve([
    P('browser', { status: 'connected', config: { allow_domains: ['example.com'], deny_domains: [] } }),
    P('github', { status: 'connected', config: { repo: 'acme/app' }, secrets_set: ['token'] }),
    P('vercel'),
    P('insforge', { status: 'disabled', config: { url: 'https://db.example.com' }, secrets_set: ['api_key'] }),
    P('microsoft365', { status: 'needs_auth', secrets_set: ['client_secret'], config: { mode: 'delegated', accounts: {} }, attention: 'Sign in with Microsoft so the agent can act as you.' }),
  ]);
  await open();
  expect(connectedNames()).toEqual(['Browser', 'GitHub', 'Microsoft 365']);
  expect(tileNames()).toEqual(['Vercel', 'InsForge']);
  expect(el.querySelector('#tabcount')?.textContent).toBe('3');
  expect(section('pl-con-h')?.querySelector('.count')?.textContent).toBe('3');
  // the account each is on, in its own terms, and who uses it
  expect(row('GitHub').textContent).toContain('acme/app');
  expect(row('GitHub').textContent).toContain('Used by Mail helper');
  expect(row('Browser').textContent).toContain('Only example.com');
  expect(row('Browser').textContent).toContain('Not used by any setup');
  expect(row('Microsoft 365').querySelector('.pl-warn')?.textContent).toBe('Sign in with Microsoft so the agent can act as you.');
  expect(button('Reconnect', row('Microsoft 365'))).toBeTruthy();
  // one turned off says so: Connect turns it back on as it was
  expect(tile('InsForge').textContent).toContain('Turned off here.');
});

test('the browser connects in one click, and a plugin turned off comes back as it was', async () => {
  serve([P('browser'), P('github'), P('insforge', { status: 'disabled', secrets_set: ['api_key'], config: { url: 'https://db.example.com' } })]);
  await open();
  await click(button('Connect', tile('Browser')));
  expect(m.setPlug).toHaveBeenCalledWith('browser', { enabled: true });
  expect(say).toHaveBeenCalledWith('Browser connected.');
  expect(connectedNames()).toEqual(['Browser']);
  expect(sheet()).toBeNull();

  await click(button('Connect', tile('InsForge')));
  expect(m.setPlug).toHaveBeenLastCalledWith('insforge', { enabled: true });
  expect(connectedNames()).toEqual(['Browser', 'InsForge']);
});

test('a plugin that takes a credential: its names, then the secret, sent once on Connect', async () => {
  serve([P('github')]);
  await open();
  await click(button('Connect', tile('GitHub')));
  const s = sheet() as HTMLElement;
  expect(s.querySelector('h2, [id="pch"]')?.textContent).toContain('Connect GitHub');
  expect(Array.from(s.querySelectorAll('.set-f > label')).map((l) => l.textContent)).toEqual(
    ['Repository (owner/name)', 'Owneroptional', 'Default branchoptional', 'Access token']);
  expect(s.textContent).toContain('github_read');
  const go = button('Connect', s);
  expect(go.disabled).toBe(true);
  await type(input('pc-repo'), 'acme/app');
  await type(input('pc-token'), 'ghp_secret');
  expect(input('pc-token').type).toBe('password');
  // the server's own sentence when the service refuses the credential, and the sheet stays
  m.setPlug.mockRejectedValueOnce(new Error('GitHub answered 401: Bad credentials'));
  await click(button('Connect', s));
  expect(sheet()?.querySelector('.mcp-say')?.textContent).toBe('GitHub answered 401: Bad credentials.');
  await click(button('Connect', sheet() as HTMLElement));
  expect(m.setPlug).toHaveBeenLastCalledWith('github', { enabled: true, config: { repo: 'acme/app', owner: '', default_branch: '' }, secrets: { token: 'ghp_secret' } });
  expect(sheet()).toBeNull();
  expect(say).toHaveBeenCalledWith('GitHub connected.');
  expect(connectedNames()).toEqual(['GitHub']);
});

test('Manage changes the names alone, replaces the credential on request, and Remove deletes it', async () => {
  serve([P('github', { status: 'connected', config: { repo: 'acme/app' }, secrets_set: ['token'] })]);
  await open();
  await click(button('Manage', row('GitHub')));
  expect(input('pc-token')).toBeNull();                  // a stored secret is never asked for again
  expect(button('Done', sheet() as HTMLElement)).toBeTruthy();
  await type(input('pc-repo'), 'acme/other');
  await click(button('Save', sheet() as HTMLElement));
  expect(m.setPlug).toHaveBeenLastCalledWith('github', { enabled: true, config: { repo: 'acme/other', owner: '', default_branch: '' } });
  expect(say).toHaveBeenCalledWith('GitHub saved.');

  await click(button('Manage', row('GitHub')));
  await click(button('Use a different credential', sheet() as HTMLElement));
  await type(input('pc-token'), 'ghp_new');
  await click(button('Connect', sheet() as HTMLElement));
  expect(m.setPlug).toHaveBeenLastCalledWith('github', { enabled: true, config: { repo: 'acme/other', owner: '', default_branch: '' }, secrets: { token: 'ghp_new' } });

  await click(button('Manage', row('GitHub')));
  await click(button('Remove', sheet() as HTMLElement));
  expect(sheet()?.querySelector('.mcp-ask')?.textContent).toContain('Its stored credential is deleted');
  await click(button('Remove', sheet()?.querySelector('.mcp-ask') as HTMLElement));
  expect(m.deletePlug).toHaveBeenCalledWith('github');
  expect(say).toHaveBeenCalledWith('GitHub removed.');
  expect(connectedNames()).toEqual([]);
  expect(tileNames()).toEqual(['GitHub']);
});

test('the browser keeps the sites it may visit', async () => {
  serve([P('browser', { status: 'connected', config: { allow_domains: [], deny_domains: [] } })]);
  await open();
  await click(button('Manage', row('Browser')));
  await type(input('pc-allow'), 'docs.example.org, example.com');
  await click(button('Save', sheet() as HTMLElement));
  expect(m.setPlug).toHaveBeenLastCalledWith('browser', { enabled: true, config: { allow_domains: ['docs.example.org', 'example.com'], deny_domains: [] } });
  expect(row('Browser').textContent).toContain('Only docs.example.org, example.com');
});

test('Microsoft 365 as each person: connected, it waits for a sign-in, which starts at Microsoft', async () => {
  serve([P('microsoft365')]);
  m.setPlug.mockImplementationOnce(async () => P('microsoft365', {
    status: 'needs_auth', secrets_set: ['client_secret'], config: { tenant_id: 't', client_id: 'c', mode: 'delegated', accounts: {} },
    attention: 'Sign in with Microsoft so the agent can act as you.',
  }));
  m.microsoftStart.mockReturnValue(new Promise(() => { /* Microsoft's page: never back in this test */ }));
  await open();
  await click(button('Connect', tile('Microsoft 365')));
  expect((document.getElementById('pc-mode') as HTMLSelectElement).value).toBe('delegated');
  await type(input('pc-tenant_id'), 't');
  await type(input('pc-client_id'), 'c');
  await type(input('pc-client_secret'), 's3cret');
  await click(button('Connect', sheet() as HTMLElement));
  expect(m.setPlug).toHaveBeenLastCalledWith('microsoft365', { enabled: true, config: { tenant_id: 't', client_id: 'c', mode: 'delegated' }, secrets: { client_secret: 's3cret' } });
  // still open, at its sign-in
  expect(sheet()?.textContent).toContain('Sign in with Microsoft so the agent can act as you.');
  await click(button('Sign in with Microsoft', sheet() as HTMLElement));
  expect(m.microsoftStart).toHaveBeenCalledWith(`${window.location.origin}/plugins`);
});

test('signed in, a person sees who they are signed in as, and Sign out forgets only them', async () => {
  const accounts = { 'ada@example.com': { upn: 'ada@contoso.com' }, 'bo@example.com': { upn: 'bo@contoso.com' } };
  serve([P('microsoft365', { status: 'connected', secrets_set: ['client_secret'], config: { tenant_id: 't', client_id: 'c', mode: 'delegated', accounts } })]);
  m.microsoftSignout.mockResolvedValue(P('microsoft365', { status: 'connected', secrets_set: ['client_secret'], config: { mode: 'delegated', accounts: { 'bo@example.com': accounts['bo@example.com'] } } }));
  await open();
  await click(button('Manage', row('Microsoft 365')));
  expect(sheet()?.textContent).toContain('Signed in as ada@contoso.com.');
  expect(sheet()?.textContent).toContain('Also signed in here: bo@contoso.com.');
  await click(button('Sign out', sheet() as HTMLElement));
  expect(m.microsoftSignout).toHaveBeenCalled();
  expect(button('Sign in with Microsoft', sheet() as HTMLElement)).toBeTruthy();
});

test('back from Microsoft, the tab finishes the sign-in once and forgets the code', async () => {
  serve([P('microsoft365', { status: 'needs_auth', secrets_set: ['client_secret'], config: { mode: 'delegated', accounts: {} } })]);
  m.microsoftComplete.mockImplementation(async () => {
    catalog = [P('microsoft365', { status: 'connected', secrets_set: ['client_secret'], config: { mode: 'delegated', accounts: { 'ada@example.com': { upn: 'ada@contoso.com' } } } })];
    return catalog[0];
  });
  window.history.replaceState(null, '', '/extensions?code=abc&state=st_1&session_state=x');
  await open();
  expect(m.microsoftComplete).toHaveBeenCalledTimes(1);
  expect(m.microsoftComplete).toHaveBeenCalledWith('abc', 'st_1');
  expect(window.location.search).toBe('');
  expect(say).toHaveBeenCalledWith('Signed in with Microsoft.');
  expect(row('Microsoft 365').querySelector('.pl-warn')).toBeNull();
});

test('a sign-in Microsoft did not finish is said, and nothing is sent', async () => {
  serve([P('microsoft365')]);
  window.history.replaceState(null, '', '/extensions?error=access_denied&error_description=The+user+declined&state=st_1');
  await open();
  expect(m.microsoftComplete).not.toHaveBeenCalled();
  expect(say).toHaveBeenCalledWith('Microsoft did not complete the sign-in: The user declined');
  expect(window.location.search).toBe('');
  expect(signInReturn('?tab=envs')).toBeNull();
});

test('Disconnect says which setups lose it, then turns it off with its settings kept', async () => {
  serve([P('github', { status: 'connected', config: { repo: 'acme/app' }, secrets_set: ['token'] })]);
  await open();
  await click(button('Disconnect', row('GitHub')));
  const ask = document.querySelector('[role="dialog"], [role="alertdialog"]') as HTMLElement;
  expect(ask.textContent).toContain('Mail helper uses it.');
  await click(button('Disconnect', ask));
  expect(m.setPlug).toHaveBeenCalledWith('github', { enabled: false });
  expect(say).toHaveBeenCalledWith('GitHub disconnected.');
  expect(connectedNames()).toEqual([]);
  expect(tile('GitHub').textContent).toContain('Turned off here.');
});

test('one search over both sections', async () => {
  serve([P('browser', { status: 'connected' }), P('github', { status: 'connected', config: { repo: 'acme/app' } }), P('vercel')]);
  await open();
  await type(el.querySelector('.pl-q input') as HTMLInputElement, 'git');
  expect(connectedNames()).toEqual(['GitHub']);
  expect(section('pl-con-h')?.querySelector('.count')?.textContent).toBe('1');
  expect(section('pl-all-h')?.textContent).toContain('Nothing else to connect matches “git”.');
  await type(el.querySelector('.pl-q input') as HTMLInputElement, 'zzz');
  expect(section('pl-con-h')).toBeFalsy();
  expect(section('pl-all-h')?.textContent).toContain('Nothing matches “zzz”.');
});
