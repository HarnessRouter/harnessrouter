'use client';
// Memories: what every part of the page shares. The words and colour for each record type, the
// glyphs, how a record's Markdown body becomes the editor's blocks and back, how a time and a
// writer read, and the small controls (an icon, a name being typed in place, a confirm dialog).
// Nothing here calls the service.
import { useEffect, useRef, useState } from 'react';
import { bodyOf, labelOf, type MemoryRecord, type Writer } from '@/lib/memories';

/** What each record type is, in the reader's words. The protocol fixes the six. */
export const TYPE_INFO: Record<string, { one: string; plural: string; hint: string }> = {
  fact: { one: 'Fact', plural: 'Facts', hint: 'Something true. Agents use it as what is known.' },
  note: { one: 'Note', plural: 'Notes', hint: 'Context or an observation, not settled.' },
  procedure: { one: 'Procedure', plural: 'Procedures', hint: 'How something is done. Agents follow it.' },
  episode: { one: 'Episode', plural: 'Episodes', hint: 'A conversation kept as it happened. Agents add these.' },
  link: { one: 'Link', plural: 'Links', hint: 'A document or page that lives elsewhere.' },
  entity: { one: 'Entity', plural: 'Entities', hint: 'A person, company or thing other records are about.' },
};
/** The types a person may add by hand: an episode is kept by an agent, never written here. */
export const WRITABLE_TYPES = ['fact', 'note', 'procedure', 'link', 'entity'];
export const KINDS = ['person', 'company', 'product', 'other'];
const TYPE_COLOR: Record<string, string> = {
  entity: '#e0457b', fact: '#7c3aed', note: '#0ea5c6', procedure: '#14a38b', link: '#5b6b82', episode: '#ef4444',
};
export const LEGEND = ['entity', 'fact', 'note', 'procedure', 'link', 'episode'];
const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
export const typeOne = (t: string) => TYPE_INFO[t]?.one || cap(t);
export const typePlural = (t: string) => TYPE_INFO[t]?.plural || cap(t);
export const typeColor = (t: string) => TYPE_COLOR[t] || TYPE_COLOR.note;
export const capWord = cap;

export const ICON = {
  person: 'M8 7.6a2.4 2.4 0 1 0 0-4.8 2.4 2.4 0 0 0 0 4.8M3.5 13.4c0-2.5 2-4.2 4.5-4.2s4.5 1.7 4.5 4.2',
  company: 'M3 13.5V3.5h6v10M9 6.5h4v7M5 6h2M5 8.5h2M5 11h2M11 9h.01M11 11h.01M2 13.5h12',
  fact: 'M8 1.8 13 3.6v4.2c0 3-2.1 5.2-5 6.4-2.9-1.2-5-3.4-5-6.4V3.6zM5.9 8l1.5 1.5 2.8-3',
  note: 'M3.5 2.5h9v11h-9zM6 5.5h4M6 8h4M6 10.5h2.5',
  procedure: 'M6 4h7.5M6 8h7.5M6 12h7.5M2.5 4h.01M2.5 8h.01M2.5 12h.01',
  link: 'M6.8 9.2a2.6 2.6 0 0 0 3.7 0l2-2a2.6 2.6 0 0 0-3.7-3.7l-.6.6M9.2 6.8a2.6 2.6 0 0 0-3.7 0l-2 2a2.6 2.6 0 0 0 3.7 3.7l.6-.6',
  episode: 'M2.5 4h11v7h-6l-3 2.5V11h-2z',
  folder: 'M1.8 4h4.4l1.4 1.6h6.6v7.4H1.8z',
  folderOpen: 'M1.8 13V4h4.4l1.4 1.6h5.6v1.9M1.8 13l1.8-5.5h10.6L12.4 13z',
  folderNew: 'M1.8 4h4.4l1.4 1.6h6.6v7.4H1.8zM8 7.5v4M6 9.5h4',
  search: 'M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10M10.6 10.6 14 14',
  pencil: 'M10.5 2.5l3 3-7.5 7.5H3v-3z',
  share: 'M6 7.2a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0 0 4.4M2 13.2c0-2.2 1.8-3.8 4-3.8s4 1.6 4 3.8M12 6v4M10 8h4',
  trash: 'M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 9h5.8l.6-9',
  info: 'M8 14a6 6 0 1 0 0-12 6 6 0 0 0 0 12M8 7.2v3.6M8 5h.01',
  relate: 'M4 4.5a1.5 1.5 0 1 0 0-.01M12 11.5a1.5 1.5 0 1 0 0-.01M5.4 5.4l5.2 5.2',
  fit: 'M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10',
};
/** A record's glyph: its type's, and for an entity a person or a building. */
export const recordIcon = (r: Pick<MemoryRecord, 'type' | 'attributes'>) =>
  r.type === 'entity' ? (r.attributes?.kind === 'person' ? ICON.person : ICON.company) : (ICON as Record<string, string>)[r.type] || ICON.note;

export function Ico({ d, size = 14, sw = 1.4, className, style }: { d: string; size?: number; sw?: number; className?: string; style?: React.CSSProperties }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" className={className} style={{ flex: 'none', ...style }}><path d={d} /></svg>
  );
}

/** The small triangle of a row that opens, and of a button that drops a menu. */
export function Caret({ open = true, className }: { open?: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 8 8" width={8} height={8} aria-hidden="true" className={className} style={{ flex: 'none' }}>
      <path d={open ? 'M1 2.5h6L4 6.5z' : 'M2.5 1v6l4-3z'} fill="currentColor" />
    </svg>
  );
}

/** An engine by the name people know it by; one we have no name for shows as the service names it. */
const ENGINE_NAME: Record<string, string> = { mem0: 'Mem0' };
export const engineName = (id: string) => ENGINE_NAME[id] || id;
/** The line under a memory's name: its engine, and whose account it runs on. */
export const engineLine = (id: string) => (id === 'mem0' ? 'Mem0 · your key' : engineName(id));
export const engineMark = (id: string) => (id === 'mem0' ? 'M0' : engineName(id).slice(0, 2).toUpperCase());

/** "Oct 3, 08:14", or a dash for a record that carries no time. */
export function whenOf(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

/** Who wrote a record, by name where we know one: the reader, a harness, or the id the service gave. */
export type WhoFn = (w: Writer | undefined) => string;
export function makeWho(me: string[], harnessName: (id: string) => string | undefined): WhoFn {
  return (w) => {
    if (!w || !w.id) return '—';
    const id = w.id.replace(/^member:/, '');
    if (me.includes(id)) return 'You';
    return harnessName(id) || (w.kind && w.kind !== 'member' ? engineName(id) : id);
  };
}

export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

// ── a record's body: Markdown in the service, blocks in the editor ───────────────────────────
export interface Block { id: string; t: 'p' | 'h2' | 'li'; x: string }
let seq = 0;
export const blockId = () => `b${++seq}`;
/** Paragraphs, `## ` headings and `- ` list items, one block each. */
export function mdToBlocks(md: string): Block[] {
  const out: Block[] = [];
  let para: string[] = [];
  const flush = () => { if (para.length) { out.push({ id: blockId(), t: 'p', x: para.join('\n') }); para = []; } };
  for (const raw of (md || '').replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd();
    const h = /^#{1,6}\s+(.*)$/.exec(line);
    const li = /^\s*[-*]\s+(.*)$/.exec(line);
    if (!line.trim()) flush();
    else if (h) { flush(); out.push({ id: blockId(), t: 'h2', x: h[1] }); }
    else if (li) { flush(); out.push({ id: blockId(), t: 'li', x: li[1] }); }
    else para.push(line);
  }
  flush();
  return out;
}
export function blocksToMd(blocks: { t: Block['t']; x: string }[]): string {
  let md = '';
  let prev: Block['t'] | null = null;
  for (const b of blocks) {
    const x = (b.x || '').replace(/ /g, ' ').trim();
    if (!x) continue;
    const line = b.t === 'h2' ? `## ${x.replace(/\s*\n+\s*/g, ' ')}` : b.t === 'li' ? `- ${x.replace(/\s*\n+\s*/g, ' ')}` : x;
    md += (md ? (b.t === 'li' && prev === 'li' ? '\n' : '\n\n') : '') + line;
    prev = b.t;
  }
  return md;
}
/** The blocks a record reads as. An episode's turns keep who said them. */
export function recordBlocks(r: Pick<MemoryRecord, 'type' | 'content'>): Block[] {
  if (r.type === 'episode') {
    return (r.content || []).filter((p) => p.text || p.file).map((p) => ({
      id: blockId(), t: 'p' as const, x: p.text ? (p.role ? `${capWord(p.role)}: ${p.text}` : p.text) : (p.file?.name || p.file?.id || ''),
    }));
  }
  return mdToBlocks(bodyOf(r));
}
/** The line under a record's label in a list: how its body begins, past any heading. */
export function excerptOf(r: Pick<MemoryRecord, 'title' | 'content'>): string {
  const lines = bodyOf(r).split('\n').map((l) => l.trim()).filter((l) => l && !/^#{1,6}\s/.test(l)).map((l) => l.replace(/^[-*]\s+/, ''));
  if (r.title) return lines[0] || '';
  const label = labelOf(r);
  return lines.find((l) => l.slice(0, 120) !== label) || '';
}

/** How wide an element is, so a pane can lay itself out by the room it has, not the window's. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setW(el.clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** A name typed in place: Enter or leaving keeps it, Escape drops it. */
export function NameInput({ initial, label, placeholder, className, onCommit, onCancel }: {
  initial: string; label: string; placeholder?: string; className?: string; onCommit: (name: string) => void; onCancel: () => void;
}) {
  const [v, setV] = useState(initial);
  const dropped = useRef(false);
  return (
    <input autoFocus className={className} value={v} aria-label={label} placeholder={placeholder}
      onChange={(e) => setV(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur();
        if (e.key === 'Escape') { dropped.current = true; onCancel(); }
      }}
      onBlur={() => { if (dropped.current) return; const name = v.trim(); if (name && name !== initial) onCommit(name); else onCancel(); }} />
  );
}

/** The page's own confirm: what will happen, an optional list, and for what cannot be undone a
 *  box to tick first. Escape and the backdrop cancel. */
export function ConfirmDialog({ title, body, list, label, tone = 'danger', needsAck, busy, wait, error, onConfirm, onCancel }: {
  title: string; body: React.ReactNode; list?: string | null; label: string; tone?: 'danger' | 'accent';
  needsAck?: boolean; busy?: boolean; wait?: boolean; error?: string; onConfirm: () => void; onCancel: () => void;
}) {
  const [ack, setAck] = useState(false);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onCancel(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [busy, onCancel]);
  const ready = (!needsAck || ack) && !busy && !wait;
  return (
    <div className="modal-backdrop" onClick={() => busy || onCancel()}>
      <section className="modal mem-dlg mem-confirm" role="alertdialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h2 className="mem-confirm-title">{title}</h2>
        <div className="mem-confirm-body">{body}</div>
        {list && <div className="mem-confirm-list">{list}</div>}
        {needsAck && (
          <label className="mem-ack"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>I understand this cannot be undone</span></label>
        )}
        {error && <div className="mem-field-err" role="alert">{error}</div>}
        <div className="mem-dlg-actions">
          <button type="button" className="mem-btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className={'mem-btn ' + (tone === 'danger' ? 'is-danger' : 'is-primary')} disabled={!ready} onClick={onConfirm}>{label}</button>
        </div>
      </section>
    </div>
  );
}
