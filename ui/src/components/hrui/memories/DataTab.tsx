'use client';
// The Data tab (the design's mmDataHtml, mmTreeHtml): the records on the left, the open record in the
// middle, what it links to on the right. The tree follows the provider: real folders where it keeps
// files, one group per kind of record everywhere else. On a narrow window the two sides are drawers.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  bodyOf, graphAround, labelOf, recall, reviseRecord,
  type GraphEdge, type Memory, type MemoryGraph, type MemoryRecord, type Provider, type RecallFilter,
} from '@/lib/memories';
import { plain } from '../setup/settingsModel';
import { toast } from '../toast';
import {
  canEdit, connectionsHidden, coreKindsToWrite, hasFolders, hasRelations, hasSchema, keepsLinks, kindOf, labelsOf, recordTypeOfSchemaKind, schemaGuides, schemaLabels,
} from './caps';
import { Connections, type LinkOption } from './Connections';
import { Dot, FILTER, FOLDER, FOLDER_OPEN, MmIco, PLUS, SEARCH, useDismiss, X } from './parts';
import { RecordDoc } from './RecordDoc';
import { typeLabel, type LSchema } from './schemaModel';
import { allFolders, folderName, folderOf, folderTree, groupsOf, kindInfo, type FolderNode } from './tree';

export interface RecordsRead {
  records: MemoryRecord[] | null; failed: boolean; retry: () => void; more: (() => void) | null;
  put: (r: MemoryRecord) => void; drop: (id: string) => void;
}
const hit = (r: MemoryRecord, q: string) => !q || labelOf(r).toLowerCase().includes(q) || bodyOf(r).toLowerCase().includes(q);
/** The filter that finds a fact by one of its labels. */
export const labelFilter = (value: string): RecallFilter => ({ field: 'attributes.labels', op: 'contains', value });

export function DataTab({ memory, provider, schema, read, setups, typeFilter, initialRecord, onOpenRecord, onSchema, onOtherMemory, onChanged }: {
  memory: Memory; provider: Provider | null; schema: LSchema | null; read: RecordsRead; setups: Map<string, string> | null;
  typeFilter: string; initialRecord: string; onOpenRecord: (id: string) => void; onSchema: () => void;
  onOtherMemory: (memoryId: string, recordId: string) => void; onChanged: () => void;
}) {
  const write = !!memory.privileges?.includes('write');
  const folders = hasFolders(provider);
  const labelled = schemaLabels(provider);
  // a record's kind comes from a schema of types; labels are a vocabulary on facts, not kinds of record
  const kinds = schemaGuides(provider) ? schema : null;
  const [sel, setSel] = useState(initialRecord);
  const [draft, setDraft] = useState<MemoryRecord | null>(null);
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState(typeFilter);
  const [label, setLabel] = useState('');
  const [labelHits, setLabelHits] = useState<MemoryRecord[] | null>(null);
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const [made, setMade] = useState<string[]>([]);
  const [folderSel, setFolderSel] = useState('');
  const [newFolder, setNewFolder] = useState(false);
  const [pop, setPop] = useState<'' | 'new' | 'filter'>('');
  const [treeOpen, setTreeOpen] = useState(false);
  const [connOpen, setConnOpen] = useState(false);
  const [hops, setHops] = useState(1);
  const newWrap = useRef<HTMLSpanElement | null>(null);
  const filterWrap = useRef<HTMLSpanElement | null>(null);
  const closePop = useCallback(() => setPop(''), []);
  useDismiss(pop === 'new', newWrap, closePop);
  useDismiss(pop === 'filter', filterWrap, closePop);
  useEffect(() => { setFilter(typeFilter); }, [typeFilter]);
  useEffect(() => { onOpenRecord(sel); }, [sel, onOpenRecord]);

  const all = useMemo(() => read.records || [], [read.records]);
  // the first record with something in it opens by itself; a person's own choice is never replaced
  useEffect(() => {
    if (sel || draft || !read.records?.length) return;
    const first = [...read.records].sort((a, b) => Number(a.type === 'episode') - Number(b.type === 'episode') || bodyOf(b).length - bodyOf(a).length)[0];
    if (first) setSel(first.id);
  }, [read.records, sel, draft]);

  // a label filters what the service finds. Whatever it answers, only a record that carries the label is
  // listed: a read that lists everything is never shown as what the label holds
  useEffect(() => {
    setLabelHits(null);
    if (!label) return;
    let live = true;
    const words = q.trim();
    const signals = provider?.recall?.signals || [];
    const asked = words ? (signals.includes('query') ? { query: words } : signals.includes('text') ? { text: words } : {}) : {};
    const t = setTimeout(() => {
      recall(memory.id, { filters: labelFilter(label), limit: 100, ...asked })
        .then((d) => { if (live) setLabelHits(d.results.map((x) => x.record)); })
        .catch(() => { if (live) setLabelHits([]); });
    }, words ? 300 : 0);
    return () => { live = false; clearTimeout(t); };
  }, [label, q, memory.id, provider]);

  const needle = q.trim().toLowerCase();
  const shown = useMemo(() => {
    if (label) {
      const byId = new Map<string, MemoryRecord>();
      [...all, ...(labelHits || [])].forEach((r) => byId.set(r.id, r));
      return [...byId.values()].filter((r) => labelsOf(r).includes(label) && hit(r, needle));
    }
    return all.filter((r) => hit(r, needle) && (!filter || kindOf(r) === filter));
  }, [all, labelHits, label, needle, filter]);

  const record = draft || all.find((r) => r.id === sel) || labelHits?.find((r) => r.id === sel) || null;

  // ── what a record links to ────────────────────────────────────────────────────────────────
  const links = keepsLinks(provider);
  const [graph, setGraph] = useState<MemoryGraph | null>(null);
  const [graphFailed, setGraphFailed] = useState(false);
  const rid = record?.id || '';
  const version = record?.version || 0;
  const readGraph = useCallback(() => {
    setGraphFailed(false);
    if (!rid || !links) { setGraph(null); return () => {}; }
    let live = true;
    graphAround(memory.id, rid, hops)
      .then((g) => { if (live) setGraph(g); })
      .catch(() => { if (live) { setGraph(null); setGraphFailed(true); } });
    return () => { live = false; };
  }, [rid, hops, links, memory.id]);
  useEffect(() => readGraph(), [readGraph, version]);

  const edges = useMemo(() => (graph?.edges || []).filter((e) => e.from.record_id === rid || e.to.record_id === rid), [graph, rid]);
  const linkCount = links ? edges.length : (record?.references?.length || 0);

  const options = useMemo<LinkOption[] | null>(() => {
    if (!record || !record.id || !links || !canEdit(record, provider, memory)) return null;
    if (hasSchema(provider) && !hasRelations(provider)) return null;
    if (!hasSchema(provider)) return [{ key: 'free', rel: '', out: true, other: null, label: '' }];
    const kind = kindOf(record);
    const nameOf = (id: string) => schema?.types.find((t) => t.id === id)?.name || '';
    return (schema?.relations || []).flatMap((r) => {
      const a = nameOf(r.from), b = nameOf(r.to), o: LinkOption[] = [];
      if (a === kind) o.push({ key: `${r.id}:o`, rel: r.name, out: true, other: b, label: `${r.name} → ${typeLabel(b)}` });
      if (b === kind) o.push({ key: `${r.id}:i`, rel: r.name, out: false, other: a, label: `← ${r.name} from ${typeLabel(a)}` });
      return o;
    });
  }, [record, links, provider, memory, schema]);
  const candidates = (o: LinkOption) => all.filter((x) => x.id !== rid && (o.other === null || kindOf(x) === o.other) && (o.out || canEdit(x, provider, memory)));
  const refsOf = (r: MemoryRecord) => (r.references || []).filter((x) => x.available !== false).map((x) => ({ rel: x.rel || 'related', record_id: x.record_id, ...(x.memory_id ? { memory_id: x.memory_id } : {}) }));
  const holderOf = (e: GraphEdge) => graph?.nodes.find((n) => n.record.id === e.from.record_id)?.record;
  const canUnlink = (e: GraphEdge) => { const h = holderOf(e); return !!h && e.available && canEdit(h, provider, memory); };
  const savedLink = (r: MemoryRecord) => { read.put(r); readGraph(); };
  const link = async (o: LinkOption, rel: string, to: string) => {
    const holder = o.out ? record : all.find((x) => x.id === to);
    if (!holder) return;
    try {
      savedLink(await reviseRecord(memory.id, holder.id, { references: [...refsOf(holder), { rel, record_id: o.out ? to : rid }] }));
    } catch (e) { toast(plain(e, 'That link was not made. Try again.')); }
  };
  const unlink = (e: GraphEdge) => {
    const h = holderOf(e);
    if (!h) return;
    const kept = refsOf(h).filter((x) => !(x.record_id === e.to.record_id && x.rel === (e.rel || 'related')));
    reviseRecord(memory.id, h.id, { references: kept }).then(savedLink).catch((x) => toast(plain(x, 'That link was not removed. Try again.')));
  };
  const hideConn = connectionsHidden(provider, linkCount, !!options?.length);

  // ── the tree ──────────────────────────────────────────────────────────────────────────────
  const tree = useMemo(() => (folders ? folderTree(shown, needle || filter || label ? [] : made) : null), [folders, shown, made, needle, filter, label]);
  const groups = useMemo(() => (folders ? [] : groupsOf(shown, kinds)), [folders, shown, kinds]);
  const everyFolder = useMemo(() => (folders ? allFolders(folderTree(all, made)) : []), [folders, all, made]);
  const openRecord = (id: string) => { setDraft(null); setSel(id); setTreeOpen(false); setPop(''); };
  const row = (r: MemoryRecord, d: number) => {
    const k = kindInfo(kindOf(r), kinds), on = r.id === record?.id;
    return (
      <button key={r.id} type="button" className={`mm-tr mm-trr${on ? ' on' : ''}`} style={{ '--d': d } as React.CSSProperties} aria-current={on ? 'true' : undefined} onClick={() => openRecord(r.id)}>
        <span className="mm-car" /><span className="mm-ti" style={{ color: k.color }}><MmIco k={k.icon} size={14} /></span><span className="mm-tt">{labelOf(r) || 'Untitled'}</span>
      </button>
    );
  };
  const folderRows = (n: FolderNode, d: number): React.ReactNode => (
    <>
      {n.folders.map((f) => {
        const isOpen = !!needle || !!filter || !closed[f.path];
        return (
          <div key={f.path}>
            <button type="button" className={`mm-tr mm-tf${folderSel === f.path ? ' sel' : ''}`} style={{ '--d': d } as React.CSSProperties} aria-expanded={isOpen}
              onClick={() => { setFolderSel(f.path); setClosed((c) => ({ ...c, [f.path]: isOpen })); }}>
              <span className="mm-car">{isOpen ? '▾' : '▸'}</span>{isOpen ? FOLDER_OPEN : FOLDER}<span className="mm-tt">{f.name}</span><small>{f.total}</small>
            </button>
            {isOpen ? folderRows(f, d + 1) : null}
          </div>
        );
      })}
      {n.records.map((r) => row(r, d))}
    </>
  );

  // ── new ───────────────────────────────────────────────────────────────────────────────────
  const blank = (type: string, attributes: Record<string, unknown>): MemoryRecord => ({
    id: '', object: 'memory.record', memory_id: memory.id, type, title: '', content: [],
    attributes: { ...attributes, ...(folders && folderSel ? { folder: folderSel } : {}) }, version: 0, status: 'active', supersedes: null,
    time: { valid_from: null, valid_to: null, written_at: null, invalidated_at: null },
    written_by: { kind: 'member', id: '' }, references: [], trust: 'untrusted',
  });
  const startDraft = (r: MemoryRecord) => { setDraft(r); setSel(''); setPop(''); setFilter(''); setLabel(''); setQ(''); setTreeOpen(false); };
  const typedKinds = schemaGuides(provider) ? schema?.types || [] : [];
  const coreKinds = coreKindsToWrite(provider);
  const newMenu = (
    <div className="mm-pop mm-pop-new" role="menu">
      <div className="mm-pop-h">{`New record${folderSel ? ` in ${folderSel.split('/').pop()}` : ''}`}</div>
      {typedKinds.map((t) => (
        <button key={t.id} type="button" className="mm-mi row" role="menuitem" onClick={() => startDraft(blank(recordTypeOfSchemaKind(provider), { entity_type: t.name }))}>
          <Dot color={t.color} icon={t.icon} />{typeLabel(t.name)}
        </button>
      ))}
      {coreKinds.map((k) => {
        const c = kindInfo(k, null);
        return <button key={k} type="button" className="mm-mi row" role="menuitem" onClick={() => startDraft(blank(k, {}))}><Dot color={c.color} icon={c.icon} />{c.one}</button>;
      })}
      {folders ? (
        <>
          <div className="mm-pop-sep" />
          <button type="button" className="mm-mi row" role="menuitem" onClick={() => { setPop(''); setNewFolder(true); }}><span className="mm-dot plain">{FOLDER}</span>Folder</button>
        </>
      ) : null}
    </div>
  );
  const addFolder = (v: string) => {
    setNewFolder(false);
    const name = folderName(v.trim());
    if (!name) return;
    const path = folderSel ? `${folderSel}/${name}` : name;
    setMade((m) => (m.includes(path) ? m : [...m, path]));
    setFolderSel(path);
  };

  // ── filter ────────────────────────────────────────────────────────────────────────────────
  const kindsHere = useMemo(() => groupsOf(all, kinds).map((g) => g.kind), [all, kinds]);
  const labelsHere = useMemo(() => {
    const seen = new Set<string>(schema?.types.map((t) => t.name) || []);
    all.forEach((r) => labelsOf(r).forEach((l) => seen.add(l)));
    return [...seen].sort();
  }, [all, schema]);
  const filterKinds = labelled ? [] : kindsHere;
  const canFilter = labelled ? labelsHere.length > 0 : kindsHere.length > 1;
  const chip = label ? { name: typeLabel(label), color: schema?.types.find((t) => t.name === label)?.color || '#64748b' }
    : filter ? { name: kindInfo(filter, kinds).one, color: kindInfo(filter, kinds).color } : null;

  const recordRows = read.failed ? (
    <p className="mm-muted mm-tree-none" role="alert">The records could not be read just now. <button type="button" className="link-q inl" onClick={read.retry}>Try again</button></p>
  ) : !read.records ? <p className="mm-muted mm-tree-none">Loading…</p> : (
    <>
      {draft ? (
        <button type="button" className="mm-tr mm-trr on" style={{ '--d': 0 } as React.CSSProperties} aria-current="true"><span className="mm-car" /><span className="mm-tt">Untitled</span></button>
      ) : null}
      {folders && tree ? folderRows(tree, 0) : groups.map((g) => {
        const isOpen = !!needle || !closed[g.kind.key];
        return (
          <div key={g.kind.key}>
            <button type="button" className="mm-tr mm-tf" style={{ '--d': 0 } as React.CSSProperties} aria-expanded={isOpen} onClick={() => setClosed((c) => ({ ...c, [g.kind.key]: isOpen }))}>
              <span className="mm-car">{isOpen ? '▾' : '▸'}</span><span className="mm-ti" style={{ color: g.kind.color }}><MmIco k={g.kind.icon} size={14} /></span><span className="mm-tt">{g.kind.many}</span><small>{g.records.length}</small>
            </button>
            {isOpen ? g.records.map((r) => row(r, 1)) : null}
          </div>
        );
      })}
      {!shown.length && !draft && !(folders && tree?.folders.length) ? <p className="mm-muted mm-tree-none">{needle || filter || label ? 'Nothing matches.' : 'No records yet.'}</p> : null}
      {read.more ? <button type="button" className="link-q mm-more" onClick={read.more}>Show more</button> : null}
    </>
  );

  return (
    <div className={`mm-data${treeOpen ? ' tree-open' : ''}${connOpen ? ' conn-open' : ''}${hideConn ? ' no-conn' : ''}`}>
      <aside className="mm-tree" aria-label="Records">
        <div className="mm-tree-top">
          <label className="mm-find">{SEARCH}<input value={q} placeholder={`Find in ${memory.name}`} aria-label={`Find in ${memory.name}`} autoComplete="off" onChange={(e) => setQ(e.target.value)} /></label>
          {canFilter ? (
            <span className="mm-newwrap" ref={filterWrap}>
              <button type="button" className="icon-btn sm mm-plus" aria-label={labelled ? 'Filter by label' : 'Filter by type'} title={labelled ? 'Filter by label' : 'Filter by type'} aria-haspopup="menu" aria-expanded={pop === 'filter'} onClick={() => setPop(pop === 'filter' ? '' : 'filter')}>{FILTER}</button>
              {pop === 'filter' ? (
                <div className="mm-pop" role="menu">
                  <div className="mm-pop-h">{labelled ? 'Label' : 'Type'}</div>
                  {labelled ? labelsHere.map((l) => (
                    <button key={l} type="button" className={`mm-mi row${label === l ? ' on' : ''}`} role="menuitem" onClick={() => { setLabel(l); setPop(''); }}>{typeLabel(l)}</button>
                  )) : filterKinds.map((k) => (
                    <button key={k.key} type="button" className={`mm-mi row${filter === k.key ? ' on' : ''}`} role="menuitem" onClick={() => { setFilter(k.key); setPop(''); }}><Dot color={k.color} icon={k.icon} />{k.one}</button>
                  ))}
                </div>
              ) : null}
            </span>
          ) : null}
          {write ? (
            <span className="mm-newwrap" ref={newWrap}>
              <button type="button" className="icon-btn sm mm-plus" aria-label="New" title={folders ? 'New record or folder' : 'New record'} aria-haspopup="menu" aria-expanded={pop === 'new'} onClick={() => setPop(pop === 'new' ? '' : 'new')}>{PLUS}</button>
              {pop === 'new' ? newMenu : null}
            </span>
          ) : null}
        </div>
        {chip ? (
          <div className="mm-filt"><span className="mm-chip"><span className="mm-dot sm" style={{ background: chip.color }} />{chip.name}
            <button type="button" aria-label={labelled ? 'Show every label' : 'Show every type'} onClick={() => { setFilter(''); setLabel(''); }}>{X}</button></span></div>
        ) : null}
        {newFolder ? (
          <div className="mm-tr mm-tf-new">{FOLDER}
            <input className="set-in slim" autoFocus placeholder="Folder name" aria-label="Folder name"
              onKeyDown={(e) => { if (e.key === 'Enter') addFolder(e.currentTarget.value); if (e.key === 'Escape') setNewFolder(false); }}
              onBlur={(e) => addFolder(e.currentTarget.value)} />
          </div>
        ) : null}
        <div className="mm-tree-list">{recordRows}</div>
        {folders && made.some((m) => !all.some((r) => folderOf(r) === m)) ? <p className="set-help mm-tree-note">A folder is kept once a record is in it.</p> : null}
      </aside>
      <div className="mm-scrim" onClick={() => { setTreeOpen(false); setConnOpen(false); }} />
      <main className="mm-doc">
        {record ? (
          <RecordDoc key={record.id || 'draft'} memory={memory} provider={provider} record={record} schema={kinds} setups={setups} links={linkCount} folders={everyFolder}
            onSaved={(r) => { read.put(r); if (draft) { setDraft(null); setSel(r.id); onChanged(); } }}
            onGone={(id) => { read.drop(id); setLabelHits((h) => h?.filter((x) => x.id !== id) || null); setSel(''); onChanged(); }}
            onTree={() => { setTreeOpen(true); setConnOpen(false); }} onConn={() => { setConnOpen(true); setTreeOpen(false); }} connShown={!hideConn} />
        ) : (
          <>
            <div className="mm-doc-bar"><button type="button" className="btn small line mm-dtog" onClick={() => setTreeOpen(true)}>Records</button><span className="grow" /></div>
            {read.records ? (
              <div className="mm-doc-empty">
                <h2>{all.length ? 'Pick a record' : 'Nothing kept yet'}</h2>
                <p>{all.length ? 'Choose one on the left to read it.' : `Add the first record, or give ${memory.name} to a setup and let it write.`}</p>
                {!all.length && write ? <button type="button" className="btn primary small" onClick={() => { setTreeOpen(true); setPop('new'); }}>{PLUS}New record</button> : null}
                {!all.length && schemaGuides(provider) && !schema?.types.length ? <p className="set-help mm-doc-alt"><button type="button" className="link-q inl" onClick={onSchema}>Design the schema</button></p> : null}
              </div>
            ) : null}
          </>
        )}
      </main>
      {hideConn ? null : (
        <aside className="mm-conn" aria-label="Connections">
          <Connections record={record} graph={graph} failed={graphFailed} retry={readGraph} hops={hops} setHops={setHops} schema={kinds} options={options} candidates={candidates} provider={provider}
            onOpen={(id, mid) => { if (mid && mid !== memory.id) onOtherMemory(mid, id); else { openRecord(id); setConnOpen(false); } }}
            onLink={link} onUnlink={unlink} canUnlink={canUnlink} onClose={() => setConnOpen(false)} />
        </aside>
      )}
    </div>
  );
}
