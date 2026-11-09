'use client';
// One record (the design's mmDocHtml): its title, properties and text, and its version; who wrote it and what the
// engine kept beside it (the task, the model) are under Details, for operators. What a person
// can change follows caps.ts: a record a provider found reads as found, and an action the provider does not serve is
// not drawn. An open record is a live document: everyone who has it open edits it together and sees what an agent
// writes as it lands, and it's written back to the memory, as a new version, in the pauses. A record not made yet is
// plain fields until its author leaves them. Its properties are written as they change.
import dynamic from 'next/dynamic';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { LOCAL_MEMBER } from '@/lib/edition';
import { getSession } from '@/lib/auth';
import {
  addRecord, bodyOf, eraseRecords, forgetRecord, getHistory, labelOf, recordFileUrl, reviseRecord,
  type ContentPart, type Memory, type MemoryRecord, type Provider, type RecordInput,
} from '@/lib/memories';
import { ConfirmSheet, Sheet, SheetTop } from '../Sheet';
import { ago } from '../setups';
import { plain, plural } from '../setup/settingsModel';
import { toast } from '../toast';
import {
  canEdit, canErase, canForget, hasFolders, hasHistory, hasProperties, kindOf, labelsOf, readOnlyNote, recordTypeOfSchemaKind, relText, schemaGuides, sentenceFirst,
} from './caps';
import { DOTS, HISTORY, Dot, shownName, whenOf } from './parts';
import { LiveTitle } from './editor/LiveTitle';
import { useLiveRecord, useLiveText } from './editor/liveRecord';
import { peerColor } from './editor/presence';
import { typeLabel, choicesOf, type LSchema } from './schemaModel';
import { folderOf, kindInfo } from './tree';
import { vendorName } from './vendors';

const DocEditor = dynamic(() => import('./editor/DocEditor').then((m) => m.DocEditor), { ssr: false, loading: () => <p className="mm-muted">Opening…</p> });

/** The record's fields a person does not read as a field of their own. */
const NOT_A_ROW = new Set(['entity_type', 'folder', 'labels', 'predicate']);

/** Who wrote a record, in a person's words. */
function writerOf(r: MemoryRecord, setups: Map<string, string> | null): string {
  const w = r.written_by;
  if (!w) return '';
  if (w.kind === 'provider') return `Found by ${vendorName(w.id)}`;
  const named = setups?.get(w.id);
  if (named) return named;
  const me = getSession()?.member;
  if (w.id === LOCAL_MEMBER || (me && (w.id === me.email || w.id === me.id))) return 'You';
  return w.id?.startsWith('chrn_') ? 'An agent' : w.id || '';
}

const asText = (v: unknown) => (v == null ? '' : typeof v === 'string' ? v : typeof v === 'number' || typeof v === 'boolean' ? String(v) : JSON.stringify(v));
/** A text field's words as the record's parts: files keep their place behind the text. */
const contentWith = (r: MemoryRecord, text: string): ContentPart[] => [
  ...(text.trim() ? [{ type: 'text', text }] : []),
  ...(r.content || []).filter((p) => p.type !== 'text'),
];

export function RecordDoc({ memory, provider, record, schema, setups, links, folders, onSaved, onGone }: {
  memory: Memory; provider: Provider | null; record: MemoryRecord; schema: LSchema | null; setups: Map<string, string> | null;
  links: number; folders: string[]; onSaved: (r: MemoryRecord) => void; onGone: (id: string) => void;
}) {
  const isNew = !record.id;
  const open = isNew || canEdit(record, provider, memory);
  const forgettable = !isNew && canForget(record, provider, memory);
  const erasable = !isNew && canErase(record, provider, memory);
  const history = !isNew && hasHistory(provider);
  const movable = open && !isNew && hasFolders(provider);
  const typedKinds = schemaGuides(provider) ? schema?.types || [] : [];
  const kindKey = kindOf(record);
  const kind = kindInfo(kindKey, schema);
  const stype = schema?.types.find((t) => t.name === kindKey) || null;
  const props = hasProperties(provider) && stype ? stype.properties : [];

  const [title, setTitle] = useState(record.title);
  const [body, setBody] = useState(bodyOf(record));
  const [attrs, setAttrs] = useState<Record<string, unknown>>(record.attributes || {});
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [pop, setPop] = useState<'' | 'hist' | 'more' | 'type'>('');
  const [versions, setVersions] = useState<MemoryRecord[] | null>(null);
  const [histFailed, setHistFailed] = useState(false);
  const [confirm, setConfirm] = useState<'' | 'forget' | 'erase'>('');
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState('');
  const [leftover, setLeftover] = useState(false);
  const { live, state } = useLiveRecord(memory.id, isNew ? '' : record.id, peerColor);
  const member = getSession()?.member;
  const me = useMemo(() => ({ id: member?.id || member?.email || LOCAL_MEMBER, name: member?.name || member?.email || 'Operator' }), [member?.id, member?.email, member?.name]);
  const titleEl = useRef<HTMLHeadingElement | null>(null);
  const toBody = useRef(false);
  const bodyEl = useRef<HTMLTextAreaElement | null>(null);
  const barPops = useRef<HTMLDivElement | null>(null);
  const typePop = useRef<HTMLSpanElement | null>(null);

  // a new version of this record: the fields read it again, except the text being typed right now
  const typing = useRef(false);
  typing.current = editing;
  useEffect(() => {
    setTitle(record.title); setAttrs(record.attributes || {});
    if (!typing.current) setBody(bodyOf(record));
    setErr(''); setVersions(null); setHistFailed(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record.version]);
  useLayoutEffect(() => {
    const t = bodyEl.current;
    if (!t) return;
    t.style.height = 'auto';
    t.style.height = `${t.scrollHeight}px`;
  }, [editing, body]);
  useEffect(() => {
    if (!pop) return;
    const down = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!barPops.current?.contains(t) && !typePop.current?.contains(t)) setPop('');
    };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setPop(''); };
    document.addEventListener('mousedown', down);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key); };
  }, [pop]);

  const write = async (patch: RecordInput, next?: { title?: string; body?: string; attrs?: Record<string, unknown> }) => {
    const t = next?.title ?? title, b = next?.body ?? body, a = next?.attrs ?? attrs;
    if (isNew && !t.trim() && !b.trim()) return;   // nothing to keep yet
    setSaving(true); setErr('');
    try {
      const out = isNew
        ? await addRecord(memory.id, { type: record.type, ...(t.trim() ? { title: t.trim() } : {}), ...(b.trim() ? { content: b } : {}), attributes: a })
        : await reviseRecord(memory.id, record.id, patch);
      onSaved(out);
    } catch (e) { setErr(plain(e, 'That was not saved. Try again.')); } finally { setSaving(false); }
  };
  const saveTitle = (to: EventTarget | null) => {
    const v = (titleEl.current?.textContent || '').replace(/\s+/g, ' ').trim();
    if (v === title) { if (!isNew || !v) return; }
    setTitle(v);
    // a new record is made once its author leaves it, not between its title and its text
    if (isNew && ((to as Element | null)?.closest?.('.mm-doc-col') || toBody.current)) return;
    void write({ title: v }, { title: v });
  };
  const saveBody = () => {
    setEditing(false);
    if (isNew) { void write({}); return; }
    if (body === bodyOf(record)) return;
    void write({ content: contentWith(record, body) });
  };
  const setProp = (name: string, value: unknown) => {
    const next = { ...attrs, [name]: value };
    setAttrs(next);
    void write({ attributes: { [name]: value } }, { attrs: next });
  };
  const propOfText = (t: string, v: string): unknown => {
    if (!v) return null;
    if (t === 'number') { const n = Number(v); return Number.isFinite(n) ? n : v; }
    if (t === 'yesno') return v === 'Yes';
    return v;
  };

  const openHistory = async () => {
    const on = pop === 'hist';
    setPop(on ? '' : 'hist');
    if (on || versions) return;
    setHistFailed(false);
    try { setVersions(await getHistory(memory.id, record.id)); } catch { setHistFailed(true); }
  };
  const forget = async () => {
    setBusy(true); setRefused('');
    try { await forgetRecord(memory.id, record.id); toast(`${short(record)} forgotten`); setConfirm(''); onGone(record.id); }
    catch (e) { setRefused(plain(e, 'It was not forgotten. Try again.')); } finally { setBusy(false); }
  };
  const erase = async () => {
    setBusy(true); setRefused('');
    try {
      const res = await eraseRecords(memory.id, [record.id]);
      setConfirm('');
      if (res.unreachable?.includes(record.id)) setLeftover(true);
      else { toast(`${short(record)} erased`); onGone(record.id); }
    } catch (e) { setRefused(plain(e, 'It was not erased. Try again.')); } finally { setBusy(false); }
  };
  const move = (path: string) => { setPop(''); void write({ attributes: { folder: path } }); toast(path ? `Moved to ${path}` : `Moved to ${memory.name}`); };

  const sentence = sentenceFirst({ type: record.type, title });
  const writable = open && (isNew || (!!state?.canWrite && !state?.gone));
  const liveText = useLiveText(live);
  const savedWord = saving || state?.saving === 'saving' ? 'Saving…' : isNew ? 'Not saved yet'
    : state?.link === 'lost' ? 'Reconnecting…' : state?.saving === 'unsaved' ? 'Not saved yet, trying again' : state?.saving === 'refused' ? 'Not saved'
      : `Saved · v${state?.version ?? record.version}`;
  const note = readOnlyNote(record);
  const counted = !isNew && live && state?.synced ? liveText : body;
  const when = whenOf(record.time?.written_at);
  const who = writerOf(record, setups);
  const extra = Object.entries(attrs).filter(([k, v]) => !NOT_A_ROW.has(k) && !props.some((p) => p.name === k) && v != null && v !== '');
  const labels = labelsOf({ attributes: attrs });
  const predicate = String(attrs.predicate || '');
  const files = (record.content || []).map((p, i) => [p, i] as const).filter(([p]) => p.type === 'file');
  const crumbs = folderOf({ attributes: attrs });

  const bodyBlock = !isNew ? (
    live && state?.synced ? (
      <div className={`mm-live mm-body${sentence ? ' mm-sentence' : ''}`}>
        <DocEditor doc={live.doc} provider={live} currentUser={me} readOnly={!writable} placeholder={writable ? 'Write it down. Setups read all of it.' : ''} />
      </div>
    ) : state?.denied ? <p className="mm-err" role="alert">{state.denied}</p> : <div className={`mm-body${sentence ? ' mm-sentence' : ''}`}>{body ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown> : null}</div>
  ) : open ? (
    editing ? (
      <textarea ref={bodyEl} className={`mm-bodyed${sentence ? ' mm-sentence' : ''}`} aria-label="Text" autoFocus value={body} placeholder="Write it down. Setups read all of it."
        onFocus={(e) => { const n = e.currentTarget.value.length; e.currentTarget.setSelectionRange(n, n); }} onChange={(e) => setBody(e.target.value)} onBlur={saveBody} />
    ) : (
      <div className={`mm-body mm-bodyro${sentence ? ' mm-sentence' : ''}`} role="textbox" aria-label="Text" tabIndex={0} data-ph="Write it down. Setups read all of it."
        onFocus={() => setEditing(true)} onClick={() => setEditing(true)}>
        {body ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown> : null}
      </div>
    )
  ) : (
    <div className={`mm-body${sentence ? ' mm-sentence' : ''}`}>{body ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown> : null}</div>
  );

  return (
    <>
      <div className="mm-doc-bar" ref={barPops}>
        <div className="mm-crumbs">
          <span className="mm-cr">{shownName(memory)}</span>
          {crumbs.split('/').filter(Boolean).map((c, i) => <span key={i} className="mm-crw"><span className="mm-crs">/</span><span className="mm-cr">{c}</span></span>)}
        </div>
        {state?.people.length ? (
          <span className="mm-peers" aria-label={`Also here: ${state.people.map((p) => p.name).join(', ')}`}>
            {state.people.slice(0, 5).map((p) => <span key={p.id} className={`mm-peer${p.agent ? ' agent' : ''}`} style={{ background: p.color }} title={p.name}>{p.name.slice(0, 1).toUpperCase()}</span>)}
          </span>
        ) : null}
        <span className="mm-saved" role="status">{savedWord}</span>
        {history ? (
          <span className="mm-popw">
            <button type="button" className="icon-btn sm" aria-label="Versions" title="Versions" aria-expanded={pop === 'hist'} onClick={() => void openHistory()}>{HISTORY}</button>
            {pop === 'hist' ? (
              <div className="mm-pop mm-pop-r" role="menu">
                <div className="mm-pop-h">Versions</div>
                {histFailed ? <p className="mm-pop-p" role="alert">The versions could not be read just now.</p> : !versions ? <p className="mm-pop-p">Loading…</p> : versions.length ? [...versions].sort((a, b) => b.version - a.version).map((v, i) => {
                  const at = whenOf(v.time?.written_at);
                  return (
                    <div key={v.version} className={`mm-vr${i === 0 ? ' cur' : ''}`}>
                      <b className="mono">{`v${v.version}`}</b>
                      <span>{writerOf(v, setups)}{at ? <small>{ago(at)}</small> : null}</span>
                      {i === 0 ? <em>Current</em> : null}
                    </div>
                  );
                }) : <p className="mm-pop-p">No earlier versions.</p>}
              </div>
            ) : null}
          </span>
        ) : null}
        {forgettable || erasable || movable ? (
          <span className="mm-popw">
            <button type="button" className="icon-btn sm" aria-label="More" title="More" aria-expanded={pop === 'more'} onClick={() => setPop(pop === 'more' ? '' : 'more')}>{DOTS}</button>
            {pop === 'more' ? (
              <div className="mm-pop mm-pop-r" role="menu">
                {movable ? (
                  <>
                    <label className="mm-mv"><span>Move to</span>
                      <select className="set-in slim" value={folderOf({ attributes: attrs })} onChange={(e) => move(e.target.value)}>
                        <option value="">{memory.name}</option>
                        {folders.map((f) => <option key={f} value={f}>{f.split('/').join(' / ')}</option>)}
                      </select>
                    </label>
                    {forgettable || erasable ? <div className="mm-pop-sep" /> : null}
                  </>
                ) : null}
                {forgettable ? (
                  <button type="button" className="mm-mi" role="menuitem" onClick={() => { setPop(''); setRefused(''); setConfirm('forget'); }}>
                    <b>Forget</b><small>{history ? 'Agents stop seeing it. Its history stays.' : 'Agents stop seeing it.'}</small>
                  </button>
                ) : null}
                {erasable ? (
                  <button type="button" className="mm-mi bad" role="menuitem" onClick={() => { setPop(''); setRefused(''); setConfirm('erase'); }}>
                    <b>Erase</b><small>Destroys it and every version. Cannot be undone.</small>
                  </button>
                ) : null}
              </div>
            ) : null}
          </span>
        ) : null}
      </div>
      <div className="mm-doc-scroll">
        <article className="mm-doc-col">
          {state?.gone ? <p className="mm-ronote" role="status">This record was forgotten. What it said stays here until you leave.</p> : null}
          {sentence ? bodyBlock : !isNew && live && state?.synced ? (
            <LiveTitle key={record.id} text={live.doc.getText('title')} readOnly={!writable} className="mm-title" placeholder="Untitled" />
          ) : open ? (
            <h1 key={record.id} ref={titleEl} className="mm-title" contentEditable="plaintext-only" suppressContentEditableWarning spellCheck={false} role="textbox" aria-label="Title" data-ph="Untitled"
              onBlur={(e) => { saveTitle(e.relatedTarget); toBody.current = false; }} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); toBody.current = true; (e.currentTarget as HTMLElement).blur(); setEditing(true); } }}>{record.title}</h1>
          ) : <h1 className="mm-title">{record.title}</h1>}
          {err || state?.refused ? <p className="mm-err" role="alert">{err || state?.refused}</p> : null}
          <div className={`mm-props${sentence ? ' after-sentence' : ''}`}>
            <div className="mm-prow">
              <label>Type</label>
              {open && typedKinds.length && record.type === recordTypeOfSchemaKind(provider) ? (
                <span className="mm-popw" ref={typePop}>
                  <button type="button" className="mm-type" aria-expanded={pop === 'type'} onClick={() => setPop(pop === 'type' ? '' : 'type')}><span className="mm-dot sm" style={{ background: kind.color }} />{kind.one}<span className="mm-chev">▾</span></button>
                  {pop === 'type' ? (
                    <div className="mm-pop" role="menu">
                      {typedKinds.map((t) => (
                        <button key={t.id} type="button" className={`mm-mi row${t.name === kindKey ? ' on' : ''}`} role="menuitem" onClick={() => { setPop(''); if (t.name !== kindKey) setProp('entity_type', t.name); }}>
                          <Dot color={t.color} icon={t.icon} />{typeLabel(t.name)}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </span>
              ) : <span className="mm-pv mm-typev"><span className="mm-dot sm" style={{ background: kind.color }} />{kind.one}</span>}
            </div>
            {props.map((p) => {
              const v = attrs[p.name];
              const id = `mmp-${p.name}`;
              const shown = p.type === 'yesno' ? (v === true ? 'Yes' : v === false ? 'No' : '') : asText(v);
              return (
                <div className="mm-prow" key={p.name}>
                  <label htmlFor={id}>{p.name}</label>
                  {!open ? <span className="mm-pv">{shown || '—'}</span> : p.type === 'choice' || p.type === 'yesno' ? (
                    <select id={id} className="mm-pin" value={shown} onChange={(e) => setProp(p.name, propOfText(p.type, e.target.value))}>
                      <option value="">Empty</option>
                      {(p.type === 'yesno' ? ['Yes', 'No'] : choicesOf(p.options)).map((o) => <option key={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input key={`${record.id}.${record.version}.${p.name}`} id={id} className="mm-pin" type={p.type === 'date' ? 'date' : p.type === 'number' ? 'number' : 'text'} defaultValue={shown} placeholder="Empty"
                      onBlur={(e) => { const val = e.target.value; if (val !== shown) setProp(p.name, propOfText(p.type, val)); }} />
                  )}
                </div>
              );
            })}
            {labels.length ? (
              <div className="mm-prow"><label>Labels</label><span className="mm-labs">{labels.map((l) => <span key={l} className="mm-lab">{typeLabel(l)}</span>)}</span></div>
            ) : null}
            {predicate ? <div className="mm-prow"><label>Relation</label><span className="mm-pv mm-pred">{relText(predicate)}</span></div> : null}
            {record.time?.valid_from ? <div className="mm-prow"><label>True from</label><span className="mm-pv">{record.time.valid_from.slice(0, 10)}</span></div> : null}
            {record.time?.valid_to ? <div className="mm-prow"><label>True until</label><span className="mm-pv">{record.time.valid_to.slice(0, 10)}</span></div> : null}
          </div>
          {note ? <p className="mm-ronote">{note}</p> : null}
          {sentence ? null : bodyBlock}
          {files.length ? (
            <div className="mm-files">
              {files.map(([p, i]) => (
                <a key={i} className="mm-file" href={recordFileUrl(memory.id, record.id, i)} download={p.file?.name || undefined}>{p.file?.name || 'File'}</a>
              ))}
            </div>
          ) : null}
          {/* what the engine and the task kept beside it (which task, which model, who wrote it), for operators: out of
              the way of what the record says */}
          {!isNew && (extra.length || who || when) ? (
            <details className="mm-details">
              <summary>Details</summary>
              <div className="mm-props mm-props-d">
                {extra.map(([k, v]) => <div className="mm-prow" key={k}><label title={k}>{k}</label><span className="mm-pv">{asText(v)}</span></div>)}
                <div className="mm-prow"><label>Written by</label><span className="mm-pv">{[who, when ? ago(when) : ''].filter(Boolean).join(' · ') || '—'}</span></div>
              </div>
            </details>
          ) : null}
        </article>
      </div>
      <div className="mm-doc-foot">
        <span>{plural(links, 'link')}</span><span>{plural(counted.split(/\s+/).filter(Boolean).length, 'word')}</span><span>{`${counted.length.toLocaleString('en-US')} characters`}</span>
      </div>
      {confirm === 'forget' ? (
        <ConfirmSheet id="mmFg" title={`Forget ${short(record) || 'this record'}?`} confirmLabel="Forget" busy={busy} refused={refused || undefined}
          body={history ? 'Setups stop seeing it, and its history is kept.' : 'Setups stop seeing it.'} onClose={() => setConfirm('')} onConfirm={() => void forget()} />
      ) : null}
      {confirm === 'erase' ? (
        <ConfirmSheet id="mmEr" title={`Erase ${short(record) || 'this record'}?`} confirmLabel="Erase" busy={busy} refused={refused || undefined}
          body="Its text, properties and every version are destroyed, along with its links. This cannot be undone." onClose={() => setConfirm('')} onConfirm={() => void erase()} />
      ) : null}
      {leftover ? (
        <Sheet onClose={() => { setLeftover(false); onGone(record.id); }} labelledBy="mmLo" className="small-sheet" alert>
          <SheetTop id="mmLo" title="Not all of it could be erased" onClose={() => { setLeftover(false); onGone(record.id); }} />
          <p className="del-p">{`The record is gone from ${memory.name}, but ${vendorName(provider?.id || '')} may still hold its words in what it came from. Remove them there if they must be gone.`}</p>
          <div className="del-act"><button type="button" className="btn" onClick={() => { setLeftover(false); onGone(record.id); }}>Close</button></div>
        </Sheet>
      ) : null}
    </>
  );
}

/** A record's line, short enough for a sheet's title or a toast. */
function short(r: MemoryRecord): string {
  const l = labelOf(r);
  return l.length > 60 ? `${l.slice(0, 59).trim()}…` : l;
}
