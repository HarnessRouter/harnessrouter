'use client';
// A memory's data, in three columns you can drag: everything it holds on the left, the open record in the middle as
// a document people edit together, and the graph of what connects to what on the right. Under 900 px they become tabs.
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  bodyOf, getRecord, graphAround, reviseRecord,
  type GraphEdge, type Memory, type MemoryGraph, type MemoryRecord, type Provider,
} from '@/lib/memories';
import { plain } from '../setup/settingsModel';
import { toast } from '../toast';
import { canEdit, connectionsHidden, hasFolders, hasRelations, hasSchema, keepsLinks, kindOf, schemaGuides } from './caps';
import { Connections, type LinkOption } from './Connections';
import { PLUS } from './parts';
import { ResizableColumns } from './ResizableColumns';
import { typeLabel, type LSchema } from './schemaModel';
import { allFolders, folderTree } from './tree';
import { MemoryTree } from './tree/MemoryTree';
import { recordOfKind } from './tree/treeModel';

// Client only: the live document's library is the server's too, and a second copy of it in the same process warns and misbehaves.
const RecordDoc = dynamic(() => import('./RecordDoc').then((m) => m.RecordDoc), { ssr: false });
const MemoryGraphView = dynamic(() => import('./graph/MemoryGraph').then((m) => m.MemoryGraph), { ssr: false, loading: () => <p className="mm-muted mm-cpad">Drawing the graph…</p> });

export interface RecordsRead {
  records: MemoryRecord[] | null; failed: boolean; retry: () => void; more: (() => void) | null;
  put: (r: MemoryRecord) => void; drop: (id: string) => void;
}
export { labelFilter } from './tree/treeModel';

export function DataTab({ memory, provider, schema, read, setups, typeFilter, initialRecord, onOpenRecord, onSchema, onOtherMemory, onChanged, liveTick, pulse }: {
  memory: Memory; provider: Provider | null; schema: LSchema | null; read: RecordsRead; setups: Map<string, string> | null;
  typeFilter: string; initialRecord: string; onOpenRecord: (id: string) => void; onSchema: () => void;
  onOtherMemory: (memoryId: string, recordId: string) => void; onChanged: () => void; liveTick: number; pulse: string[];
}) {
  const write = !!memory.privileges?.includes('write');
  // a record's kind comes from a schema of types; labels are a vocabulary on facts, not kinds of record
  const kinds = schemaGuides(provider) ? schema : null;
  const [sel, setSel] = useState(initialRecord);
  const [draft, setDraft] = useState<MemoryRecord | null>(null);
  const [outside, setOutside] = useState<MemoryRecord | null>(null);    // open, but not in the list: forgotten, or past a page
  const [tab, setTab] = useState('doc');
  useEffect(() => { onOpenRecord(sel); }, [sel, onOpenRecord]);

  const all = useMemo(() => read.records || [], [read.records]);
  // the first record with something in it opens by itself; a person's own choice is never replaced
  useEffect(() => {
    if (sel || draft || !read.records?.length) return;
    const first = [...read.records].sort((a, b) => Number(a.type === 'episode') - Number(b.type === 'episode') || bodyOf(b).length - bodyOf(a).length)[0];
    if (first) setSel(first.id);
  }, [read.records, sel, draft]);

  const listed = all.find((r) => r.id === sel) || null;
  useEffect(() => {
    if (!sel || listed || !read.records) { setOutside(null); return undefined; }
    let live = true;
    getRecord(memory.id, sel).then((r) => { if (live) setOutside(r); }).catch(() => { if (live) setOutside(null); });
    return () => { live = false; };
  }, [sel, listed, read.records, memory.id]);
  const record = draft || listed || outside;

  const open = useCallback((rid: string, mid?: string) => {
    if (mid && mid !== memory.id) { onOtherMemory(mid, rid); return; }
    setDraft(null); setSel(rid); setTab('doc');
  }, [memory.id, onOtherMemory]);

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
    graphAround(memory.id, rid, 1)
      .then((g) => { if (live) setGraph(g); })
      .catch(() => { if (live) { setGraph(null); setGraphFailed(true); } });
    return () => { live = false; };
  }, [rid, links, memory.id]);
  useEffect(() => readGraph(), [readGraph, version, liveTick]);

  const edges = useMemo(() => (graph?.edges || []).filter((e) => e.from.record_id === rid || e.to.record_id === rid), [graph, rid]);
  const linkCount = links ? edges.length : (record?.references?.length || 0);

  const options = useMemo<LinkOption[] | null>(() => {
    if (!record || !record.id || !links || !canEdit(record, provider, memory)) return null;
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
    setSel(''); setTab('doc');
  }, [memory.id, provider, schema]);
  const everyFolder = useMemo(() => (hasFolders(provider) ? allFolders(folderTree(all, [])) : []), [provider, all]);

  const tree = <MemoryTree memory={memory} provider={provider} schema={kinds} read={read} activeId={record?.id || ''} pulse={pulse} filterKind={typeFilter} onOpen={open} onNew={startNew} onChanged={onChanged} />;
  const doc = (
    <main className="mm-doc">
      {record ? (
        <RecordDoc key={record.id || 'draft'} memory={memory} provider={provider} record={record} schema={kinds} setups={setups} links={linkCount} folders={everyFolder}
          onSaved={(r) => { read.put(r); if (draft) { setDraft(null); setSel(r.id); onChanged(); } }}
          onGone={(id) => { read.drop(id); setSel(''); onChanged(); }} />
      ) : (
        <>
          <div className="mm-doc-bar"><span className="grow" /></div>
          {read.records ? (
            <div className="mm-doc-empty">
              <h2>{all.length ? 'Pick a record' : 'Nothing kept yet'}</h2>
              <p>{all.length ? 'Choose one from the list or the graph to read it.' : `Add the first record, or give ${memory.name} to a setup and let it write.`}</p>
              {!all.length && write ? <button type="button" className="btn primary small" onClick={() => startNew(kinds?.types[0]?.name || 'note')}>{PLUS}New record</button> : null}
              {!all.length && schemaGuides(provider) && !schema?.types.length ? <p className="set-help mm-doc-alt"><button type="button" className="link-q inl" onClick={onSchema}>Set what it should look for first</button></p> : null}
            </div>
          ) : null}
        </>
      )}
    </main>
  );
  const right = (
    <aside className="mm-conn" aria-label="Graph">
      <div className="mm-graphbox">
        <MemoryGraphView memory={memory} provider={provider} schema={kinds} activeRecordId={rid} refreshKey={liveTick} changed={pulse} onOpenRecord={open} />
      </div>
      {hideLinks || !record?.id ? null : (
        <div className="mm-linksbox">
          <Connections record={record} graph={graph} failed={graphFailed} retry={readGraph} schema={kinds} options={options} candidates={candidates} provider={provider}
            onOpen={open} onLink={link} onUnlink={unlink} canUnlink={canUnlink} />
        </div>
      )}
    </aside>
  );
  return (
    <div className="mm-data">
      <ResizableColumns storageKey="hr.memory.columns" tab={tab} onTab={setTab} panes={[
        { id: 'tree', label: 'Records', min: 220, initial: 280, node: tree },
        { id: 'doc', label: 'Record', min: 380, initial: 640, grow: true, node: doc },
        { id: 'graph', label: 'Graph', min: 280, initial: 440, node: right },
      ]} />
    </div>
  );
}
