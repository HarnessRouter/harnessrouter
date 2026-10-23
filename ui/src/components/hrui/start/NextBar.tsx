'use client';
// The Next card at the end of a new setup's first test (Richard, 2026-10-19: the "nx2" design; ported
// from the hosted console 10-22, "下面 set up the app 的动画"): once that test has finished, it shows what
// comes next. At the left end your app, a brick still to build, built by your coding agent; at the
// right end the setup, a built brick, by its own name; between them the task going over and the result
// coming back, and under the wires Set up the app. Pressing it asks the setup's page for its Set up the
// app sheet (SET_UP_APP_EVENT, heard where the page's Agent stack bricks are, settingsModel.useBrickNav),
// so the card needs nothing from the page.
import { Fragment } from 'react';

/** Fired on window to open the setup page's Set up the app sheet. */
export const SET_UP_APP_EVENT = 'hrui:set-up-app';

// The design's brick: the same art system as the bricks elsewhere (bricks.tsx partIcon, tower.ts),
// its classes and states, but four studs on a square brick at 96 x 71, which partIcon (one large stud)
// does not draw. Each stud: its centre, its side's left and top, and its shine.
const STUDS: [number, number, number, number, number, number][] = [
  [0, 0.1, -6.4, -4.1, -2.5, -4.8], [22.5, 13.1, 16.1, 8.9, 20.1, 8.2],
  [-22.5, 13.1, -28.9, 8.9, -25, 8.2], [0, 26.1, -6.4, 21.9, -2.5, 21.2],
];

function Brick({ state }: { state: 'next' | 'built' }) {
  return (
    <svg className="iso nx-b" viewBox="0 0 96 71" width="96" height="71" aria-hidden="true" focusable="false">
      <g transform="translate(48,15.9)">
        <g className={`bk ${state}`}>
          <polygon className="t" points="0,-12.9 45,13.1 0,39.1 -45,13.1" />
          <polygon className="l" points="-45,26 0,52 0,39.1 -45,13.1" />
          <polygon className="r" points="45,26 0,52 0,39.1 45,13.1" />
          <polyline className="hl" points="-44.4,13.5 0,39.1 44.4,13.5" />
          {STUDS.map(([cx, cy, x, top, hx, hy]) => (
            <Fragment key={`${cx},${cy}`}>
              <ellipse className="sd" cx={cx} cy={cy} rx="6.4" ry="3.8" />
              <rect className="sd" x={x} y={top} width="12.8" height="4.2" />
              <ellipse className="su" cx={cx} cy={top} rx="6.4" ry="3.8" />
              <ellipse className="sh" cx={hx} cy={hy} rx="2.1" ry="1" />
            </Fragment>
          ))}
        </g>
      </g>
    </svg>
  );
}

export function NextBar({ id, name }: { id: string; name: string }) {
  // The flow holds the button, so it is a labelled group rather than a picture (a picture's contents
  // are hidden from a screen reader, the button with them): the sentence says what the drawing shows,
  // the drawing itself is hidden, and the button is read after it.
  return (
    <div className="bs-next nx2">
      <span className="bs-nk">Next</span>
      <div className="nx-flow" role="group"
        aria-label={`Your app, built by your coding agent, sends each task to ${name}. It runs in HarnessRouter and the result comes back.`}>
        <div className="nx-end nx-app" aria-hidden="true">
          <Brick state="next" />
          <b>Your app</b>
          <span>Built by your coding agent</span>
        </div>
        <div className="nx-mid">
          <div className="nx-wire" aria-hidden="true"><i className="go"><em>task</em></i><i className="back"><em>result</em></i></div>
          <button type="button" className="btn small primary"
            onClick={() => window.dispatchEvent(new CustomEvent(SET_UP_APP_EVENT, { detail: { id } }))}>Set up the app</button>
        </div>
        <div className="nx-end nx-setup" aria-hidden="true">
          <Brick state="built" />
          <b title={name}>{name}</b>
          <span>Runs every task in HarnessRouter</span>
        </div>
      </div>
    </div>
  );
}
