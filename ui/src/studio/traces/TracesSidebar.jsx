'use client';
import { useEffect, useRef, useState } from 'react';
import { IconByName } from '@/studio/lib/iconCatalog.jsx';
import { tracesApi } from './api';
import { traceStore, useTraces } from './store';

const PAGE = 25;

function relTime(sec) {
  if (!sec) return '';
  const d = Math.max(0, Date.now() / 1000 - Number(sec));
  if (d < 60) return `${Math.floor(d)}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}
const shortId = (s) => (s || '').replace(/^hsess/, '').slice(0, 10);

function StatusPill({ status }) {
  const s = status || 'done';
  return <span className={`tr-pill tr-${s}`}>{s}</span>;
}

export function TracesSidebar() {
  const { selected } = useTraces();
  const [cards, setCards] = useState([]);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);
  const [cursor, setCursor] = useState('');        // next-page token from the API
  const [stack, setStack] = useState([]);          // cursors of previous pages (for Prev)
  const [page, setPage] = useState(0);
  const cur = useRef('');                           // cursor used to load the current page

  async function load(c) {
    setLoading(true);
    try {
      const r = await tracesApi.list({ limit: PAGE, cursor: c || '' });
      const list = r.sessions || [];
      setCards(list);
      setCursor(r.cursor || '');
      cur.current = c || '';
      // auto-select the first session of THIS list when nothing valid is selected (the store's
      // selection is global, so on entering a harness it may hold another harness's stale session).
      const sel = traceStore.get().selected;
      if (!sel || !list.some((s) => s.session_id === sel)) traceStore.select(list[0]?.session_id || null);
    } catch { setCards([]); setCursor(''); }
    setLoading(false);
  }
  useEffect(() => { load(''); /* first page */ }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  // light auto-refresh of the first page so new/running sessions appear
  useEffect(() => {
    if (page !== 0) return undefined;
    const t = setInterval(() => load(''), 8000);
    return () => clearInterval(t);
  }, [page]);                                            // eslint-disable-line react-hooks/exhaustive-deps

  const next = () => { if (!cursor) return; setStack((s) => [...s, cur.current]); setPage((p) => p + 1); load(cursor); };
  const prev = () => { if (!stack.length) return; const s = [...stack]; const c = s.pop(); setStack(s); setPage((p) => Math.max(0, p - 1)); load(c); };

  const ql = q.trim().toLowerCase();
  const shown = ql
    ? cards.filter((c) => `${c.title} ${c.model} ${c.status} ${c.backend}`.toLowerCase().includes(ql))
    : cards;

  return (
    <aside className="side app-side tr-side">
      <div className="tr-head"><div className="tr-head-title">Traces</div></div>
      <div className="tr-search">
        <IconByName name="Search" size={15} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search sessions" aria-label="Search sessions" />
      </div>
      <nav className="side-nav scroll tr-list">
        {loading && !cards.length && <div className="tr-empty">Loading sessions…</div>}
        {!loading && !shown.length && <div className="tr-empty">No sessions yet.</div>}
        {shown.map((c) => (
          <button key={c.session_id}
            className={'tr-card' + (selected === c.session_id ? ' active' : '')}
            onClick={() => traceStore.select(c.session_id)}>
            <div className="tr-card-q">{c.title || c.user_prompt || shortId(c.session_id)}</div>
            <div className="tr-card-foot">
              <span className="tr-card-ago">{relTime(c.finished_at)}</span>
              <span className="tr-card-badges">
                {c.backend && <span className="tr-card-be">{c.backend}</span>}
                <StatusPill status={c.status} />
              </span>
            </div>
          </button>
        ))}
      </nav>
      <div className="tr-foot">
        <button className="tr-pg" disabled={!stack.length} onClick={prev}>‹ Prev</button>
        <span className="tr-pg-lbl">Page {page + 1}</span>
        <button className="tr-pg" disabled={!cursor} onClick={next}>Next ›</button>
      </div>
    </aside>
  );
}
