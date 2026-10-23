'use client';
// The second step of making a skill or an MCP server in Add-ons (Richard, 2026-10-18): make it
// first, then choose the setups it goes in. The setups are a list of checkboxes; Add writes each
// chosen setup as adding it to that one setup does, and says which did not take, keeping those
// chosen so Try again sends only them (the ones that took are marked Added). Nothing is lost:
// before anything is added, Back (or Escape) returns to the item as it was. An item lives only in
// the setups that use it, so at least one is needed.
import { useRef, useState } from 'react';
import { harnessLogoSrc } from '@/components/HarnessLogo';
import { Sheet, SheetTop } from '../Sheet';
import '../mcp/mcp.css';

/** A setup the item can go in. `off`: why it cannot (shown, and the row is not offered); `warn`:
 *  it can, with something to know first. Nothing else is said under a setup. */
export interface AddTarget { id: string; name: string; base: string; off?: string; warn?: string }
/** What Add did: the setups that have it now, and the ones that did not take, each with its reason. */
export interface AddResult { done: string[]; failed: { id: string; why: string }[] }

const CHECK = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} aria-hidden="true"><path d="M5 12l5 5L20 7" /></svg>;
const sayNames = (names: string[]) => (names.length <= 2 ? names.join(' and ') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`);

export function AddToSheet({ item, targets, initial, onAdd, onBack, onDone }: {
  /** the item's name, as it is saved */
  item: string;
  targets: AddTarget[];
  /** chosen to begin with (the only setup that can take it, when there is one) */
  initial: string[];
  onAdd: (ids: string[]) => Promise<AddResult>;
  /** before anything is added: back to the item, as it was */
  onBack: () => void;
  /** the setups that have it now; the flow is over */
  onDone: (added: string[]) => void;
}) {
  const [to, setTo] = useState<string[]>(initial);
  const [added, setAdded] = useState<string[]>([]);
  const [say, setSay] = useState('');
  const [busy, setBusy] = useState(false);
  const firstRef = useRef<HTMLButtonElement | null>(null);
  const nameOf = (id: string) => targets.find((t) => t.id === id)?.name || id;
  const left = to.filter((id) => !added.includes(id));
  const firstOpen = targets.find((t) => !t.off && !added.includes(t.id))?.id;

  async function add() {
    if (busy || !left.length) return;
    setBusy(true); setSay('');
    const r = await onAdd(left).catch(() => ({ done: [], failed: left.map((id) => ({ id, why: '' })) }) as AddResult);
    const now = [...added, ...r.done];
    setAdded(now);
    setBusy(false);
    if (!r.failed.length) { onDone(now); return; }
    const w = r.failed.length === 1 ? r.failed[0].why.trim() : '';
    const why = w ? ` ${w}${/[.!?]$/.test(w) ? '' : '.'}` : '';
    setSay(`Not added to ${sayNames(r.failed.map((f) => nameOf(f.id)))}.${why} Try again.`);
  }
  // Escape and the close button: back to the item while nothing is added; done once something is
  const close = () => (added.length ? onDone(added) : onBack());

  return (
    <Sheet onClose={close} labelledBy="ath" className="small-sheet mcp-x" busy={busy} initialFocus={firstRef}>
      <SheetTop id="ath" title={`Add ${item} to setups`} onClose={close} />
      <div className="set-f mcp-to">
        <span className="mcp-to-l" id="atL">Setups</span>
        {targets.length ? (
          <div className="pick-list at-list" role="group" aria-labelledby="atL">
            {targets.map((t) => {
              const done = added.includes(t.id), on = done || to.includes(t.id), logo = harnessLogoSrc(t.base);
              const note = done ? 'Added' : t.off || t.warn || '';
              return (
                <button key={t.id} type="button" role="checkbox" aria-checked={on} disabled={!!t.off || done || busy}
                  ref={t.id === firstOpen ? firstRef : undefined} className={`opt mcp-opt${on ? ' on' : ''}`}
                  onClick={() => { setTo((x) => (on ? x.filter((y) => y !== t.id) : [...x, t.id])); setSay(''); }}>
                  <span className="mcp-box" aria-hidden="true">{on ? CHECK : null}</span>
                  {/* eslint-disable-next-line @next/next/no-img-element -- a static brand mark */}
                  {logo ? <img className="h-logo" src={logo} alt="" /> : <span className="h-logo" />}
                  <span className="grow">{t.name}{note ? <small className={!done && (t.off || t.warn) ? 'mcp-warn' : undefined}>{note}</small> : null}</span>
                </button>
              );
            })}
          </div>
        ) : <p className="set-help">No setups yet. Make one in Harness Studio first.</p>}
      </div>
      <div className="sheet-actions mcp-act">
        {added.length
          ? <button type="button" className="btn" disabled={busy} onClick={() => onDone(added)}>Done</button>
          : <button type="button" className="btn" disabled={busy} onClick={onBack}>Back</button>}
        <span className={`set-help mcp-say${say ? ' bad' : ''}`} role="status">{say}</span>
        <button type="button" className="btn primary" disabled={busy || !left.length} onClick={() => void add()}>
          {added.length ? 'Try again' : left.length > 1 ? `Add to ${left.length} setups` : 'Add'}
        </button>
      </div>
    </Sheet>
  );
}
