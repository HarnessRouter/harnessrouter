'use client';
// The API key step, the same in every sheet that hands a prompt to a coding agent: Connect your app,
// Make <kit> yours, Start in your codebase, Migrate an existing agent. Richard, 10-18: "所有的 API Key
// 每次 Popup 都让它创建一个新的 Key"; 10-19: in the leaner form of his "Set up a starter app" design
// (its step 2, "Create an API key").
//
// The name field is there at once, filled with the next name no live key of the workspace has (the
// sheet's own name as a slug, then -2, -3), and Create beside it. Create makes a new key in the
// current workspace (the API Keys page's own call, start/keys) and shows it once in the warning box,
// with Copy key. Once it is copied the step folds to the key's name and last four, and the secret
// leaves the page; New key opens the name row again, with the next free name. Each time a sheet opens
// the step starts at the name row: a key made before is never shown as done, and no sheet offers to
// reuse one. A name that cannot be used is said under the field. When the workspace's keys could not be
// read, the step says so with Try again in place of the name row: a free name is never guessed.
import { useEffect, useId, useRef, useState, type RefObject } from 'react';
import { useCopyConfirm } from './copy';
import { keyMask, type KeysState, type WsKey } from './keys';
import { HxStep, useFocusOnFold } from './Steps';

/** The step's title, in every sheet. */
export const KEY_TITLE = 'Create an API key';
const SHOWN = 'Shown once. Paste it only into the secure prompt it opens.';
/** The name a guide's key starts from: it has no setup yet, and the key goes into the app's backend. */
export const KEY_BASE = 'app-backend';
/** How long "Copied" shows before the step folds. */
const FOLD_MS = 600;

/** A key made in the step: what its summary shows once the secret has left the page. */
export interface MadeKey { id: string; name: string; tail: string }

/** A sheet's name as a key name: "Photo edit" is photo-edit. Letters of any script stay; spaces and
 *  punctuation become one hyphen. */
export function keySlug(s: string): string {
  return s.trim().toLowerCase()
    .replace(/[\s!-\/:-@[-`{-~\u00a0-\u00bf\u2000-\u206f\u3000-\u303f\uff01-\uff0f\uff1a-\uff20]+/g, '-')
    .replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/, '');
}

/** The first of base, base-2, base-3 … that no live key of the workspace is named (names compare
 *  as the keys page compares them, ignoring case). */
export function freeName(base: string, keys: WsKey[] | null): string {
  const taken = new Set((keys || []).filter((k) => !k.revoked).map((k) => (k.name || '').trim().toLowerCase()));
  const b = base.toLowerCase();
  if (!taken.has(b)) return base;
  let i = 2;
  while (taken.has(`${b}-${i}`)) i++;
  return `${base}-${i}`;
}

export function KeyStep({ n, k, surface, base, state, onKey, entry }: {
  n: number;
  k: KeysState;
  /** where the key was made, for the api_key_created event */
  surface: string;
  /** the name the field starts from (keySlug of the setup's name), before -2, -3 */
  base: string;
  /** the brick until a key is made: 'next' while it is the step at hand */
  state: 'empty' | 'next';
  /** the key was copied and the step folded (the key), or New key opened it again (null) */
  onKey?: (made: MadeKey | null) => void;
  /** set to the name field, for a sheet that focuses it on open */
  entry?: RefObject<HTMLElement | null>;
}) {
  const id = useId();
  // what the person typed; null while the field shows the next free name
  const [typed, setTyped] = useState<string | null>(null);
  const [why, setWhy] = useState('');
  // the key just made, on screen until it is copied
  const [shown, setShown] = useState<{ id: string; name: string; secret: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [made, setMade] = useState<MadeKey | null>(null);
  const { copy } = useCopyConfirm();
  const input = useRef<HTMLInputElement | null>(null);
  const secret = useRef<HTMLElement | null>(null);
  const again = useRef<HTMLButtonElement | null>(null);
  const fold = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(fold.current), []);
  useFocusOnFold(!!made, again);
  const name = typed ?? freeName(base, k.keys);

  const create = async () => {
    if (k.busy) return;
    const problem = k.nameProblem(name);
    if (problem) { setWhy(problem); input.current?.focus(); return; }
    // the gateway's refusal (who can make this key, by role) is said under the name, as a name problem is
    const r = await k.create(name, surface, (no) => { setWhy(no); input.current?.focus(); });
    if (!r) return;
    setShown({ id: r.id, name: name.trim(), secret: r.secret });
    setCopied(false); setWhy('');
  };
  const copyKey = () => {
    if (!shown) return;
    copy(shown.secret, secret, 'Key copied', () => {
      setCopied(true);
      clearTimeout(fold.current);
      fold.current = setTimeout(() => {
        const m = { id: shown.id, name: shown.name, tail: shown.secret.slice(-4) };
        setShown(null); setMade(m); setTyped(null);
        onKey?.(m);
      }, FOLD_MS);
    });
  };
  const newKey = () => {
    setMade(null); setTyped(null); setWhy('');
    onKey?.(null);
    setTimeout(() => { input.current?.focus(); input.current?.select(); }, 0);
  };

  const sum = made ? (
    <>
      <span className="kb-n">{made.name}</span> · <span className="mono">{keyMask(made.tail)}</span>
      <button ref={again} type="button" className="link-q inl" onClick={newKey}>New key</button>
    </>
  ) : null;
  // the list could not be read: which names are taken is not known, so no name is offered and none is
  // checked against a list that may be missing keys; the line says so, with Try again
  const unread = k.error ? (
    <p className="kb-why" role="alert">Your keys could not be read just now.{' '}
      <button type="button" className="link-q inl" onClick={k.retry}>Try again</button></p>
  ) : null;
  const body = shown ? (
    <div className="reveal kb-reveal">
      <b>{SHOWN}</b>
      {/* ph-no-capture: the secret stays out of session replay */}
      <code id={`${id}-key`} className="ph-no-capture" ref={secret}>{shown.secret}</code>
      <button type="button" className={`btn small ${copied ? 'kb-done' : 'primary'}`} onClick={copyKey}>{copied ? 'Copied' : 'Copy key'}</button>
    </div>
  ) : unread || (
    <>
      <div className="keyrow">
        <label className="sr" htmlFor={`${id}-name`}>Key name</label>
        <input id={`${id}-name`} ref={(el) => { input.current = el; if (entry) entry.current = el; }}
          className={`keyname${why ? ' bad' : ''}`} placeholder="Key name, e.g. production" autoComplete="off" spellCheck={false}
          aria-invalid={why ? true : undefined} aria-describedby={why ? `${id}-why` : undefined} value={name}
          onChange={(e) => { setTyped(e.target.value); setWhy(''); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void create(); } }} />
        <button type="button" className="btn small primary" disabled={k.busy} onClick={() => void create()}>{k.busy ? 'Creating' : 'Create'}</button>
      </div>
      {why ? <p className="kb-why" id={`${id}-why`} role="alert">{why}</p> : null}
    </>
  );
  return <HxStep n={n} state={made ? 'built' : state} title={KEY_TITLE} sum={sum}>{body}</HxStep>;
}
