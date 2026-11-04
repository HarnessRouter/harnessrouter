'use client';
// One memory (the design's memoryView): back, its name and who keeps it, its id with Copy, "Used by N
// setups", and the tabs, at the right end as on every bar of this console. The tabs are the provider's: Schema where a schema guides it, Labels where it applies
// labels, and no tabs at all where nothing reads one, just Data.
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  deleteMemory, getHarnessMemories, getMemory, listGrants, listRecords, MemoryApiError,
  type Grant, type Memory, type MemoryRecord,
} from '@/lib/memories';
import { ConfirmSheet } from '../Sheet';
import { Skel, SkHead, SkRows } from '../Skel';
import { plain, plural } from '../setup/settingsModel';
import { tabKeys } from '../tabKeys';
import { toast } from '../toast';
import { hasSchema, kindOf, schemaLabels, schemaTab, schemaWord } from './caps';
import { DataTab, type RecordsRead } from './DataTab';
import { BACK_IC, COPY, DOTS, setupsOf, useDismiss, useProviders, useSetupNames } from './parts';
import { LabelsTab, SchemaTab } from './SchemaTab';
import { ConnectSheet, RenameSheet } from './sheets';
import { useSchemaDoc } from './useSchemaDoc';
import { vendorName } from './vendors';
import './memories.css';

const enc = encodeURIComponent;
const PAGE = 200;

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

export function MemoryPage({ id, tabParam, recordParam, onTab }: { id: string; tabParam: string | null; recordParam: string | null; onTab: (t: 'schema' | 'data') => void }) {
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
  const guided = hasSchema(provider);
  const ro = !memory?.privileges?.includes('write');

  // the tab: Schema only where a schema is read; with none asked for, a memory with nothing in it opens
  // on its schema and any other on its data
  const empty = (memory?.records?.count ?? 1) === 0;
  const tab: 'schema' | 'data' = guided && (tabParam === 'schema' || tabParam === 'labels' || (!tabParam && empty)) ? 'schema' : 'data';
  const [typeFilter, setTypeFilter] = useState('');
  // going to Schema and back opens the record that was open
  const openRecord = useRef(recordParam || '');
  const keepOpen = useCallback((rid: string) => { openRecord.current = rid; }, []);

  // "Used by": grants to setups; none of it is drawn when the grants could not be read
  const [grants, setGrants] = useState<Grant[] | null>(null);
  useEffect(() => { listGrants(id).then(setGrants).catch(() => setGrants(null)); }, [id]);
  const users = useMemo(() => (grants && names ? setupsOf(grants, names) : null), [grants, names]);
  const [pop, setPop] = useState<'' | 'users' | 'more'>('');
  const [defaults, setDefaults] = useState<Record<string, boolean>>({});
  const usersWrap = useRef<HTMLDivElement | null>(null);
  const moreWrap = useRef<HTMLSpanElement | null>(null);
  const closePop = useCallback(() => setPop(''), []);
  useDismiss(pop === 'users', usersWrap, closePop);
  useDismiss(pop === 'more', moreWrap, closePop);
  const openUsers = () => {
    setPop(pop === 'users' ? '' : 'users');
    (users || []).forEach((u) => {
      getHarnessMemories(u.id).then((d) => setDefaults((m) => ({ ...m, [u.id]: d.default_memory_id === id }))).catch(() => {});
    });
  };

  const [sheet, setSheet] = useState<'' | 'rename' | 'delete' | 'connect'>('');
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState('');
  const remove = async () => {
    setBusy(true); setRefused('');
    try { await deleteMemory(id); toast(`${memory?.name} deleted`); router.push('/memories'); }
    catch (e) { setRefused(plain(e, 'The memory was not deleted. Try again.')); setBusy(false); }
  };

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
  const line = [guided && doc.schema ? plural(doc.schema.types.length, schemaWord(provider)) : '', m.records?.count != null ? plural(m.records.count, 'record') : ''].filter(Boolean).join(' · ');
  const copy = async () => {
    try { await navigator.clipboard.writeText(m.id); toast('Memory ID copied'); }
    catch { toast('Text selected. Press Cmd or Ctrl + C.'); }
  };
  const tabs: ['schema' | 'data', string][] = [['schema', schemaTab(provider)], ['data', 'Data']];
  const canRename = !!m.privileges?.includes('write'), canDelete = !!m.privileges?.includes('delete');
  const disconnected = provider ? provider.connected === false : true;

  return (
    <div className="tk-page mm-page">
      <header className="ag-bar ag-rt">
        <div className="ag-lft">
          <Link className="ag-back" href="/memories" aria-label="Back to Memories" title="Memories">{BACK_IC}</Link>
          <div className="ag-ident">
            <div className="ag-l1"><h1 className="ag-name" title={m.name}>{m.name}</h1><span className="pill neutral">{vendorName(m.provider)}</span></div>
            <div className="ag-l2">
              {line ? <span className="mm-l2d">{line}</span> : null}
              {line ? <span className="sep sep-id" aria-hidden="true">·</span> : null}
              <span className="hid ag-hid"><span className="mono">{m.id}</span><button type="button" className="icon-btn xs" aria-label="Copy memory ID" title="Copy memory ID" onClick={() => void copy()}>{COPY}</button></span>
            </div>
          </div>
        </div>
        <div className="ag-right mm-rights">
          {users ? (
            <div className="mm-right" ref={usersWrap}>
              <button type="button" className="btn small line" aria-expanded={pop === 'users'} onClick={openUsers}>{users.length ? `Used by ${plural(users.length, 'setup')}` : 'Not used yet'}</button>
              {pop === 'users' ? (
                <div className="mm-pop mm-pop-r" role="menu">
                  {users.length ? users.map((u) => (
                    <button key={u.id} type="button" className="mm-mi" role="menuitem" onClick={() => router.push(`/studio/${enc(u.id)}?tab=settings&layer=memory`)}>
                      <b>{u.name}</b><small>{u.grant.privileges.includes('write') ? 'Reads and writes' : 'Reads'}{defaults[u.id] ? ' · writes here by default' : ''}</small>
                    </button>
                  )) : <p className="mm-pop-p">Give it to a setup in that setup’s Settings, under Memory.</p>}
                </div>
              ) : null}
            </div>
          ) : null}
          {canRename || canDelete ? (
            <span className="mm-popw" ref={moreWrap}>
              <button type="button" className="icon-btn sm" aria-label="More" title="More" aria-expanded={pop === 'more'} onClick={() => setPop(pop === 'more' ? '' : 'more')}>{DOTS}</button>
              {pop === 'more' ? (
                <div className="mm-pop mm-pop-r" role="menu">
                  {canRename ? <button type="button" className="mm-mi" role="menuitem" onClick={() => { setPop(''); setSheet('rename'); }}><b>Rename and describe</b></button> : null}
                  {canDelete ? <button type="button" className="mm-mi bad" role="menuitem" onClick={() => { setPop(''); setRefused(''); setSheet('delete'); }}><b>Delete memory</b></button> : null}
                </div>
              ) : null}
            </span>
          ) : null}
        </div>
        {guided ? (
          <div className="tabs inline ag-tabs" role="tablist" onKeyDown={(e) => tabKeys(e, tabs.map(([k]) => k), tab, onTab)}>
            {tabs.map(([k, label]) => <button key={k} type="button" role="tab" aria-selected={tab === k} tabIndex={tab === k ? 0 : -1} className={tab === k ? 'on' : ''} onClick={() => onTab(k)}>{label}</button>)}
          </div>
        ) : null}
      </header>
      {disconnected ? (
        <div className="conn-stale" role="alert">
          <span className="grow">{`${vendorName(m.provider)} is not connected, so what ${m.name} keeps can’t be read.`}</span>
          <button type="button" className="btn small" onClick={() => setSheet('connect')}>Connect</button>
        </div>
      ) : null}
      {tab === 'schema' && provider ? (
        schemaLabels(provider) ? <LabelsTab provider={provider} doc={doc} ro={ro} /> : (
          <SchemaTab memory={m} provider={provider} doc={doc} ro={ro} countOf={countOf}
            onOpenData={(t) => { setTypeFilter(t); onTab('data'); }} />
        )
      ) : (
        <DataTab memory={m} provider={provider} schema={doc.schema} read={read} setups={names} typeFilter={typeFilter} initialRecord={openRecord.current} onOpenRecord={keepOpen}
          onSchema={() => onTab('schema')} onOtherMemory={(mid, rid) => router.push(`/memories/${enc(mid)}?tab=data&record=${enc(rid)}`)} onChanged={readMemory} />
      )}
      {sheet === 'rename' ? <RenameSheet m={m} onClose={() => setSheet('')} onDone={(x) => { setMemory({ ...m, ...x }); setSheet(''); toast('Saved'); }} /> : null}
      {sheet === 'delete' ? (
        <ConfirmSheet id="mmDl" title={`Delete ${m.name}?`} confirmLabel="Delete memory" busy={busy} refused={refused || undefined}
          body={`${m.name}, its records and anything below it are destroyed, and setups lose it at once. This cannot be undone.`}
          onClose={() => setSheet('')} onConfirm={() => void remove()} />
      ) : null}
      {sheet === 'connect' ? (
        <ConnectSheet id={m.provider} onClose={() => setSheet('')}
          onConnected={async () => { await reloadProviders(); setSheet(''); readMemory(); read.retry(); toast(`${vendorName(m.provider)} connected.`); }} />
      ) : null}
    </div>
  );
}
