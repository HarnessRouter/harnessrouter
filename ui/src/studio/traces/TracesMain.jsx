'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { IconByName } from '@/studio/lib/iconCatalog.jsx';
import { Markdown } from '@/studio/lib/markdown.jsx';
import { tracesApi } from './api';
import { flatten, lanes, fmtK } from './flatten';
import { useTraces } from './store';

const clip = (s, n) => (s && s.length > n ? s.slice(0, n) + '…' : s || '');
const PILL = { user: 'User', agent: 'Agent', tool: 'Tool', result: 'Result', thinking: 'Thinking', system: 'System' };
const IDLE_GAP = 20; // seconds between events that counts as a "Session idle" boundary

// H:MM:SS offset from session start
const fmtClock = (s) => {
  if (s == null || !isFinite(s)) return '';
  const t = Math.max(0, Math.round(s));
  return `${Math.floor(t / 3600)}:${String(Math.floor((t % 3600) / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
};
const fmtDur = (sec) => {
  if (sec == null) return '';
  const s = Number(sec);
  if (s < 1) return `${Math.round(s * 1000)}ms`;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
};
const fmtAgo = (sec) => {
  if (!sec) return '';
  const d = Math.max(0, Date.now() / 1000 - Number(sec));
  if (d < 60) return `${Math.floor(d)}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
};
const fmtTok = (t) => (t ? `${fmtK(t.in)} / ${fmtK(t.out)}` : '');

// thin proportional timeline; one segment per event coloured by kind, plus a cursor at the end
function Strip({ rows, t0, span, hover, setHover, onJump, lane }) {
  if (!rows.length || !span) return <div className={'tr-strip' + (lane ? ' lane' : '')} />;
  const segs = [];
  rows.forEach((r, k) => {
    const left = ((r.ts - t0) / span) * 100;
    const dur = r.kind === 'tool' && r.dur ? r.dur : 0;   // bar = tool execution; messages = thin tick
    const w = Math.max(0.5, (dur / span) * 100);
    segs.push(
      <span key={`s${r.i}`} className={`tr-seg tr-${r.kind}` + (hover === r.i ? ' hot' : '')}
        style={{ left: `${left}%`, width: `${w}%` }}
        title={`${PILL[r.kind] || r.kind} +${(r.ts - t0).toFixed(1)}s${dur ? ` · ${fmtDur(dur)}` : ''}`}
        onMouseEnter={() => setHover(r.i)} onMouseLeave={() => setHover(null)}
        onClick={() => onJump(r.i)} />
    );
    if (k + 1 < rows.length) {                              // gap to next event = waiting time
      const g = rows[k + 1].ts - r.ts;
      if (g > IDLE_GAP) segs.push(
        <span key={`i${r.i}`} className="tr-seg-idle"
          style={{ left: `${left + w}%`, width: `${Math.max(0.5, (g / span) * 100 - w)}%` }} />);
    }
  });
  return <div className={'tr-strip' + (lane ? ' lane' : '')}>{segs}</div>;
}

// one clean line per event: pill | (tool name bold + lighter param | message text) … | tokens | dur | clock
function Row({ r, t0, active, hover, setHover, onOpen }) {
  const rel = r.ts != null && t0 != null ? fmtClock(r.ts - t0) : '';
  return (
    <div id={`tr-step-${r.i}`}
      className={'tr-row' + (active ? ' active' : '') + (hover === r.i ? ' hot' : '') + (r.sub ? ' sub' : '')}
      onMouseEnter={() => setHover(r.i)} onMouseLeave={() => setHover(null)}
      onClick={() => onOpen(r)}>
      <span className={`tr-badge tr-${r.kind}`}>{PILL[r.kind] || r.kind}</span>
      <span className="tr-row-main">
        {r.kind === 'tool'
          ? <><span className="tr-tname">{r.label}</span>{r.param && <span className="tr-tparam">{clip(r.param, 90)}</span>}</>
          : <span className="tr-rmsg">{clip(r.text, 140)}</span>}
      </span>
      {r.is_error && <span className="tr-errbadge"><IconByName name="XCircle" size={12} /> Error</span>}
      <span className="tr-row-stats">
        {r.tokens && (r.tokens.in != null || r.tokens.out != null) && <span className="tr-stat"><IconByName name="Database" size={12} />{fmtTok(r.tokens)}</span>}
        {r.dur != null && <span className="tr-stat"><IconByName name="Timer" size={12} />{fmtDur(r.dur)}</span>}
        {rel && <span className="tr-rts">{rel}</span>}
      </span>
    </div>
  );
}

function JsonBlock({ obj }) {
  let s; try { s = JSON.stringify(obj, null, 2); } catch { s = String(obj); }
  const parts = []; const re = /("(?:[^"\\]|\\.)*")(\s*:)?|(-?\b\d+(?:\.\d+)?\b)|(\btrue\b|\bfalse\b|\bnull\b)/g;
  let last = 0; let m; let i = 0;
  while ((m = re.exec(s)) !== null) {
    if (m.index > last) parts.push(s.slice(last, m.index));
    if (m[1]) {
      if (m[2]) { parts.push(<span key={i++} className="j-key">{m[1]}</span>); parts.push(m[2]); }
      else parts.push(<span key={i++} className="j-str">{m[1]}</span>);
    } else if (m[3]) parts.push(<span key={i++} className="j-num">{m[3]}</span>);
    else if (m[4]) parts.push(<span key={i++} className="j-bool">{m[4]}</span>);
    last = m.index + m[0].length;
  }
  if (last < s.length) parts.push(s.slice(last));
  return <pre className="tr-json">{parts}</pre>;
}

// Skeleton shown while a session's transcript loads — no stale rows, no placeholder text.
function TraceSkeleton() {
  return (
    <>
      <div className="tr-mhead">
        <div className="tr-skel tr-skel-title" />
        <div className="tr-mmeta">
          <div className="tr-skel tr-skel-pill" /><div className="tr-skel tr-skel-pill" /><div className="tr-skel tr-skel-pill" />
        </div>
      </div>
      <div className="tr-strips"><div className="tr-skel tr-skel-strip" /></div>
      <div className="tr-rows">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="tr-skel-rowline">
            <div className="tr-skel tr-skel-badge" />
            <div className="tr-skel tr-skel-line" style={{ width: `${38 + ((i * 11) % 48)}%` }} />
          </div>
        ))}
      </div>
    </>
  );
}

function Detail({ r, t0, width, onClose, loadingFull }) {
  if (!r) return null;
  const id = r.tool_use_id ? String(r.tool_use_id).slice(0, 18) : `step ${r.i + 1}`;
  const rel = r.ts != null && t0 != null ? fmtClock(r.ts - t0) : '';
  const sub = [id, rel, r.dur != null ? fmtDur(r.dur) : ''].filter(Boolean).join('  ·  ');
  const isMsg = r.kind === 'agent' || r.kind === 'user' || r.kind === 'result' || r.kind === 'thinking';
  return (
    <div className="tr-detail" style={width ? { width, flex: `0 0 ${width}px` } : undefined}>
      <div className="tr-detail-head">
        <span className={`tr-badge tr-${r.kind}`}>{PILL[r.kind] || r.kind}</span>
        <span className="tr-detail-title">{r.kind === 'tool' ? r.label : 'Message'}</span>
        {r.is_error && <span className="tr-errbadge"><IconByName name="XCircle" size={12} /> Error</span>}
        <button className="tr-x" onClick={onClose} aria-label="Close"><IconByName name="X" size={16} /></button>
      </div>
      <div className="tr-detail-id">{sub}</div>
      {loadingFull && <div className="tr-detail-loading">Loading full content…</div>}
      {isMsg && (<>
        <div className="tr-detail-cap">Content</div>
        {r.md ? <Markdown text={r.text} className="tr-md" /> : <div className={'tr-text' + (r.kind === 'thinking' ? ' italic' : '')}>{r.text}</div>}
      </>)}
      {r.kind === 'tool' && (r.tools || []).map((t, k) => (
        <div key={k} className="tr-tooldetail">
          {r.tools.length > 1 && <div className="tr-tool-sep">{t.name}</div>}
          <div className="tr-detail-cap">Tool use</div>
          <JsonBlock obj={t.input} />
          {t.result != null && <>
            <div className="tr-detail-cap">Tool result</div>
            <pre className={'tr-code' + (t.is_error ? ' err' : '')}>{clip(t.result, 6000)}</pre>
          </>}
        </div>
      ))}
    </div>
  );
}

function IdleBoundary({ secs }) {
  return <div className="tr-idle"><span>Session idle · {fmtDur(secs)}</span></div>;
}

export default function TracesMain() {
  const { selected } = useTraces();
  const [manifest, setManifest] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState(null);
  const [sel, setSel] = useState(null);
  // Lazy full transcript: the timeline loads a COMPACT transcript (long strings truncated) so even a
  // 30 MB trace renders instantly. The first time a clipped event is opened we fetch the full
  // (un-clipped) transcript once; its flatten() rows align positionally, so full[r.i] is r's full text.
  const [full, setFull] = useState(null);
  const [loadingFull, setLoadingFull] = useState(false);
  const [detailW, setDetailW] = useState(440);
  const startDetailResize = (e) => {
    e.preventDefault();
    const sx = e.clientX, base = detailW;
    document.body.classList.add('hr-resizing');
    const move = (ev) => setDetailW(Math.min(900, Math.max(300, base - (ev.clientX - sx))));
    const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); document.body.style.cursor = ''; document.body.classList.remove('hr-resizing'); };
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up); document.body.style.cursor = 'col-resize';
  };
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!selected) { setManifest(null); setRows([]); setSel(null); setFull(null); return; }
    let live = true;
    let timer = null;
    setLoading(true); setSel(null); setRows([]); setManifest(null); setFull(null);   // drop the prior session's data while loading
    const isRunning = (m) => { const s = m?.status; return !s || s === 'running' || s === 'starting' || s === 'in_progress'; };
    const load = async (first) => {
      try {
        const m = await tracesApi.manifest(selected).catch(() => null);
        if (!live) return;
        if (m) setManifest(m);
        // /all?compact=1 now returns ALL chunks flushed so far (incl. a still-running turn), so each
        // poll grows the live transcript.
        const evs = await tracesApi.events(selected, (m && m.chunks) || []);
        if (!live) return;
        setRows(flatten(evs));
        if (first) setLoading(false);
        // Live-tail a running session: re-load on an interval until it reaches a terminal state.
        if (isRunning(m)) { timer = setTimeout(() => load(false), 2500); }
      } catch { if (live && first) { setManifest(null); setRows([]); setLoading(false); } }
    };
    load(true);
    return () => { live = false; if (timer) clearTimeout(timer); };
  }, [selected]);

  // When a clipped event is opened, fetch the full (un-clipped) transcript once and cache it.
  useEffect(() => {
    if (!sel || !sel.clipped || full || loadingFull || !selected) return;
    let live = true;
    setLoadingFull(true);
    (async () => {
      try {
        const evs = await tracesApi.fullEvents(selected);
        if (live) setFull(flatten(evs));
      } catch { /* keep the clipped preview if the full fetch fails */ }
      if (live) setLoadingFull(false);
    })();
    return () => { live = false; };
  }, [sel, full, loadingFull, selected]);

  const { main, subs } = useMemo(() => lanes(rows), [rows]);
  const tsAll = rows.map((r) => r.ts).filter((x) => x != null);
  const t0 = tsAll.length ? Math.min(...tsAll) : 0;
  const t1 = tsAll.length ? Math.max(...tsAll) : 0;
  const span = t1 - t0 || 1;

  const jump = (i) => { const el = document.getElementById(`tr-step-${i}`); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' }); };

  if (!selected) return <div className="tr-main tr-blank">Select a session to view its trace.</div>;
  if (loading) return <div className="tr-main"><div className="tr-pane"><TraceSkeleton /></div></div>;

  return (
    <div className={'tr-main' + (sel ? ' with-detail' : '')}>
      <div className="tr-pane">
        <div className="tr-mhead">
          <div className="tr-mtitle">{manifest?.title || selected}</div>
          <div className="tr-mmeta">
            {manifest?.status && <span className={`tr-pill tr-${manifest.status}`}>{manifest.status}</span>}
            {manifest?.backend && <span className="tr-tag"><IconByName name="Cpu" size={13} />{manifest.backend}</span>}
            {manifest?.model && <span className="tr-tag"><IconByName name="Box" size={13} />{manifest.model}</span>}
            <span className="tr-tag"><IconByName name="ListTree" size={13} />{rows.length} events</span>
            {manifest?.elapsed != null && <span className="tr-tag"><IconByName name="Timer" size={13} />{fmtDur(manifest.elapsed)}</span>}
            {manifest?.finished_at && <span className="tr-tag"><IconByName name="Clock" size={13} />{fmtAgo(manifest.finished_at)}</span>}
          </div>
        </div>
        <div className="tr-strips">
          <Strip rows={main} t0={t0} span={span} hover={hover} setHover={setHover} onJump={jump} />
          {[...subs.entries()].map(([id, lane]) => (
            <Strip key={id} rows={lane} t0={t0} span={span} hover={hover} setHover={setHover} onJump={jump} lane />
          ))}
        </div>
        <div className="tr-rows scroll" ref={scrollRef}>
          {loading && <div className="tr-empty">Loading transcript…</div>}
          {!loading && !rows.length && <div className="tr-empty">No events recorded.</div>}
          {(() => {
            const shownSubs = new Set();
            const subGroup = (id) => (
              <div className="tr-subgroup">
                <div className="tr-sub-boundary"><IconByName name="GitBranch" size={13} /> Subagent · {String(id).slice(0, 14)}</div>
                {subs.get(id).map((r) => <Row key={r.i} r={r} t0={t0} active={sel?.i === r.i} hover={hover} setHover={setHover} onOpen={setSel} />)}
              </div>
            );
            const els = main.map((r, k) => {
              const prev = main[k - 1];
              const gap = prev && r.ts != null && prev.ts != null ? r.ts - prev.ts : 0;
              // the Task tool that spawned a subagent -> nest that subagent's events right here
              const subId = r.kind === 'tool' ? (r.tools || []).map((t) => t.id).find((id) => subs.has(id)) : null;
              if (subId) shownSubs.add(subId);
              return (
                <div key={r.i}>
                  {gap > IDLE_GAP && <IdleBoundary secs={gap} />}
                  <Row r={r} t0={t0} active={sel?.i === r.i} hover={hover} setHover={setHover} onOpen={setSel} />
                  {subId && subGroup(subId)}
                </div>
              );
            });
            // any subagents whose parent tool we couldn't match -> append at the end
            const orphans = [...subs.keys()].filter((id) => !shownSubs.has(id))
              .map((id) => <div key={`orphan-${id}`}>{subGroup(id)}</div>);
            return [...els, ...orphans];
          })()}
        </div>
      </div>
      {sel && <div className="tr-vresize" onMouseDown={startDetailResize} title="Drag to resize" />}
      {sel && <Detail r={(sel.clipped && full && full[sel.i]) ? full[sel.i] : sel}
                      loadingFull={sel.clipped && !full && loadingFull}
                      t0={t0} width={detailW} onClose={() => setSel(null)} />}
    </div>
  );
}
