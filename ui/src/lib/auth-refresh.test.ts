/** @jest-environment jsdom */
// A session refresh that is still in flight when the user switches organization must not
// write the pre-switch session back when its answer lands: the merge goes onto the session
// current at completion, or is dropped when the token changed underneath it.
import { logout, refreshMe, refreshToken, reconcileSession, switchOrg } from './auth';

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

/** fetch answering each listed path from its function; the first call to a path named in
 *  `deferred` waits until the test releases it, every other call answers at once. */
function engine(
  answers: Record<string, (init?: RequestInit) => { body: unknown; status?: number }>,
  deferred: string[] = [],
) {
  const waiting: Record<string, () => void> = {};
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const path = Object.keys(answers).find((p) => url.endsWith(p));
    if (!path) return Promise.resolve(json({}));
    const answer = () => { const a = answers[path](init); return json(a.body, a.status ?? 200); };
    if (deferred.includes(path) && !waiting[path]) {
      return new Promise((resolve) => { waiting[path] = () => resolve(answer()); });
    }
    return Promise.resolve(answer());
  });
  return (path: string) => { waiting[path]?.(); };
}

const switchAnswer = (init?: RequestInit) => {
  const orgId = JSON.parse(String(init?.body)).org_id;
  return { body: { token: `tok${orgId}`, org_id: orgId } };
};
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('an answer for a session the user has already left', () => {
  it('a token slide that lands after an organization switch keeps the switched session', async () => {
    const release = engine({ '/v1/auth/refresh': () => ({ body: { token: 'tokA2' } }), '/v1/auth/switch-org': switchAnswer }, ['/v1/auth/refresh']);
    const sliding = refreshToken();
    await switchOrg('B');

    release('/v1/auth/refresh');

    expect(await sliding).toBe(false);
    // Before: token tokA2 (org A's) stored with orgId B, so requests ran against A.
    expect(stored()).toMatchObject({ token: 'tokB', orgId: 'B' });
  });

  it('a 401 for the pre-switch token does not sign the switched session out', async () => {
    const release = engine({ '/v1/auth/refresh': () => ({ body: {}, status: 401 }), '/v1/auth/switch-org': switchAnswer }, ['/v1/auth/refresh']);
    const sliding = refreshToken();
    await switchOrg('B');

    release('/v1/auth/refresh');

    expect(await sliding).toBe(false);
    expect(stored()).toMatchObject({ token: 'tokB', orgId: 'B' });
  });

  it('an organization switch answered after sign-out does not sign back in', async () => {
    const release = engine({ '/v1/auth/switch-org': switchAnswer }, ['/v1/auth/switch-org']);
    const switching = switchOrg('B');
    logout();

    release('/v1/auth/switch-org');

    await expect(switching).rejects.toThrow();
    expect(stored()).toBeNull();
  });

  it("reconcileSession's fallback switch answered after sign-out writes nothing back", async () => {
    localStorage.setItem(SESSION_KEY, JSON.stringify({ token: 'tokZ', member: { id: 'member.ann' }, orgs: [{ id: 'Z' }], orgId: 'Z' }));
    const release = engine({ '/v1/auth/me': () => ({ body: ME }), '/v1/auth/switch-org': switchAnswer }, ['/v1/auth/switch-org']);
    const reconciling = reconcileSession();
    await settle();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/v1/auth/switch-org'))).toBe(true);
    logout();

    release('/v1/auth/switch-org');

    expect(await reconciling).toBeNull();
    expect(stored()).toBeNull();
  });

  it('with nothing in between, a token slide still stores the fresh token', async () => {
    engine({ '/v1/auth/refresh': () => ({ body: { token: 'tokA2' } }) });

    expect(await refreshToken()).toBe(true);
    expect(stored()).toMatchObject({ token: 'tokA2', orgId: 'A' });
  });

  it('with nothing in between, a switch still lands and keeps the member and org list', async () => {
    engine({ '/v1/auth/switch-org': switchAnswer });

    const result = await switchOrg('B');

    expect(result).toMatchObject({ token: 'tokB', orgId: 'B', member: { id: 'member.ann' }, orgs: [{ id: 'A' }, { id: 'B' }] });
    expect(stored()).toMatchObject({ token: 'tokB', orgId: 'B' });
  });
});
