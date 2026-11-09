'use client';
// One memory (the design's memoryView): back, its name and the engine that keeps it, and three tabs (Richard 11-09), as a
// setup's page has Tasks and Settings: Data, what it holds, the open record, and the graph of what connects to what,
// open until a person folds it to the right; Schema, called that for every engine (Richard 11-09: "make them
// consistent called schema"), what it makes itself and what a person sets; Settings, its name and description, its
// ID, the agent harnesses that use it, and Delete. The last thing that failed here is said at the top, in the service's
// words, until something works again. Whatever changes in the memory while this is open, by anyone, comes in on its
// event stream. A person's own memory (below an agent's, kept for one person) says where it sits: under its name, the
// agent's memory, which Back returns to, with when this person's was last used.
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getMemory, getRecord, listRecords, MemoryApiError, recordHref, type Memory, type MemoryRecord,
} from '@/lib/memories';
import { Skel, SkHead, SkRows } from '../Skel';
import { SETTINGS_IC } from '../setup/parts';
import { tabKeys } from '../tabKeys';
import { toast } from '../toast';
import { keepsLinks, kindOf } from './caps';
import { DataTab, type RecordsRead } from './DataTab';
import { ago } from '../setups';
import { BACK_IC, BADGE, engineOf, msOf, shownName, useProviders, useSetupNames } from './parts';
import { MemorySettings } from './MemorySettings';
import { ConnectSheet } from './sheets';
import { useMemoryEvents, type MemoryEvent } from './editor/useMemoryEvents';
import { useSchemaDoc } from './useSchemaDoc';
import { vendorName } from './vendors';
import './memories.css';

const SchemaEditor = dynamic(() => import('./graph/SchemaEditor').then((m) => m.SchemaEditor), { ssr: false, loading: () => <p className="mm-muted mm-cpad">Drawing the schema…</p> });

const enc = encodeURIComponent;
const PAGE = 200;
export type MemoryTab = 'data' | 'schema' | 'settings';
// the tabs' icons, drawn as a setup's (setup/parts): Data, records as rows; Schema, types joined; Settings, the gear
const DATA_IC = <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6h11M9 12h11M9 18h11" /><path d="M4 6h.01M4 12h.01M4 18h.01" /></svg>;
const SCHEMA_IC = BADGE;
const PULSE_MS = 2500;

function useRecords(mid: string): RecordsRead {
  const [records, setRecords] = useState<MemoryRecord[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const read = useCallback(() => {
    setFailed(false);
    listRecords(mid, { limit: PAGE }).then((d) => { setRecords(d.data); setNext(d.next || null); }).catch(() => setFailed(true));
  }, [mid]);
  useEffect(() => { read(); }, [read]);
  const more = useCallback(() => {
    if (!next) return;
    listRecords(mid, { limit: PAGE, cursor: next }).then((d) => { setRecords((r) => [...(r || []), ...d.data]); setNext(d.next || null); }).catch(() => toast('More records could not be read just now.'));
  }, [mid, next]);
  const put = useCallback((r: MemoryRecord) => setRecords((l) => (l?.some((x) => x.id === r.id) ? l.map((x) => (x.id === r.id ? r : x)) : [r, ...(l || [])])), []);
  const drop = useCallback((id: string) => setRecords((l) => l?.filter((x) => x.id !== id) || null), []);
  return { records, failed, retry: read, more: next ? more : null, put, drop };
}

export function MemoryPage({ id, tabParam, recordParam, inParam = null, onTab }: {
  id: string; tabParam: string | null; recordParam: string | null;
  /** the memory below this one `recordParam` is in (a person's own), where it isn't this one's */
  inParam?: string | null;
  onTab: (t: MemoryTab) => void;
}) {
  const router = useRouter();
  const [memory, setMemory] = useState<Memory | null>(null);
  const [missing, setMissing] = useState(false);
  const [failed, setFailed] = useState(false);
  const { providers, reload: reloadProviders } = useProviders();
  const names = useSetupNames();
  const readMemory = useCallback(() => {
    setFailed(false);
    getMemory(id).then(setMemory).catch((e) => {
      if (e instanceof MemoryApiError && e.status === 404) setMissing(true); else setFailed(true);
    });
  }, [id]);
  useEffect(() => { readMemory(); }, [readMemory]);

  const provider = useMemo(() => (memory ? (providers || []).find((p) => p.id === memory.provider) || null : null), [providers, memory]);
  const doc = useSchemaDoc(id, provider);
  const read = useRecords(id);
  const ro = !memory?.privileges?.includes('write');

  // the open tab is in the address; Data where it names none
  const tab: MemoryTab = tabParam === 'schema' || tabParam === 'labels' ? 'schema' : tabParam === 'settings' ? 'settings' : 'data';
  // the graph has its column wherever there can be one: an engine that keeps links, or records that link
  const linked = useMemo(() => (read.records || []).some((r) => (r.references || []).some((x) => x.available !== false)), [read.records]);
  const [typeFilter, setTypeFilter] = useState('');
  // going to Schema and back opens the record that was open, in the memory it was open in
  const openRecord = useRef({ rid: recordParam || '', in: (recordParam && inParam) || '' });
  const keepOpen = useCallback((rid: string, inMid: string) => { openRecord.current = { rid, in: inMid }; }, []);
  // the open record in the address (DataTab says how): a phone's Back from a record comes back to the list
  const place = useCallback((rid: string, inMid: string, how: 'push' | 'replace') => {
    const to = rid ? recordHref(id, inMid || id, rid) : `/memories/${enc(id)}?tab=data`;
    if (how === 'push') router.push(to, { scroll: false }); else router.replace(to, { scroll: false });
  }, [id, router]);

  // what changes while the page is open: the tree and the graph read it again, and what changed shows for a moment
  const [liveTick, setLiveTick] = useState(0);
  const [pulse, setPulse] = useState<string[]>([]);
  const lit = useCallback((ids: string[]) => {
    if (!ids.length) return;
    setPulse((p) => [...new Set([...p, ...ids])]);
    setTimeout(() => setPulse((p) => p.filter((x) => !ids.includes(x))), PULSE_MS);
  }, []);
  useMemoryEvents(id, (e: MemoryEvent) => {
    if (e.type === 'schema.changed') { doc.retry(); return; }
    setLiveTick((n) => n + 1);
    if (e.type === 'record.created' || e.type === 'record.revised') {
      const rid = e.record_id || '';
      if (rid) getRecord(id, rid).then((r) => { read.put(r); lit([rid]); }).catch(() => undefined);
    } else if (e.type === 'record.forgotten') {
      if (e.record_id) read.drop(e.record_id);
    } else if (e.type === 'records.erased') {
      (e.record_ids || []).forEach((x) => read.drop(x));
    } else {
      read.retry();
      lit(e.record_ids || []);
    }
    if (e.type !== 'record.revised') readMemory();
  });

  // the memory this one is below (a person's own below an agent's): where Back goes, and who uses it
  const parentId = memory?.parent_id || '';
  const [parent, setParent] = useState<Memory | null>(null);
  useEffect(() => {
    if (!parentId) { setParent(null); return undefined; }
    let live = true;
    getMemory(parentId).then((x) => { if (live) setParent(x); }).catch(() => { if (live) setParent(null); });
    return () => { live = false; };
  }, [parentId]);

  const [sheet, setSheet] = useState<'' | 'connect'>('');
  // the tabs, and the keys that move between them, as a setup's
  const tabsRef = useRef<HTMLDivElement | null>(null);
  const refocus = useRef(false);
  useEffect(() => {
    if (!refocus.current) return;
    refocus.current = false;
    tabsRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus();
  }, [tabParam]);

  const countOf = useCallback((typeName: string) => {
    if (!read.records || read.more) return null;
    return read.records.filter((r) => kindOf(r) === typeName).length;
  }, [read.records, read.more]);

  if (missing) {
    return <div className="scroll"><div className="list-wrap lw-n"><div className="empty-list" role="alert">This memory is not here. <Link className="link-q inl" href="/memories">Back to Memories</Link></div></div></div>;
  }
  if (failed) {
    return <div className="scroll"><div className="list-wrap lw-n"><div className="empty-list ws-fail" role="alert">This memory could not be read just now. <button type="button" className="link-q inl" onClick={readMemory}>Try again</button></div></div></div>;
  }
  if (!memory || !providers) {
    return <div className="scroll"><div className="list-wrap lw-n"><Skel label="Loading memory"><SkHead /><SkRows n={4} /></Skel></div></div>;
  }

  const m = memory;
  const disconnected = provider ? provider.connected === false : true;
  const graphOn = keepsLinks(provider) || linked;
  const tabs: MemoryTab[] = provider ? ['data', 'schema', 'settings'] : ['data', 'settings'];
  const tb = (k: MemoryTab, icon: React.ReactNode, label: string) => (
    <button type="button" role="tab" aria-selected={tab === k} tabIndex={tab === k ? 0 : -1} className={tab === k ? 'on' : ''} onClick={() => onTab(k)}>{icon}{label}</button>
  );
  // the last failure, said until something works again after it
  const failedAt = msOf(m.last_error_at), okAt = msOf(m.last_ok_at);
  const failing = !!m.last_error && (!okAt || !failedAt || failedAt > okAt);
  // a person's memory: under the agent's memory it is in, which Back returns to, and when it was last used
  const upHref = m.parent_id ? `/memories/${enc(m.parent_id)}?tab=data` : '/memories';
  const upName = m.parent_id ? (parent ? shownName(parent) : '') : '';
  const lastUsed = m.parent_id ? msOf(m.last_used_at) : null;

  return (
    <div className="tk-page mm-page">
      <header className="ag-bar ag-rt">
        <div className="ag-lft">
          <Link className="ag-back" href={upHref} aria-label={m.parent_id ? `Back to ${upName || 'the memory it is in'}` : 'Back to Memories'} title={m.parent_id ? upName || undefined : 'Memories'}>{BACK_IC}</Link>
          <div className="ag-ident">
            <div className="ag-l1"><h1 className="ag-name" title={m.name}>{shownName(m)}</h1><span className="pill neutral">{vendorName(engineOf(m))}</span></div>
            {m.parent_id && (upName || lastUsed) ? (
              <div className="ag-l2 mm-up">
                {upName ? <Link className="mm-up-l" href={upHref} title={`In ${upName}`}>{upName}</Link> : null}
                {upName && lastUsed ? <span className="sep" aria-hidden="true">·</span> : null}
                {lastUsed ? <span className="mm-up-t">{`Used ${ago(lastUsed)}`}</span> : null}
              </div>
            ) : null}
          </div>
        </div>
        {/* the memory's tabs, where a setup's Tasks and Settings sit */}
        <div ref={tabsRef} className="tabs inline ag-tabs" role="tablist" aria-label="Memory" onKeyDown={(e) => tabKeys(e, tabs, tab, (k) => { refocus.current = true; onTab(k); })}>
          {tb('data', DATA_IC, 'Data')}
          {provider ? tb('schema', SCHEMA_IC, 'Schema') : null}
          {tb('settings', SETTINGS_IC, 'Settings')}
        </div>
      </header>
      {failing ? (
        <div className="conn-stale mm-failing" role="alert">
          <span className="grow">{m.last_error}{failedAt ? <small>{` ${ago(failedAt)}`}</small> : null}</span>
        </div>
      ) : null}
      {disconnected ? (
        <div className="conn-stale" role="alert">
          <span className="grow">{`${vendorName(m.provider)} is not connected, so what ${m.name} keeps can’t be read.`}</span>
          <button type="button" className="btn small" onClick={() => setSheet('connect')}>Connect</button>
        </div>
      ) : null}
      {tab === 'schema' && provider ? (
        <SchemaEditor memory={m} provider={provider} doc={doc} ro={ro} countOf={countOf} onOpenData={(t: string) => { setTypeFilter(t); onTab('data'); }} />
      ) : tab === 'settings' ? (
        <MemorySettings memory={m} onSaved={(x) => setMemory({ ...m, ...x })} onDeleted={() => router.push(m.parent_id ? upHref : '/memories')} />
      ) : (
        <DataTab memory={m} provider={provider} schema={doc.schema} read={read} setups={names} typeFilter={typeFilter} initialRecord={openRecord.current.rid} initialIn={openRecord.current.in} onOpenRecord={keepOpen}
          urlRecord={recordParam} urlIn={inParam} onPlace={place} showGraph={graphOn}
          onSchema={() => onTab('schema')} onOtherMemory={(mid, rid) => router.push(`/memories/${enc(mid)}?tab=data&record=${enc(rid)}`)} onChanged={readMemory}
          onBelowChanged={(ids) => { setLiveTick((x) => x + 1); lit(ids); }} liveTick={liveTick} pulse={pulse} />
      )}
      {sheet === 'connect' ? (
        <ConnectSheet id={m.provider} onClose={() => setSheet('')}
          onConnected={async () => { await reloadProviders(); setSheet(''); readMemory(); read.retry(); toast(`${vendorName(m.provider)} connected.`); }} />
      ) : null}
    </div>
  );
}
