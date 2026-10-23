'use client';
// The sign-in screens of the redesign (docs/uxuidesign/console-79: renderAuth, authView): one card on
// the grid, the lockup on the left of its head and the three progress bricks on the right. These pages
// (sign-in, and an address with no page for someone signed out) sit outside the console's frame, so
// this is their own root for the design's stylesheet; the pages load it on demand.
import '../hrui.css';
import '../hrui-console.css';
import './auth.css';
import { useMemo, type ChangeEvent, type ReactNode, type Ref } from 'react';
import { HR_LOGO, auMark } from './art';

/** The page: the grid behind, one card in the middle. `n` is how many of the three bricks are built
 *  (3 on every screen here). */
export function AuthFrame({ n, children }: { n: number; children: ReactNode }) {
  const svg = useMemo(() => auMark(n), [n]);
  return (
    <div id="hrui">
      <div className="auth-layer">
        <div className="au-bg" aria-hidden="true" />
        <main className="au-stage">
          <div className="au-card ticks">
            <i className="tk tl" /><i className="tk tr" /><i className="tk bl" /><i className="tk br" />
            <div className="au-head">
              <a className="au-brand" href="https://harnessrouter.ai" aria-label="HarnessRouter" dangerouslySetInnerHTML={{ __html: HR_LOGO }} />
              <span className="au-markw" aria-hidden="true" dangerouslySetInnerHTML={{ __html: svg }} />
            </div>
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

/** One field: label, input, then its hint, or its error in the hint's place. */
export function Field({ id, label, type = 'text', ac, value, onChange, err, hint, side, ph, autoFocus, inputRef, name }: {
  id: string; label: string; type?: string; ac: string; value: string; onChange: (v: string) => void;
  err?: string; hint?: string; side?: ReactNode; ph?: string; autoFocus?: boolean; inputRef?: Ref<HTMLInputElement>; name?: string;
}) {
  const msg = err || hint || '';
  const hid = `${id}Msg`;
  return (
    <div className="au-f">
      {side ? <div className="au-frow"><label htmlFor={id}>{label}</label>{side}</div> : <label htmlFor={id}>{label}</label>}
      <input ref={inputRef} id={id} name={name} className="set-in" type={type} autoComplete={ac} placeholder={ph} value={value} autoFocus={autoFocus}
        spellCheck={type === 'email' ? false : undefined}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
        aria-invalid={err ? true : undefined} aria-describedby={msg ? hid : undefined} />
      {msg ? <small className={`au-hint${err ? ' bad' : ''}`} id={hid} role={err ? 'alert' : undefined}>{msg}</small> : null}
    </div>
  );
}

/** A loose error, one that belongs to no field. */
export const LooseErr = ({ err }: { err: string }) => (err ? <p className="au-err" role="alert">{err}</p> : null);
