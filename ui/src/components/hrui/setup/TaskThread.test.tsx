/** @jest-environment jsdom */
// #594: a reply's link to a file its task made opened "file not found" unless the task was shared.
// Md pointed the link at the task's file address, /{harness}/{session}/workspace/{path}, which the
// console relays to the PUBLIC read: it answers only for a shared task, and a plain link carries no
// sign-in. A click in the signed-in console now hands the path to the page, which opens the file
// beside the conversation and reads it with the sign-in, as the file's card does. The address stays
// the link's own, for a shared view and for opening in a new tab.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// The links of a Markdown text drawn through Md's own `a`, and nothing else of Markdown. Each href is
// sanitized first, as react-markdown 9 does (its defaultUrlTransform, unless the caller gives its own):
// a scheme it does not know reaches `a` as ''.
jest.mock('react-markdown', () => {
  const safe = /^(https?|ircs?|mailto|xmpp)$/i;
  const defaultUrlTransform = (v: string) => {
    const colon = v.indexOf(':'), q = v.indexOf('?'), h = v.indexOf('#'), sl = v.indexOf('/');
    return colon === -1 || (sl !== -1 && colon > sl) || (q !== -1 && colon > q) || (h !== -1 && colon > h)
      || safe.test(v.slice(0, colon)) ? v : '';
  };
  type A = (p: { href?: string; children?: unknown }) => import('react').ReactElement;
  const Markdown = ({ children, components, urlTransform }: {
    children: string; components: { a: unknown }; urlTransform?: (url: string, key: string) => string;
  }) => {
    const out: unknown[] = [];
    const re = /\[([^\]]*)\]\(([^)]*)\)/g;
    let last = 0;
    let m: RegExpExecArray | null;
    const Link = components.a as A;
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

import { Md } from './TaskThread';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
beforeEach(() => { el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

const draw = (text: string, extra: Partial<Parameters<typeof Md>[0]> = {}) => act(() => {
  root.render(<Md text={text} sid="hsess_1" harnessId="chrn_1" produced={['hello-world.pptx', 'out/report v2.pdf']} {...extra} />);
});
const link = (name: string) => Array.from(el.querySelectorAll('a')).find((a) => a.textContent === name) as HTMLAnchorElement;
/** a click as the browser sends it; true when the page took it (the browser does not follow the link) */
const click = (a: HTMLAnchorElement, init: MouseEventInit = {}) => {
  const ev = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ...init });
  act(() => { a.dispatchEvent(ev); });
  return ev.defaultPrevented;
};

test('a click on a link to a file the task made opens it in the console, signed in, not at the public address', () => {
  const onOpen = jest.fn();
  draw('Here it is: [Download hello-world.pptx](hello-world.pptx)', { onOpen });
  const a = link('Download hello-world.pptx');
  expect(click(a)).toBe(true);
  expect(onOpen).toHaveBeenCalledWith('hello-world.pptx');
});

test('the link keeps the file address for a new tab and a shared view, and opens in a new tab only when asked', () => {
  const onOpen = jest.fn();
  draw('[the deck](/workspace/hello-world.pptx)', { onOpen });
  const a = link('the deck');
  expect(a.getAttribute('href')).toBe('/chrn_1/hsess_1/workspace/hello-world.pptx');
  expect(a.getAttribute('target')).toBe('_blank');
  for (const mod of [{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { altKey: true }]) {
    expect(click(a, mod)).toBe(false);
  }
  expect(onOpen).not.toHaveBeenCalled();
});

test('a name in another folder and an escaped name resolve to the file the task made', () => {
  const onOpen = jest.fn();
  draw('[report](sandbox:/workspace/report%20v2.pdf)', { onOpen });
  const a = link('report');
  expect(a.getAttribute('href')).toBe('/chrn_1/hsess_1/workspace/out/report%20v2.pdf');
  click(a);
  expect(onOpen).toHaveBeenCalledWith('out/report v2.pdf');
});

test('a name the task did not make is plain text, and a web address is left as it is', () => {
  const onOpen = jest.fn();
  draw('[notes](notes.md) and [the docs](https://example.com/guide.html)', { onOpen });
  expect(link('notes')).toBeUndefined();
  expect(el.textContent).toContain('notes');
  const web = link('the docs');
  expect(web.getAttribute('href')).toBe('https://example.com/guide.html');
  expect(click(web)).toBe(false);
  expect(onOpen).not.toHaveBeenCalled();
});

test('a link with a stray percent sign is drawn rather than breaking the reply', () => {
  draw('[odd](100%.pptx)', { produced: [] });
  expect(link('odd').getAttribute('href')).toBe('/chrn_1/hsess_1/workspace/100%25.pptx');
});

test('without a place to open it (a view with no sign-in), the link is the file address and the browser follows it', () => {
  draw('[Download hello-world.pptx](hello-world.pptx)');
  expect(click(link('Download hello-world.pptx'))).toBe(false);
});

test('a sandbox: link, as some agents write their files, resolves like any other instead of being blanked', () => {
  const onOpen = jest.fn();
  draw('[the deck](sandbox:/mnt/data/hello-world.pptx)', { onOpen });
  const a = link('the deck');
  expect(a.getAttribute('href')).toBe('/chrn_1/hsess_1/workspace/hello-world.pptx');
  click(a);
  expect(onOpen).toHaveBeenCalledWith('hello-world.pptx');
});

test('a sandbox: link with no task to resolve it against is plain text, never an address as written', () => {
  act(() => { root.render(<Md text="[the deck](sandbox:/mnt/data/hello-world.pptx) and [x](javascript:alert(1))" />); });
  expect(link('the deck')).toBeUndefined();
  expect(el.textContent).toContain('the deck');
  expect(el.querySelector('a[href^="sandbox:"]')).toBeNull();
  expect(link('x').getAttribute('href')).toBe('');
});
