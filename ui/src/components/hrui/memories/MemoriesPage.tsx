'use client';
// Memories (docs: the design's memoriesView): one card per memory, each with its picture, the engine that keeps it,
// which setups use it and when it was last used. Search narrows by name, description, engine or setup, and the list is
// in the order it was last used (the memories spec, C3). Every figure is the service's; what a service before 0.40
// doesn't say (who uses it, when) is not drawn. With no engine connected here the page looks for the ones running beside
// this instance by itself, once, says what it found, and leads to connecting one; New memory's list connects any other.
//
// A card's picture (Richard 11-09) is its schema graph as the Schema tab draws it, kept by the service and only loaded
// here, or the memory's brick where there is no graph (cover.ts). The page reads nothing else for it: the covers still
// missing are made after it has settled, one at a time, in the background.
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { findEngines, getSchema, listMemories, type Memory } from '@/lib/memories';
import { ago } from '../setups';
import { Skel, SkCards, SkHead } from '../Skel';
import { toast } from '../toast';
import { hasSchema } from './caps';
import { Ghost } from './CardArt';
import { canDraw, coverGraphOf, coverState, drawnCover, isGraph, keepCover, picKindOf, type Drawn } from './cover';
import { MemoryArt } from './MemoryArt';
import { engineOf, msOf, PLUS, SEARCH, shownName, useProviders, X } from './parts';
import { schemaIn, type LSchema } from './schemaModel';
import { ChooseServiceSheet, ConnectSheet, NewMemorySheet } from './sheets';
import { vendorName } from './vendors';
import './memories.css';

/** How long the page rests, once read, before it makes any cover still missing. */
const SETTLE_MS = 900;
/** A moment the browser has nothing else to do, between two covers. */
const idle = () => new Promise<void>((r) => {
  const w = window as { requestIdleCallback?: (f: () => void, o?: { timeout: number }) => void };
  if (w.requestIdleCallback) w.requestIdleCallback(() => r(), { timeout: 600 }); else setTimeout(r, 40);
});

type Open = { k: 'new'; picked?: string } | { k: 'choose'; then?: 'new' } | { k: 'connect'; id: string } | null;
type Sort = 'recent' | 'name';
const enc = encodeURIComponent;
// Cards or a list, as on Studio, and remembered the same way (for this person, in this browser)
const VM_KEY = 'hr.memories.view';
type View = 'cards' | 'list';
const GRID_IC = <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true"><rect x="2" y="2" width="5" height="5" rx="1.2" /><rect x="9" y="2" width="5" height="5" rx="1.2" /><rect x="2" y="9" width="5" height="5" rx="1.2" /><rect x="9" y="9" width="5" height="5" rx="1.2" /></svg>;
const LIST_IC = <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" aria-hidden="true"><path d="M2.5 4h11M2.5 8h11M2.5 12h11" /></svg>;
/** Chips past this many are counted, not named. */
const CHIPS = 2;

/** Who uses a memory, as chips: the first few by name, the rest as a count. Nothing where nobody does, or where the
 *  service doesn't say: a memory is given to an agent from its own Settings, never from here (Richard 11-09: "Used in is
 *  sloppy, put it in a Setting tab"). */
function UsedBy({ m }: { m: Memory }) {
  const u = Array.isArray(m.used_by) ? m.used_by : [];
  if (!u.length) return null;
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
  // covers made in this visit, and memories found to have no graph to picture (their brick shows)
  const [drawn, setDrawn] = useState<Record<string, Drawn>>({});
  const [flat, setFlat] = useState<Record<string, true>>({});
  const [open, setOpen] = useState<Open>(null);
  const [vm, setVm] = useState<View>('cards');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('recent');
  useEffect(() => { try { if (localStorage.getItem(VM_KEY) === 'list') setVm('list'); } catch { /* none */ } }, []);
  const pick = (v: View) => { setVm(v); try { localStorage.setItem(VM_KEY, v); } catch { /* none */ } };

  const read = useCallback(() => {
    setFailed(false);
    // no counts: the page shows none, and counting asked every memory's service in turn (13 s for sixty, 2026-11-06)
    listMemories({ counts: false, sort: 'recent' }).then(setList).catch(() => setFailed(true));
  }, []);
  useEffect(() => { read(); }, [read]);
  // Back on the page (another tab or window shown again): read the list again, so an agent's memory made meanwhile
  // is there without a reload. Quietly: a read that fails keeps what is shown. At most once in five seconds.
  useEffect(() => {
    let last = Date.now();
    const again = () => {
      if (document.visibilityState !== 'visible' || Date.now() - last < 5000) return;
      last = Date.now();
      listMemories({ counts: false, sort: 'recent' }).then(setList).catch(() => { /* keep what is shown */ });
    };
    window.addEventListener('focus', again);
    document.addEventListener('visibilitychange', again);
    return () => { window.removeEventListener('focus', again); document.removeEventListener('visibilitychange', again); };
  }, []);
  // a setup's Settings sends a person here to make a memory
  useEffect(() => { if (new URLSearchParams(window.location.search).get('new') === '1') setOpen({ k: 'new' }); }, []);

  // A memory's provider as the memory's own workspace reaches it: what a provider makes itself can differ by connection
  // (Mem0's own service makes facts; a Mem0 server, facts and the names in them), and the list says which.
  const providerOf = useCallback((m: Memory) => {
    const p = (providers || []).find((x) => x.id === m.provider) || null;
    return p && m.builtin !== undefined ? { ...p, schema: { ...p.schema, builtin: m.builtin || undefined } } : p;
  }, [providers]);
  // The covers still missing, and the ones drawn before the drawing changed, made one at a time once the page has
  // settled: the schema read where the engine reads one and nothing says what the cover showed (its only read), drawn
  // offscreen as the Schema tab draws it, kept where this person may write the memory, and shown. One with a person's
  // own types is made again by its Schema tab, never here. Until a new one comes, a card shows the one it has.
  useEffect(() => {
    if (!list || !providers || !canDraw()) return undefined;
    const todo = list.flatMap((m) => {
      if (drawnCover(m.id)) return [];
      const p = providerOf(m), k = picKindOf(m, p);
      if (k === 'graph' || k === 'maybe') return [{ m, read: hasSchema(p) }];
      if (k !== 'cover' || !m.privileges?.includes('write')) return [];
      const st = coverState(m, p);
      return st === 'fresh' ? [] : [{ m, read: st === 'read' }];
    });
    if (!todo.length) return undefined;
    let live = true;
    const t = setTimeout(() => {
      void (async () => {
        for (const { m, read: wants } of todo) {
          await idle();
          if (!live) return;
          const p = providerOf(m);
          let schema: LSchema | null = null, read = true;
          if (wants) {
            try { schema = schemaIn(await getSchema(m.id)); } catch { read = false; }
          }
          if (!live) return;
          const g = coverGraphOf(schema, p);
          if (!isGraph(g)) {
            if (read && !m.cover_at) setFlat((f) => ({ ...f, [m.id]: true }));
            continue;
          }
          // a schema that couldn't be read draws what the engine makes, for this visit only: never kept
          if (!read && m.cover_at) continue;
          try {
            const d = await keepCover(m, g, read && !!m.privileges?.includes('write'));
            if (live && d) setDrawn((x) => ({ ...x, [m.id]: d }));
          } catch { /* this one waits for the next visit */ }
        }
      })();
    }, SETTLE_MS);
    return () => { live = false; clearTimeout(t); };
  }, [list, providers, providerOf]);
  const art = (m: Memory, mini?: boolean) => (
    <MemoryArt m={m} kind={flat[m.id] ? 'brick' : picKindOf(m, providerOf(m))} drawn={drawn[m.id] || drawnCover(m.id)} mini={mini} />
  );

  const created = (m: Memory) => {
    toast(`${m.name} created.`);
    router.push(`/memories/${enc(m.id)}?tab=data`);
  };
  // With no engine connected here (nor the instance's, inherited), the engines running beside this instance are looked
  // for once, by themselves (the service connects those that need no key, on an instance with one operator, and
  // refuses elsewhere, quietly), and what was found is said in one line.
  const [found, setFound] = useState('');
  const looked = useRef(false);
  useEffect(() => {
    if (!providers || looked.current || providers.some((p) => p.connected)) return;
    looked.current = true;
    void (async () => {
      try {
        const said = await findEngines();
        const after = (await reloadProviders()) || [];
        const now = after.filter((p) => p.connected).map((p) => vendorName(p.id));
        const more = said.filter((x) => x.state === 'running' || x.state === 'refused').map((x) => x.message).filter(Boolean);
        setFound([now.length ? `${now.join(', ')} connected.` : '', ...more].filter(Boolean).join(' '));
      } catch { /* not this instance's to look: the page says what it can do */ }
    })();
  }, [providers, reloadProviders]);

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
        <p>Your agents remember through an engine. Connect one to start.</p>
        {found ? <p className="mm-found" role="status">{found}</p> : null}
        <div className="mm-none-acts">
          <button type="button" className="btn primary" onClick={() => setOpen({ k: 'choose' })}>Connect an engine</button>
        </div>
      </div>
    );
  } else if (!L.length) {
    body = (
      <div className="mm-empty-list">
        <div className="mm-art big"><Ghost /></div>
        <h2>No memories yet</h2>
        {found ? <p className="mm-found" role="status">{found}</p> : null}
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
            const p = providerOf(m);
            return (
              <div key={m.id} className="mm-roww">
                <Link href={`/memories/${enc(m.id)}`} className="row mm-rows-g mm-row">
                  <span className="t with-mini">
                    <span className="mm-mini-box">{art(m, true)}</span>
                    <span className="mm-rn">
                      <span className="mm-ct"><b>{shownName(m)}</b>{p && !p.connected ? <span className="pill neutral">Not connected</span> : null}</span>
                      <small className="sub2 mm-cp">{engineLine(m)}</small>
                      <UsedBy m={m} />
                    </span>
                  </span>
                  <span className="mm-rd">{m.description || 'No description yet.'}</span>
                </Link>
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
          const p = providerOf(m);
          return (
            <div key={m.id} className="mm-cardw">
              <Link href={`/memories/${enc(m.id)}`} className="card mm-card">
                <span className="mm-art">{art(m)}</span>
                <span className="mm-cb">
                  <span className="mm-ct"><b>{shownName(m)}</b>{p && !p.connected ? <span className="pill neutral">Not connected</span> : null}</span>
                  <span className="mm-cp">{engineLine(m)}</span>
                  <span className="mm-cd">{m.description || 'No description yet.'}</span>
                  <UsedBy m={m} />
                </span>
              </Link>
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
          onClose={() => setOpen(null)} onCreated={created} onConnect={(id) => setOpen(id ? { k: 'connect', id } : { k: 'choose', then: 'new' })} />
      ) : null}
      {open?.k === 'connect' ? (
        <ConnectSheet id={open.id} onClose={() => setOpen({ k: 'new' })}
          onConnected={async (id) => { await reloadProviders(); setOpen({ k: 'new', picked: id }); toast(`${vendorName(id)} connected.`); }} />
      ) : null}
      {open?.k === 'choose' && providers ? (
        <ChooseServiceSheet providers={providers} onClose={() => setOpen(null)}
          onConnected={async (id) => { const then = open.then; await reloadProviders(); setOpen(then === 'new' || !L.length ? { k: 'new', picked: id } : null); toast(`${vendorName(id)} connected.`); }} />
      ) : null}
    </div>
  );
}
