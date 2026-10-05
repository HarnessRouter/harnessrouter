'use client';
// Memories: the tree on the left of an open memory. Memories and the records kept in them sit in
// one tree, a level at a time: opening a memory asks the service for what is inside it. A row
// shows what its reader may do with that memory (new memory inside, rename, share, delete) and
// nothing else. The find box narrows what has been opened so far.
import { useMemo, useState } from 'react';
import { labelOf, type Memory, type MemoryRecord } from '@/lib/memories';
import { SkelLine } from '@/components/Skel';
import { Caret, ICON, Ico, NameInput, recordIcon, typeColor } from './kit';

export interface TreeRecords { data: MemoryRecord[]; more: boolean }

type Row =
  | { kind: 'mem'; m: Memory; depth: number; open: boolean }
  | { kind: 'rec'; r: MemoryRecord; depth: number }
  | { kind: 'draft'; depth: number; key: string }
  | { kind: 'more'; m: Memory; depth: number; label: string }
  | { kind: 'loading'; depth: number; key: string }
  | { kind: 'empty'; m: Memory; depth: number };

export function MemoryTree({ root, mems, kids, recs, open, selId, recId, draftIn, current, onSelect, onToggle, onOpenRecord, onNewChild, onRename, onShare, onDelete }: {
  root: Memory; mems: Record<string, Memory>; kids: Record<string, string[] | undefined>; recs: Record<string, TreeRecords | undefined>;
  open: string[]; selId: string; recId: string; draftIn: string | null; current: MemoryRecord | null;
  onSelect: (id: string) => void; onToggle: (id: string) => void; onOpenRecord: (memoryId: string, recordId: string) => void;
  onNewChild: (m: Memory) => void; onRename: (m: Memory, name: string) => void; onShare: (m: Memory) => void; onDelete: (m: Memory) => void;
}) {
  const [query, setQuery] = useState('');
  const [renaming, setRenaming] = useState<string | null>(null);
  const tq = query.trim().toLowerCase();

  const rows = useMemo(() => {
    const out: Row[] = [];
    const recHit = (r: MemoryRecord) => labelOf(r).toLowerCase().includes(tq);
    const hits = (m: Memory): boolean =>
      m.name.toLowerCase().includes(tq) || (recs[m.id]?.data || []).some(recHit) || (kids[m.id] || []).some((k) => mems[k] && hits(mems[k]));
    const walk = (m: Memory, depth: number) => {
      if (tq && !hits(m)) return;
      const loaded = kids[m.id] !== undefined && recs[m.id] !== undefined;
      const isOpen = tq ? loaded : open.includes(m.id);
      out.push({ kind: 'mem', m, depth, open: isOpen });
      if (!isOpen) return;
      if (!loaded) { out.push({ kind: 'loading', depth: depth + 1, key: 'l:' + m.id }); return; }
      const ks = (kids[m.id] || []).map((k) => mems[k]).filter(Boolean);
      ks.forEach((k) => walk(k, depth + 1));
      if (draftIn === m.id && !tq) out.push({ kind: 'draft', depth: depth + 1, key: 'd:' + m.id });
      const listed = recs[m.id]?.data || [];
      // the record on screen always has its row, also past the first few the tree asks for
      const extra = current && current.memory_id === m.id && current.status === 'active' && !listed.some((r) => r.id === current.id) ? [current] : [];
      const rs = [...listed, ...extra].filter((r) => !tq || recHit(r));
      rs.forEach((r) => out.push({ kind: 'rec', r, depth: depth + 1 }));
      if (!tq) {
        const total = m.records?.count;
        const rest = typeof total === 'number' ? total - rs.length : null;
        if (rest !== null ? rest > 0 : recs[m.id]?.more) out.push({ kind: 'more', m, depth: depth + 1, label: rest !== null ? `${rest} more in ${m.name}` : `More in ${m.name}` });
        if (!ks.length && !rs.length && draftIn !== m.id) out.push({ kind: 'empty', m, depth: depth + 1 });
      }
    };
    walk(root, 0);
    return out;
  }, [root, mems, kids, recs, open, tq, draftIn, current]);

  const findLabel = `Find in ${root.name}`;
  return (
    <>
      <div className="mem-tree-head">
        <div className="mem-tree-find">
          <Ico d={ICON.search} size={12} sw={1.5} style={{ color: 'var(--v2-cap)' }} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} aria-label={findLabel} placeholder={findLabel} />
        </div>
        {root.privileges.includes('create') && (
          <button type="button" className="mem-iconbtn" title="New memory" aria-label={`New memory inside ${root.name}`} onClick={() => onNewChild(root)}><Ico d={ICON.folderNew} /></button>
        )}
      </div>
      <div className="mem-tree-scroll" role="tree" aria-label={`Inside ${root.name}`}>
        {rows.map((row) => {
          const pad = 10 + row.depth * 16;
          if (row.kind === 'loading') return <div key={row.key} className="mem-trow" style={{ paddingLeft: pad + 18 }} aria-busy="true"><SkelLine w={120} h={10} /></div>;
          if (row.kind === 'draft') return (
            <div key={row.key} className="mem-trow is-on"><span className="mem-trec-hit is-blank" style={{ paddingLeft: pad + 18 }}><Ico d={ICON.note} size={13} /><span className="mem-ell">Untitled</span></span></div>
          );
          if (row.kind === 'rec') {
            const r = row.r; const name = labelOf(r);
            return (
              <div key={'r:' + r.id} className={'mem-trow' + (r.id === recId ? ' is-on' : '')} role="treeitem" aria-selected={r.id === recId}>
                <button type="button" className={'mem-trec-hit' + (name ? '' : ' is-blank')} style={{ paddingLeft: pad + 18 }} title={name || 'Untitled'} onClick={() => onOpenRecord(r.memory_id, r.id)}>
                  <Ico d={recordIcon(r)} size={13} style={{ color: typeColor(r.type) }} /><span className="mem-ell">{name || 'Untitled'}</span>
                </button>
              </div>
            );
          }
          if (row.kind === 'more') return (
            <div key={'m:' + row.m.id} className="mem-trow"><button type="button" className="mem-tmore" style={{ paddingLeft: pad + 18 }} onClick={() => onSelect(row.m.id)}>{row.label}</button></div>
          );
          if (row.kind === 'empty') return (
            <div key={'e:' + row.m.id} className="mem-trow mem-tempty" style={{ paddingLeft: pad + 18 }}>
              <span>Empty</span>
              {row.m.privileges.includes('create') && <button type="button" onClick={() => onNewChild(row.m)}>New memory inside</button>}
            </div>
          );
          const m = row.m; const on = m.id === selId && !recId;
          const p = m.privileges || [];
          const count = m.records?.count;
          if (renaming === m.id) return (
            <div key={m.id} className="mem-trow is-on" style={{ paddingLeft: pad + 16 }}>
              <Ico d={ICON.folder} sw={1.3} style={{ color: 'var(--v2-warn-ink)' }} />
              <NameInput className="mem-trename" initial={m.name} label="Memory name" onCancel={() => setRenaming(null)} onCommit={(name) => { setRenaming(null); onRename(m, name); }} />
            </div>
          );
          return (
            <div key={m.id} className={'mem-trow is-mem' + (on ? ' is-on' : '') + (m.id === selId ? ' is-sel' : '') + (row.depth === 0 ? ' is-top' : '')} role="treeitem" aria-expanded={row.open} aria-selected={m.id === selId}>
              <button type="button" className="mem-caret" style={{ marginLeft: pad - 4 }} aria-label={(row.open ? 'Close ' : 'Open ') + m.name} onClick={() => onToggle(m.id)}><Caret open={row.open} /></button>
              <button type="button" className="mem-tmem-hit" onClick={() => onSelect(m.id)} onDoubleClick={() => { if (p.includes('write')) setRenaming(m.id); }}>
                <Ico d={row.open ? ICON.folderOpen : ICON.folder} sw={1.3} className="mem-tmem-ico" /><span className="mem-ell">{m.name}</span>
              </button>
              {!row.open && typeof count === 'number' && <span className="mem-tcount">{count}</span>}
              <span className="mem-tacts">
                {p.includes('create') && <button type="button" title="New memory inside" aria-label={`New memory inside ${m.name}`} onClick={() => onNewChild(m)}><Ico d={ICON.folderNew} size={12} sw={1.5} /></button>}
                {p.includes('write') && <button type="button" title="Rename" aria-label={`Rename ${m.name}`} onClick={() => setRenaming(m.id)}><Ico d={ICON.pencil} size={12} sw={1.5} /></button>}
                {p.includes('delete') && <>
                  <button type="button" title="Share" aria-label={`Share ${m.name}`} onClick={() => onShare(m)}><Ico d={ICON.share} size={12} sw={1.5} /></button>
                  <button type="button" className="is-danger" title="Delete" aria-label={`Delete ${m.name}`} onClick={() => onDelete(m)}><Ico d={ICON.trash} size={12} sw={1.5} /></button>
                </>}
              </span>
            </div>
          );
        })}
        {tq && rows.length === 0 && <div className="mem-tnone">Nothing here matches that.</div>}
      </div>
    </>
  );
}
