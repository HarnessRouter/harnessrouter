/** @jest-environment jsdom */
// A press on a card's picture must open the card. React 19 sets innerHTML again for every new `{ __html }` object, so a
// drawing written in place was rebuilt on each render, and a press that began on a brick ended on a node that was gone
// (Studio's cards needed a second click, 2026-11-06). Markup.tsx keeps the drawing while its markup is the same.
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { readdirSync, readFileSync, statSync } from 'fs';
import { join, relative } from 'path';
import { Iso } from './Iso';
import { Markup } from './Markup';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const TOWER = '<svg viewBox="0 0 10 10"><polygon points="0,0 10,0 5,10"/></svg>';

function Card({ tick }: { tick: number }) {
  return <a href="/studio/x" data-tick={tick}><Iso svg={TOWER} /><Markup className="lib-ic" html={TOWER} /><span className="tasks">{`Tasks ${tick}`}</span></a>;
}

test('a card that renders again keeps the very drawing a press began on', () => {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const root = createRoot(host);
  let bump: () => void = () => {};
  function Page() {
    const [tick, setTick] = useState(0);
    bump = () => setTick((t) => t + 1);
    return <Card tick={tick} />;
  }
  act(() => root.render(<Page />));
  const [brick, icon] = Array.from(host.querySelectorAll('polygon'));
  for (let i = 0; i < 3; i++) act(() => bump());
  expect(host.querySelector('.tasks')?.textContent).toBe('Tasks 3');
  const [brick2, icon2] = Array.from(host.querySelectorAll('polygon'));
  expect(brick2).toBe(brick);
  expect(icon2).toBe(icon);
  expect(brick.isConnected && icon.isConnected).toBe(true);
  act(() => root.unmount());
  host.remove();
});

test('no drawing in the console builds its markup object in place', () => {
  const walk = (dir: string): string[] => readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
  const inPlace = walk(__dirname)
    .filter((f) => /\.tsx$/.test(f) && !/\.test\.tsx$/.test(f))
    .filter((f) => /dangerouslySetInnerHTML=\{\{/.test(readFileSync(f, 'utf8')))
    .map((f) => relative(__dirname, f));
  expect(inPlace).toEqual([]);
});

test('the way it replaces did lose the drawing on every render, which is the bug this guards', () => {
  const host = document.createElement('div');
  const root = createRoot(host);
  // eslint-disable-next-line react/no-danger
  const Old = ({ tick }: { tick: number }) => <a href="/x" data-tick={tick}><span dangerouslySetInnerHTML={{ __html: TOWER }} /></a>;
  act(() => root.render(<Old tick={0} />));
  const brick = host.querySelector('polygon');
  act(() => root.render(<Old tick={1} />));
  expect(host.querySelector('polygon')).not.toBe(brick);
  expect(brick?.isConnected).toBe(false);
  act(() => root.unmount());
});
