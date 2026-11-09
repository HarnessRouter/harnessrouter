/** @jest-environment jsdom */
// The public share page: a conversation that could not be read is said, with Try again, never drawn
// as a conversation with nothing in it (the gateway answers a failed read with a 503).
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/app/revamp.css', () => ({}));
jest.mock('iconify-icon', () => ({}));
jest.mock('next/navigation', () => ({ useParams: () => ({ token: 'shr1' }) }));
// The links of a reply drawn through the page's own `a`, each href sanitized first as react-markdown 9
// does (a scheme it does not know reaches `a` as ''), and nothing else of Markdown.
jest.mock('react-markdown', () => {
  const safe = /^(https?|ircs?|mailto|xmpp)$/i;
  const defaultUrlTransform = (v: string) => {
    const colon = v.indexOf(':'), q = v.indexOf('?'), h = v.indexOf('#'), sl = v.indexOf('/');
    return colon === -1 || (sl !== -1 && colon > sl) || (q !== -1 && colon > q) || (h !== -1 && colon > h)
      || safe.test(v.slice(0, colon)) ? v : '';
  };
  type A = (p: { href?: string; children?: unknown }) => import('react').ReactElement;
  const Markdown = ({ children, components, urlTransform }: {
    children: string; components?: { a?: unknown }; urlTransform?: (url: string, key: string) => string;
  }) => {
    const out: unknown[] = [];
    const re = /\[([^\]]*)\]\(([^)]*)\)/g;
    let last = 0;
    let m: RegExpExecArray | null;
    const Link = (components?.a || (({ href, children: c }: { href?: string; children?: unknown }) => <a href={href}>{c as never}</a>)) as A;
    while ((m = re.exec(children))) {
      out.push(children.slice(last, m.index));
      out.push(<Link key={m.index} href={(urlTransform || defaultUrlTransform)(m[2], 'href')}>{m[1]}</Link>);
      last = re.lastIndex;
    }
    out.push(children.slice(last));
    return <p>{out as never}</p>;
  };
  return { __esModule: true, default: Markdown, defaultUrlTransform };
});
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => null }));
jest.mock('@/components/FileTypeIcon', () => ({ FileTypeIcon: () => null }));

import SharePage from './page';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
const json = (status: number, body: unknown) => Promise.resolve({ ok: status < 400, status, json: async () => body } as Response);
const flush = async () => { for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); }); };
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('a conversation that could not be read says so, and Try again reads it again', async () => {
  let turnsAnswer = 503;
  global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta') ? json(200, { title: 'Pet Food' })
    : String(url).endsWith('/files') ? json(200, { files: [] })
    : turnsAnswer === 503 ? json(503, { error: { type: 'server_error', code: 'server_error' } })
    : json(200, { turns: [{ id: 'resp_1', user: 'Pet food', assistant: 'Done.' }] }))) as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<SharePage />); });
  await flush();
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('This conversation could not be loaded just now.');
  expect(el.textContent).not.toContain('No conversation content.');
  turnsAnswer = 200;
  await act(async () => { (Array.from(el.querySelectorAll('button')).find((b) => b.textContent === 'Try again') as HTMLButtonElement).click(); });
  await flush();
  expect(el.textContent).toContain('Done.');
  expect(el.querySelector('[role="alert"]')).toBeNull();
});

test('a conversation with no turns still says so plainly', async () => {
  global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta') ? json(200, { title: 'Pet Food' })
    : String(url).endsWith('/files') ? json(200, { files: [] })
    : json(200, { turns: [] }))) as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<SharePage />); });
  await flush();
  expect(el.textContent).toContain('No conversation content.');
  expect(el.querySelector('[role="alert"]')).toBeNull();
});

// Same rule, the artifacts read four lines above the turns read: a failed read is said, never drawn
// as a Task that produced nothing (the gateway answers 500 when the workspace tarball is truncated).
const alertWith = (text: string) => Array.from(el.querySelectorAll('[role="alert"]')).find((n) => n.textContent?.includes(text));

test('artifacts that could not be read say so, and are never drawn as a Task with none', async () => {
  global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta') ? json(200, { title: 'Pet Food' })
    : String(url).endsWith('/files') ? json(500, { detail: 'boom' })
    : json(200, { turns: [{ id: 'resp_1', user: 'Pet food', assistant: 'Done.' }] }))) as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<SharePage />); });
  await flush();
  expect(alertWith('The artifacts could not be loaded just now.')).toBeTruthy();
  expect(el.textContent).not.toContain('No artifacts in this Task.');
  expect(el.textContent).not.toContain('0 files');
});

test('a Task with no artifacts still says so plainly', async () => {
  global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta') ? json(200, { title: 'Pet Food' })
    : String(url).endsWith('/files') ? json(200, { files: [] })
    : json(200, { turns: [{ id: 'resp_1', user: 'Pet food', assistant: 'Done.' }] }))) as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<SharePage />); });
  await flush();
  expect(el.textContent).toContain('No artifacts in this Task.');
  expect(el.textContent).toContain('0 files');
  expect(alertWith('The artifacts could not be loaded just now.')).toBeUndefined();
});

// #573: the link could not be read just now (503) is not a link that is gone (404). Only a 404 may say
// the link was revoked or never existed; anything else says to try again, and Try again reads it again.
test('a share the server could not read just now says so with Try again, never that the link is gone', async () => {
  let metaAnswer = 503;
  global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta')
    ? (metaAnswer === 503 ? json(503, { error: { type: 'server_error' } }) : json(200, { title: 'Pet Food' }))
    : String(url).endsWith('/files') ? json(200, { files: [] })
    : json(200, { turns: [{ id: 'resp_1', user: 'Pet food', assistant: 'Done.' }] }))) as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<SharePage />); });
  await flush();
  expect(el.textContent).toContain('This shared Task could not be loaded just now');
  expect(el.textContent).not.toContain('unavailable');
  expect(el.textContent).not.toContain('revoked');
  metaAnswer = 200;
  await act(async () => { (Array.from(el.querySelectorAll('button')).find((b) => b.textContent === 'Try again') as HTMLButtonElement).click(); });
  await flush();
  expect(el.textContent).toContain('Pet Food');
  expect(el.textContent).toContain('Done.');
});

test('a link the server says is gone (404) says it is unavailable', async () => {
  global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta') ? json(404, { detail: 'share not found' })
    : json(404, { detail: 'share not found' }))) as unknown as typeof fetch;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<SharePage />); });
  await flush();
  expect(el.textContent).toContain('This shared Task is unavailable');
  expect(el.textContent).not.toContain('could not be loaded just now');
});

// #594: a reply's link to a file the task made opens it through this share's own file route, the
// route the server checks the token at; so does every artifact card, also once the task's ids are known
// (the task's own file address asks a self-hosted box's sign-in, which a link-holder does not have).
describe('files open through the share link', () => {
  const META = { title: 'Deck', harness_id: 'chrn_1', session_id: 'hsess_1' };
  const TURN = { id: 'resp_1', user: 'A deck please', files: [{ filename: 'out/hello-world.pptx' }],
    assistant: 'Here: [Download hello-world.pptx](hello-world.pptx), [the deck](sandbox:/mnt/data/hello-world.pptx), '
      + '[notes](notes.md), [docs](https://example.com/guide) and [the site](site/index.html).' };
  async function open() {
    global.fetch = jest.fn((url: string) => (String(url).endsWith('/meta') ? json(200, META)
      : String(url).endsWith('/files') ? json(200, { files: [{ path: 'out/hello-world.pptx', bytes: 9 }, { path: 'site/index.html', bytes: 9 }] })
      : json(200, { turns: [TURN] }))) as unknown as typeof fetch;
    el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
    await act(async () => { root.render(<SharePage />); });
    await flush();
  }
  const link = (name: string) => Array.from(el.querySelectorAll('.share-asst a')).find((a) => a.textContent === name) as HTMLAnchorElement | undefined;

  test("a reply's links to the task's files open them through the share, in a new tab", async () => {
    await open();
    for (const name of ['Download hello-world.pptx', 'the deck']) {
      expect(link(name)?.getAttribute('href')).toBe('/api/share/shr1/f/out/hello-world.pptx');
      expect(link(name)?.getAttribute('target')).toBe('_blank');
    }
    expect(link('the site')?.getAttribute('href')).toBe('/api/share/shr1/f/site/index.html');
  });

  test('a name the task did not make is plain text, and a web address is left as it is', async () => {
    await open();
    expect(link('notes')).toBeUndefined();
    expect(el.querySelector('.share-asst')?.textContent).toContain('notes');
    expect(link('docs')?.getAttribute('href')).toBe('https://example.com/guide');
    expect(el.querySelector('a[href*="/workspace/"]')).toBeNull();
  });

  test("the artifact cards' downloads keep the share route and the file's own name once the task's ids are known", async () => {
    await open();
    const dl = Array.from(el.querySelectorAll('a.wbx-filecard-dl')) as HTMLAnchorElement[];
    expect(dl.map((a) => [a.getAttribute('href'), a.getAttribute('download')])).toEqual([
      ['/api/share/shr1/f/out/hello-world.pptx', 'hello-world.pptx'],
      ['/api/share/shr1/f/site/index.html', 'index.html'],
    ]);
    const opened: string[] = [];
    const spy = jest.spyOn(window, 'open').mockImplementation((u) => { opened.push(String(u)); return null; });
    act(() => { (el.querySelector('.wbx-filecard') as HTMLElement).click(); });
    expect(opened).toEqual(['/api/share/shr1/f/out/hello-world.pptx']);
    spy.mockRestore();
  });
});
