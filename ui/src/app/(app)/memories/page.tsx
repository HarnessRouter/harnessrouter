'use client';
// Memories, per the console design (Memories.dc.html): what the workspace's agents keep from one
// conversation to the next. The home is one card per memory the reader enters at. Inside one,
// a tree on the left holds its memories and their records together, and the right is whatever is
// selected: a memory (its records, its graph, a search of it and everything below) or a record,
// opened in that same place as a document. Where the reader is lives in the address
// (?m=<memory>&r=<record>&view=graph&q=<search>), so a reload or a shared link returns to it.
// Every name, count and control on the page is the service's: the tree is asked for a level at a
// time, each memory says what this reader may do with it, and each engine says what it can do.
import '@/app/memories.css';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { getSession } from '@/lib/auth';
import { listCustom } from '@/lib/harness';
import {
  getMemory, listChildren, listProviders, listRecords, listRoots, updateMemory, MemoryApiError,
  type Memory, type MemoryRecord, type Provider,
} from '@/lib/memories';
import { SkelLine } from '@/components/Skel';
import { engineLine, engineMark, errText, ICON, Ico, makeWho, NameInput } from '@/components/memories/kit';
import { MemoryTree, type TreeRecords } from '@/components/memories/MemoryTree';
import { MemoryPane, type Loc } from '@/components/memories/MemoryPane';
import { RecordEditor } from '@/components/memories/RecordEditor';
import { CreateDialog, DeleteDialog, ShareDialog } from '@/components/memories/MemoryDialogs';

/** How many of a memory's records the tree asks for; the rest are a line that opens the memory. */
const TREE_RECORDS = 8;

export default function MemoriesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const m = params.get('m') || '', r = params.get('r') || '', q = params.get('q') || '';
  const view = params.get('view') === 'graph' ? 'graph' : 'records';

  const [roots, setRoots] = useState<Memory[] | null>(null);
  const [rootsErr, setRootsErr] = useState<Error | null>(null);
  const [mems, setMems] = useState<Record<string, Memory>>({});
  const [kids, setKids] = useState<Record<string, string[] | undefined>>({});
  const [recs, setRecs] = useState<Record<string, TreeRecords | undefined>>({});
  const [open, setOpen] = useState<string[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [harnesses, setHarnesses] = useState<{ id: string; name: string }[]>([]);
  const [selErr, setSelErr] = useState<Error | null>(null);
  const [draftIn, setDraftIn] = useState<string | null>(null);
  const [current, setCurrent] = useState<MemoryRecord | null>(null);
  const [create, setCreate] = useState<{ parent: Memory | null } | null>(null);
  const [share, setShare] = useState<string | null>(null);
  const [del, setDel] = useState<Memory | null>(null);
  const [notice, setNotice] = useState<{ text: string; err?: boolean } | null>(null);
  const [treeOpen, setTreeOpen] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [rev, setRev] = useState(0);
  const loading = useRef(new Set<string>());

  /** Move within the page. Going to another memory leaves the record and the search behind. */
  const go = useCallback((to: Loc, replace = false) => {
    const cur = new URLSearchParams(window.location.search);
    const next: Record<string, string | null | undefined> = { m: cur.get('m'), r: cur.get('r'), view: cur.get('view'), q: cur.get('q') };
    if ('m' in to && (to.m || '') !== (next.m || '')) { next.r = null; next.q = null; }
    Object.assign(next, to);
    if (!next.m) { next.r = null; next.q = null; next.view = null; }
    const qs = new URLSearchParams();
    for (const k of ['m', 'r', 'view', 'q']) if (next[k]) qs.set(k, next[k] as string);
    const url = `/memories${qs.toString() ? `?${qs.toString()}` : ''}`;
    if (replace) router.replace(url, { scroll: false }); else router.push(url, { scroll: false });
  }, [router]);

  const putMems = useCallback((list: Memory[]) => setMems((prev) => ({ ...prev, ...Object.fromEntries(list.map((x) => [x.id, x])) })), []);
  const loadRoots = useCallback(() => listRoots().then((d) => { setRoots(d); putMems(d); setRootsErr(null); }).catch((e) => { setRoots([]); setRootsErr(e); }), [putMems]);
  /** One level of the tree: the memories inside this one, and the first of its records. */
  const loadNode = useCallback(async (id: string) => {
    if (loading.current.has(id)) return;
    loading.current.add(id);
    const [c, rr] = await Promise.allSettled([listChildren(id), listRecords(id, { limit: TREE_RECORDS })]);
    loading.current.delete(id);
    if (c.status === 'fulfilled') { putMems(c.value); setKids((k) => ({ ...k, [id]: c.value.map((x) => x.id) })); }
    else setKids((k) => ({ ...k, [id]: k[id] ?? [] }));
    setRecs((x) => ({ ...x, [id]: rr.status === 'fulfilled' ? { data: rr.value.data, more: Boolean(rr.value.next) } : { data: [], more: false } }));
  }, [putMems]);
  const refreshNode = useCallback(async (id: string) => {
    getMemory(id).then((x) => putMems([x])).catch(() => { /* it may be gone; the tree says so on its own */ });
    await loadNode(id);
  }, [loadNode, putMems]);

  useEffect(() => {
    void loadRoots();
    listProviders().then(setProviders).catch(() => setProviders([]));
    listCustom().then((hs) => setHarnesses(hs.map((h) => ({ id: h.id, name: h.name })))).catch(() => setHarnesses([]));
  }, [loadRoots]);

  // the selected memory and the memories above it, which give the breadcrumb and the tree's top
  useEffect(() => {
    setSelErr(null);
    if (!m) return;
    let alive = true;
    getMemory(m).then(async (mem) => {
      const above = (await Promise.all(mem.ancestors.map((id) => getMemory(id).catch(() => null)))).filter((x): x is Memory => x !== null);
      if (!alive) return;
      putMems([...above, mem]);
      setOpen((o) => [...new Set([...o, ...above.map((a) => a.id), mem.id])]);
    }).catch((e) => { if (alive) setSelErr(e); });
    return () => { alive = false; };
  }, [m, putMems]);

  useEffect(() => { for (const id of open) if (kids[id] === undefined || recs[id] === undefined) void loadNode(id); }, [open, kids, recs, loadNode]);
  useEffect(() => { if (r) setDraftIn(null); }, [r]);
  useEffect(() => { setTreeOpen(false); }, [m, r]);
  useEffect(() => { if (!m) { void loadRoots(); setDraftIn(null); } }, [m, loadRoots]);

  const sel = m ? mems[m] : undefined;
  const above = useMemo(() => (sel ? sel.ancestors.map((id) => mems[id]).filter(Boolean) : []), [sel, mems]);
  const root = sel ? above[0] || sel : undefined;
  const path = useMemo(() => (sel ? [...above, sel] : []), [above, sel]);
  const provider = sel ? providers.find((p) => p.id === sel.provider) : undefined;
  const who = useMemo(() => {
    const me = getSession()?.member;
    return makeWho([me?.id, me?.email].filter((x): x is string => Boolean(x)), (id) => harnesses.find((h) => h.id === id)?.name);
  }, [harnesses]);

  const rename = async (mem: Memory, name: string) => {
    try {
      const x = await updateMemory(mem.id, { name });
      putMems([x]);
      setRoots((rs) => rs?.map((o) => (o.id === x.id ? x : o)) ?? rs);
    } catch (e) { setNotice({ text: errText(e), err: true }); }
  };
  const describe = async (text: string) => {
    if (!sel) return;
    const x = await updateMemory(sel.id, { description: text });
    putMems([x]);
    setRoots((rs) => rs?.map((o) => (o.id === x.id ? x : o)) ?? rs);
  };
  const created = async (mem: Memory) => {
    setCreate(null);
    putMems([mem]);
    if (mem.parent_id) { setOpen((o) => [...new Set([...o, mem.parent_id as string])]); void refreshNode(mem.parent_id); }
    else void loadRoots();
    go({ m: mem.id });
  };
  const deleted = (ids: string[]) => {
    const target = del;
    setDel(null);
    if (!target) return;
    const gone = new Set(ids);
    // the answer lists every memory that went with it
    const names = ids.map((id) => mems[id]?.name).filter(Boolean);
    setNotice({ text: `Deleted ${ids.length} ${ids.length === 1 ? 'memory' : 'memories'}${names.length ? `: ${names.join(', ')}` : ''}.` });
    setOpen((o) => o.filter((id) => !gone.has(id)));
    setKids((k) => Object.fromEntries(Object.entries(k).filter(([id]) => !gone.has(id)).map(([id, v]) => [id, v?.filter((x) => !gone.has(x))])));
    setRoots((rs) => rs?.filter((x) => !gone.has(x.id)) ?? rs);
    if (target.parent_id && mems[target.parent_id]) void refreshNode(target.parent_id);
    if (m && gone.has(m)) go({ m: target.parent_id && mems[target.parent_id] ? target.parent_id : null, r: null, q: null });
    else void loadRoots();
  };
  const changed = useCallback((memoryId: string) => { void refreshNode(memoryId); setRev((v) => v + 1); }, [refreshNode]);

  const newMemory = (parent: Memory | null) => setCreate({ parent });
  const shared = share ? mems[share] : undefined;

  return (
    <section className={'mem' + (m ? ' is-inside' : '')} id="view-memories">
      {!m ? (
        <header className="mem-head">
          <div className="mem-head-row">
            <div style={{ minWidth: 0 }}>
              <h1>Memories</h1>
              <p>What your agents keep from one conversation to the next.</p>
            </div>
            <button type="button" className="mem-newbtn" aria-label="New memory" onClick={() => newMemory(null)}><i>+</i><span className="mem-wide">New memory</span></button>
          </div>
        </header>
      ) : (
        <header className="mem-head is-inside">
          <button type="button" className="mem-head-back" onClick={() => go({ m: null })}>Memories</button>
          <div className="mem-head-name">
            {root ? <><h1>{root.name}</h1><span className="mem-pill">{engineLine(root.provider)}</span></> : selErr ? <h1>Memories</h1> : <SkelLine w={220} h={28} />}
          </div>
        </header>
      )}

      <div className="mem-body">
        {notice && (
          <div className={'mem-banner is-top' + (notice.err ? ' is-err' : '')} role={notice.err ? 'alert' : 'status'}>
            <span>{notice.text}</span><button type="button" aria-label="Dismiss" onClick={() => setNotice(null)}>✕</button>
          </div>
        )}
        {!m ? (
          <div className="mem-home">
            {roots === null ? (
              <div className="mem-cards" aria-busy="true" aria-label="Loading">{[0, 1, 2].map((i) => <span key={i} className="sk mem-card" />)}</div>
            ) : rootsErr ? (
              <div className="mem-empty"><div>
                <b>{rootsErr instanceof MemoryApiError && rootsErr.code === 'memory_unavailable' ? 'Memories are not answering right now' : 'Memories could not be listed'}</b>
                <span>{rootsErr.message}</span>
                <button type="button" className="mem-btn" style={{ marginTop: 18 }} onClick={() => { setRoots(null); void loadRoots(); }}>Try again</button>
              </div></div>
            ) : roots.length === 0 ? (
              <div className="mem-empty"><div>
                <b>No memories yet</b>
                <span>A memory is where your agents keep what should outlast one conversation. Create one, then give it to a harness.</span>
                <button type="button" className="mem-newbtn" onClick={() => newMemory(null)}>New memory</button>
              </div></div>
            ) : (
              <div className="mem-cards">
                {roots.map((mem) => {
                  const p = mem.privileges || [];
                  return (
                    <article key={mem.id} className="mem-card">
                      <button type="button" className="mem-card-hit" onClick={() => go({ m: mem.id })}>
                        <span className="mem-card-top">
                          <span className="mem-mark" aria-hidden="true">{engineMark(mem.provider)}</span>
                          <span className="mem-card-id"><span className="mem-card-name">{mem.name}</span><span className="mem-card-engine">{engineLine(mem.provider)}</span></span>
                        </span>
                        <span className="mem-card-desc">{mem.description}</span>
                        <span className="mem-grow" />
                        <span className="mem-card-stats">
                          <span><b>{typeof mem.records?.count === 'number' ? mem.records.count : '—'}</b><i>records</i></span>
                          <span><b>{typeof mem.children?.count === 'number' ? mem.children.count : '—'}</b><i>memories inside</i></span>
                        </span>
                      </button>
                      {renaming === mem.id ? (
                        <NameInput className="mem-card-rename" initial={mem.name} label="Memory name" onCancel={() => setRenaming(null)} onCommit={(name) => { setRenaming(null); void rename(mem, name); }} />
                      ) : (
                        <span className="mem-card-acts">
                          {p.includes('write') && <button type="button" title="Rename" aria-label={`Rename ${mem.name}`} onClick={() => setRenaming(mem.id)}><Ico d={ICON.pencil} size={13} sw={1.5} /></button>}
                          {p.includes('delete') && <>
                            <button type="button" title="Share" aria-label={`Share ${mem.name}`} onClick={() => setShare(mem.id)}><Ico d={ICON.share} size={13} sw={1.5} /></button>
                            <button type="button" className="is-danger" title="Delete" aria-label={`Delete ${mem.name}`} onClick={() => setDel(mem)}><Ico d={ICON.trash} size={13} sw={1.5} /></button>
                          </>}
                        </span>
                      )}
                    </article>
                  );
                })}
                <button type="button" className="mem-card-new" onClick={() => newMemory(null)}><i>+</i><span>New memory</span></button>
              </div>
            )}
          </div>
        ) : (
          <div className="mem-frame">
            <nav className={'mem-tree' + (treeOpen ? ' is-open' : '')} aria-label="Memories">
              {root ? (
                <MemoryTree root={root} mems={mems} kids={kids} recs={recs} open={open} selId={m} recId={r} draftIn={draftIn} current={current}
                  onSelect={(id) => { setDraftIn(null); setTreeOpen(false); go({ m: id, r: null, q: null }); }}
                  onToggle={(id) => setOpen((o) => (o.includes(id) ? o.filter((x) => x !== id) : [...o, id]))}
                  onOpenRecord={(mid, rid) => { setDraftIn(null); setTreeOpen(false); go({ m: mid, r: rid, q: null }); }}
                  onNewChild={newMemory} onRename={(mem, name) => void rename(mem, name)} onShare={(mem) => setShare(mem.id)} onDelete={setDel} />
              ) : !selErr && <div className="mem-tree-skel" aria-busy="true"><SkelLine w={150} h={11} /><SkelLine w={110} h={11} /><SkelLine w={130} h={11} /></div>}
            </nav>
            {treeOpen && <button type="button" className="mem-scrim is-open" aria-label="Close the tree" onClick={() => setTreeOpen(false)} />}
            {selErr ? (
              <div className="mem-pane"><div className="mem-state">
                <strong>{selErr instanceof MemoryApiError && selErr.code === 'memory_unavailable' ? 'This memory is not answering right now' : 'This memory could not be opened'}</strong>
                <span>{selErr.message}</span>
                <button type="button" className="mem-btn" onClick={() => go({ m: null })}>Back to Memories</button>
              </div></div>
            ) : !sel ? (
              <div className="mem-pane" aria-busy="true"><div className="mem-pane-head"><SkelLine w={200} h={20} style={{ display: 'block', marginTop: 22 }} /><SkelLine w="60%" h={12} style={{ display: 'block', marginTop: 12 }} /></div></div>
            ) : r || draftIn === m ? (
              <RecordEditor memory={sel} path={path} provider={provider} recordId={r || null} who={who} onRecord={setCurrent}
                onOpenRecord={(mid, rid) => go({ m: mid, r: rid })} onOpenMemory={(id) => { setDraftIn(null); go({ m: id, r: null, q: null }); }} onOpenTree={() => setTreeOpen(true)}
                onSaved={(rec, isNew) => { changed(rec.memory_id); if (isNew) go({ r: rec.id }, true); }}
                onGone={(mid, text) => { changed(mid); if (text) setNotice({ text }); go({ r: null }); }}
                onCancelDraft={() => setDraftIn(null)} />
            ) : (
              <MemoryPane memory={sel} ancestors={above} provider={provider} view={view} q={q} rev={rev} who={who} onGo={go}
                onShare={() => setShare(sel.id)} onAdd={() => { setOpen((o) => [...new Set([...o, sel.id])]); setDraftIn(sel.id); }}
                onDescription={describe} onOpenTree={() => setTreeOpen(true)} onChanged={changed} />
            )}
          </div>
        )}
      </div>

      {create && <CreateDialog parent={create.parent} onClose={() => setCreate(null)} onCreated={(mem) => void created(mem)} />}
      {shared && (
        <ShareDialog memory={shared} parentName={shared.parent_id ? mems[shared.parent_id]?.name || null : null} harnesses={harnesses} memoryName={(id) => mems[id]?.name}
          onClose={() => setShare(null)} onGoMemory={(id) => { setShare(null); go({ m: id, r: null, q: null }); }} onMemory={(x) => putMems([x])} />
      )}
      {del && <DeleteDialog memory={del} onClose={() => setDel(null)} onDeleted={deleted} />}
    </section>
  );
}
