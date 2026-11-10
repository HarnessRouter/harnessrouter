/** @jest-environment jsdom */
// Deploy to Cloud, the setup page bar's second action: one click deploys; the first time it opens the
// HarnessRouter Cloud sign-in in a new tab and goes on by itself once the key lands on this instance;
// it always says where the setup stands (Deploy to Cloud, Update Cloud, In Cloud).
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/cloud-upload', () => ({
  listTargets: jest.fn(), statusOne: jest.fn(), uploadOne: jest.fn(), addTarget: jest.fn(),
  startDeploySignIn: jest.fn(), pollDeploySignIn: jest.fn(),
}));
jest.mock('../toast', () => ({ toast: jest.fn() }));

import { DeployCloud, SIGNIN_EVERY_MS } from './DeployCloud';

const lib = jest.requireMock('@/lib/cloud-upload') as Record<string, jest.Mock>;
const { toast } = jest.requireMock('../toast') as { toast: jest.Mock };
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let root: Root;
let host: HTMLElement;
const TARGET = { id: 't1', label: 'Research (richard)', revoked: false, base_url: 'https://api.harnessrouter.ai', key_hint: 'sk-hr-…abcd', member: 'richard', workspace_name: 'Research' };
const flush = async () => { for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); }); };
const btn = () => host.querySelector<HTMLButtonElement>('.dc-b') as HTMLButtonElement;
const label = () => btn().querySelector('.ag-act-l')?.textContent;

async function show() {
  act(() => root.render(<DeployCloud id="chrn_a" name="Weekly feedback summary" />));
  await flush();
}

beforeEach(() => {
  jest.useRealTimers();
  Object.values(lib).forEach((m) => m.mockReset());
  toast.mockReset();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('Deploy to Cloud', () => {
  test('never deployed, a destination kept: one click deploys, and the button says In Cloud', async () => {
    lib.statusOne.mockResolvedValue({ uploaded: false });
    lib.listTargets.mockResolvedValue({ targets: [TARGET], last: 't1' });
    lib.uploadOne.mockResolvedValue({ ok: true, action: 'create', remote_id: 'chrn_a', open_url: 'https://app.harnessrouter.ai/studio/chrn_a',
      status: { uploaded: true, changed: false, target: 'Research (richard)' } });
    const open = jest.spyOn(window, 'open').mockReturnValue(null);
    await show();
    expect(label()).toBe('Deploy to Cloud');
    await act(async () => { btn().click(); });
    await flush();
    expect(lib.uploadOne).toHaveBeenCalledWith('chrn_a', 't1');
    expect(open).not.toHaveBeenCalled();                       // no sign-in, no tab
    expect(lib.startDeploySignIn).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith('Weekly feedback summary is deployed to HarnessRouter Cloud.');
    expect(label()).toBe('In Cloud');
    open.mockRestore();
  });

  test('the first time: the click opens the Cloud sign-in in a new tab, and the deploy goes on by itself once signed in', async () => {
    jest.useFakeTimers();
    lib.statusOne.mockResolvedValue({ uploaded: false });
    lib.listTargets.mockResolvedValue({ targets: [], last: '' });
    lib.startDeploySignIn.mockResolvedValue({ code: 'c1', url: 'https://app.harnessrouter.ai/get-key?code=c1' });
    lib.pollDeploySignIn.mockResolvedValueOnce('waiting').mockResolvedValueOnce(TARGET);
    lib.uploadOne.mockResolvedValue({ ok: true, action: 'create', remote_id: 'chrn_a', open_url: 'https://app.harnessrouter.ai/studio/chrn_a',
      status: { uploaded: true, changed: false } });
    const tab = { location: { href: '' }, opener: {} as unknown, close: jest.fn() };
    const open = jest.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    await show();
    await act(async () => { btn().click(); });
    expect(open).toHaveBeenCalledWith('about:blank', '_blank');    // opened in the click, so it is not blocked
    await flush();
    expect(tab.opener).toBeNull();
    expect(tab.location.href).toBe('https://app.harnessrouter.ai/get-key?code=c1');
    expect(label()).toBe('Finish signing in');
    await act(async () => { jest.advanceTimersByTime(SIGNIN_EVERY_MS); });
    await flush();
    expect(lib.uploadOne).not.toHaveBeenCalled();                // still on the Cloud page
    await act(async () => { jest.advanceTimersByTime(SIGNIN_EVERY_MS); });
    await flush();
    expect(lib.uploadOne).toHaveBeenCalledWith('chrn_a', 't1');  // the key landed: deployed to it
    expect(label()).toBe('In Cloud');
    open.mockRestore();
  });

  test('changed since its deploy: Update Cloud, with its dot, and one click replaces the copy', async () => {
    lib.statusOne.mockResolvedValue({ uploaded: true, changed: true });
    lib.listTargets.mockResolvedValue({ targets: [TARGET], last: 't1' });
    lib.uploadOne.mockResolvedValue({ ok: true, action: 'replace', status: { uploaded: true, changed: false } });
    await show();
    expect(label()).toBe('Update Cloud');
    expect(host.querySelector('.dc-dot')).not.toBeNull();
    await act(async () => { btn().click(); });
    await flush();
    expect(lib.uploadOne).toHaveBeenCalledWith('chrn_a', 't1');
    expect(toast).toHaveBeenCalledWith('Weekly feedback summary is updated in HarnessRouter Cloud.');
    expect(label()).toBe('In Cloud');
  });

  test('In Cloud: its menu opens the copy in Cloud, deploys again, or deploys to another workspace', async () => {
    lib.statusOne.mockResolvedValue({ uploaded: true, changed: false, open_url: 'https://app.harnessrouter.ai/studio/chrn_a' });
    lib.listTargets.mockResolvedValue({ targets: [TARGET], last: 't1' });
    const open = jest.spyOn(window, 'open').mockReturnValue(null);
    await show();
    expect(label()).toBe('In Cloud');
    expect(btn().getAttribute('aria-haspopup')).toBe('menu');
    await act(async () => { btn().click(); });
    const items = [...host.querySelectorAll<HTMLButtonElement>('.dc-pop [role="menuitem"]')];
    expect(items.map((b) => b.textContent)).toEqual(['Open in HarnessRouter Cloud ↗', 'Deploy again', 'Deploy to another workspace…']);
    await act(async () => { items[0].click(); });
    expect(open).toHaveBeenCalledWith('https://app.harnessrouter.ai/studio/chrn_a', '_blank', 'noopener');
    expect(host.querySelector('.dc-pop')).toBeNull();
    open.mockRestore();
  });

  test('a deploy the server refuses says so in its words and the button is back as it was', async () => {
    lib.statusOne.mockResolvedValue({ uploaded: false });
    lib.listTargets.mockResolvedValue({ targets: [TARGET], last: 't1' });
    lib.uploadOne.mockRejectedValue(new Error('the cloud workspace rejected this key'));
    await show();
    await act(async () => { btn().click(); });
    await flush();
    expect(toast).toHaveBeenCalledWith('The cloud workspace rejected this key.');
    expect(label()).toBe('Deploy to Cloud');
    expect(btn().disabled).toBe(false);
  });

  test('Cloud cannot be reached for the sign-in: the tab it opened closes and the reason is said', async () => {
    lib.statusOne.mockResolvedValue({ uploaded: false });
    lib.listTargets.mockResolvedValue({ targets: [], last: '' });
    lib.startDeploySignIn.mockRejectedValue(new Error('502'));
    const tab = { location: { href: '' }, opener: null, close: jest.fn() };
    const open = jest.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    await show();
    await act(async () => { btn().click(); });
    await flush();
    expect(tab.close).toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith('HarnessRouter Cloud could not be reached just now. Try again.');
    expect(label()).toBe('Deploy to Cloud');
    open.mockRestore();
  });

  test('the kept workspaces could not be read: the click opens no sign-in, says why, and reads them again', async () => {
    // a failed read used to read as "none kept", and the click started a new pairing in silence
    lib.statusOne.mockResolvedValue({ uploaded: false });
    lib.listTargets.mockRejectedValueOnce(new Error('503')).mockResolvedValue({ targets: [TARGET], last: 't1' });
    const open = jest.spyOn(window, 'open').mockReturnValue(null);
    await show();
    await act(async () => { btn().click(); });
    await flush();
    expect(open).not.toHaveBeenCalled();
    expect(lib.startDeploySignIn).not.toHaveBeenCalled();
    expect(lib.uploadOne).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith('Your HarnessRouter Cloud workspaces could not be read just now, so nothing was deployed. Try again.');
    expect(lib.listTargets).toHaveBeenCalledTimes(2);
    open.mockRestore();
  });

  test('every kept key was refused by Cloud: the button says Reconnect to Cloud and why, and only then signs in', async () => {
    lib.statusOne.mockResolvedValue({ uploaded: true, changed: false });
    lib.listTargets.mockResolvedValue({ targets: [{ ...TARGET, revoked: true }], last: 't1' });
    lib.startDeploySignIn.mockResolvedValue({ code: 'c1', url: 'https://app.harnessrouter.ai/get-key?code=c1' });
    const tab = { location: { href: '' }, opener: {} as unknown, close: jest.fn() };
    const open = jest.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    await show();
    expect(label()).toBe('Reconnect to Cloud');
    expect(btn().title).toBe('HarnessRouter Cloud refused the key this instance keeps. Sign in again to reconnect, then Weekly feedback summary deploys.');
    expect(btn().getAttribute('aria-haspopup')).toBeNull();     // no In Cloud menu on a key that cannot deploy
    await act(async () => { btn().click(); });
    await flush();
    expect(lib.startDeploySignIn).toHaveBeenCalled();
    expect(tab.location.href).toBe('https://app.harnessrouter.ai/get-key?code=c1');
    open.mockRestore();
  });

  test('a deploy Cloud refuses the key on reads the workspaces again, so the button turns to Reconnect to Cloud', async () => {
    lib.statusOne.mockResolvedValue({ uploaded: false });
    lib.listTargets.mockResolvedValueOnce({ targets: [TARGET], last: 't1' })
      .mockResolvedValue({ targets: [{ ...TARGET, revoked: true }], last: 't1' });
    lib.uploadOne.mockRejectedValue(new Error('HarnessRouter Cloud refused the key this instance keeps for that workspace. Sign in again to reconnect it.'));
    await show();
    expect(label()).toBe('Deploy to Cloud');
    await act(async () => { btn().click(); });
    await flush();
    expect(toast).toHaveBeenCalledWith('HarnessRouter Cloud refused the key this instance keeps for that workspace. Sign in again to reconnect it.');
    expect(label()).toBe('Reconnect to Cloud');
  });
});
