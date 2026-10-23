/** @jest-environment jsdom */
// Start's first way starts in the box above it: a click on its card puts the cursor there (Richard, 10-21: the card
// did nothing when clicked), while its demo tasks keep their own buttons and the other two ways open their guides.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/harness', () => ({ ...jest.requireActual('@/lib/harness'), useBases: () => null, useModelCatalog: () => null }));
jest.mock('./start/art', () => ({ wayPic: () => '<svg></svg>' }));
jest.mock('./start/Handoff', () => ({ Handoff: ({ kind }: { kind: string }) => <div id="handoff">{kind}</div> }));
jest.mock('./NewSetup', () => ({ NewSetup: () => <div id="newsetup" /> }));

import { StartPage } from './StartPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let el: HTMLDivElement;
const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve(); }); };
const click = async (n: Element | null) => { await act(async () => { (n as HTMLElement).click(); }); await flush(); };
const box = () => el.querySelector('#stAsk') as HTMLTextAreaElement;

beforeEach(async () => {
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<StartPage />); });
  await flush();
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('a click on the first card puts the cursor in the box above it, at the end of what is written', async () => {
  expect(document.activeElement).not.toBe(box());
  await click(el.querySelector('#sgMainT'));
  expect(document.activeElement).toBe(box());
  expect(box().selectionStart).toBe(box().value.length);
});

test("a demo task's own button still starts that demo, not the box", async () => {
  const demo = el.querySelector('.sg-main .td-list button');
  expect(demo).not.toBeNull();
  await click(demo);
  expect(document.activeElement).not.toBe(box());
});

test('the other two ways still open their guides', async () => {
  const sides = el.querySelectorAll('.sg-side');
  await click(sides[0]);
  expect(el.querySelector('#handoff')?.textContent).toBe('new');
});

describe('after a demo task types its sentence', () => {
  const realWidth = window.innerWidth;
  const realMM = window.matchMedia;
  beforeEach(() => {   // reduced motion: the sentence lands at once, so the end of the typing is one tick away
    window.matchMedia = ((q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => {
    Object.defineProperty(window, 'innerWidth', { value: realWidth, configurable: true });
    window.matchMedia = realMM;
  });
  const typed = async () => {
    await click(el.querySelector('.sg-main .td-list button'));
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
    await flush();
  };

  test('on a phone the cursor moves to Continue, now that it can be pressed', async () => {
    Object.defineProperty(window, 'innerWidth', { value: 390, configurable: true });
    await typed();
    const go = el.querySelector('#stAskGo') as HTMLButtonElement;
    expect(go.disabled).toBe(false);
    expect(document.activeElement).toBe(go);
  });

  test('on a wider screen the cursor goes to the end of the sentence in the box', async () => {
    Object.defineProperty(window, 'innerWidth', { value: 1280, configurable: true });
    await typed();
    expect(document.activeElement).toBe(box());
    expect(box().value.length).toBeGreaterThan(0);
    expect(box().selectionStart).toBe(box().value.length);
  });
});
