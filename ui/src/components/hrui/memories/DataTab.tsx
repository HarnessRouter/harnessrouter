'use client';
// A memory's data, in columns you can drag: everything it holds on the left, the open record in the middle as a
// document people edit together, and, where its records link to each other (or when asked), the graph of what
// connects to what on the right. Under 900 px they become tabs, and the page opens on the list (or on a record it was
// sent to), never on an empty record. Opened, it shows the most recent record that says something (never an episode
// or a bare role name), or nothing. A record of a memory below this one (a person's own, below an agent's) opens here
// too, in that memory, its place said above it (this memory › the person), so nobody loses their place.
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  bodyOf, getMemory, getRecord, graphAround, labelOf, reviseRecord, shownName, userOf,
  type GraphEdge, type Memory, type MemoryGraph, type MemoryRecord, type Provider,
} from '@/lib/memories';
import { plain } from '../setup/settingsModel';
import { toast } from '../toast';
import { canEdit, connectionsHidden, hasFolders, hasRelations, hasSchema, keepsLinks, kindOf, schemaGuides, shapeOf } from './caps';
import { KindArt } from './CardArt';
import { NewSubMemorySheet } from './tree/TreeSheets';
import { Connections, type LinkOption } from './Connections';
import { PLUS } from './parts';
import { ResizableColumns } from './ResizableColumns';
import { typeLabel, type LSchema } from './schemaModel';
import { allFolders, folderTree } from './tree';
import { MemoryTree } from './tree/MemoryTree';
import { listChildren } from './tree/api';
import { recordOfKind } from './tree/treeModel';

// Client only: the live document's library is the server's too, and a second copy of it in the same process warns and misbehaves.
// Its code is read ahead as the page opens, and until it is here a record shows what the list holds of it (never a blank
// page while it loads, a phone's first tap on 11-09).
let recordDocHere = false;
const loadRecordDoc = () => import('./RecordDoc').then((m) => { recordDocHere = true; return m.RecordDoc; });
const RecordDoc = dynamic(loadRecordDoc, { ssr: false });
const MemoryGraphView = dynamic(() => import('./graph/MemoryGraph').then((m) => m.MemoryGraph), { ssr: false, loading: () => <p className="mm-muted mm-cpad">Drawing the graph…</p> });

export interface RecordsRead {
  records: MemoryRecord[] | null; failed: boolean; retry: () => void; more: (() => void) | null;
  put: (r: MemoryRecord) => void; drop: (id: string) => void;
}
export { labelFilter } from './tree/treeModel';

/** Names that stand for a role in a conversation, not for anything a person would look up. */
const ROLES = new Set(['user', 'assistant', 'system', 'agent', 'human', 'ai', 'me', 'you']);
/** The record a memory opens on: the most recently written one that says something, never an episode (a whole task),
 *  a role's bare name or a record with no words. Null when none is worth opening. */
export function latestWorthOpening(records: MemoryRecord[]): MemoryRecord | null {
  const worth = records.filter((r) => {
    if (r.status !== 'active' || r.type === 'episode') return false;
    const said = (labelOf(r) || '').trim();
    if (said.length < 3 || ROLES.has(said.toLowerCase())) return false;
    return !!(bodyOf(r).trim() || r.title.trim());
  });
  const at = (r: MemoryRecord) => Date.parse(r.time?.written_at || '') || 0;
  return worth.sort((a, b) => at(b) - at(a))[0] || null;
}

export function DataTab({ memory, provider, schema, read, setups, typeFilter, initialRecord, initialIn = '', onOpenRecord, onSchema, onOtherMemory, onChanged, onBelowChanged, liveTick, pulse, showGraph = true, onUseIn, urlRecord = null, urlIn = null, onPlace }: {
  memory: Memory; provider: Provider | null; schema: LSchema | null; read: RecordsRead; setups: Map<string, string> | null;
  typeFilter: string; initialRecord: string;
  /** the memory below this one that `initialRecord` is in (a person's own), where it isn't this one's */
  initialIn?: string;
  onOpenRecord: (id: string, inMemory: string) => void; onSchema: () => void;
  onOtherMemory: (memoryId: string, recordId: string) => void; onChanged: () => void;
  /** a record of a memory below this one was changed here: the list reads what is below again */
  onBelowChanged?: (recordIds: string[]) => void;
  liveTick: number; pulse: string[];
  /** the graph's column: where records link, or when a person asked for it */
  showGraph?: boolean;
  /** give this memory to a setup, where nothing uses it yet */
  onUseIn?: () => void;
  /** the record the address names now (?record=, and ?in= for one below this memory): Back and Forward move it */
  urlRecord?: string | null; urlIn?: string | null;
  /** put the open record in the address: `push` where opening it is going somewhere (the columns are tabs, and the
   *  list gives way to it, so Back returns to the list), else `replace`; '' takes it out */
  onPlace?: (recordId: string, inMemory: string, how: 'push' | 'replace') => void;
}) {
  const write = !!memory.privileges?.includes('write');
  // a record's kind comes from a schema of types; labels are a vocabulary on facts, not kinds of record
  const kinds = schemaGuides(provider) ? schema : null;
  const [sel, setSel] = useState(initialRecord);
  // the memory below this one the open record is in ('' for this one's own)
  const [selIn, setSelIn] = useState(initialRecord && initialIn !== memory.id ? initialIn : '');
  const [inMemory, setInMemory] = useState<Memory | null>(null);
  const [draft, setDraft] = useState<MemoryRecord | null>(null);
  const [outside, setOutside] = useState<MemoryRecord | null>(null);    // open, but not in the list: forgotten, or past a page
  // the list's own copy of the record just opened from it: its title and words show at once, while the record (and,
  // for a person's record, their memory) is read
  const [peek, setPeek] = useState<MemoryRecord | null>(null);
  const [missed, setMissed] = useState('');      // the open record that could not be read ("in:id")
  const [docHere, setDocHere] = useState(recordDocHere);
  useEffect(() => {
    if (docHere) return undefined;
    let live = true;
    loadRecordDoc().catch(() => undefined).finally(() => { if (live) setDocHere(true); });
    return () => { live = false; };
  }, [docHere]);
  // where the columns are tabs: the list, unless the page was sent to a record
  const [tab, setTab] = useState(initialRecord ? 'doc' : 'tree');
  const [subSheet, setSubSheet] = useState(false);
  useEffect(() => { onOpenRecord(sel, selIn); }, [sel, selIn, onOpenRecord]);

  // ── the open record in the address ────────────────────────────────────────────────────────
  // Where the columns are tabs (a phone), opening a record from the list is going somewhere: it is pushed, so Back
  // comes back to the list, not out of the memory. Side by side, the list stays and a record is only picked: the
  // address follows it in place. Back and Forward (and a link) move the open record with the address.
  const narrow = useRef(false);
  const pushed = useRef(false);                  // the address's record is one this page pushed (Back is the list)
  const at = useRef(`${urlIn || ''}:${urlRecord || ''}`);
  const placed = useRef<string | null>(null);    // the address this page last asked for
  const placeRef = useRef(onPlace);
  placeRef.current = onPlace;
  const place = useCallback((rid: string, inMid: string, going: boolean) => {
    const key = `${rid ? inMid : ''}:${rid}`;
    if (!placeRef.current || key === at.current) return;
    const push = going && narrow.current && !!rid;
    if (push) pushed.current = true;
    placed.current = key;
    placeRef.current(rid, rid ? inMid : '', push ? 'push' : 'replace');
  }, []);
  const selNow = useRef({ sel, selIn });
  selNow.current = { sel, selIn };
  useEffect(() => {
    const key = `${urlIn || ''}:${urlRecord || ''}`;
    if (key === at.current) return;
    at.current = key;
    if (key === placed.current) { placed.current = null; return; }   // the page's own doing
    if (!urlRecord) {
      // Back to the list
      pushed.current = false;
      if (narrow.current) setTab('tree');
      return;
    }
    // Forward, or a link: that record
    const inMid = urlIn && urlIn !== memory.id ? urlIn : '';
    if (urlRecord !== selNow.current.sel || inMid !== selNow.current.selIn) { setDraft(null); setPeek(null); setSelIn(inMid); setSel(urlRecord); }
    setTab('doc');
  }, [urlRecord, urlIn, memory.id]);
  // the tabs: the Record tab is going to the record (pushed, so Back is the list), and the Records tab after a push is Back
  const pickTab = useCallback((id: string) => {
    if (id === 'doc' && selNow.current.sel) place(selNow.current.sel, selNow.current.selIn, true);
    if (id === 'tree' && at.current !== ':') {
      if (pushed.current && typeof window !== 'undefined') { pushed.current = false; window.history.back(); }
      else place('', '', false);
    }
    setTab(id);
  }, [place]);

  // the memory below this one a record is open in: read for what it lets a person do, and checked to be below this one
  // (anything else opens on its own page)
  const otherRef = useRef(onOtherMemory);
  otherRef.current = onOtherMemory;
  const selRef = useRef(sel);
  selRef.current = sel;
  useEffect(() => {
    if (!selIn) { setInMemory(null); return undefined; }
    let live = true;
    setInMemory(null);
    getMemory(selIn).then((m) => {
      if (!live) return;
      if (m.parent_id === memory.id || (m.ancestors || []).includes(memory.id)) setInMemory(m);
      else otherRef.current(selIn, selRef.current);
    }).catch(() => { if (live) setInMemory(null); });
    return () => { live = false; };
  }, [selIn, memory.id]);

  // what the memories below this one hold, where this one holds nothing itself (an agent that keeps each person apart):
  // the page says "Nothing kept yet" only when nothing is kept anywhere in it
  const [below, setBelow] = useState<{ n: number | null; people: boolean } | null>(null);
  const kids = memory.children?.count || 0;
  useEffect(() => {
    if (!kids) { setBelow({ n: 0, people: false }); return undefined; }
    let live = true;
    listChildren(memory.id).then((l) => {
      if (!live) return;
      const counts = l.map((k) => k.records?.count);
      setBelow({ n: counts.some((c) => typeof c !== 'number') ? null : (counts as number[]).reduce((a, b) => a + b, 0), people: l.some((k) => !!userOf(k)) });
    }).catch(() => { if (live) setBelow({ n: null, people: false }); });
    return () => { live = false; };
  }, [memory.id, kids, liveTick]);

  const all = useMemo(() => read.records || [], [read.records]);
  // the most recent record that says something opens by itself, or none: never an episode, a role's bare name or an
  // empty one (Richard 11-09: a memory opened on "user"); a person's own choice is never replaced
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current || sel || draft || !read.records?.length) return;
    opened.current = true;
    const first = latestWorthOpening(read.records);
    if (first) setSel(first.id);
  }, [read.records, sel, draft]);

  const listed = selIn ? null : all.find((r) => r.id === sel) || null;
  useEffect(() => {
    if (!sel || listed || !read.records) { setOutside(null); return undefined; }
    let live = true;
    getRecord(selIn || memory.id, sel).then((r) => { if (live) setOutside(r); }).catch(() => { if (live) { setOutside(null); setMissed(`${selIn}:${sel}`); } });
    return () => { live = false; };
  }, [sel, selIn, listed, read.records, memory.id]);
  const record = draft || listed || outside;
  // the memory the open record is in: this one, or the one below it it was opened in (once read)
  const docMemory = selIn ? inMemory : memory;

  // A record picked on the graph opens in the graph's own panel, so where the columns are tabs the graph stays (Richard
  // 11-06: in a narrow view the panel takes the bottom of the graph); picked anywhere else, the Record tab shows it.
  const pick = useCallback((rid: string, mid?: string) => {
    if (mid && mid !== memory.id) { onOtherMemory(mid, rid); return false; }
    setDraft(null); setPeek(null); setSelIn(''); setSel(rid);
    return true;
  }, [memory.id, onOtherMemory]);
  // from the graph or a link: the record is picked where it is (the graph stays), and the address follows in place
  const show = useCallback((rid: string, mid?: string) => {
    const ok = pick(rid, mid);
    if (ok) place(rid, '', false);
    return ok;
  }, [pick, place]);
  // from the list: a record of a memory below this one (a person's own) opens here, in that memory; on a phone the
  // list gives way to it, and Back brings the list back
  const open = useCallback((rid: string, mid?: string, item?: MemoryRecord) => {
    const below = !!mid && mid !== memory.id;
    if (below) { setDraft(null); setSelIn(mid); setSel(rid); }
    else if (!pick(rid, mid)) return;
    setPeek(item && item.id === rid ? item : null);
    setTab('doc');
    place(rid, below ? mid : '', true);
  }, [pick, place, memory.id]);

  // ── what the open record links to ─────────────────────────────────────────────────────────
  const links = keepsLinks(provider);
  const [graph, setGraph] = useState<MemoryGraph | null>(null);
  const [graphFailed, setGraphFailed] = useState(false);
  // a record forgotten while it's open stays readable here, and has nothing left to ask about
  const rid = record && record.status === 'active' ? record.id : '';
  const version = record?.version || 0;
  const readGraph = useCallback(() => {
    setGraphFailed(false);
    if (!rid || !links) { setGraph(null); return () => {}; }
    let live = true;
    graphAround(selIn || memory.id, rid, 1)
      .then((g) => { if (live) setGraph(g); })
      .catch(() => { if (live) { setGraph(null); setGraphFailed(true); } });
    return () => { live = false; };
  }, [rid, links, memory.id, selIn]);
  useEffect(() => readGraph(), [readGraph, version, liveTick]);

  const edges = useMemo(() => (graph?.edges || []).filter((e) => e.from.record_id === rid || e.to.record_id === rid), [graph, rid]);
  const linkCount = links ? edges.length : (record?.references?.length || 0);

  const options = useMemo<LinkOption[] | null>(() => {
    if (!record || !record.id || !links || !docMemory || !canEdit(record, provider, docMemory)) return null;
    if (hasSchema(provider) && !hasRelations(provider)) return null;
    const free: LinkOption[] = [{ key: 'free', rel: '', out: true, other: null, label: '' }];
    if (!hasSchema(provider)) return free;
    const kind = kindOf(record);
    const nameOf = (id: string) => schema?.types.find((t) => t.id === id)?.name || '';
    const designed = (schema?.relations || []).flatMap((r) => {
      const a = nameOf(r.from), b = nameOf(r.to), o: LinkOption[] = [];
      if (a === kind) o.push({ key: `${r.id}:o`, rel: r.name, out: true, other: b, label: `${r.name} → ${typeLabel(b)}` });
      if (b === kind) o.push({ key: `${r.id}:i`, rel: r.name, out: false, other: a, label: `← ${r.name} from ${typeLabel(a)}` });
      return o;
    });
    // A schema steers what the provider pulls out; it does not limit what is stated. An agent links any two records
    // with a word of its own, so a person can too where the schema relates this type to nothing.
    return designed.length ? designed : free;
  }, [record, links, provider, docMemory, schema]);
  const candidates = (o: LinkOption) => all.filter((x) => x.id !== rid && (o.other === null || kindOf(x) === o.other) && (o.out || canEdit(x, provider, memory)));
  const refsOf = (r: MemoryRecord) => (r.references || []).filter((x) => x.available !== false).map((x) => ({ rel: x.rel || 'related', record_id: x.record_id, ...(x.memory_id ? { memory_id: x.memory_id } : {}) }));
  const holderOf = (e: GraphEdge) => graph?.nodes.find((n) => n.record.id === e.from.record_id)?.record;
  const canUnlink = (e: GraphEdge) => { const h = holderOf(e); return !!h && e.available && canEdit(h, provider, memory); };
  const savedLink = (r: MemoryRecord) => { read.put(r); readGraph(); };
  const link = async (o: LinkOption, rel: string, to: string) => {
    const holder = o.out ? record : all.find((x) => x.id === to);
    if (!holder) return;
    try {
      savedLink(await reviseRecord(selIn || memory.id, holder.id, { references: [...refsOf(holder), { rel, record_id: o.out ? to : rid }] }));
    } catch (e) { toast(plain(e, 'That link was not made. Try again.')); }
  };
  const unlink = (e: GraphEdge) => {
    const h = holderOf(e);
    if (!h) return;
    const kept = refsOf(h).filter((x) => !(x.record_id === e.to.record_id && x.rel === (e.rel || 'related')));
    reviseRecord(selIn || memory.id, h.id, { references: kept }).then(savedLink).catch((x) => toast(plain(x, 'That link was not removed. Try again.')));
  };
  const hideLinks = connectionsHidden(provider, linkCount, !!options?.length);

  // ── a new record, not made until its author leaves it ─────────────────────────────────────
  const startNew = useCallback((kind: string, folder?: string) => {
    const made = recordOfKind(kind, provider, schema);
    setDraft({
      id: '', object: 'memory.record', memory_id: memory.id, type: made.type, title: '', content: [],
      attributes: { ...made.attributes, ...(folder ? { folder } : {}) }, version: 0, status: 'active', supersedes: null,
      time: { valid_from: null, valid_to: null, written_at: null, invalidated_at: null },
      written_by: { kind: 'member', id: '' }, references: [], trust: 'untrusted',
    });
    setSel(''); setSelIn(''); setTab('doc');
  }, [memory.id, provider, schema]);
  const everyFolder = useMemo(() => (hasFolders(provider) ? allFolders(folderTree(all, [])) : []), [provider, all]);

  const tree = <MemoryTree memory={memory} provider={provider} schema={kinds} read={read} activeId={record?.id || ''} pulse={pulse} filterKind={typeFilter} onOpen={open} onNew={startNew} onChanged={onChanged} />;
  // something is kept here, in this memory or below it (null while what is below is still being read)
  const held = all.length ? true : below === null ? (kids ? null : false) : below.n === null ? true : below.n > 0;
  const doc = (
    <main className="mm-doc">
      {record && docMemory && docHere ? (
        <RecordDoc key={`${selIn}:${record.id || 'draft'}`} memory={docMemory} above={selIn ? shownName(memory) : undefined} provider={provider} record={record} schema={kinds} setups={setups} links={linkCount} folders={selIn ? [] : everyFolder}
          onSaved={(r) => {
            if (selIn) { onBelowChanged?.([r.id]); return; }
            read.put(r); if (draft) { setDraft(null); setSel(r.id); onChanged(); }
          }}
          onGone={(id) => {
            if (selIn) { setSel(''); setSelIn(''); onBelowChanged?.([id]); return; }
            read.drop(id); setSel(''); onChanged();
          }} />
      ) : record || (peek && peek.id === sel) ? (
        // read, or its memory still being read: what the list showed of it, at once
        <RecordPeek r={(record || peek) as MemoryRecord} />
      ) : sel && !draft && read.records && missed !== `${selIn}:${sel}` ? (
        <><div className="mm-doc-bar"><span className="grow" /><span className="mm-saved" role="status">Opening…</span></div></>
      ) : (
        <>
          <div className="mm-doc-bar"><span className="grow" /></div>
          {read.records && held !== null ? (
            <div className="mm-doc-empty">
              <h2>{held ? 'Pick a record' : 'Nothing kept yet'}</h2>
              <p>{held
                ? (!all.length && below?.people ? 'What it keeps about each person is under their name. Choose a record to read it.'
                  : showGraph ? 'Choose one from the list or the graph to read it.' : 'Choose one from the list to read it.')
                : `Add the first record, or give ${memory.name} to a setup and let it write.`}</p>
              {!held && write ? <button type="button" className="btn primary small" onClick={() => startNew(kinds?.types[0]?.name || 'note')}>{PLUS}New record</button> : null}
              {!held && schemaGuides(provider) && !schema?.types.length ? <p className="set-help mm-doc-alt"><button type="button" className="link-q inl" onClick={onSchema}>Set what it should look for first</button></p> : null}
            </div>
          ) : null}
        </>
      )}
    </main>
  );
  const right = (
    <aside className="mm-conn" aria-label="Graph">
      <div className="mm-graphbox">
        {/* One list of links, in the panel a record opens on the graph (Richard 11-06: not a strip under it as well,
            and nothing until a record is clicked). The open record's are the ones that can be changed. */}
        <MemoryGraphView memory={memory} provider={provider} schema={kinds} activeRecordId={rid} refreshKey={liveTick} changed={pulse} onOpenRecord={show}
          linksFor={(id: string) => (hideLinks || !record?.id || id !== record.id ? null : (
            <Connections record={record} graph={graph} failed={graphFailed} retry={readGraph} schema={kinds} options={options} candidates={candidates} provider={provider}
              onOpen={show} onLink={link} onUnlink={unlink} canUnlink={canUnlink} />
          ))} />
      </div>
    </aside>
  );
  // A memory that holds nothing at all (no records, no sub memories) is said once, in the middle: what it will hold,
  // drawn dashed in the next blue, and the ways to start. The list and the graph would each only say "empty" again.
  const nothing = !!read.records && !all.length && !draft && !record && !memory.children?.count;
  if (nothing) {
    const create = !!memory.privileges?.includes('create');
    return (
      <div className="mm-data mm-data-none">
        <div className="mm-none">
          <span className="mm-none-pic"><KindArt kind={shapeOf(provider)} /></span>
          <h2>Nothing kept yet</h2>
          <p>{`Add the first record, or give ${memory.name} to a setup and let it write.`}</p>
          {write || create || onUseIn ? (
            <div className="mm-none-acts">
              {write ? <button type="button" className="btn primary small" onClick={() => startNew(kinds?.types[0]?.name || 'note')}>{PLUS}New record</button> : null}
              {create ? <button type="button" className="btn small" onClick={() => setSubSheet(true)}>New sub memory</button> : null}
              {onUseIn ? <button type="button" className="btn small" onClick={onUseIn}>Use in…</button> : null}
            </div>
          ) : null}
          {schemaGuides(provider) && !schema?.types.length ? <p className="set-help mm-doc-alt"><button type="button" className="link-q inl" onClick={onSchema}>Set what it should look for first</button></p> : null}
        </div>
        {subSheet ? <NewSubMemorySheet parent={memory} onClose={() => setSubSheet(false)} onDone={(m) => { setSubSheet(false); toast(`${m.name} created`); onChanged(); }} /> : null}
      </div>
    );
  }
  return (
    <div className="mm-data">
      <ResizableColumns storageKey={showGraph ? 'hr.memory.columns' : 'hr.memory.columns.nograph'} tab={tab} panes={[
        { id: 'tree', label: 'Records', min: 220, initial: 280, node: tree },
        { id: 'doc', label: 'Record', min: 380, initial: 640, grow: true, node: doc },
        ...(showGraph ? [{ id: 'graph', label: 'Graph', min: 280, initial: 440, node: right }] : []),
      ]} onTab={pickTab} onNarrow={(n) => { narrow.current = n; }} />
    </div>
  );
}

const PEEK_MAX = 600;
/** A record as the list holds it, drawn at once while it is opened: its title and the start of its words, laid out as
 *  the record itself will be, and "Opening…" where its version will say how it is saved. */
function RecordPeek({ r }: { r: MemoryRecord }) {
  const title = (r.title || '').trim();
  const words = (bodyOf(r) || (title ? '' : labelOf(r))).replace(/\s+/g, ' ').trim();
  const excerpt = words.length > PEEK_MAX ? `${words.slice(0, PEEK_MAX - 1).trim()}…` : words;
  return (
    <>
      <div className="mm-doc-bar"><span className="grow" /><span className="mm-saved" role="status">Opening…</span></div>
      <div className="mm-doc-scroll">
        <article className="mm-doc-col mm-peek" aria-busy="true">
          {title ? <h1 className="mm-title">{title}</h1> : null}
          {excerpt ? <div className={`mm-body${title ? '' : ' mm-sentence'}`}><p>{excerpt}</p></div> : null}
        </article>
      </div>
    </>
  );
}
