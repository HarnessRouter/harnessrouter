'use client';
// Memories (docs: the design's memoriesView): one card per memory, each with the picture of its schema, the engine that
// keeps it, which setups use it and when it was last used. Search narrows by name, description, engine or setup, and
// the list is in the order it was last used (the memories spec, C3). Every figure is the service's; what a service before
// 0.40 doesn't say (who uses it, when) is not drawn. Connecting an engine, and finding the ones running beside this
// instance, are under More. With no engine connected the page says so in one sentence and leads to connecting one.
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { findEngines, getSchema, labelOf, listMemories, listRecords, type Memory, type Provider } from '@/lib/memories';
import { ago } from '../setups';
import { plain } from '../setup/settingsModel';
import { Skel, SkCards, SkHead } from '../Skel';
import { toast } from '../toast';
import { hasSchema, schemaLabels } from './caps';
import { CardArt, Ghost, MiniArt, saysNothing } from './CardArt';
import { listChildren } from './tree/api';
import { concepts } from './graph/builtin';
import { DOTS, engineOf, msOf, pool, PLUS, SEARCH, shownName, speaksUse, useDismiss, useProviders, X } from './parts';
import { schemaIn, type LSchema } from './schemaModel';
import { ChooseServiceSheet, NewMemorySheet, UseInSheet } from './sheets';
import { vendorName } from './vendors';
import './memories.css';

/** What a memory's picture draws (Richard 11-06): labels as Vivian's chips where a person set them; otherwise the
 *  provider's own concepts with any types a person set, as the Schema tab draws them. */
const pictureOf = (f: { schema?: LSchema | null } | undefined, p: Provider | null | undefined) => {
  const asLabels = schemaLabels(p) && !!f?.schema?.types.length;
  return { s: asLabels ? f?.schema : concepts(f?.schema, p), labels: asLabels };
};

// `recent`: what a memory with no schema to draw shows on its card, the first few records it keeps (or, where it keeps
// each person apart and holds nothing itself, the first few people), and `count` how many of them there are, where known
interface Facts { schema?: LSchema | null; recent?: string[] | null; count?: number | null }
const FIRST = 3;
/** The first few things a memory keeps, for its card: its own records, or the people below it where it has none. */
async function firstWords(m: Memory): Promise<{ lines: string[]; count: number | null } | null> {
  try {
    const d = await listRecords(m.id, { limit: FIRST });
    const lines = d.data.map(labelOf).filter(Boolean);
    if (lines.length || !m.children?.count) return { lines, count: d.next ? null : lines.length };
    const kids = await listChildren(m.id);
    return { lines: kids.slice(0, FIRST).map(shownName), count: kids.length };
  } catch { return null; }
}
type Open = { k: 'new'; picked?: string } | { k: 'choose'; then?: 'new' } | { k: 'use'; m: Memory } | null;
type Sort = 'recent' | 'name';
const enc = encodeURIComponent;
// Cards or a list, as on Studio, and remembered the same way (for this person, in this browser)
const VM_KEY = 'hr.memories.view';
type View = 'cards' | 'list';
const GRID_IC = <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true"><rect x="2" y="2" width="5" height="5" rx="1.2" /><rect x="9" y="2" width="5" height="5" rx="1.2" /><rect x="2" y="9" width="5" height="5" rx="1.2" /><rect x="9" y="9" width="5" height="5" rx="1.2" /></svg>;
const LIST_IC = <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" aria-hidden="true"><path d="M2.5 4h11M2.5 8h11M2.5 12h11" /></svg>;
/** Chips past this many are counted, not named. */
const CHIPS = 2;

/** Who uses a memory, as chips: the first few by name, the rest as a count. Null where the service doesn't say. */
function UsedBy({ m }: { m: Memory }) {
  if (!Array.isArray(m.used_by)) return null;
  const u = m.used_by;
  if (!u.length) return <span className="mm-ub none">Not used yet</span>;
  return (
    <span className="mm-ub" title={`Used by ${u.map((x) => x.name).join(', ')}`}>
      <span className="mm-ub-k">Used by</span>
      {u.slice(0, CHIPS).map((x) => <span key={x.harness_id} className="mm-uc">{x.name}</span>)}
      {u.length > CHIPS ? <span className="mm-uc more">{`+${u.length - CHIPS}`}</span> : null}
    </span>
  );
}
/** The engine, and when it was last used where the service says. */
const engineLine = (m: Memory) => {
  const last = msOf(m.last_used_at);
  return [vendorName(engineOf(m)), last ? `Used ${ago(last)}` : ''].filter(Boolean).join(' · ');
};

export function MemoriesPage() {
  const router = useRouter();
  const { providers, failed: providersFailed, reload: reloadProviders } = useProviders();
  const [list, setList] = useState<Memory[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [facts, setFacts] = useState<Record<string, Facts>>({});
  const [open, setOpen] = useState<Open>(null);
  const [vm, setVm] = useState<View>('cards');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('recent');
  const [more, setMore] = useState(false);
  const [finding, setFinding] = useState(false);
  const moreWrap = useRef<HTMLSpanElement | null>(null);
  const closeMore = useCallback(() => setMore(false), []);
  useDismiss(more, moreWrap, closeMore);
  useEffect(() => { try { if (localStorage.getItem(VM_KEY) === 'list') setVm('list'); } catch { /* none */ } }, []);
  const pick = (v: View) => { setVm(v); try { localStorage.setItem(VM_KEY, v); } catch { /* none */ } };

  const read = useCallback(() => {
    setFailed(false);
    // no counts: the page shows none, and counting asked every memory's service in turn (13 s for sixty, 2026-11-06)
    listMemories({ counts: false, sort: 'recent' }).then(setList).catch(() => setFailed(true));
  }, []);
  useEffect(() => { read(); }, [read]);
  // a setup's Settings sends a person here to make a memory
  useEffect(() => { if (new URLSearchParams(window.location.search).get('new') === '1') setOpen({ k: 'new' }); }, []);

  // A memory's provider as the memory's own workspace reaches it: what a provider makes itself can differ by connection
  // (Mem0's own service makes facts; a Mem0 server, facts and the names in them), and the list says which.
  const providerOf = useCallback((m: Memory) => {
    const p = (providers || []).find((x) => x.id === m.provider) || null;
    return p && m.builtin !== undefined ? { ...p, schema: { ...p.schema, builtin: m.builtin || undefined } } : p;
  }, [providers]);
  useEffect(() => {
    if (!list || !providers) return;
    let live = true;
    void pool(list, 4, async (m) => {
      const withSchema = hasSchema(providerOf(m));
      // the picture's own reads only: a schema where one is read, and the first records where a service has no schema
      // and its own concepts would draw nothing worth drawing (one type, related to nothing: Mem0's "Fact")
      const p = providerOf(m);
      const [schema, recent] = await Promise.all([
        withSchema ? getSchema(m.id).then(schemaIn).catch(() => null) : Promise.resolve(null),
        !withSchema && saysNothing(concepts(null, p)) ? firstWords(m) : Promise.resolve(null),
      ]);
      if (live) setFacts((f) => ({ ...f, [m.id]: { schema, recent: recent?.lines ?? null, count: recent?.count ?? null } }));
    });
    return () => { live = false; };
  }, [list, providers, providerOf]);

  const created = (m: Memory) => {
    toast(`${m.name} created.`);
    router.push(`/memories/${enc(m.id)}?tab=data`);
  };
  /** Look for engines running beside this instance, and say which were connected (the providers read before and
   *  after), then, in the service's words, any that is running and needs its key, or that couldn't be connected. */
  const find = async () => {
    setMore(false);
    if (finding) return;
    setFinding(true);
    const before = new Set((providers || []).filter((p) => p.connected).map((p) => p.id));
    try {
      const said = await findEngines();
      const after = (await reloadProviders()) || [];
      const found = after.filter((p) => p.connected && !before.has(p.id)).map((p) => vendorName(p.id));
      const more = said.filter((x) => x.state === 'running' || x.state === 'refused').map((x) => x.message).filter(Boolean);
      toast([found.length ? `${found.join(', ')} connected.` : more.length ? '' : 'No new engine found running here.', ...more].filter(Boolean).join(' '));
    } catch (e) { toast(plain(e, 'Engines could not be looked for just now. Try again.')); }
    finally { setFinding(false); }
  };

  const loading = !failed && (!list || (!providers && !providersFailed));
  const noneConnected = !!providers && !providers.some((p) => p.connected);
  const L = useMemo(() => list || [], [list]);
  // the order the service gave is the order it was last used in, where it says (0.40); by name is a click away
  const dated = L.some((m) => m.last_used_at !== undefined);
  const needle = q.trim().toLowerCase();
  const shown = useMemo(() => {
    const hit = (m: Memory) => !needle || [m.name, m.description, vendorName(engineOf(m)), ...(m.used_by || []).map((u) => u.name)]
      .some((t) => (t || '').toLowerCase().includes(needle));
    const out = L.filter(hit);
    if (sort === 'name' || !dated) return [...out].sort((a, b) => a.name.localeCompare(b.name));
    return [...out].sort((a, b) => (msOf(b.last_used_at) || 0) - (msOf(a.last_used_at) || 0) || a.name.localeCompare(b.name));
  }, [L, needle, sort, dated]);

  const moreMenu = (
    <span className="mm-popw" ref={moreWrap}>
      <button type="button" className="icon-btn mm-more" aria-label="More" title="More" aria-haspopup="menu" aria-expanded={more} onClick={() => setMore(!more)}>{DOTS}</button>
      {more ? (
        <div className="mm-pop mm-pop-r" role="menu">
          <button type="button" className="mm-mi" role="menuitem" onClick={() => { setMore(false); setOpen({ k: 'choose' }); }}><b>Connect an engine</b><small>An engine you run, by its address</small></button>
          <button type="button" className="mm-mi" role="menuitem" disabled={finding} onClick={() => void find()}><b>{finding ? 'Looking for engines…' : 'Find engines'}</b><small>The ones running beside this instance</small></button>
        </div>
      ) : null}
    </span>
  );

  const top = (
    <div className="list-top mm-top">
      <div>
        <h1>Memories</h1>
        {L.length ? null : <p className="sub">What your agents remember from one task to the next.</p>}
      </div>
      {loading || failed ? null : (
        <div className="top-actions">
          {L.length ? (
            <div className="seg vm-seg" role="group" aria-label="View">
              <button type="button" className={vm === 'cards' ? 'on' : ''} aria-pressed={vm === 'cards'} onClick={() => pick('cards')}>{GRID_IC}Cards</button>
              <button type="button" className={vm === 'list' ? 'on' : ''} aria-pressed={vm === 'list'} onClick={() => pick('list')}>{LIST_IC}List</button>
            </div>
          ) : null}
          {noneConnected && !L.length ? null : <button type="button" className="btn primary" onClick={() => setOpen({ k: 'new' })}>{PLUS}New memory</button>}
          {moreMenu}
        </div>
      )}
    </div>
  );
  const tools = L.length && !loading && !failed ? (
    <div className="mm-ltools">
      <label className="mm-find mm-lfind">{SEARCH}<input type="search" value={q} placeholder={`Search ${L.length} ${L.length === 1 ? 'memory' : 'memories'}`} aria-label="Search memories" autoComplete="off" spellCheck={false} onChange={(e) => setQ(e.target.value)} />
        {q ? <button type="button" className="mt-clear" aria-label="Clear" onClick={() => setQ('')}>{X}</button> : null}</label>
      {dated ? (
        <label className="mm-sort"><span>Sort</span>
          <select className="set-in slim" value={sort} aria-label="Sort memories" onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="recent">Recently used</option>
            <option value="name">Name</option>
          </select>
        </label>
      ) : null}
    </div>
  ) : null;
  /** Use in, on a memory nothing uses yet and this person may give: beside the card, never inside its link. */
  const useIn = (m: Memory) => (speaksUse(m) && !m.parent_id && !m.used_by?.length && m.privileges?.includes('write')
    ? <button type="button" className="btn small mm-usein" onClick={() => setOpen({ k: 'use', m })}>Use in…</button> : null);

  let body: React.ReactNode;
  if (failed) {
    body = <div className="empty-list ws-fail" role="alert">Your memories could not be read just now. <button type="button" className="link-q inl" onClick={read}>Try again</button></div>;
  } else if (loading) {
    body = <Skel label="Loading memories"><div className="cards mm-cards"><SkCards n={3} /></div></Skel>;
  } else if (noneConnected && !L.length) {
    body = (
      <div className="mm-empty-list">
        <div className="mm-art big"><Ghost /></div>
        <h2>Connect a memory engine</h2>
        <p>Your agents remember through an engine. Connect one, or find the ones running beside this instance.</p>
        <div className="mm-none-acts">
          <button type="button" className="btn primary" onClick={() => setOpen({ k: 'choose' })}>Connect an engine</button>
          <button type="button" className="btn" disabled={finding} onClick={() => void find()}>{finding ? 'Looking…' : 'Find engines'}</button>
        </div>
      </div>
    );
  } else if (!L.length) {
    body = (
      <div className="mm-empty-list">
        <div className="mm-art big"><Ghost /></div>
        <h2>No memories yet</h2>
        <p>A memory is where your agents keep what should outlast one task: who your customers are, the rules they follow, what happened last time. A new setup gets one of its own.</p>
        <button type="button" className="btn primary" onClick={() => setOpen({ k: 'new' })}>{PLUS}New memory</button>
      </div>
    );
  } else if (!shown.length) {
    body = <p className="empty-list" role="status">No memory matches that. <button type="button" className="link-q inl" onClick={() => setQ('')}>Clear the search</button></p>;
  } else if (vm === 'list') {
    body = (
      <>
        <div className="rows-head mm-rows-g"><span>Name</span><span>Description</span></div>
        <div className="rows mm-rows">
          {shown.map((m) => {
            const p = providerOf(m), f = facts[m.id];
            return (
              <div key={m.id} className="mm-roww">
                <Link href={`/memories/${enc(m.id)}`} className="row mm-rows-g mm-row">
                  <span className="t with-mini">
                    <span className="mm-mini-box">{f ? <MiniArt {...pictureOf(f, p)} records={f.count ?? f.recent?.length ?? null} /> : null}</span>
                    <span className="mm-rn">
                      <span className="mm-ct"><b>{shownName(m)}</b>{p && !p.connected ? <span className="pill neutral">Not connected</span> : null}</span>
                      <small className="sub2 mm-cp">{engineLine(m)}</small>
                      <UsedBy m={m} />
                    </span>
                  </span>
                  <span className="mm-rd">{m.description || 'No description yet.'}</span>
                </Link>
                {useIn(m)}
              </div>
            );
          })}
        </div>
      </>
    );
  } else {
    body = (
      <div className="cards mm-cards">
        {shown.map((m) => {
          const p = providerOf(m), f = facts[m.id];
          return (
            <div key={m.id} className="mm-cardw">
              <Link href={`/memories/${enc(m.id)}`} className="card mm-card">
                <span className="mm-art"><CardArt {...pictureOf(f, p)} records={f?.count ?? f?.recent?.length ?? null} recent={f?.recent} pending={!f} /></span>
                <span className="mm-cb">
                  <span className="mm-ct"><b>{shownName(m)}</b>{p && !p.connected ? <span className="pill neutral">Not connected</span> : null}</span>
                  <span className="mm-cp">{engineLine(m)}</span>
                  <span className="mm-cd">{m.description || 'No description yet.'}</span>
                  <UsedBy m={m} />
                </span>
              </Link>
              {useIn(m)}
            </div>
          );
        })}
        {needle ? null : (
          <button type="button" className="card new-card mm-new" onClick={() => setOpen({ k: 'new' })}>
            <span className="mm-art"><Ghost /></span>
            <span className="nc-b">{PLUS}<span>New memory</span></span>
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="scroll">
      <div className="list-wrap">
        {loading ? <Skel label="Loading"><SkHead /></Skel> : top}
        {tools}
        {body}
      </div>
      {open?.k === 'new' ? (
        <NewMemorySheet providers={providers} failed={providersFailed} retry={() => void reloadProviders()} picked={open.picked}
          onClose={() => setOpen(null)} onCreated={created} onConnect={() => setOpen({ k: 'choose', then: 'new' })} />
      ) : null}
      {open?.k === 'choose' && providers ? (
        <ChooseServiceSheet providers={providers} onClose={() => setOpen(null)}
          onConnected={async (id) => { const then = open.then; await reloadProviders(); setOpen(then === 'new' || !L.length ? { k: 'new', picked: id } : null); toast(`${vendorName(id)} connected.`); }} />
      ) : null}
      {open?.k === 'use' ? (
        <UseInSheet m={open.m} onClose={() => setOpen(null)} onDone={(setup) => { setOpen(null); toast(`${setup} remembers in ${open.m.name} now.`); read(); }} />
      ) : null}
    </div>
  );
}
