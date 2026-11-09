'use client';
// The left column of a memory: everything it holds, as a tree. Sub memories are folders that read
// themselves when opened; where the provider keeps files its real folders follow, and elsewhere one
// group per kind of record. A row acts when pressed, a chevron only folds, and hovering a row brings out
// its actions. Whatever a row offers comes from the provider's capability document and from what this
// person may do on that memory, so nothing here would be refused. Searching keeps the way to a match
// open and reads whatever it has to first. A search asks the engine too, by meaning (recall), where it
// answers that way: what it finds is listed with what matches the words, so "how does Dana like help"
// finds "prefers written steps". A memory kept for one person is listed by that person's name.
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';
import { ChevronDown, ChevronRight, Eye, FilePlus2, FolderPlus, History, Link2, Lock, Pencil, SquareArrowOutUpRight, Trash2 } from 'lucide-react';
import { deleteMemory, forgetRecord, labelOf, recall, recordHref, type Memory, type MemoryRecord, type Provider } from '@/lib/memories';
import { ConfirmSheet } from '../../Sheet';
import { plain } from '../../setup/settingsModel';
import { toast } from '../../toast';
import { canForget, hasFolders, hasHistory, kindOf, labelsOf, schemaGuides, schemaLabels, servesForget, standingOf, NOTED } from '../caps';
import type { RecordsRead } from '../DataTab';
import { Dot, DOTS, FILTER, FOLDER, FOLDER_OPEN, MmIco, PLUS, SEARCH, shownName, userOf, X } from '../parts';
import { typeLabel, type LSchema } from '../schemaModel';
import { RenameSheet } from '../sheets';
import { folderName, folderOf, groupsOf, kindInfo, type Kind } from '../tree';
import {
  buildRows, folderKey, groupKey, hitRecord, isExpandable, isOpenRow, kindsToWrite, labelFilter, meaningHits, memoryKey, rankOf, recordOfKind, treeKey,
  type BranchView, type Row,
} from './treeModel';
import { NewRecordSheet, NewSubMemorySheet } from './TreeSheets';
import { SEARCH_CAP, useBranches } from './useBranches';
import '../memories.css';
import './tree.css';

export interface MemoryTreeProps {
  memory: Memory; provider: Provider | null; schema: LSchema | null; read: RecordsRead;
  activeId: string; pulse?: string[];
  /** A type to start filtered to, chosen somewhere else on the page. */
  filterKind?: string;
  /** `record`: the list's own copy of it, drawn at once while the record itself is read */
  onOpen: (recordId: string, memoryId?: string, record?: MemoryRecord) => void;
  /** A new record of this memory, as a draft: `type` is a kind, a schema's type name or a kind every
   *  memory has (recordOfKind in ./treeModel turns it into what the service takes); `folder` is where it goes. */
  onNew: (type: string, folder?: string) => void;
  onChanged: () => void;
}

interface MenuItem { key: string; label?: string; icon?: ReactNode; bad?: boolean; on?: boolean; head?: boolean; sep?: boolean; run?: () => void }
type SheetState =
  | { t: 'forget'; r: MemoryRecord; mid: string }
  | { t: 'delete'; m: Memory; parent: string }
  | { t: 'rename'; m: Memory; parent: string }
  | { t: 'newsub'; parent: Memory }
  | { t: 'newrec'; m: Memory; label: string; type: string; attributes: Record<string, unknown> };

const IC = 13;
const FRESH_MS = 700;
/** A standing instruction says so on its row; one an agent set, that agents get only as a note, says that. */
function standTag(r: MemoryRecord): ReactNode {
  const st = standingOf(r);
  if (st === 'person') return <small className="mt-mark mt-stand">Standing</small>;
  return st ? <small className="mt-mark mt-noted">{NOTED[st].tag}</small> : null;
}
const short = (r: MemoryRecord) => { const l = labelOf(r) || 'this record'; return l.length > 60 ? `${l.slice(0, 59).trim()}…` : l; };
const storeKey = (id: string) => `hr.memories.tree.${id}`;
const readStore = (id: string): Record<string, boolean> => {
  try { return JSON.parse(window.localStorage.getItem(storeKey(id)) || '{}') as Record<string, boolean>; } catch { return {}; }
};
const parentIdOf = (rowParent: string, root: string) => (rowParent.startsWith('m:') ? rowParent.slice(2) : root);

function withExtras(base: MemoryRecord[] | null, ...extras: MemoryRecord[][]): MemoryRecord[] | null {
  if (!base) return null;
  const ids = new Set(base.map((r) => r.id));
  const more: MemoryRecord[] = [];
  extras.forEach((l) => l.forEach((r) => { if (!ids.has(r.id)) { ids.add(r.id); more.push(r); } }));
  return more.length ? [...base, ...more] : base;
}

export function MemoryTree({ memory, provider, schema, read, activeId, pulse, filterKind, onOpen, onNew, onChanged }: MemoryTreeProps) {
  const labelled = schemaLabels(provider);
  const rootKinds = schemaGuides(provider) ? schema : null;
  const b = useBranches(memory, provider);
  const { branches, ensure, loadBelow, patch, refresh, showGone: askGone, setTruncated } = b;

  const [q, setQ] = useState('');
  const [kindFilter, setKindFilter] = useState(filterKind || '');
  useEffect(() => { setKindFilter(filterKind || ''); }, [filterKind]);
  const [label, setLabel] = useState('');
  const [labelHits, setLabelHits] = useState<MemoryRecord[]>([]);
  // what the engine found by meaning for the words in the search (records of this memory and those below it), the
  // matches only, in its order; and whether it is still being asked
  const [meant, setMeant] = useState<MemoryRecord[]>([]);
  const [asking, setAsking] = useState(false);
  const [gone, setGone] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>(() => (typeof window === 'undefined' ? {} : readStore(memory.id)));
  const [allShown, setAllShown] = useState<Record<string, boolean>>({});
  const [made, setMade] = useState<Record<string, string[]>>({});
  const [folderSel, setFolderSel] = useState('');
  const [newFolder, setNewFolder] = useState<{ mid: string; base: string } | null>(null);
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const [sheet, setSheet] = useState<SheetState | null>(null);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState('');
  const [focusKey, setFocusKey] = useState('');
  const [fresh, setFresh] = useState<Record<string, boolean>>({});
  const listRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const wantFocus = useRef(false);

  useEffect(() => { setOpen(readStore(memory.id)); setFolderSel(''); }, [memory.id]);
  useEffect(() => {
    try { window.localStorage.setItem(storeKey(memory.id), JSON.stringify(open)); } catch { /* private window */ }
  }, [open, memory.id]);

  const needle = q.trim().toLowerCase();
  const filtering = !!needle || !!kindFilter || !!label;

  // ── what is in each memory ────────────────────────────────────────────────────────────────
  const hitsOf = useCallback((mid: string) => [
    ...(label ? labelHits : []), ...(needle && !label ? meant : []),
  ].filter((r) => (r.memory_id || memory.id) === mid), [label, labelHits, needle, meant, memory.id]);
  const meantIds = useMemo(() => new Set(needle && !label ? meant.map((r) => r.id) : []), [needle, label, meant]);
  const goneOf = useCallback((mid: string) => (gone ? branches[mid]?.gone || [] : []), [gone, branches]);
  const rootRecords = useMemo(() => withExtras(read.records, hitsOf(memory.id), goneOf(memory.id)), [read.records, hitsOf, goneOf, memory.id]);
  const view = useCallback((id: string): BranchView | null => {
    const x = branches[id];
    if (id === memory.id) {
      return {
        memory, kinds: rootKinds, folders: hasFolders(provider), records: rootRecords, failed: read.failed, hasMore: !!read.more,
        children: x?.children ?? (memory.children?.count ? null : []), childrenFailed: !!x?.childrenFailed, made: made[id] || [],
      };
    }
    if (!x?.memory) return null;
    return {
      memory: x.memory, kinds: x.kinds, folders: hasFolders(x.provider), records: withExtras(x.records, hitsOf(id), goneOf(id)), failed: x.failed, hasMore: !!x.next,
      children: x.children, childrenFailed: x.childrenFailed, made: made[id] || [],
    };
  }, [branches, memory, rootKinds, provider, rootRecords, read.failed, read.more, made, hitsOf, goneOf]);

  const match = useCallback((r: MemoryRecord) => (label
    ? labelsOf(r).includes(label) && hitRecord(r, needle)
    : (hitRecord(r, needle) || meantIds.has(r.id)) && (!kindFilter || kindOf(r) === kindFilter)), [label, needle, kindFilter, meantIds]);
  const isOpen = useCallback((key: string, otherwise: boolean) => (key in open ? open[key] : otherwise), [open]);
  const showAll = useCallback((key: string) => !!allShown[key], [allShown]);
  // a search by words lists what it found best first (the engine's order), not by name
  const order = useMemo(() => (needle && !label ? rankOf(meant) : undefined), [needle, label, meant]);
  const rows = useMemo(() => buildRows({ rootId: memory.id, view, match, needle, filtering, isOpen, showAll, activeId, order }),
    [memory.id, view, match, needle, filtering, isOpen, showAll, activeId, order]);
  const matches = useMemo(() => {
    if (!filtering) return 0;
    let n = (rootRecords || []).filter(match).length;
    Object.keys(branches).forEach((id) => { if (id !== memory.id) n += (view(id)?.records || []).filter(match).length; });
    return n;
  }, [filtering, rootRecords, match, branches, view, memory.id]);

  // a sub memory that stands open has to have been read, whichever way it came to stand open
  useEffect(() => { rows.forEach((r) => { if (r.kind === 'memory' && r.open && !filtering) void ensure(r.memory); }); }, [rows, filtering, ensure]);

  // ── a search reads what it has to ─────────────────────────────────────────────────────────
  useEffect(() => { if (filtering) void loadBelow(); }, [filtering, loadBelow]);
  const asked = useRef(-1);
  const readOn = useCallback(() => {
    const have = read.records?.length || 0;
    if (!read.more || asked.current === have) return;
    if (have >= SEARCH_CAP) { setTruncated(true); return; }
    asked.current = have;
    read.more();
  }, [read, setTruncated]);
  useEffect(() => { if (filtering) readOn(); }, [filtering, readOn, read.records?.length]);
  // a label is what the service finds, so the rows that carry it can be ones not read yet
  useEffect(() => {
    setLabelHits([]);
    if (!label) return undefined;
    let live = true;
    const words = q.trim();
    const signals = provider?.recall?.signals || [];
    const say = words ? (signals.includes('query') ? { query: words } : signals.includes('text') ? { text: words } : {}) : {};
    const t = setTimeout(() => {
      recall(memory.id, { filters: labelFilter(label), limit: 100, ...say })
        .then((d) => { if (live) setLabelHits(d.results.map((x) => x.record)); })
        .catch(() => { if (live) setLabelHits([]); });
    }, words ? 300 : 0);
    return () => { live = false; clearTimeout(t); };
  }, [label, q, memory.id, provider]);

  // words in the search are asked of the engine too, by meaning where it recalls that way, else by its own text search;
  // what it found that matches comes in its order (meaningHits: an engine that ranks everything it holds for any words
  // is read for what stands out)
  useEffect(() => {
    setMeant([]);
    const words = q.trim();
    const signals = provider?.recall?.signals || [];
    if (!words || label || !(signals.includes('query') || signals.includes('text'))) { setAsking(false); return undefined; }
    let live = true;
    setAsking(true);
    const t = setTimeout(() => {
      recall(memory.id, { ...(signals.includes('query') ? { query: words } : { text: words }), limit: 50 })
        .then((d) => { if (live) setMeant(meaningHits(d.results || [])); })
        .catch(() => { if (live) setMeant([]); })
        .finally(() => { if (live) setAsking(false); });
    }, 300);
    return () => { live = false; clearTimeout(t); };
  }, [q, label, memory.id, provider]);

  // ── the open record, when it was opened from elsewhere ────────────────────────────────────
  const found = useMemo(() => {
    if (!activeId) return null;
    const here = (rootRecords || []).find((r) => r.id === activeId);
    if (here) return { mid: memory.id, r: here };
    for (const id of Object.keys(branches)) {
      const r = branches[id].records?.find((x) => x.id === activeId) || branches[id].gone.find((x) => x.id === activeId);
      if (r) return { mid: id, r };
    }
    return null;
  }, [activeId, rootRecords, branches, memory.id]);
  useEffect(() => {
    if (!activeId || found || !read.records) return;
    if (read.more) readOn(); else void loadBelow();
  }, [activeId, found, read.records, read.more, readOn, loadBelow]);
  const expanded = useRef('');
  useEffect(() => {
    if (!activeId) { expanded.current = ''; return; }
    if (!found || expanded.current === activeId) return;
    expanded.current = activeId;
    const add: Record<string, boolean> = {};
    const v = view(found.mid);
    if (v?.folders) {
      let path = '';
      folderOf(found.r).split('/').filter(Boolean).forEach((p) => { path = path ? `${path}/${p}` : p; add[folderKey(found.mid, path)] = true; });
    } else add[groupKey(found.mid, kindOf(found.r))] = true;
    let m = found.mid;
    const seen = new Set<string>();
    while (m !== memory.id && !seen.has(m)) {
      seen.add(m);
      add[memoryKey(m)] = true;
      m = branches[m]?.memory?.parent_id || memory.id;
    }
    setOpen((o) => ({ ...o, ...add }));
  }, [activeId, found, view, branches, memory.id]);
  const activeRow = rows.find((r) => r.kind === 'record' && r.record.id === activeId);
  const activeKey = activeRow?.key || '';
  const scrolled = useRef('');
  useEffect(() => {
    if (!activeKey) { if (!activeId) scrolled.current = ''; return; }
    if (scrolled.current === activeKey) return;
    scrolled.current = activeKey;
    setFocusKey(activeKey);
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: 'nearest' });
  }, [activeKey, activeId]);

  // ── what just changed live ────────────────────────────────────────────────────────────────
  const pulseSet = useMemo(() => new Set(pulse || []), [pulse]);
  const pulseSeen = useRef('');
  useEffect(() => {
    const said = (pulse || []).join(',');
    if (!said || said === pulseSeen.current) return;
    pulseSeen.current = said;
    const rootHas = new Set((read.records || []).map((r) => r.id));
    if ((pulse || []).every((id) => rootHas.has(id))) return;
    refresh(rows.flatMap((r) => (r.kind === 'memory' && r.open ? [r.memory.id] : [])));
  }, [pulse, read.records, rows, refresh]);
  const known = useRef(new Map<string, Set<string>>());
  useEffect(() => {
    const came: string[] = [];
    const note = (mid: string, recs: MemoryRecord[] | null) => {
      if (!recs) return;
      const set = known.current.get(mid);
      if (!set) { known.current.set(mid, new Set(recs.map((r) => r.id))); return; }
      recs.forEach((r) => { if (!set.has(r.id)) { set.add(r.id); came.push(r.id); } });
    };
    note(memory.id, read.records);
    Object.keys(branches).forEach((id) => { if (id !== memory.id) note(id, branches[id].records); });
    if (!came.length) return undefined;
    setFresh((f) => ({ ...f, ...Object.fromEntries(came.map((id) => [id, true])) }));
    const t = setTimeout(() => setFresh((f) => { const n = { ...f }; came.forEach((id) => { delete n[id]; }); return n; }), FRESH_MS);
    return () => clearTimeout(t);
  }, [read.records, branches, memory.id]);

  // ── what a row does ───────────────────────────────────────────────────────────────────────
  const openRecordRow = useCallback((r: Row) => { if (r.kind === 'record') onOpen(r.record.id, r.memoryId === memory.id ? undefined : r.memoryId, r.record); }, [onOpen, memory.id]);
  const toggle = (r: Row, to?: boolean) => {
    if (filtering || !isExpandable(r)) return;
    setOpen((o) => ({ ...o, [r.key]: to ?? !isOpenRow(r) }));
  };
  const pageMore = (mid: string) => {
    if (mid === memory.id) { read.more?.(); return; }
    b.more(mid).catch(() => toast('More records could not be read just now.'));
  };
  const act = (r: Row) => {
    setFocusKey(r.key);
    if (r.kind === 'record') openRecordRow(r);
    else if (r.kind === 'more') { if (r.action === 'all') setAllShown((a) => ({ ...a, [r.scope]: true })); else pageMore(r.scope); }
    else {
      if (r.kind === 'folder') setFolderSel(r.memoryId === memory.id ? r.path : '');
      toggle(r);
    }
  };
  const providerOfMemory = (mid: string): Provider | null => {
    if (mid === memory.id) return provider;
    return branches[mid]?.provider ?? (branches[mid]?.memory?.provider === provider?.id ? provider : null);
  };
  const memoryOf = (mid: string): Memory | null => (mid === memory.id ? memory : branches[mid]?.memory || null);
  const newOf = (mid: string, k: Kind, folder?: string) => {
    setMenu(null);
    if (mid === memory.id) { onNew(k.key, folder); return; }
    const m = memoryOf(mid);
    if (!m) return;
    const made2 = recordOfKind(k.key, providerOfMemory(mid), view(mid)?.kinds || null);
    setSheet({ t: 'newrec', m, label: k.one, type: made2.type, attributes: { ...made2.attributes, ...(folder ? { folder } : {}) } });
  };
  const kindItems = (mid: string, folder?: string): MenuItem[] => {
    const m = memoryOf(mid);
    if (!m?.privileges?.includes('write')) return [];
    return kindsToWrite(providerOfMemory(mid), view(mid)?.kinds || null).map((k) => ({
      key: `new:${k.key}`, label: `New ${k.one}`, icon: <Dot color={k.color} icon={k.icon} />, run: () => newOf(mid, k, folder),
    }));
  };
  const copyLink = (r: MemoryRecord, mid: string) => {
    setMenu(null);
    // a record below this memory (a person's own) opens on this page, open in its memory
    const url = `${window.location.origin}${recordHref(memory.id, mid, r.id)}`;
    const done = () => toast('Link copied');
    const failed = () => toast('The link could not be copied.');
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(url).then(done, failed); else failed();
  };
  const itemsOfRow = (r: Row): MenuItem[] => {
    if (r.kind === 'record') {
      const m = memoryOf(r.memoryId);
      return [
        { key: 'open', label: 'Open', icon: <SquareArrowOutUpRight size={IC} />, run: () => { setMenu(null); openRecordRow(r); } },
        { key: 'copy', label: 'Copy link', icon: <Link2 size={IC} />, run: () => copyLink(r.record, r.memoryId) },
        ...(canForget(r.record, providerOfMemory(r.memoryId), m) ? [{ key: 'forget', label: 'Forget', icon: <Trash2 size={IC} />, bad: true, run: () => { setMenu(null); setRefused(''); setSheet({ t: 'forget', r: r.record, mid: r.memoryId }); } }] : []),
      ];
    }
    if (r.kind === 'group') {
      const k = kindItems(r.memoryId).find((i) => i.key === `new:${r.group.key}`);
      return k ? [k] : [];
    }
    if (r.kind === 'folder') {
      const kinds = kindItems(r.memoryId, r.path);
      return kinds.length ? [...kinds, { key: 'sep', sep: true }, {
        key: 'folder', label: 'New folder', icon: <FolderPlus size={IC} />, run: () => { setMenu(null); setNewFolder({ mid: r.memoryId, base: r.path }); },
      }] : [];
    }
    if (r.kind === 'memory') {
      const m = r.memory, can = (x: 'write' | 'create' | 'delete') => !!m.privileges?.includes(x);
      const parent = parentIdOf(r.parent, memory.id);
      const items: MenuItem[] = [...kindItems(m.id)];
      if (can('create')) items.push({ key: 'sub', label: 'New sub memory', icon: <FolderPlus size={IC} />, run: () => { setMenu(null); setSheet({ t: 'newsub', parent: m }); } });
      if (items.length && (can('write') || can('delete'))) items.push({ key: 'sep', sep: true });
      if (can('write')) items.push({ key: 'rename', label: 'Rename', icon: <Pencil size={IC} />, run: () => { setMenu(null); setSheet({ t: 'rename', m, parent }); } });
      if (can('delete')) items.push({ key: 'delete', label: 'Delete', icon: <Trash2 size={IC} />, bad: true, run: () => { setMenu(null); setRefused(''); setSheet({ t: 'delete', m, parent }); } });
      return items;
    }
    return [];
  };

  // ── the header's two menus ────────────────────────────────────────────────────────────────
  const write = !!memory.privileges?.includes('write');
  const create = !!memory.privileges?.includes('create');
  const folders = hasFolders(provider);
  const newItems: MenuItem[] = [
    ...(write ? [{ key: 'h', head: true, label: `New record${folderSel ? ` in ${folderSel.split('/').pop()}` : ''}` }] : []),
    ...(write ? kindItems(memory.id, folderSel || undefined) : []),
    ...((write && folders) || create ? [{ key: 'sep', sep: true }] : []),
    ...(write && folders ? [{ key: 'folder', label: 'Folder', icon: <span className="mm-dot plain">{FOLDER}</span>, run: () => { setMenu(null); setNewFolder({ mid: memory.id, base: folderSel }); } }] : []),
    ...(create ? [{ key: 'sub', label: 'Sub memory', icon: <span className="mm-dot plain"><FolderPlus size={12} /></span>, run: () => { setMenu(null); setSheet({ t: 'newsub', parent: memory }); } }] : []),
  ];
  const allLoaded = useMemo(() => [...(read.records || []), ...Object.keys(branches).flatMap((id) => (id === memory.id ? [] : branches[id].records || []))], [read.records, branches, memory.id]);
  const kindsHere = useMemo(() => {
    const byKey = new Map<string, Kind>();
    groupsOf(read.records || [], rootKinds).forEach((g) => byKey.set(g.kind.key, g.kind));
    Object.keys(branches).forEach((id) => { if (id !== memory.id) groupsOf(branches[id].records || [], branches[id].kinds).forEach((g) => { if (!byKey.has(g.kind.key)) byKey.set(g.kind.key, g.kind); }); });
    return [...byKey.values()];
  }, [read.records, rootKinds, branches, memory.id]);
  const labelsHere = useMemo(() => {
    const seen = new Set<string>(schema?.types.map((t) => t.name) || []);
    allLoaded.forEach((r) => labelsOf(r).forEach((l) => seen.add(l)));
    return [...seen].sort();
  }, [allLoaded, schema]);
  const canFilter = labelled ? labelsHere.length > 0 : kindsHere.length > 1;
  const canShowGone = hasHistory(provider) || servesForget(provider);
  const filterItems: MenuItem[] = [
    ...(canFilter ? [{ key: 'h', head: true, label: labelled ? 'Label' : 'Type' }] : []),
    ...(canFilter && labelled ? labelsHere.map((l) => ({ key: `l:${l}`, label: typeLabel(l), on: label === l, run: () => { setLabel(l); setMenu(null); } })) : []),
    ...(canFilter && !labelled ? kindsHere.map((k) => ({ key: `k:${k.key}`, label: k.one, icon: <Dot color={k.color} icon={k.icon} />, on: kindFilter === k.key, run: () => { setKindFilter(k.key); setMenu(null); } })) : []),
    ...(canFilter && canShowGone ? [{ key: 'sep', sep: true }] : []),
    ...(canShowGone ? [{ key: 'gone', label: gone ? 'Hide forgotten and replaced' : 'Show forgotten and replaced', icon: <History size={IC} />, on: gone, run: () => { const on = !gone; setGone(on); askGone(on); setMenu(null); } }] : []),
  ];
  const chip = label ? { name: typeLabel(label), color: schema?.types.find((t) => t.name === label)?.color || '#64748b' }
    : kindFilter ? { name: kindInfo(kindFilter, rootKinds).one, color: kindInfo(kindFilter, rootKinds).color } : null;

  // ── the menu, wherever it was asked for ───────────────────────────────────────────────────
  const menuItems: MenuItem[] = !menu ? [] : menu.id === 'head:new' ? newItems : menu.id === 'head:filter' ? filterItems
    : (() => { const r = rows.find((x) => x.key === menu.id); return r ? itemsOfRow(r) : []; })();
  const openMenu = (id: string, at: DOMRect | { left: number; right: number; top: number; bottom: number }, count: number) => {
    const w = 220, h = Math.min(count * 34 + 12, window.innerHeight * 0.6);
    const x = Math.max(8, Math.min(at.right - w, window.innerWidth - w - 8));
    const y = at.bottom + 4 + h > window.innerHeight ? Math.max(8, at.top - h - 4) : at.bottom + 4;
    setMenu((cur) => (cur?.id === id ? null : { id, x, y }));
  };
  const openRowMenu = (r: Row, at: DOMRect) => {
    if (r.kind === 'memory') void ensure(r.memory);    // what it offers depends on what it is
    openMenu(r.key, at, Math.max(itemsOfRow(r).length, 3));
  };
  useEffect(() => {
    if (!menu) return undefined;
    const down = (e: MouseEvent) => { const t = e.target as Element; if (!menuRef.current?.contains(t) && !t.closest?.('.mt-opens')) setMenu(null); };
    const key = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // the keys carry on from the row the menu came from
      Array.from(listRef.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') || []).find((x) => x.dataset.key === menu.id)?.focus();
      setMenu(null);
    };
    const scroll = () => setMenu(null);
    const list = listRef.current;
    document.addEventListener('mousedown', down);
    document.addEventListener('keydown', key);
    list?.addEventListener('scroll', scroll);
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key); list?.removeEventListener('scroll', scroll); };
  }, [menu]);
  const menuId = menu?.id || '';
  useEffect(() => { if (menuId) menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus(); }, [menuId]);
  const menuKeys = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const all = Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') || []);
    const at = all.indexOf(document.activeElement as HTMLElement);
    all[(at + (e.key === 'ArrowDown' ? 1 : -1) + all.length) % all.length]?.focus();
  };

  // ── the keys ──────────────────────────────────────────────────────────────────────────────
  const focusable = rows.filter((r) => r.kind !== 'note');
  const focused = focusable.some((r) => r.key === focusKey) ? focusKey : activeKey || focusable[0]?.key || '';
  useEffect(() => {
    if (!wantFocus.current) return;
    wantFocus.current = false;
    const el = Array.from(listRef.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') || []).find((x) => x.dataset.key === focused);
    el?.focus();
    el?.scrollIntoView?.({ block: 'nearest' });
  }, [focused]);
  const onKeys = (e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('input,textarea')) return;
    const me = rows.find((r) => r.key === focused);
    if (me && (e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey))) {
      e.preventDefault();
      const el = Array.from(listRef.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') || []).find((x) => x.dataset.key === focused);
      if (el && itemsOfRow(me).length) openRowMenu(me, el.getBoundingClientRect());
      return;
    }
    const mv = treeKey(rows, focused, e.key);
    if (!mv) return;
    e.preventDefault();
    const at = rows.find((r) => r.key === (mv.open || mv.close || mv.activate));
    if (mv.focus) { wantFocus.current = true; setFocusKey(mv.focus); if (mv.focus === focused) wantFocus.current = false; }
    else if (at && mv.open) toggle(at, true);
    else if (at && mv.close) toggle(at, false);
    else if (at && mv.activate) act(at);
  };

  // ── new folder ────────────────────────────────────────────────────────────────────────────
  const addFolder = (v: string) => {
    const at = newFolder;
    setNewFolder(null);
    const name = folderName(v.trim());
    if (!at || !name) return;
    const path = at.base ? `${at.base}/${name}` : name;
    setMade((m) => ({ ...m, [at.mid]: (m[at.mid] || []).includes(path) ? m[at.mid] : [...(m[at.mid] || []), path] }));
    if (at.base) setOpen((o) => ({ ...o, [folderKey(at.mid, at.base)]: true }));   // it is drawn inside its parent, so that stands open
    if (at.mid === memory.id) setFolderSel(path);
  };
  const madeEmpty = Object.keys(made).some((mid) => (made[mid] || []).some((p) => !(view(mid)?.records || []).some((r) => folderOf(r) === p)));

  // ── what the sheets do ────────────────────────────────────────────────────────────────────
  const closeSheet = () => { setSheet(null); setRefused(''); setBusy(false); };
  const forget = async (r: MemoryRecord, mid: string) => {
    setBusy(true); setRefused('');
    try {
      await forgetRecord(mid, r.id);
      toast(`${short(r)} forgotten`);
      if (mid === memory.id) read.drop(r.id);
      else patch(mid, (c) => ({ records: c.records?.filter((x) => x.id !== r.id) || null }));
      closeSheet();
      onChanged();
    } catch (e) { setRefused(plain(e, 'It was not forgotten. Try again.')); setBusy(false); }
  };
  const removeMemory = async (m: Memory, parent: string) => {
    setBusy(true); setRefused('');
    try {
      await deleteMemory(m.id);
      toast(`${m.name} deleted`);
      patch(parent, (c) => ({ children: c.children?.filter((x) => x.id !== m.id) || null }));
      closeSheet();
      onChanged();
    } catch (e) { setRefused(plain(e, 'The memory was not deleted. Try again.')); setBusy(false); }
  };
  const bump = (id: string, change: (m: Memory) => Memory) => {
    Object.keys(branches).forEach((pid) => {
      if (branches[pid].children?.some((k) => k.id === id)) patch(pid, (c) => ({ children: c.children?.map((k) => (k.id === id ? change(k) : k)) || null }));
    });
    if (branches[id]?.memory) patch(id, (c) => ({ memory: c.memory ? change(c.memory) : c.memory }));
  };

  // ── the rows ──────────────────────────────────────────────────────────────────────────────
  const rowEl = (r: Row) => {
    if (r.kind === 'note') {
      return (
        <div key={r.key} className={`mt-note${r.tone === 'failed' ? ' bad' : ''}`} role={r.tone === 'failed' ? 'alert' : undefined} style={{ '--d': r.depth } as CSSProperties}>
          {r.tone === 'loading' ? <span className="mt-skel" aria-hidden="true" /> : null}
          <span>{r.text}</span>
          {r.retry ? <button type="button" className="link-q inl" onClick={() => { if (r.memoryId === memory.id && r.retry === 'records') read.retry(); else b.retry(r.memoryId, r.retry as 'records' | 'children'); }}>Try again</button> : null}
        </div>
      );
    }
    const on = r.kind === 'record' && r.record.id === activeId;
    const items = r.kind === 'more' ? [] : itemsOfRow(r);
    const expandable = isExpandable(r);
    const isOn = isOpenRow(r);
    const menuOpen = menu?.id === r.key;
    const cls = ['mt-row', `mt-${r.kind}`, on ? 'on' : '', r.kind === 'folder' && r.memoryId === memory.id && folderSel === r.path ? 'sel' : '',
      r.kind === 'record' && pulseSet.has(r.record.id) ? 'mt-pulse' : '', r.kind === 'record' && fresh[r.record.id] ? 'mt-fresh' : '',
      r.kind === 'record' && r.record.status !== 'active' ? 'gone' : ''].filter(Boolean).join(' ');
    let name = '', title = '';
    let icon: ReactNode = null;
    if (r.kind === 'record') { name = labelOf(r.record) || 'Untitled'; title = name; icon = <span className="mt-ic" style={{ color: r.info.color }}><MmIco k={r.info.icon} size={14} /></span>; }
    if (r.kind === 'group') { name = r.group.many; title = name; icon = <span className="mt-ic" style={{ color: r.group.color }}><MmIco k={r.group.icon} size={14} /></span>; }
    if (r.kind === 'folder') { name = r.name; title = r.path; icon = <span className="mt-ic">{isOn ? FOLDER_OPEN : FOLDER}</span>; }
    if (r.kind === 'memory') { name = shownName(r.memory); title = r.memory.description ? `${name}: ${r.memory.description}` : name; icon = <span className="mt-ic">{isOn ? FOLDER_OPEN : FOLDER}</span>; }
    if (r.kind === 'more') name = r.action === 'all' ? `Show all (${r.hidden.toLocaleString()} more)` : 'Show more';
    const count = r.kind === 'group' || r.kind === 'folder' ? `${r.count.toLocaleString()}${r.plus ? '+' : ''}` : r.kind === 'memory' && r.count !== null ? r.count.toLocaleString() : '';
    const inGroup = r.kind === 'group' && items.length === 1 ? items[0] : null;
    return (
      <div key={r.key} data-key={r.key} className={cls} style={{ '--d': r.depth } as CSSProperties} role="treeitem" aria-level={r.depth + 1}
        aria-selected={r.kind === 'record' ? on : undefined} aria-expanded={expandable ? isOn : undefined} tabIndex={focused === r.key ? 0 : -1} title={title || undefined}
        onClick={() => act(r)} onFocus={(e) => { if (e.target === e.currentTarget) setFocusKey(r.key); }}
        onContextMenu={items.length ? (e) => { e.preventDefault(); if (r.kind === 'memory') void ensure(r.memory); openMenu(r.key, { left: e.clientX, right: e.clientX + 220, top: e.clientY, bottom: e.clientY }, items.length); } : undefined}>
        {icon}
        <span className="mt-lbl">{name}</span>
        {r.kind === 'record' && r.record.status === 'forgotten' ? <small className="mt-mark">Forgotten</small> : null}
        {r.kind === 'record' && r.record.status === 'superseded' ? <small className="mt-mark">Replaced</small> : null}
        {r.kind === 'record' && r.record.status === 'active' ? standTag(r.record) : null}
        <span className="mt-right">
          {r.kind === 'memory' && r.memory.restricted ? <span className="mt-ro" title="Limited access"><Lock size={12} /></span> : null}
          {r.kind === 'memory' && !r.memory.privileges?.includes('write') ? <span className="mt-ro" title="View only"><Eye size={12} /></span> : null}
          {count ? <small className="mt-count">{count}</small> : null}
          {inGroup ? (
            <button type="button" className="mt-rowact" tabIndex={-1} aria-label={inGroup.label} title={inGroup.label} onClick={(e) => { e.stopPropagation(); inGroup.run?.(); }}><FilePlus2 size={14} /></button>
          ) : items.length ? (
            <button type="button" className={`mt-rowact mt-opens${menuOpen ? ' on' : ''}`} tabIndex={-1} aria-label={`More actions for ${name}`} title="More actions" aria-haspopup="menu" aria-expanded={menuOpen}
              onClick={(e) => { e.stopPropagation(); openRowMenu(r, e.currentTarget.getBoundingClientRect()); }}>{DOTS}</button>
          ) : null}
          {expandable ? (
            <button type="button" className="mt-chev" tabIndex={-1} aria-label={isOn ? `Collapse ${name}` : `Expand ${name}`} onClick={(e) => { e.stopPropagation(); setFocusKey(r.key); toggle(r); }}>
              {isOn ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            </button>
          ) : null}
        </span>
      </div>
    );
  };

  const loadingBelow = filtering && b.searching;
  // a person's memory is theirs: "Find in Dana", but never "Find in You (this console)"
  const findIn = userOf(memory) ? 'Find in this memory' : `Find in ${shownName(memory)}`;
  return (
    <aside className="mt" aria-label="Records">
      <div className="mt-top">
        <label className="mm-find">{SEARCH}<input value={q} placeholder={findIn} aria-label={findIn} autoComplete="off" spellCheck={false} onChange={(e) => setQ(e.target.value)} />
          {q ? <button type="button" className="mt-clear" aria-label="Clear" onClick={() => setQ('')}>{X}</button> : null}</label>
        {filterItems.length ? (
          <button type="button" className={`icon-btn sm mm-plus mt-opens${gone ? ' mt-btn-on' : ''}`} aria-label={labelled ? 'Filter by label' : 'Filter by type'} title={labelled ? 'Filter by label' : 'Filter by type'} aria-haspopup="menu" aria-expanded={menu?.id === 'head:filter'}
            onClick={(e) => openMenu('head:filter', e.currentTarget.getBoundingClientRect(), filterItems.length)}>{FILTER}</button>
        ) : null}
        {newItems.length ? (
          <button type="button" className="icon-btn sm mm-plus mt-opens" aria-label="New" title={folders ? 'New record or folder' : 'New record'} aria-haspopup="menu" aria-expanded={menu?.id === 'head:new'}
            onClick={(e) => openMenu('head:new', e.currentTarget.getBoundingClientRect(), newItems.length)}>{PLUS}</button>
        ) : null}
      </div>
      {chip || gone ? (
        <div className="mm-filt mt-chips">
          {chip ? <span className="mm-chip"><span className="mm-dot sm" style={{ background: chip.color }} />{chip.name}
            <button type="button" aria-label={labelled ? 'Show every label' : 'Show every type'} onClick={() => { setKindFilter(''); setLabel(''); }}>{X}</button></span> : null}
          {gone ? <span className="mm-chip">Forgotten and replaced<button type="button" aria-label="Hide forgotten and replaced" onClick={() => { setGone(false); askGone(false); }}>{X}</button></span> : null}
        </div>
      ) : null}
      <div className="mt-status" role="status" aria-live="polite">
        {filtering ? (loadingBelow ? 'Looking through everything…' : `${matches.toLocaleString()} ${matches === 1 ? 'record' : 'records'}`) : null}
        {filtering && b.truncated ? ` Only the first ${SEARCH_CAP.toLocaleString()} of a memory are searched.` : null}
      </div>
      {filtering && b.belowFailed ? <p className="mm-muted mt-pad" role="alert">What is below this could not be searched just now. <button type="button" className="link-q inl" onClick={() => void loadBelow()}>Try again</button></p> : null}
      {newFolder ? (
        <div className="mt-newfolder">{FOLDER}
          <input className="set-in slim" autoFocus placeholder="Folder name" aria-label="Folder name"
            onKeyDown={(e) => { if (e.key === 'Enter') addFolder(e.currentTarget.value); if (e.key === 'Escape') setNewFolder(null); }}
            onBlur={(e) => addFolder(e.currentTarget.value)} />
        </div>
      ) : null}
      <div className="mt-list" ref={listRef} role="tree" aria-label={`What ${memory.name} holds`} onKeyDown={onKeys}>
        {rows.map(rowEl)}
        {!rows.length && filtering && !loadingBelow && !(asking && needle) ? (
          <p className="mm-muted mt-pad" role="status">{needle ? `Nothing here matches “${q.trim()}”.` : 'Nothing matches.'}</p>
        ) : null}
      </div>
      {madeEmpty ? <p className="set-help mt-pad">A folder is kept once a record is in it.</p> : null}
      {menu && menuItems.length ? (
        <div className="mt-menu" ref={menuRef} role="menu" style={{ top: menu.y, left: menu.x }} onKeyDown={menuKeys} onClick={(e) => e.stopPropagation()}>
          {menuItems.map((i) => (i.sep ? <div key={i.key} className="mt-sep" /> : i.head ? <div key={i.key} className="mt-mh">{i.label}</div> : (
            <button key={i.key} type="button" role="menuitem" className={`mt-mi${i.bad ? ' bad' : ''}${i.on ? ' on' : ''}`} onClick={i.run}>{i.icon}<span>{i.label}</span></button>
          )))}
        </div>
      ) : null}
      {sheet?.t === 'forget' ? (
        <ConfirmSheet id="mtFg" title={`Forget ${short(sheet.r)}?`} confirmLabel="Forget" busy={busy} refused={refused || undefined}
          body={hasHistory(providerOfMemory(sheet.mid)) ? 'Setups stop seeing it, and its history is kept.' : 'Setups stop seeing it.'}
          onClose={closeSheet} onConfirm={() => void forget(sheet.r, sheet.mid)} />
      ) : null}
      {sheet?.t === 'delete' ? (
        <ConfirmSheet id="mtDl" title={`Delete ${sheet.m.name}?`} confirmLabel="Delete memory" busy={busy} refused={refused || undefined}
          body={`${sheet.m.name}, its records and anything below it are destroyed, and setups lose it at once. This cannot be undone.`}
          onClose={closeSheet} onConfirm={() => void removeMemory(sheet.m, sheet.parent)} />
      ) : null}
      {sheet?.t === 'rename' ? (
        <RenameSheet m={sheet.m} onClose={closeSheet} onDone={(x) => { bump(x.id, (m) => ({ ...m, ...x })); closeSheet(); toast('Saved'); }} />
      ) : null}
      {sheet?.t === 'newsub' ? (
        <NewSubMemorySheet parent={sheet.parent} onClose={closeSheet} onDone={(m) => {
          const parent = sheet.parent;
          void (async () => {
            if (parent.id !== memory.id) await ensure(parent);
            patch(parent.id, (c) => ({ children: c.children?.some((k) => k.id === m.id) ? c.children : [...(c.children || []), m] }));
            patch(m.id, { memory: m });
            if (parent.id !== memory.id) { bump(parent.id, (p) => ({ ...p, children: { count: (p.children?.count || 0) + 1 } })); setOpen((o) => ({ ...o, [memoryKey(parent.id)]: true })); }
            closeSheet();
            toast(`${m.name} created`);
            onChanged();
          })();
        }} />
      ) : null}
      {sheet?.t === 'newrec' ? (
        <NewRecordSheet memory={sheet.m} label={sheet.label} type={sheet.type} attributes={sheet.attributes} onClose={closeSheet} onDone={(r) => {
          const mid = sheet.m.id;
          patch(mid, (c) => ({ records: [r, ...(c.records || [])] }));
          bump(mid, (m) => ({ ...m, records: { count: (m.records?.count || 0) + 1 } }));
          setOpen((o) => ({ ...o, [memoryKey(mid)]: true }));
          closeSheet();
          onOpen(r.id, mid, r);
          onChanged();
        }} />
      ) : null}
    </aside>
  );
}
