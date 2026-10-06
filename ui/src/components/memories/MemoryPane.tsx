'use client';
// Memories: the selected memory, on the right of the tree. Its name and the description agents
// read, a search box, and under them either its records as a list, the same memory as a graph,
// or what a search found. A search covers this memory and everything below it, so each result
// says which memory it is in and links there; when the engine could not do all that was asked,
// or found nothing that answers, the page says so. Which controls show follows the reader's
// privileges on this memory and what its engine says it can do.
import { useEffect, useState } from 'react';
import { labelOf, listRecords, recall, MemoryApiError, RECORD_TYPES, type Memory, type MemoryRecord, type Provider, type Recall } from '@/lib/memories';
import { SkelLine } from '@/components/Skel';
import { Caret, engineName, errText, excerptOf, ICON, Ico, TYPE_INFO, typeColor, typeOne, typePlural, useWidth, whenOf, type WhoFn } from './kit';
import { MemoryGraph } from './MemoryGraph';

const PAGE = 50;
export interface Loc { m?: string | null; r?: string | null; view?: 'graph' | null; q?: string | null }

function Unavailable({ error, what }: { error: Error; what: string }) {
  const down = error instanceof MemoryApiError && error.code === 'memory_unavailable';
  return (
    <div className="mem-state">
      <strong>{down ? 'This memory is not answering right now' : what}</strong>
      <span>{error.message}</span>
    </div>
  );
}

export function MemoryPane({ memory, ancestors, provider, view, q, rev, who, onGo, onShare, onAdd, onDescription, onOpenTree, onChanged }: {
  memory: Memory; ancestors: Memory[]; provider: Provider | undefined; view: 'records' | 'graph'; q: string; rev: number; who: WhoFn;
  onGo: (to: Loc) => void; onShare: () => void; onAdd: () => void; onDescription: (text: string) => Promise<void>; onOpenTree: () => void;
  onChanged: (memoryId: string) => void;
}) {
  const [type, setType] = useState('all');
  const [typeMenu, setTypeMenu] = useState(false);
  const [mode, setMode] = useState<'meaning' | 'words'>('meaning');
  const [query, setQuery] = useState(q);
  const [descEditing, setDescEditing] = useState(false);
  const [descDraft, setDescDraft] = useState('');
  const [descErr, setDescErr] = useState('');
  const [list, setList] = useState<{ data: MemoryRecord[]; next: string | null } | null>(null);
  const [listErr, setListErr] = useState<Error | null>(null);
  const [moreBusy, setMoreBusy] = useState(false);
  const [found, setFound] = useState<Recall | null>(null);
  const [findErr, setFindErr] = useState<Error | null>(null);
  const [box, width] = useWidth<HTMLDivElement>();

  const p = memory.privileges || [];
  const canWrite = p.includes('write'), canManage = p.includes('delete');
  const canWords = Boolean(provider?.recall?.signals?.includes('text'));
  const searched = Boolean(q);
  const useWords = mode === 'words' && canWords;

  useEffect(() => { setQuery(q); }, [q, memory.id]);
  useEffect(() => { setDescEditing(false); setDescErr(''); setTypeMenu(false); }, [memory.id]);

  useEffect(() => {
    if (searched || view !== 'records') return;
    let alive = true;
    setList(null); setListErr(null);
    listRecords(memory.id, { limit: PAGE, type: type === 'all' ? undefined : type })
      .then((d) => { if (alive) setList({ data: d.data, next: d.next }); }).catch((e) => { if (alive) setListErr(e); });
    return () => { alive = false; };
  }, [memory.id, type, rev, searched, view]);

  useEffect(() => {
    if (!searched) { setFound(null); setFindErr(null); return; }
    let alive = true;
    setFound(null); setFindErr(null);
    recall(memory.id, { ...(useWords ? { text: q } : { query: q }), types: type === 'all' ? undefined : [type], limit: 30 })
      .then((d) => { if (alive) setFound(d); }).catch((e) => { if (alive) setFindErr(e); });
    return () => { alive = false; };
  }, [memory.id, q, useWords, type, searched, rev]);

  const showMore = async () => {
    if (!list?.next || moreBusy) return;
    setMoreBusy(true);
    try {
      const d = await listRecords(memory.id, { limit: PAGE, cursor: list.next, type: type === 'all' ? undefined : type });
      setList({ data: [...list.data, ...d.data], next: d.next });
    } catch (e) { setListErr(e as Error); }
    finally { setMoreBusy(false); }
  };
  const commitDesc = async () => {
    const text = descDraft.trim();
    if (text === (memory.description || '')) { setDescEditing(false); return; }
    try { await onDescription(text); setDescEditing(false); setDescErr(''); }
    catch (e) { setDescErr(errText(e)); }
  };

  const top = found?.results.reduce((mx, r) => Math.max(mx, r.score ?? 0), 0) || 0;
  const dots = (score: number | null) => {
    if (score === null || !top) return '—';
    const n = score / top >= 0.67 ? 3 : score / top >= 0.34 ? 2 : 1;
    return '●●●'.slice(0, n) + '○○○'.slice(0, 3 - n);
  };
  const WHY: Record<string, string> = { query: 'by meaning', text: 'by its exact words', filters: 'by a filter' };
  const inside = (memory.children?.count ?? 0) > 0;
  const searchLabel = `Search ${memory.name}${inside ? ' and everything inside' : ''}`;
  const count = memory.records?.count;

  return (
    <div className={'mem-pane' + (width >= 760 ? ' is-wide' : '')} ref={box}>
      <div className="mem-pane-head">
        <div className="mem-crumbs">
          <button type="button" className="mem-treebtn" aria-label="Show memories" onClick={onOpenTree}>
            <Ico d={ICON.folder} size={13} style={{ color: 'var(--v2-warn-ink)' }} /><span>Tree</span>
          </button>
          {ancestors.map((a) => <span key={a.id}><button type="button" onClick={() => onGo({ m: a.id, r: null, q: null })}>{a.name}</button><i>/</i></span>)}
        </div>
        <div className="mem-pane-title">
          <div className="mem-pane-id">
            <h2>{memory.name}</h2>
            {descEditing ? (
              <>
                <textarea autoFocus rows={2} className="mem-desc-edit" value={descDraft} aria-label="Description" placeholder="What is kept here, in one or two sentences"
                  onChange={(e) => setDescDraft(e.target.value)} onBlur={() => void commitDesc()}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.currentTarget.blur(); }
                    if (e.key === 'Escape') { setDescDraft(memory.description || ''); setDescEditing(false); setDescErr(''); }
                  }} />
                {descErr && <div className="mem-field-err" role="alert">{descErr}</div>}
              </>
            ) : memory.description ? (
              canWrite
                ? <button type="button" className="mem-desc is-edit" title="Click to edit" onClick={() => { setDescDraft(memory.description); setDescEditing(true); }}>{memory.description}</button>
                : <p className="mem-desc">{memory.description}</p>
            ) : canWrite ? (
              <button type="button" className="mem-desc-add" onClick={() => { setDescDraft(''); setDescEditing(true); }}>Add a description. Agents read it to decide whether to look inside.</button>
            ) : null}
          </div>
          {canManage && (
            <button type="button" className="mem-btn mem-sharebtn" aria-label="Share" onClick={onShare}><Ico d={ICON.share} size={13} sw={1.5} /><span className="mem-wide">Share</span></button>
          )}
        </div>

        <div className="mem-searchrow">
          <form className="mem-search" role="search" onSubmit={(e) => { e.preventDefault(); onGo({ q: query.trim() || null, r: null }); }}>
            <Ico d={ICON.search} sw={1.5} style={{ color: 'var(--v2-cap)' }} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} aria-label={searchLabel} placeholder={searchLabel} enterKeyHint="search" />
            {searched && <button type="button" className="mem-search-x" aria-label="Clear search" onClick={() => { setQuery(''); onGo({ q: null }); }}>✕</button>}
          </form>
          <div className="mem-modes" role="radiogroup" aria-label="How to search">
            <button type="button" role="radio" aria-checked={!useWords} className={!useWords ? 'is-on' : ''} onClick={() => setMode('meaning')}>Meaning</button>
            <button type="button" role="radio" aria-checked={useWords} className={useWords ? 'is-on' : ''} disabled={!canWords}
              title={canWords ? 'Find records that contain these words' : `${engineName(memory.provider)} has no exact word search`} onClick={() => setMode('words')}>Exact words</button>
          </div>
        </div>
        {!canWords && provider && <div className="mem-modes-why">{`${engineName(memory.provider)} has no exact word search, so every search here is by meaning.`}</div>}

        <div className="mem-toolbar">
          {!searched ? (
            <div className="mem-views" role="tablist">
              <button type="button" role="tab" aria-selected={view === 'records'} className={view === 'records' ? 'is-on' : ''} onClick={() => onGo({ view: null })}>
                Records {typeof count === 'number' && <span>{count}</span>}
              </button>
              <button type="button" role="tab" aria-selected={view === 'graph'} className={view === 'graph' ? 'is-on' : ''} onClick={() => onGo({ view: 'graph' })}>Graph</button>
            </div>
          ) : (
            <span className="mem-results-title mem-ell">
              {found ? `${found.results.length} ${found.results.length === 1 ? 'result' : 'results'} in ${memory.name}` : `Searching ${memory.name}`}
            </span>
          )}
          <div className="mem-pop-wrap">
            <button type="button" className={'mem-typefilter' + (type !== 'all' ? ' is-set' : '')} aria-haspopup="listbox" aria-expanded={typeMenu} onClick={() => setTypeMenu(!typeMenu)}>
              <span>{type === 'all' ? 'All types' : typePlural(type)}</span><Caret className="mem-caret-s" />
            </button>
            {typeMenu && (
              <>
                <div className="mem-pop-scrim" onClick={() => setTypeMenu(false)} />
                <div className="mem-menu mem-typemenu" role="listbox" aria-label="Record type">
                  {['all', ...RECORD_TYPES].map((t) => (
                    <button key={t} type="button" role="option" aria-selected={t === type} className={t === type ? 'is-on' : ''} onClick={() => { setType(t); setTypeMenu(false); }}>
                      <i style={{ background: t === 'all' ? 'var(--v2-dis)' : typeColor(t) }} />
                      <span><b>{t === 'all' ? 'All types' : typePlural(t)}</b><em>{t === 'all' ? 'Everything kept here' : TYPE_INFO[t]?.hint}</em></span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          {canWrite && !searched && (
            <button type="button" className="mem-btn is-sm mem-addbtn" aria-label="Add record" onClick={onAdd}><span className="mem-plus">+</span><span className="mem-wide">Add record</span></button>
          )}
        </div>
      </div>

      <div className="mem-pane-body">
        {searched ? (
          <div className="mem-list">
            {findErr ? <Unavailable error={findErr} what="The search could not be run" /> : !found ? (
              <div aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="mem-row is-skel"><SkelLine w={64} h={18} /><SkelLine w={`${70 - i * 12}%`} h={12} /></div>)}</div>
            ) : (
              <>
                {found.degraded.length > 0 && <div className="mem-banner">{`${engineName(memory.provider)} could not do everything this search asked for: ${found.degraded.join(', ')}.`}</div>}
                {found.abstain && <div className="mem-none">{`Nothing in ${memory.name} answers this.`}</div>}
                {found.results.map(({ record: r, memory: at, score, why }) => (
                  <div key={at.id + r.id} className="mem-row is-result">
                    <span className="mem-type" style={{ background: typeColor(r.type) + '14', color: typeColor(r.type) }}>{typeOne(r.type)}</span>
                    <span className="mem-row-main">
                      <button type="button" className="mem-row-hit" onClick={() => onGo({ m: at.id, r: r.id, q: null, view: null })}>{labelOf(r) || 'Untitled'}</button>
                      <span className="mem-row-meta">{`${typeOne(r.type)} · ${who(r.written_by)}`}</span>
                      <button type="button" className="mem-row-in" onClick={() => onGo({ m: at.id, r: null, q: null, view: null })}>{`in ${at.name} →`}</button>
                    </span>
                    <span className="mem-dots" title={why.length ? `Found ${why.map((w) => WHY[w] || w).join(' and ')}` : undefined}
                      aria-label={score === null ? 'No score' : `Strength ${dots(score).replace(/○/g, '').length} of 3`}>{dots(score)}</span>
                  </div>
                ))}
                {found.results.length === 0 && !found.abstain && <div className="mem-none">{`Nothing in ${memory.name} matches this.`}</div>}
                {found.children.length > 0 && (
                  <div className="mem-next">
                    <span>Places to look next</span>
                    <div>
                      {found.children.map((c) => (
                        <button key={c.id} type="button" title={c.description || undefined} onClick={() => onGo({ m: c.id, r: null })}>
                          <Ico d={ICON.folder} size={12} sw={1.3} style={{ color: 'var(--v2-warn-ink)' }} />{c.name}
                          {typeof c.records?.count === 'number' && <i>{c.records.count}</i>}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        ) : view === 'graph' ? (
          <MemoryGraph memory={memory} type={type} canEdit={canWrite} rev={rev} recId="" onOpen={(m, r) => onGo({ m, r })} onAdded={() => onChanged(memory.id)} />
        ) : (
          <div className="mem-list">
            {listErr ? <Unavailable error={listErr} what="The records could not be listed" /> : !list ? (
              <div aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="mem-row is-skel"><SkelLine w={64} h={18} /><SkelLine w={`${72 - i * 11}%`} h={12} /></div>)}</div>
            ) : (
              <>
                {list.data.map((r) => {
                  const ex = excerptOf(r);
                  return (
                    <div key={r.id} className="mem-row">
                      <span className="mem-type" style={{ background: typeColor(r.type) + '14', color: typeColor(r.type) }}>{typeOne(r.type)}</span>
                      <span className="mem-row-main">
                        <button type="button" className="mem-row-hit" onClick={() => onGo({ m: r.memory_id, r: r.id })}>{labelOf(r) || 'Untitled'}</button>
                        {ex && <span className="mem-row-ex">{ex}</span>}
                        <span className="mem-row-meta">{`${typeOne(r.type)} · ${who(r.written_by)}`}</span>
                      </span>
                      <span className="mem-row-by mem-ell">{who(r.written_by)}</span>
                      <span className="mem-row-when">{whenOf(r.time?.written_at)}</span>
                    </div>
                  );
                })}
                {list.data.length === 0 && <div className="mem-none">{type === 'all' ? 'Nothing kept here yet.' : `No ${type} records here.`}</div>}
                {list.next && <button type="button" className="mem-btn is-sm mem-morerows" disabled={moreBusy} onClick={() => void showMore()}>{moreBusy ? 'Loading…' : 'Show more'}</button>}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
