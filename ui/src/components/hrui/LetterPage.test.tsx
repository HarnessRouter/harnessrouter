/** @jest-environment jsdom */
// The team's letter on a self-hosted instance: the hosted letter word for word, with this instance's count
// of agent harnesses in its marked place and no P.S. (the free requests it names are the hosted service's).
import { readFileSync } from 'fs';
import { join } from 'path';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));
const mockBases = jest.fn();
jest.mock('@/lib/harness', () => ({ loadBases: () => mockBases() }));
jest.mock('./Skel', () => ({ Skel: ({ label }: { label: string }) => <div className="skel">{label}</div>, SkLine: () => null }));

import { fill, LetterPage } from './LetterPage';
import { LETTER_FILE } from './letter';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const LETTER = readFileSync(join(__dirname, '../../../public', LETTER_FILE), 'utf8');
let root: Root | null = null;
let el: HTMLElement | null = null;
let answer: { ok: boolean; text: string };

async function mount() {
  const at = document.createElement('div');
  document.body.appendChild(at);
  el = at;
  const r = createRoot(at);
  root = r;
  await act(async () => { r.render(<LetterPage />); });
  for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); });
}

beforeEach(() => {
  jest.clearAllMocks();
  answer = { ok: true, text: LETTER };
  mockBases.mockResolvedValue(Object.fromEntries(Array.from({ length: 30 }, (_, i) => [`b${i}`, {}])));
  global.fetch = jest.fn(() => Promise.resolve({ ok: answer.ok, status: answer.ok ? 200 : 503, text: async () => answer.text })) as unknown as typeof fetch;
});
afterEach(() => {
  const r = root;
  if (r) act(() => r.unmount());
  el?.remove();
  root = null;
  el = null;
});
const page = () => el as HTMLElement;

test('the letter file carries both marked places, so neither is ever shown as written', () => {
  expect(LETTER).toMatch(/<!--hr:bases-->[\s\S]*?<!--\/hr:bases-->/);
  expect(LETTER).toMatch(/<!--hr:ps-->[\s\S]*?<!--\/hr:ps-->/);
});

test('the count of agent harnesses is this instance\'s own, and the P.S. is left out', () => {
  const out = (n: number | null) => {
    const html = fill(LETTER, n);
    expect(html).not.toContain('hr:bases');
    expect(html).not.toContain('hr:ps');
    expect(html).not.toContain('class="ps"');
    return /Hermes, (or [^.]*)\./.exec(html)?.[1];
  };
  expect(out(30)).toBe('or one of 30+');
  expect(out(32)).toBe('or one of 30+');
  expect(out(7)).toBe('or one of 7');
  expect(out(3)).toBe('or another');
  expect(out(null)).toBe('or another');
});

test('the page draws the letter in its frame, with the count read from the bases', async () => {
  await mount();
  expect(global.fetch).toHaveBeenCalledWith(LETTER_FILE, expect.anything());
  const frame = page().querySelector('iframe.letter-frame') as HTMLIFrameElement;
  expect(frame.title).toBe('How it works, a letter from the team');
  const doc = frame.getAttribute('srcdoc') || '';
  expect(doc).toContain('or one of 30+');
  expect(doc).not.toContain('class="ps"');
});

test('bases that cannot be read leave the sentence without a number', async () => {
  mockBases.mockRejectedValue(new Error('down'));
  await mount();
  expect((page().querySelector('iframe.letter-frame') as HTMLIFrameElement).getAttribute('srcdoc')).toContain('Hermes, or another.');
});

test('a letter that does not load says so, and Try again loads it', async () => {
  answer = { ok: false, text: '' };
  await mount();
  expect(page().textContent).toContain('The letter did not load.');
  expect(page().querySelector('iframe')).toBeNull();
  answer = { ok: true, text: LETTER };
  await act(async () => { (page().querySelector('button') as HTMLButtonElement).click(); });
  for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); });
  expect(page().querySelector('iframe.letter-frame')).toBeTruthy();
});
