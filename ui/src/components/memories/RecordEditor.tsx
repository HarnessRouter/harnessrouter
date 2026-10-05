'use client';
// Memories: one record, opened as a document in the pane its memory was in. A title, the
// properties its type has (what it is about, an address, a kind, the two entities a fact
// relates), and a body of paragraphs, headings and list items that is kept as Markdown in one
// text part. Saving a record that exists appends a version, with an optional reason; the Info
// panel shows who wrote it and every earlier version, any of which can be read or restored. A
// new record is the same editor, empty, with its type still to choose. What the reader may do
// comes from the memory's privileges; an episode and a forgotten record are read only.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  addRecord, eraseRecords, forgetRecord, getHistory, getRecord, labelOf, listRecords, reviseRecord,
  MemoryApiError, type Memory, type MemoryRecord, type Provider, type Reference,
} from '@/lib/memories';
import { SkelLine } from '@/components/Skel';
import {
  blockId, blocksToMd, capWord, Caret, ConfirmDialog, engineName, errText, ICON, Ico, KINDS, recordBlocks,
  TYPE_INFO, typeColor, typeOne, useWidth, whenOf, WRITABLE_TYPES, type Block, type WhoFn,
} from './kit';

const str = (v: unknown) => (typeof v === 'string' ? v : '');

function caretAt(el: HTMLElement): number {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !sel.isCollapsed) return -1;
  const r = sel.getRangeAt(0);
  if (!el.contains(r.startContainer)) return -1;
  const pre = r.cloneRange();
  pre.selectNodeContents(el);
  pre.setEnd(r.startContainer, r.startOffset);
  return pre.toString().length;
}
function placeCaret(el: HTMLElement, at: number) {
  el.focus();
  el.normalize();
  const sel = window.getSelection();
  if (!sel) return;
  const range = document.createRange();
  const n = el.firstChild;
  if (n && n.nodeType === Node.TEXT_NODE) range.setStart(n, Math.min(at, (n.textContent || '').length));
  else range.setStart(el, 0);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

export function RecordEditor({ memory, path, provider, recordId, who, onRecord, onOpenRecord, onOpenMemory, onOpenTree, onSaved, onGone, onCancelDraft }: {
  memory: Memory; path: Memory[]; provider: Provider | undefined; recordId: string | null; who: WhoFn;
  onRecord: (r: MemoryRecord | null) => void;
  onOpenRecord: (memoryId: string, recordId: string) => void; onOpenMemory: (id: string) => void; onOpenTree: () => void;
  onSaved: (r: MemoryRecord, isNew: boolean) => void; onGone: (memoryId: string, notice: string) => void; onCancelDraft: () => void;
}) {
  const draft = recordId === null;
  const [rec, setRec] = useState<MemoryRecord | null>(null);
  const [loadErr, setLoadErr] = useState<Error | null>(null);
  const [type, setType] = useState('note');
  const [title0, setTitle0] = useState('');
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [attrs, setAttrs] = useState({ url: '', kind: 'other' });
  const [refs, setRefs] = useState<Reference[]>([]);
  const [refsDirty, setRefsDirty] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [docKey, setDocKey] = useState(0);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [infoOpen, setInfoOpen] = useState(false);
  const [sec, setSec] = useState({ details: true, history: true });
  const [history, setHistory] = useState<MemoryRecord[] | null>(null);
  const [historyErr, setHistoryErr] = useState('');
  const [viewV, setViewV] = useState<number | null>(null);
  const [more, setMore] = useState(false);
  const [typeMenu, setTypeMenu] = useState(false);
  const [confirm, setConfirm] = useState<'forget' | 'erase' | null>(null);
  const [confirmErr, setConfirmErr] = useState('');
  const [names, setNames] = useState<Record<string, string | null>>({});
  const [entities, setEntities] = useState<MemoryRecord[]>([]);

  const texts = useRef<Record<string, string>>({});
  const titleText = useRef('');
  const els = useRef<Record<string, HTMLDivElement | null>>({});
  const focusReq = useRef<{ id: string; at: number } | null>(null);
  const recRef = useRef<MemoryRecord | null>(null);
  const asked = useRef(new Set<string>());
  const [box, width] = useWidth<HTMLDivElement>();

  const canWrite = memory.privileges.includes('write');
  const canDelete = memory.privileges.includes('delete');
  const editableOf = useCallback((r: MemoryRecord | null) => canWrite && (!r || (r.type !== 'episode' && r.status === 'active')), [canWrite]);
  const keepsHistory = provider ? (provider.history?.content ?? 'none') !== 'none' : false;

  /** Put a record (or nothing, for a new one) on the page as the saved state. */
  const show = useCallback((r: MemoryRecord | null) => {
    const bs = r ? recordBlocks(r) : [];
    if (editableOf(r) && bs.length === 0) bs.push({ id: blockId(), t: 'p', x: '' });
    texts.current = Object.fromEntries(bs.map((b) => [b.id, b.x]));
    titleText.current = r?.title || '';
    setTitle0(r?.title || ''); setBlocks(bs);
    setAttrs({ url: str(r?.attributes?.url), kind: str(r?.attributes?.kind) || 'other' });
    setRefs(r?.references || []); setRefsDirty(false);
    setDirty(false); setReason(''); setErr(''); setViewV(null); setDocKey((k) => k + 1);
  }, [editableOf]);

  useEffect(() => {
    setMore(false); setTypeMenu(false); setConfirm(null);
    if (recordId === null) { recRef.current = null; setRec(null); setLoadErr(null); setType('note'); setHistory(null); show(null); return; }
    if (recRef.current?.id === recordId) return;       // the record this editor just saved
    let alive = true;
    recRef.current = null; setRec(null); setLoadErr(null); setHistory(null);
    getRecord(memory.id, recordId).then((r) => { if (!alive) return; recRef.current = r; setRec(r); show(r); }).catch((e) => { if (alive) setLoadErr(e); });
    return () => { alive = false; };
  }, [memory.id, recordId, show]);

  useEffect(() => { onRecord(rec); }, [rec, onRecord]);
  useEffect(() => () => onRecord(null), [onRecord]);

  // every earlier version, newest first, when the panel is open and the engine keeps them
  useEffect(() => {
    if (!infoOpen || !rec || !keepsHistory || history) return;
    let alive = true;
    setHistoryErr('');
    // An engine may serve a version a moment after it stored it. The record says which version it
    // is, so a history that does not reach it yet is read again, a few times, before it is shown.
    const read = (left: number) => getHistory(memory.id, rec.id).then((h) => {
      if (!alive) return;
      if (left > 0 && !h.some((x) => x.version === rec.version)) { window.setTimeout(() => { if (alive) void read(left - 1); }, 1500); return; }
      setHistory([...h].sort((a, b) => b.version - a.version));
    }).catch((e) => { if (alive) setHistoryErr(errText(e)); });
    void read(4);
    return () => { alive = false; };
  }, [infoOpen, rec, keepsHistory, history, memory.id]);

  const effType = rec ? rec.type : type;
  const viewing = viewV !== null ? history?.find((h) => h.version === viewV) || null : null;
  const editable = !viewing && (draft ? canWrite : editableOf(rec)) && (draft || !!rec);
  const subject = refs.find((f) => f.rel === 'subject'), object = refs.find((f) => f.rel === 'object');
  const isRelation = effType === 'fact' && !!subject && !!object;
  const about = refs.filter((f) => f.rel === 'about');
  const hasAbout = effType !== 'entity' && !isRelation;

  // the entities this record may be said to be about: this memory's and those of the memories above it
  const pathIds = path.map((m) => m.id).join(',');
  useEffect(() => {
    if (!editable || !hasAbout) return;
    let alive = true;
    Promise.all(pathIds.split(',').filter(Boolean).map((id) => listRecords(id, { type: 'entity', limit: 100 }).then((d) => d.data).catch(() => [] as MemoryRecord[])))
      .then((lists) => { if (alive) setEntities(lists.flat()); });
    return () => { alive = false; };
  }, [editable, hasAbout, pathIds]);
  // what each reference points at, by name; one the reader may not open is never asked for
  useEffect(() => {
    const known: Record<string, string | null> = {};
    for (const e of entities) known[e.id] = labelOf(e) || 'Untitled';
    setNames((n) => ({ ...n, ...known }));
    for (const f of refs) {
      if (!f.available || !f.record_id || known[f.record_id] !== undefined || asked.current.has(f.record_id)) continue;
      asked.current.add(f.record_id);
      getRecord(f.memory_id, f.record_id).then((r) => labelOf(r) || 'Untitled').catch(() => null)
        .then((label) => setNames((n) => ({ ...n, [f.record_id]: label })));
    }
  }, [refs, entities]);

  useLayoutEffect(() => {
    const f = focusReq.current;
    if (!f) return;
    focusReq.current = null;
    const el = els.current[f.id];
    if (el) placeCaret(el, f.at);
  }, [blocks]);

  const touch = () => { if (!dirty) setDirty(true); };
  /** Carry what has been typed into state, under new keys, before the blocks leave the page. */
  const syncDoc = () => {
    const next = blocks.map((b) => { const id = blockId(); const x = texts.current[b.id] ?? b.x; texts.current[id] = x; return { ...b, id, x }; });
    setBlocks(next); setTitle0(titleText.current);
  };
  const swap = (b: Block, t: Block['t'], x: string) => {
    const nb: Block = { id: blockId(), t, x };
    texts.current[nb.id] = x;
    focusReq.current = { id: nb.id, at: 0 };
    setBlocks((bs) => bs.map((o) => (o.id === b.id ? nb : o)));
    touch();
  };
  const addBelow = (idx: number, t: Block['t'], x: string) => {
    const nb: Block = { id: blockId(), t, x };
    texts.current[nb.id] = x;
    focusReq.current = { id: nb.id, at: 0 };
    setBlocks((bs) => [...bs.slice(0, idx + 1), nb, ...bs.slice(idx + 1)]);
    touch();
  };
  const onBlockInput = (b: Block, el: HTMLDivElement) => {
    let text = el.textContent || '';
    if (text === '\n') text = '';
    if (!text && el.childNodes.length) el.innerHTML = '';
    texts.current[b.id] = text;
    touch();
    // "## " starts a heading and "- " a list item, as they are written in the record
    const m = b.t === 'p' ? /^(#{1,6}|[-*])[  ]/.exec(text) : null;
    if (m) swap(b, m[1].startsWith('#') ? 'h2' : 'li', text.slice(m[0].length));
  };
  const onBlockKey = (e: React.KeyboardEvent<HTMLDivElement>, b: Block, idx: number) => {
    const el = e.currentTarget;
    const text = texts.current[b.id] ?? '';
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (b.t !== 'p' && !text.trim()) { swap(b, 'p', ''); return; }
      const c = caretAt(el), at = c < 0 ? text.length : c;
      const before = text.slice(0, at), after = text.slice(at);
      if (after) { el.textContent = before; texts.current[b.id] = before; }
      addBelow(idx, b.t === 'li' ? 'li' : 'p', after);
    } else if (e.key === 'Backspace' && caretAt(el) === 0) {
      if (b.t !== 'p') { e.preventDefault(); swap(b, 'p', text); }
      else if (idx > 0) {
        e.preventDefault();
        const prev = blocks[idx - 1], pt = texts.current[prev.id] ?? '', pel = els.current[prev.id];
        if (pel) pel.textContent = pt + text;
        texts.current[prev.id] = pt + text;
        focusReq.current = { id: prev.id, at: pt.length };
        setBlocks((bs) => bs.filter((o) => o.id !== b.id));
        touch();
      }
    } else if (e.key === 'ArrowUp' && idx > 0 && caretAt(el) === 0) {
      e.preventDefault();
      const prev = blocks[idx - 1], pel = els.current[prev.id];
      if (pel) placeCaret(pel, (texts.current[prev.id] ?? '').length);
    } else if (e.key === 'ArrowDown' && idx < blocks.length - 1 && caretAt(el) === text.length) {
      e.preventDefault();
      const nel = els.current[blocks[idx + 1].id];
      if (nel) placeCaret(nel, 0);
    }
  };

  const save = async () => {
    if (saving || !editable) return;
    const title = titleText.current.replace(/\s+/g, ' ').trim();
    const md = blocksToMd(blocks.map((b) => ({ t: b.t, x: texts.current[b.id] ?? b.x })));
    if (!title && !md) { setErr('Give it a title or write something first.'); return; }
    // the body is one text part; anything else the record carries (a file) stays as it is
    const content = [...(md ? [{ type: 'text', text: md }] : []), ...(rec?.content || []).filter((p) => p.type !== 'text')];
    const attributes: Record<string, unknown> = {};
    if (effType === 'link') attributes.url = attrs.url.trim();
    if (effType === 'entity') attributes.kind = attrs.kind;
    const references = refs.filter((f) => f.record_id).map((f) => ({ rel: f.rel || 'about', record_id: f.record_id, memory_id: f.memory_id }));
    setSaving(true); setErr('');
    try {
      const isNew = !rec;
      const saved = rec
        ? await reviseRecord(memory.id, rec.id, { title, content, attributes: { ...attributes, revision_reason: reason.trim() || null }, ...(refsDirty ? { references } : {}) })
        : await addRecord(memory.id, { type, title, content, attributes, references });
      recRef.current = saved; setRec(saved); setHistory(null); show(saved);
      onSaved(saved, isNew);
    } catch (e) { setErr(errText(e)); }
    finally { setSaving(false); }
  };
  const discard = () => { if (draft) onCancelDraft(); else show(rec); };
  const restore = async () => {
    if (!rec || !viewing || saving) return;
    setSaving(true); setErr('');
    try {
      const saved = await reviseRecord(memory.id, rec.id, { title: viewing.title, content: viewing.content, attributes: { revision_reason: `Restored v${viewing.version}` } });
      recRef.current = saved; setRec(saved); setHistory(null); show(saved);
      onSaved(saved, false);
    } catch (e) { setErr(errText(e)); }
    finally { setSaving(false); }
  };
  const doConfirm = async () => {
    if (!rec || !confirm || saving) return;
    setSaving(true); setConfirmErr('');
    try {
      if (confirm === 'forget') {
        await forgetRecord(memory.id, rec.id);
        onGone(memory.id, '');
      } else {
        const out = await eraseRecords(memory.id, [rec.id]);
        const n = out.erased.length;
        // what the engine could not remove is said, never dropped
        const left = out.unreachable.length
          ? ` ${engineName(memory.provider)} reported ${out.unreachable.length === 1 ? 'one copy' : `${out.unreachable.length} copies`} it could not remove: ${out.unreachable.join(', ')}.`
          : '';
        onGone(memory.id, (n ? `Erased ${n} ${n === 1 ? 'record' : 'records'}.` : 'Nothing was erased.') + left);
      }
    } catch (e) { setConfirmErr(errText(e)); }
    finally { setSaving(false); }
  };

  const viewBlocks = useMemo(() => (viewing ? recordBlocks(viewing) : []), [viewing]);
  const shown = viewing ? viewBlocks : blocks;
  const label = viewing ? labelOf(viewing) : rec ? labelOf(rec) : '';
  const status = draft ? 'New record' : !rec ? '' : rec.status === 'forgotten' ? 'Forgotten' : rec.type === 'episode' || !canWrite ? 'Read only'
    : viewing ? `Viewing v${viewing.version}` : dirty ? '' : `Saved · v${rec.version}`;
  const showActions = editable && (draft || dirty);
  const options = entities.filter((e) => e.id !== rec?.id && !refs.some((f) => f.record_id === e.id));
  const refChip = (f: Reference | undefined) => {
    if (!f) return null;
    if (!f.available || !f.record_id) return <span className="mem-chip is-off">Unavailable to you</span>;
    const name = names[f.record_id];
    return (
      <button type="button" className="mem-chip" onClick={() => onOpenRecord(f.memory_id, f.record_id)}>
        <i style={{ background: typeColor('entity') }} />{name === undefined ? '…' : name ?? 'Unavailable to you'}
      </button>
    );
  };
  const hidden = refs.filter((f) => !f.available);

  if (loadErr) {
    const gone = loadErr instanceof MemoryApiError && loadErr.code === 'memory_unavailable';
    return (
      <div className="mem-rec">
        <div className="mem-state">
          <strong>{gone ? 'This memory is not answering right now' : 'This record could not be opened'}</strong>
          <span>{loadErr.message}</span>
          <button type="button" className="mem-btn" onClick={() => onOpenMemory(memory.id)}>Back to {memory.name}</button>
        </div>
      </div>
    );
  }

  return (
    <div className={'mem-rec' + (infoOpen ? ' has-info' : '') + (width >= 740 ? ' is-w740' : '') + (width >= 900 ? ' is-w900' : '')} ref={box}>
      <div className="mem-recbar">
        <button type="button" className="mem-treebtn" aria-label="Show memories" onClick={onOpenTree}>
          <Ico d={ICON.folder} size={13} style={{ color: 'var(--v2-warn-ink)' }} /><span>Tree</span>
        </button>
        <div className="mem-crumbs mem-rec-crumbs">
          {path.map((m, i) => (
            <span key={m.id} className={i < path.length - 1 ? 'is-anc' : ''}>
              <button type="button" onClick={() => onOpenMemory(m.id)}>{m.name}</button><i>/</i>
            </span>
          ))}
          <span className="mem-crumb-self mem-ell">{draft ? 'Untitled' : label || (rec ? 'Untitled' : '')}</span>
        </div>
        <span className={'mem-rec-status' + (dirty && !viewing ? ' is-dirty' : '')}>{status}</span>
        {showActions && !draft && (
          <input className="mem-reason" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Why the change" placeholder="Why the change (optional)" />
        )}
        {showActions && (
          <>
            <button type="button" className="mem-textbtn" onClick={discard} disabled={saving}>{draft ? 'Cancel' : 'Discard'}</button>
            <button type="button" className="mem-btn is-primary is-sm" onClick={() => void save()} disabled={saving}>
              <span className="mem-wide">{saving ? 'Saving…' : draft ? 'Save record' : 'Save version'}</span><span className="mem-narrow">{saving ? 'Saving…' : 'Save'}</span>
            </button>
          </>
        )}
        <button type="button" className={'mem-infobtn' + (infoOpen ? ' is-on' : '')} aria-label="Information" title="Information" aria-pressed={infoOpen}
          onClick={() => { setInfoOpen(!infoOpen); setMore(false); }}>
          <Ico d={ICON.info} sw={1.5} /><span>Info</span>
        </button>
        {rec && ((rec.status === 'active' && canWrite) || canDelete) && (
          <div className="mem-pop-wrap">
            <button type="button" className="mem-morebtn" aria-label="More actions" title="More" aria-haspopup="menu" aria-expanded={more} onClick={() => setMore(!more)}>⋯</button>
            {more && (
              <>
                <div className="mem-pop-scrim" onClick={() => setMore(false)} />
                <div className="mem-menu is-right" role="menu">
                  {rec.status === 'active' && canWrite && <button type="button" role="menuitem" onClick={() => { setMore(false); setConfirmErr(''); setConfirm('forget'); }}>Forget record</button>}
                  {canDelete && <button type="button" role="menuitem" className="is-danger" onClick={() => { setMore(false); setConfirmErr(''); setConfirm('erase'); }}>Erase record</button>}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      <div className="mem-rec-main">
        <div className="mem-rec-scroll">
          {viewing && (
            <div className="mem-viewing">
              <span className="mem-viewing-what">
                {[`v${viewing.version}`, whenOf(viewing.time?.written_at), who(viewing.written_by), str(viewing.attributes?.revision_reason)].filter(Boolean).join(' · ')}
              </span>
              <span className="mem-grow" />
              <button type="button" className="mem-textbtn" onClick={() => setViewV(null)}>Back to current</button>
              {editableOf(rec) && <button type="button" className="mem-btn is-primary is-sm" disabled={saving} onClick={() => void restore()}>{saving ? 'Restoring…' : 'Restore this version'}</button>}
            </div>
          )}
          {err && <div className="mem-banner is-err" role="alert">{err}</div>}
          {!draft && !rec ? (
            <div className="mem-doc" aria-busy="true"><SkelLine w="60%" h={30} /><SkelLine w="40%" h={12} style={{ marginTop: 26, display: 'block' }} /><SkelLine w="90%" h={12} style={{ marginTop: 34, display: 'block' }} /><SkelLine w="80%" h={12} style={{ marginTop: 12, display: 'block' }} /></div>
          ) : (
            <div className="mem-doc">
              <div key={`t${docKey}${viewing ? 'v' + viewing.version : ''}`} className="mem-title" role="textbox" aria-label="Title" aria-readonly={!editable}
                contentEditable={editable ? 'plaintext-only' : false} suppressContentEditableWarning spellCheck={false} data-placeholder="Untitled"
                onInput={(e) => { const el = e.currentTarget; if (!el.textContent && el.childNodes.length) el.innerHTML = ''; titleText.current = el.textContent || ''; touch(); }}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); const first = blocks[0] && els.current[blocks[0].id]; if (first) placeCaret(first, 0); } }}>
                {viewing ? viewing.title : title0}
              </div>

              <div className="mem-props">
                <div className="mem-prop">
                  <span className="mem-prop-k">Type</span>
                  <div className="mem-pop-wrap">
                    {draft ? (
                      <button type="button" className={'mem-typebtn' + (typeMenu ? ' is-open' : '')} aria-haspopup="listbox" aria-expanded={typeMenu} onClick={() => setTypeMenu(!typeMenu)}>
                        <i style={{ background: typeColor(effType) }} /><span>{typeOne(effType)}</span><Caret className="mem-caret-s" />
                      </button>
                    ) : (
                      <span className="mem-typebtn is-static" title="A record keeps the type it was written with"><i style={{ background: typeColor(effType) }} /><span>{typeOne(effType)}</span></span>
                    )}
                    {typeMenu && (
                      <>
                        <div className="mem-pop-scrim" onClick={() => setTypeMenu(false)} />
                        <div className="mem-menu mem-typemenu" role="listbox" aria-label="Type">
                          {WRITABLE_TYPES.map((t) => (
                            <button key={t} type="button" role="option" aria-selected={t === type} className={t === type ? 'is-on' : ''} onClick={() => { setType(t); setTypeMenu(false); }}>
                              <i style={{ background: typeColor(t) }} />
                              <span><b>{TYPE_INFO[t].one}</b><em>{TYPE_INFO[t].hint}</em></span>
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                  {draft && <span className="mem-prop-hint mem-ell">{TYPE_INFO[effType]?.hint}</span>}
                </div>
                {effType === 'link' && (
                  <div className="mem-prop">
                    <span className="mem-prop-k">Address</span>
                    {editable
                      ? <input className="mem-prop-url" value={attrs.url} aria-label="Address" placeholder="https://" onChange={(e) => { setAttrs({ ...attrs, url: e.target.value }); touch(); }} />
                      : <span className="mem-prop-urltext mem-ell">{str((viewing || rec)?.attributes?.url) || '—'}</span>}
                  </div>
                )}
                {effType === 'entity' && (
                  <div className="mem-prop">
                    <span className="mem-prop-k">Kind</span>
                    <div className="mem-seg" role="radiogroup" aria-label="Kind">
                      {KINDS.map((k) => (
                        <button key={k} type="button" role="radio" aria-checked={attrs.kind === k} className={attrs.kind === k ? 'is-on' : ''} disabled={!editable}
                          onClick={() => { setAttrs({ ...attrs, kind: k }); touch(); }}>{capWord(k)}</button>
                      ))}
                    </div>
                  </div>
                )}
                {isRelation && (
                  <div className="mem-prop">
                    <span className="mem-prop-k">Relation</span>
                    <div className="mem-prop-chips">
                      {refChip(subject)}
                      <span className="mem-rel-pred">{str(rec?.attributes?.predicate).replace(/_/g, ' ')}</span>
                      {refChip(object)}
                    </div>
                  </div>
                )}
                {hasAbout && (
                  <div className="mem-prop">
                    <span className="mem-prop-k">About</span>
                    <div className="mem-prop-chips">
                      {about.map((f, i) => {
                        if (!f.available || !f.record_id) return <span key={'u' + i} className="mem-chip is-off">Unavailable to you</span>;
                        const name = names[f.record_id];
                        const text = name === undefined ? '…' : name ?? 'Unavailable to you';
                        return (
                          <span key={f.record_id} className="mem-chip">
                            <button type="button" onClick={() => onOpenRecord(f.memory_id, f.record_id)}><i style={{ background: typeColor('entity') }} />{text}</button>
                            {editable && <button type="button" className="mem-chip-x" aria-label={`Remove ${text}`} onClick={() => { setRefs(refs.filter((o) => o !== f)); setRefsDirty(true); touch(); }}>✕</button>}
                          </span>
                        );
                      })}
                      {about.length === 0 && !editable && <span className="mem-muted">Nothing yet</span>}
                      {editable && (
                        <select className="mem-about-add" value="" aria-label="Link to an entity" disabled={options.length === 0}
                          onChange={(e) => {
                            const t = entities.find((o) => o.id === e.target.value);
                            if (!t) return;
                            setRefs([...refs, { rel: 'about', record_id: t.id, memory_id: t.memory_id, available: true }]); setRefsDirty(true); touch();
                          }}>
                          <option value="">{options.length ? '+ Entity' : 'No entities to link yet'}</option>
                          {options.map((o) => <option key={o.id} value={o.id}>{labelOf(o) || 'Untitled'}</option>)}
                        </select>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {shown.map((b, i) => (
                <div key={b.id} className={'mem-block is-' + b.t}>
                  {editable && (
                    <span className="mem-block-ctl">
                      <button type="button" aria-label="Add a block below" title="Add a block below" onClick={() => addBelow(i, 'p', '')}>+</button>
                    </span>
                  )}
                  <div ref={(el) => { els.current[b.id] = el; }} className="mem-block-text" role={editable ? 'textbox' : undefined} aria-multiline={editable ? true : undefined}
                    aria-label={editable ? (b.t === 'h2' ? 'Heading' : b.t === 'li' ? 'List item' : 'Paragraph') : undefined}
                    contentEditable={editable ? 'plaintext-only' : false} suppressContentEditableWarning spellCheck={false}
                    data-placeholder={editable ? (draft && shown.length === 1 ? 'Write it down. Agents read all of it.' : 'Write something') : undefined}
                    onInput={(e) => onBlockInput(b, e.currentTarget)} onKeyDown={(e) => onBlockKey(e, b, i)}>
                    {b.x}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {infoOpen && (
          <aside className="mem-info" aria-label="Information">
            <div className="mem-info-head">
              <span>Information</span>
              <button type="button" className="mem-xbtn" aria-label="Close information" onClick={() => setInfoOpen(false)}>✕</button>
            </div>
            <div className="mem-info-sec">
              <button type="button" aria-expanded={sec.details} onClick={() => setSec({ ...sec, details: !sec.details })}><Caret open={sec.details} /><span>Details</span></button>
              {sec.details && (
                <dl>
                  <div><dt>Memory</dt><dd>{path.map((m) => m.name).join(' / ')}</dd></div>
                  <div><dt>Written by</dt><dd>{draft ? 'You' : who(rec?.written_by)}</dd></div>
                  {rec?.written_by?.on_behalf_of && <div><dt>How</dt><dd>{`On behalf of ${who({ kind: 'member', id: rec.written_by.on_behalf_of })}`}</dd></div>}
                  {hidden.map((f, i) => <div key={i}><dt>{f.rel ? capWord(f.rel) : 'Reference'}</dt><dd>Something you may not open</dd></div>)}
                  <div><dt>Last written</dt><dd>{draft ? 'Not saved yet' : whenOf(rec?.time?.written_at)}</dd></div>
                  {rec && <div><dt>Version</dt><dd>{`v${rec.version}`}</dd></div>}
                  {rec && rec.status !== 'active' && <div><dt>Status</dt><dd>{capWord(rec.status)}</dd></div>}
                </dl>
              )}
            </div>
            {rec && (
              <div className="mem-info-sec">
                <button type="button" aria-expanded={sec.history} onClick={() => setSec({ ...sec, history: !sec.history })}><Caret open={sec.history} /><span>Version history</span></button>
                {sec.history && (!keepsHistory ? (
                  <p className="mem-info-none">{`${engineName(memory.provider)} keeps no earlier versions.`}</p>
                ) : historyErr ? (
                  <p className="mem-info-none">{historyErr}</p>
                ) : !history ? (
                  <p className="mem-info-none" aria-busy="true"><SkelLine w={150} h={10} /></p>
                ) : (
                  <div className="mem-versions">
                    {history.map((h) => {
                      const current = h.version === rec.version;
                      const on = viewV === null ? current : viewV === h.version;
                      const why = str(h.attributes?.revision_reason);
                      return (
                        <button key={h.version} type="button" className={on ? 'is-on' : ''} aria-current={on}
                          onClick={() => {
                            if (current) setViewV(null); else { if (viewV === null) syncDoc(); setViewV(h.version); }
                            // where the panel covers the whole record (a phone), choosing a version
                            // closes it: the version, and what can be done with it, are underneath
                            if (width < 520) setInfoOpen(false);
                          }}>
                          <span className="mem-version-top"><b>{`v${h.version}`}</b><span>{whenOf(h.time?.written_at)}</span>{current && <em>Current</em>}</span>
                          <span className="mem-version-by">{who(h.written_by)}</span>
                          {why && <span className="mem-version-why">{why}</span>}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
          </aside>
        )}
      </div>

      {confirm === 'forget' && (
        <ConfirmDialog title="Forget this record?" body="It stops appearing in search and to agents. Its history is kept." label={saving ? 'Forgetting…' : 'Forget'} tone="accent"
          busy={saving} error={confirmErr} onConfirm={() => void doConfirm()} onCancel={() => setConfirm(null)} />
      )}
      {confirm === 'erase' && (
        <ConfirmDialog title="Erase this record?" body="Its content and every earlier version are destroyed. This cannot be recovered." label={saving ? 'Erasing…' : 'Erase 1 record'} needsAck
          busy={saving} error={confirmErr} onConfirm={() => void doConfirm()} onCancel={() => setConfirm(null)} />
      )}
    </div>
  );
}
