'use client';
// Panes side by side, the rule between two of them draggable. Dragging moves only those two; one pane
// takes whatever is left. What a person chose is kept apart from what fits: a narrow window squeezes the
// panes and a wide one gives them back. Where they can't all fit they become tabs, one at a time, full
// width, every pane staying mounted so an editor or a canvas keeps its state.
import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';
import { tabKeys } from '../tabKeys';
import './tree/columns.css';

export interface ColumnPane { id: string; label: string; min: number; initial: number; grow?: boolean; node: ReactNode }
export interface ResizableColumnsProps {
  storageKey: string;
  panes: ColumnPane[];
  /** Which pane the tabs show, for a page that moves between them; left out, the tabs keep their own. */
  tab?: string;
  onTab?: (id: string) => void;
}

/** Below this the panes are tabs, however small their minimums. */
export const NARROW = 900;
const SEP = 1;
const KEY_STEP = 16;

const growing = (panes: ColumnPane[]) => panes.find((p) => p.grow) || panes[panes.length - 1];
/** Do these panes fit side by side at their minimums? */
export function fits(panes: ColumnPane[], total: number): boolean {
  const rules = SEP * (panes.length - 1);
  return panes.reduce((n, p) => n + p.min, 0) + rules <= total;
}

/** Each pane's width at this container's width: what was chosen, then the growing pane gives way, then
 *  the others from the last one back, each down to its minimum. */
export function resolveWidths(panes: ColumnPane[], chosen: Record<string, number>, total: number): Record<string, number> {
  const g = growing(panes);
  const out: Record<string, number> = {};
  const rest = panes.filter((p) => p !== g);
  rest.forEach((p) => { out[p.id] = Math.max(p.min, chosen[p.id] ?? p.initial); });
  const left = () => total - SEP * (panes.length - 1) - rest.reduce((n, p) => n + out[p.id], 0);
  let short = g.min - left();
  for (let i = rest.length - 1; i >= 0 && short > 0; i--) {
    const take = Math.min(out[rest[i].id] - rest[i].min, short);
    out[rest[i].id] -= take;
    short -= take;
  }
  out[g.id] = Math.max(g.min, left());
  return out;
}

const readChosen = (key: string): Record<string, number> => {
  try {
    const v = JSON.parse(window.localStorage.getItem(key) || '{}') as Record<string, unknown>;
    return Object.fromEntries(Object.entries(v).filter(([, n]) => typeof n === 'number' && Number.isFinite(n))) as Record<string, number>;
  } catch { return {}; }
};

export function ResizableColumns({ storageKey, panes, tab, onTab }: ResizableColumnsProps) {
  const el = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  const [chosen, setChosen] = useState<Record<string, number>>(() => (typeof window === 'undefined' ? {} : readChosen(storageKey)));
  const chosenRef = useRef(chosen);
  chosenRef.current = chosen;
  const [dragging, setDragging] = useState(-1);
  const drag = useRef<{ i: number; x: number; a: number; b: number } | null>(null);
  const g = growing(panes);
  const [ownTab, setOwnTab] = useState(g.id);
  const shown = tab ?? ownTab;
  const pick = useCallback((id: string) => { setOwnTab(id); onTab?.(id); }, [onTab]);

  useLayoutEffect(() => {
    const node = el.current;
    if (!node) return undefined;
    const measure = () => setWidth(node.getBoundingClientRect().width);
    measure();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    return () => ro.disconnect();
  }, []);

  const narrow = width > 0 && (width < NARROW || !fits(panes, width));
  const widths = useMemo(() => (width > 0 && !narrow ? resolveWidths(panes, chosen, width) : null), [panes, chosen, width, narrow]);
  const widthOf = (p: ColumnPane) => widths?.[p.id] ?? p.initial;

  const save = useCallback(() => {
    try { window.localStorage.setItem(storageKey, JSON.stringify(chosenRef.current)); } catch { /* private window */ }
  }, [storageKey]);
  /** Move a rule from where the two panes stood: only they change, and neither goes under its minimum. */
  const moveRule = useCallback((i: number, a0: number, b0: number, dx: number) => {
    const a = panes[i], b = panes[i + 1];
    const pair = a0 + b0;
    const na = Math.min(Math.max(a0 + dx, a.min), pair - b.min);
    const next = { ...chosenRef.current };
    if (a !== g) next[a.id] = na;
    if (b !== g) next[b.id] = pair - na;
    chosenRef.current = next;
    setChosen(next);
  }, [panes, g]);

  const onDown = (e: PointerEvent<HTMLDivElement>, i: number) => {
    if (e.button !== 0) return;
    e.preventDefault();            // no text selection starts from here
    drag.current = { i, x: e.clientX, a: widthOf(panes[i]), b: widthOf(panes[i + 1]) };
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDragging(i);
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (d) moveRule(d.i, d.a, d.b, e.clientX - d.x);
  };
  const onEnd = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture?.(e.pointerId)) e.currentTarget.releasePointerCapture?.(e.pointerId);
    setDragging(-1);
    save();
  };
  const reset = (i: number) => {
    const next = { ...chosenRef.current };
    delete next[panes[i].id];
    delete next[panes[i + 1].id];
    chosenRef.current = next;
    setChosen(next);
    save();
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>, i: number) => {
    const a = widthOf(panes[i]), b = widthOf(panes[i + 1]);
    const toStart = panes[i].min - a;
    const toEnd = b - panes[i + 1].min;
    const dx = e.key === 'ArrowLeft' ? -KEY_STEP : e.key === 'ArrowRight' ? KEY_STEP : e.key === 'Home' ? toStart : e.key === 'End' ? toEnd : 0;
    if (!dx) return;
    e.preventDefault();
    moveRule(i, a, b, dx);
    save();
  };
  // the same key can be read again once the panes differ between pages
  useEffect(() => { const c = readChosen(storageKey); chosenRef.current = c; setChosen(c); }, [storageKey]);

  const ids = panes.map((p) => p.id);
  const current = ids.includes(shown) ? shown : g.id;
  return (
    <div ref={el} className={`rc${narrow ? ' narrow' : ''}${dragging >= 0 ? ' dragging' : ''}`}>
      {narrow ? (
        <div className="tabs inline rc-tabs" role="tablist" onKeyDown={(e) => tabKeys(e, ids, current, pick)}>
          {panes.map((p) => (
            <button key={p.id} type="button" role="tab" id={`rc-t-${p.id}`} aria-selected={current === p.id} aria-controls={`rc-p-${p.id}`} tabIndex={current === p.id ? 0 : -1}
              className={current === p.id ? 'on' : ''} onClick={() => pick(p.id)}>{p.label}</button>
          ))}
        </div>
      ) : null}
      <div className="rc-body">
        {panes.map((p, i) => (
          <Fragment key={p.id}>
            <section id={`rc-p-${p.id}`} className="rc-col" aria-label={p.label} role={narrow ? 'tabpanel' : undefined} aria-labelledby={narrow ? `rc-t-${p.id}` : undefined} hidden={narrow && current !== p.id}
              style={narrow ? undefined : p === g ? { flex: '1 1 0' } : { flex: `0 0 ${widthOf(p)}px` }}>
              {p.node}
            </section>
            {!narrow && i < panes.length - 1 ? (
              <div className={`rc-sep${dragging === i ? ' on' : ''}`} role="separator" aria-orientation="vertical" aria-label={`Resize ${p.label} and ${panes[i + 1].label}`} tabIndex={0}
                aria-valuenow={Math.round(widthOf(p))} aria-valuemin={p.min} aria-valuemax={Math.round(widthOf(p) + widthOf(panes[i + 1]) - panes[i + 1].min)}
                onPointerDown={(e) => onDown(e, i)} onPointerMove={onMove} onPointerUp={onEnd} onPointerCancel={onEnd} onLostPointerCapture={onEnd}
                onDoubleClick={() => reset(i)} onKeyDown={(e) => onKey(e, i)} />
            ) : null}
          </Fragment>
        ))}
      </div>
    </div>
  );
}
