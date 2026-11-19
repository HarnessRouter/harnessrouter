/** @jest-environment jsdom */
// A session refresh that is still in flight when the user switches organization must not
// write the pre-switch session back when its answer lands: the merge goes onto the session
// current at completion, or is dropped when the token changed underneath it.
import { refreshMe, reconcileSession, switchOrg } from './auth';

const SESSION_KEY = 'agentstudio.session';
const ME = { member: { id: 'member.ann', name: 'Ann' }, org_id: 'A', orgs: [{ id: 'A' }, { id: 'B' }] };

const fetchMock = jest.fn();
global.fetch = fetchMock as unknown as typeof fetch;
const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) });

/** fetch that answers /v1/auth/me only when the test says so, and switch-org at once. */
function controlledEngine() {
  let releaseMe: (() => void) | undefined;
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url.endsWith('/v1/auth/me')) {
      return new Promise((resolve) => { releaseMe = () => resolve(json(ME)); });
    }
    if (url.endsWith('/v1/auth/switch-org')) {
      const orgId = JSON.parse(String(init?.body)).org_id;
      return Promise.resolve(json({ token: `tok${orgId}`, org_id: orgId }));
    }
    return Promise.resolve(json({}));
  });
  return () => { releaseMe?.(); };
}

const stored = () => JSON.parse(localStorage.getItem(SESSION_KEY) || 'null');

beforeEach(() => {
  fetchMock.mockReset();
  localStorage.clear();
  localStorage.setItem(SESSION_KEY, JSON.stringify({ token: 'tokA', member: { id: 'member.ann' }, orgs: [{ id: 'A' }, { id: 'B' }], orgId: 'A' }));
});

describe('a refresh that lands after an organization switch', () => {
  it('refreshMe keeps the switch and merges onto the newer session', async () => {
    const answerMe = controlledEngine();
    const refreshing = refreshMe();
    await switchOrg('B');
    expect(stored()).toMatchObject({ token: 'tokB', orgId: 'B' });

    answerMe();
    const result = await refreshing;

    expect(stored()).toMatchObject({ token: 'tokB', orgId: 'B' });
    expect(result).toMatchObject({ token: 'tokB', orgId: 'B' });
  });

  it('reconcileSession keeps the switch too', async () => {
    const answerMe = controlledEngine();
    const reconciling = reconcileSession();
    await switchOrg('B');

    answerMe();
    const result = await reconciling;

    expect(stored()).toMatchObject({ token: 'tokB', orgId: 'B' });
    expect(result).toMatchObject({ token: 'tokB', orgId: 'B' });
  });

  it('with no switch in between, refreshMe still merges the fetched member and orgs', async () => {
    const answerMe = controlledEngine();
    const refreshing = refreshMe();
    answerMe();
    const result = await refreshing;

    expect(result).toMatchObject({ token: 'tokA', orgId: 'A', member: { id: 'member.ann', name: 'Ann' } });
    expect(stored()).toMatchObject({ token: 'tokA', orgId: 'A', member: { name: 'Ann' } });
  });

  it('with no switch in between, reconcileSession drops an organization that is gone', async () => {
    const answerMe = controlledEngine();
    localStorage.setItem(SESSION_KEY, JSON.stringify({ token: 'tokZ', member: { id: 'member.ann' }, orgs: [{ id: 'Z' }], orgId: 'Z' }));
    const reconciling = reconcileSession();
    answerMe();
    const result = await reconciling;

    // Z is not in the engine's list any more: the session moves to the first org it offers.
    expect(result).toMatchObject({ token: 'tokA', orgId: 'A', orgs: [{ id: 'A' }, { id: 'B' }] });
  });
});
