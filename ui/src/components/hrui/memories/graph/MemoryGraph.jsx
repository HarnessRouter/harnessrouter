'use client';
// A memory as one explorable graph: the right column of its page. On open, the whole memory, arranged by the rule in
// layout.ts and then let settle by a force simulation you can watch. Hover lights a record and what it touches. A click
// opens the record in the middle of the page; a double click brings in what it links to, on rings around it. A fact that
// relates two things is the line between them, and clicking the line opens the fact. Nothing is drawn that the read did
// not answer: a provider that keeps no links has isolated records, and that is the truth of it.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { labelOf, recall } from '@/lib/memories';
import { toast } from '../../toast';
import { kindOf } from '../caps';
import { kindInfo } from '../tree';
import CytoscapeCanvas from './CytoscapeCanvas.jsx';
import {
  computeCollapse, edgeCaption, elementOf, emptyGraph, exploreOf, kindsIn, mergeGraphs, readGraph, recordsIn, GRAPH_LIMIT,
} from './adapter';
import { I, iconUrl, needsCatalog, useIconCatalog } from './graphIcons.jsx';
import { DataEdgeDetail, DataNodeDetail, NodeContextMenu, truncateLabel } from './graphShared.jsx';
import { arrive, footprint, initialLayout, LABEL_RESERVE } from './layout';
import { createSim, loadForce } from './simulate';
import './graph.css';

const DEPTHS = [1, 2, 3];
const COMPACT_PANE_WIDTH = 760;
const FADE_MS = 420;
const PULSE_MS = 1600;
const MAX_REREAD = 8;
const NAMES_UP_TO = 60;   // past this many, names wait for a zoom or a hover, or they would cover the graph
const STEPS_FROM = 200;   // past this many, several steps between draws: moving every record on a canvas this full is the slow part, and the steps are cheap
const STEPS_A_DRAW = 8;

const storeKey = (id) => `mm-graph:${id}`;
function loadStored(id) {
  try {
    const s = JSON.parse(localStorage.getItem(storeKey(id)) || 'null');
    return s && s.v === 1 ? s : null;
  } catch { return null; }
}
const reducedMotion = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const seedOf = (s) => { let h = 7; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0; return h; };
const sizeOf = (degree) => 30 + Math.min(degree, 10) * 2.2;

/**
 * @param {{ memory: import('@/lib/memories').Memory, provider: import('@/lib/memories').Provider | null, schema: import('../schemaModel').LSchema | null,
 *   activeRecordId: string, refreshKey: number, changed?: string[], onOpenRecord: (recordId: string, memoryId?: string) => void,
 *   linksFor?: (recordId: string) => import('react').ReactNode, onFold?: () => void }} props   a record's links for its panel, where they
 *   can be changed; `onFold` folds the panel to the right, from the chevron at the end of its bar
 */
export function MemoryGraph(props) {
  return <Explorer key={props.memory.id} {...props} />;
}

function Explorer({ memory, provider, schema, activeRecordId, refreshKey, changed, onOpenRecord, linksFor, onFold }) {
  const mid = memory.id;
  const canvas = useRef(null);
  const body = useRef(null);
  const box = useRef(null);
  const [view, setViewState] = useState(() => {
    const v = loadStored(mid)?.view;
    return DEPTHS.includes(v) ? v : 'whole';
  });
  const [read, setRead] = useState({ loading: true, failed: false, base: emptyGraph() });
  const [extra, setExtra] = useState(emptyGraph);
  const [collapsed, setCollapsed] = useState({});
  const [hiddenKinds, setHiddenKinds] = useState(() => new Set());
  const [detail, setDetail] = useState(null);
  const [ctx, setCtx] = useState(null);
  const [compact, setCompact] = useState(false);
  const [q, setQ] = useState('');
  const [hits, setHits] = useState([]);
  const [searching, setSearching] = useState(false);
  const [dropOpen, setDropOpen] = useState(false);
  const [dropIdx, setDropIdx] = useState(-1);
  const roots = useRef(new Set());
  const anchors = useRef(new Map());
  const painted = useRef(false);
  const wantFit = useRef(false);
  const whole = useRef(true);        // nobody has moved the view since it last showed everything
  const wantSim = useRef(null);
  const reveal = useRef(false);  // bring what a double click brought in into view
  const fading = useRef(new Set());
  const pendingPulse = useRef(new Set());
  const seq = useRef(0);
  const camera = useRef('');
  const live = useRef(null);     // the running simulation
  const simRun = useRef(0);

  const near = view !== 'whole' && !!activeRecordId;
  const setView = useCallback((v) => {
    setViewState(v);
    try { localStorage.setItem(storeKey(mid), JSON.stringify({ ...(loadStored(mid) || { v: 1 }), v: 1, view: v })); } catch { /* private window */ }
  }, [mid]);

  const merged = useMemo(() => mergeGraphs(read.base, extra), [read.base, extra]);
  const all = useMemo(() => exploreOf(merged), [merged]);

  const captionOf = useCallback((n) => {
    if (!n.record) return 'Can’t open';
    const cap = schema?.types?.find((t) => t.name === n.kind)?.caption;
    return truncateLabel((cap && cap !== 'title' ? String(n.record.attributes?.[cap] || '') : '') || n.title || 'Untitled', 32);
  }, [schema]);

  /** What the layout needs to know: how big each record is on the canvas, and what links to what. */
  const inputOf = useCallback((nodes, edges) => {
    const degree = new Map();
    edges.forEach((e) => { degree.set(e.from, (degree.get(e.from) || 0) + 1); degree.set(e.to, (degree.get(e.to) || 0) + 1); });
    return {
      nodes: Object.values(nodes).map((n) => ({ id: n.key, ...footprint(captionOf(n), sizeOf(degree.get(n.key) || 0)) })),
      edges: edges.map((e) => ({ source: e.from, target: e.to })),
    };
  }, [captionOf]);

  const positionsNow = useCallback(() => {
    const cy = canvas.current?.getCy?.();
    const m = new Map();
    if (cy) cy.nodes().forEach((n) => { const p = n.position(); m.set(n.id(), { x: p.x, y: p.y }); });
    return m;
  }, []);

  // ── the read ──────────────────────────────────────────────────────────────────────────────
  // Where records go before they are drawn. On first paint: where this person left them, or the arrangement where
  // nothing is known. After that, what is there stays, and what is new arrives around what it links to.
  const seat = useCallback((next) => {
    const ref = canvas.current;
    if (!ref?.pinPositionsAndSkipLayout) return;
    const { nodes, edges } = inputOf(next.nodes, next.edges);
    if (!nodes.length) { painted.current = false; return; }
    const seed = seedOf(mid);
    if (!painted.current) {
      painted.current = true;
      const stored = loadStored(mid)?.positions || {};
      const known = new Map(nodes.filter((n) => stored[n.id]).map((n) => [n.id, stored[n.id]]));
      if (known.size === nodes.length) {
        ref.pinPositionsAndSkipLayout(Object.fromEntries(known), true);
      } else if (known.size) {
        const seeds = arrive(nodes, edges, known, { seed });
        ref.pinPositionsAndSkipLayout({ ...Object.fromEntries(known), ...Object.fromEntries(seeds) }, true);
        wantSim.current = { held: new Set(known.keys()) };
      } else {
        const { pos } = initialLayout(nodes, edges, { seed });
        ref.pinPositionsAndSkipLayout(Object.fromEntries(pos), true);
        wantSim.current = { held: new Set() };
      }
      wantFit.current = true;
      return;
    }
    const here = positionsNow();
    const keep = new Map(nodes.filter((n) => here.has(n.id)).map((n) => [n.id, here.get(n.id)]));
    if (keep.size === nodes.length) return;
    const seeds = arrive(nodes, edges, keep, { seed });
    seeds.forEach((_, k) => fading.current.add(k));
    ref.pinPositionsAndSkipLayout(Object.fromEntries(seeds), true);
    wantSim.current = { held: new Set(keep.keys()) };
  }, [inputOf, positionsNow, mid]);

  const around = near ? activeRecordId : '';
  const load = useCallback(async () => {
    const mine = ++seq.current;
    setRead((r) => ({ ...r, failed: false }));
    try {
      const [g, ...more] = await Promise.all([
        readGraph(mid, around ? { around, hops: view } : {}),
        // what was brought in by hand stays, read again
        ...[...anchors.current.entries()].slice(0, MAX_REREAD).map(([id, m]) => readGraph(m, { around: id, hops: 1 }).catch(() => null)),
      ]);
      if (mine !== seq.current) return;
      const again = more.filter(Boolean).reduce((acc, x) => mergeGraphs(acc, x), emptyGraph());
      seat(exploreOf(mergeGraphs(g, again)));
      setExtra(again);
      setRead({ loading: false, failed: false, base: g });
    } catch {
      if (mine === seq.current) setRead((r) => ({ ...r, loading: false, failed: true }));
    }
  }, [mid, around, view, seat]);
  useEffect(() => { void load(); }, [load, refreshKey]);

  // ── what is drawn ─────────────────────────────────────────────────────────────────────────
  const visible = useMemo(() => {
    const hidden = new Set(), gone = new Set();
    Object.values(collapsed).forEach((c) => { c.hidden.forEach((k) => hidden.add(k)); c.removed.forEach((k) => gone.add(k)); });
    const nodes = {};
    Object.values(all.nodes).forEach((n) => { if (!hidden.has(n.key) && !hiddenKinds.has(n.kind)) nodes[n.key] = n; });
    const edges = all.edges.filter((e) => !gone.has(e.key) && nodes[e.from] && nodes[e.to] && (!e.fact || !hiddenKinds.has(kindOf(e.fact))));
    // a record that can't be opened is here only because something links to it
    const held = new Set(edges.flatMap((e) => [e.from, e.to]));
    Object.keys(nodes).forEach((k) => { if (!nodes[k].record && !held.has(k)) delete nodes[k]; });
    return { nodes, edges };
  }, [all, collapsed, hiddenKinds]);

  const kindInfos = useMemo(() => [...new Set(Object.values(visible.nodes).map((n) => n.kind))].filter(Boolean).map((k) => kindInfo(k, schema).icon), [visible, schema]);
  const catalog = useIconCatalog(needsCatalog(kindInfos));

  const elements = useMemo(() => {
    const degree = new Map();
    visible.edges.forEach((e) => { degree.set(e.from, (degree.get(e.from) || 0) + 1); degree.set(e.to, (degree.get(e.to) || 0) + 1); });
    const ns = Object.values(visible.nodes).map((n) => {
      const k = n.record ? kindInfo(n.kind, schema) : { color: '#CBD5E1', icon: '' };
      const url = n.record ? iconUrl(k.icon) : null;
      return {
        data: { id: n.key, caption: captionOf(n), color: k.color, size: sizeOf(degree.get(n.key) || 0), ...(url ? { iconUrl: url } : {}) },
        ...(n.record ? {} : { classes: 'closed' }),
      };
    });
    const es = visible.edges.map((e) => ({
      data: { id: e.key, source: e.from, target: e.to, caption: edgeCaption(e), lineColor: e.fact ? kindInfo(kindOf(e.fact), schema).color : '#94A3B8' },
      classes: [e.available ? '' : 'closed', e.directed ? '' : 'plain'].filter(Boolean).join(' '),
    }));
    return [...ns, ...es];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, schema, captionOf, catalog]);

  const kinds = useMemo(() => [...kindsIn(all).entries()].map(([key, n]) => ({ key, n, info: kindInfo(key, schema) })), [all, schema]);
  const badges = useMemo(() => {
    const out = {};
    Object.entries(collapsed).forEach(([k, c]) => { if (c.hidden.length) out[k] = c.hidden.length; });
    return out;
  }, [collapsed]);
  const shown = Object.values(visible.nodes).filter((n) => n.record).length + visible.edges.filter((e) => e.fact).length;

  const activeEl = activeRecordId ? elementOf(all, activeRecordId) : null;
  const detailEl = detail ? detail.el : null;

  const fit = useCallback(() => {
    const cy = canvas.current?.getCy?.();
    if (!cy || cy.nodes().length === 0) return;
    try {
      cy.minZoom(0.02);
      cy.resize();
      if (cy.width() < 2 || cy.height() < 2) return;
      cy.fit(undefined, fitPadding(cy));
      if (cy.zoom() > 1.3) { cy.zoom(1.3); cy.center(); }
      whole.current = true;
    } catch { /* gone */ }
  }, []);

  const savePositions = useCallback(() => {
    const cy = canvas.current?.getCy?.();
    if (!cy || !cy.nodes().length) return;
    const positions = {};
    cy.nodes().forEach((n) => { const p = n.position(); positions[n.id()] = { x: Math.round(p.x), y: Math.round(p.y) }; });
    try { localStorage.setItem(storeKey(mid), JSON.stringify({ ...(loadStored(mid) || {}), v: 1, positions })); } catch { /* private window */ }
  }, [mid]);

  // What is open, brought into the part of the canvas that can be seen: under the search, and above the detail where
  // that lies over the canvas. Only if it isn't there already: a graph that fits stays whole, with nothing pushed off
  // the edge of a narrow column to make one record the middle of it.
  const centerOn = useCallback((id) => {
    const cy = canvas.current?.getCy?.();
    const el = id && cy ? cy.getElementById(id) : null;
    if (!el || !el.length) return;
    const sheet = body.current?.querySelector('.dg-detail.compact');
    const bottom = cy.height() - (sheet ? sheet.getBoundingClientRect().height : 0);
    const top = Math.min(56, bottom / 3);
    const seen = el.renderedBoundingBox ? el.renderedBoundingBox() : null;
    if (seen && seen.x1 >= 8 && seen.x2 <= cy.width() - 8 && seen.y1 >= top && seen.y2 <= bottom - 8) return;
    const p = el.isNode() ? el.position() : el.midpoint();
    const z = cy.zoom();
    const pan = { x: cy.width() / 2 - p.x * z, y: (top + bottom) / 2 - p.y * z };
    whole.current = false;
    try {
      cy.stop();
      if (reducedMotion()) cy.pan(pan); else cy.animate({ pan }, { duration: 320, easing: 'ease-out' });
    } catch { /* gone */ }
  }, []);

  // The active record, centred once when it becomes active, and lit with what it touches.
  const light = useCallback(() => {
    const cy = canvas.current?.getCy?.();
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass('act-dim');
      const el = activeEl ? cy.getElementById(activeEl) : null;
      if (el && el.length) {
        const lit = el.isNode() ? el.closedNeighborhood() : el.union(el.connectedNodes());
        cy.elements().not(lit).addClass('act-dim');
      }
    });
    if (activeEl && camera.current !== activeEl && cy.getElementById(activeEl).length) {
      camera.current = activeEl;
      centerOn(activeEl);
    }
  }, [activeEl, centerOn]);

  const pulse = useCallback((cy) => {
    const applied = [];
    pendingPulse.current.forEach((id) => {
      const key = elementOf(all, id);
      const el = key ? cy.getElementById(key) : null;
      if (!el || !el.length) return;
      el.addClass('pulse');
      applied.push(el);
      pendingPulse.current.delete(id);
    });
    if (applied.length) setTimeout(() => applied.forEach((el) => { try { el.removeClass('pulse'); } catch { /* gone */ } }), PULSE_MS);
  }, [all]);

  // The simulation, drawn as it runs: one step a frame, so it settles in front of you. A record in someone's hand stays
  // in their hand. At rest it makes the final small parting of anything still touching.
  const stopSim = useCallback(() => { simRun.current += 1; live.current = null; }, []);
  const startSim = useCallback(async ({ held }) => {
    const run = ++simRun.current;
    const cy = canvas.current?.getCy?.();
    if (!cy || !cy.nodes().length) return;
    const d3 = await loadForce();
    if (run !== simRun.current) return;
    const { nodes, edges } = inputOf(visible.nodes, visible.edges);
    const sim = createSim(d3, nodes, edges, positionsNow(), { held, seed: seedOf(mid) });
    live.current = sim;
    const apply = (pos) => cy.batch(() => {
      pos.forEach((p, id) => { const n = cy.getElementById(id); if (n.length && !n.grabbed()) n.position(p); });
    });
    const done = () => {
      if (run !== simRun.current) return;
      apply(sim.finish());
      live.current = null;
      savePositions();
      if (whole.current) showAll(cy);
    };
    if (reducedMotion()) { while (sim.step(8)); done(); return; }
    const frame = () => {
      if (run !== simRun.current) return;
      const more = sim.step(nodes.length > STEPS_FROM ? STEPS_A_DRAW : 1);
      apply(sim.positions());
      if (more) requestAnimationFrame(frame); else done();
    };
    requestAnimationFrame(frame);
  }, [inputOf, visible, positionsNow, mid, savePositions]);
  useEffect(() => () => stopSim(), [stopSim]);

  // After each change to what is drawn, once the canvas has it: the fit, the fades, the pulses, the simulation.
  useEffect(() => {
    const cy = canvas.current?.getCy?.();
    if (!cy) return;
    if (wantFit.current && cy.nodes().length) {
      if (cy.width() < 2 || cy.height() < 2) return;   // when the pane has a size
      wantFit.current = false;
      fit();
    }
    const quiet = reducedMotion();
    fading.current.forEach((k) => {
      const n = cy.getElementById(k);
      if (!n.length) return;
      fading.current.delete(k);
      if (quiet) return;
      n.style('opacity', 0);
      n.animate({ style: { opacity: 1 } }, { duration: FADE_MS, complete: () => n.removeStyle('opacity') });
    });
    light();
    pulse(cy);
    if (reveal.current) {
      reveal.current = false;
      showAll(cy);
    }
    if (wantSim.current && cy.nodes().length) {
      const w = wantSim.current;
      wantSim.current = null;
      void startSim(w);
    } else if (!live.current) savePositions();
  }, [elements, pulse, light, fit, savePositions, startSim]);

  // A change named by the page pulses as soon as it is on the canvas, which may be after the re-read it set off.
  const changedKey = (changed || []).join('|');
  useEffect(() => {
    if (!changedKey) return;
    changedKey.split('|').forEach((id) => pendingPulse.current.add(id));
    const cy = canvas.current?.getCy?.();
    if (cy) pulse(cy);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changedKey]);

  // A record opened elsewhere that this read doesn't hold is brought in, so what is open is always on the graph.
  const fetched = useRef('');
  useEffect(() => {
    if (!activeRecordId || read.loading || activeEl || fetched.current === activeRecordId) return;
    fetched.current = activeRecordId;
    readGraph(mid, { around: activeRecordId, hops: 1 }).then((g) => {
      const m = mergeGraphs(merged, g);
      if (!elementOf(exploreOf(m), activeRecordId)) return;
      seat(exploreOf(m));
      setExtra((x) => mergeGraphs(x, g));
    }).catch(() => { /* a draft, or it went away: nothing to draw */ });
  }, [activeRecordId, activeEl, read.loading, mid, merged, seat]);

  useEffect(() => { light(); }, [light]);

  // Names stay readable when a whole memory is fitted into a narrow column: as the zoom falls they grow by as much,
  // up to the room the layout kept for them, so growing never makes them overlap.
  useEffect(() => {
    const cy = canvas.current?.getCy?.();
    if (!cy) return undefined;
    let frame = 0;
    const apply = () => {
      frame = 0;
      const k = cy.nodes().length <= NAMES_UP_TO ? Math.max(1, Math.min(LABEL_RESERVE, 0.75 / cy.zoom())) : 1;
      cy.batch(() => { cy.nodes().style({ 'font-size': 10 * k, 'text-max-width': 140 * k }); });
    };
    const soon = () => { if (!frame) frame = requestAnimationFrame(apply); };
    cy.on('zoom add', soon);
    soon();
    return () => { cy.off('zoom add', soon); if (frame) cancelAnimationFrame(frame); };
  }, []);

  // Hover lights a record and its neighbours, and steps the rest back. A record picked up stays where the hand puts it.
  useEffect(() => {
    const cy = canvas.current?.getCy?.();
    if (!cy) return undefined;
    const on = (e) => {
      const t = e.target;
      const lit = t.isNode() ? t.closedNeighborhood() : t.union(t.connectedNodes());
      cy.batch(() => { cy.elements().not(lit).addClass('dim'); lit.removeClass('dim'); lit.addClass('hov'); });
    };
    const off = () => cy.batch(() => { cy.elements().removeClass('dim hov'); });
    const hold = (e) => live.current?.pin(e.target.id(), e.target.position());
    const moved = () => { whole.current = false; };
    cy.on('dragpan scrollzoom pinchzoom', moved);
    cy.on('mouseover', 'node, edge', on);
    cy.on('mouseout', 'node, edge', off);
    cy.on('grab drag free', 'node', hold);
    return () => { cy.off('dragpan scrollzoom pinchzoom', moved); cy.off('mouseover', 'node, edge', on); cy.off('mouseout', 'node, edge', off); cy.off('grab drag free', 'node', hold); };
  }, []);

  // The pane is resizable: a compact detail below a width, and a first paint that was waiting for a pane with a size.
  useEffect(() => {
    const el = body.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver((es) => {
      const w = es[es.length - 1].contentRect.width;
      setCompact(w > 0 && w < COMPACT_PANE_WIDTH);
      if (w >= 2 && wantFit.current && canvas.current?.getCy?.()?.nodes().length) {
        wantFit.current = false;
        fit();
        if (wantSim.current) { const s = wantSim.current; wantSim.current = null; void startSim(s); }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit, startSim]);

  // As the pane changes size (a column dragged, the links below it growing): a graph showing everything goes on showing
  // everything. One the person has moved keeps its middle as the middle.
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    let w0 = 0, h0 = 0;
    const ro = new ResizeObserver((es) => {
      const r = es[es.length - 1].contentRect;
      const cy = canvas.current?.getCy?.();
      if (cy && w0 >= 2 && r.width >= 2 && !wantFit.current) {
        if (whole.current) fit();
        else try { cy.panBy({ x: (r.width - w0) / 2, y: (r.height - h0) / 2 }); } catch { /* gone */ }
      }
      w0 = r.width; h0 = r.height;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  // ── going places ──────────────────────────────────────────────────────────────────────────
  const jump = useCallback((id, memoryId) => {
    const el = elementOf(all, id);
    setDetail(el ? { el, id } : null);
    setCtx(null);
    onOpenRecord(id, memoryId || undefined);
  }, [all, onOpenRecord]);

  // A detail that opens over the canvas moves what it is about into the part still showing.
  const detailKey = detail ? detail.el : '';
  useEffect(() => {
    if (!detailKey) return undefined;
    const t = requestAnimationFrame(() => requestAnimationFrame(() => centerOn(detailKey)));
    return () => cancelAnimationFrame(t);
  }, [detailKey, compact, centerOn]);

  // A panel opened from the canvas follows what is open; opening something else elsewhere closes it.
  useEffect(() => {
    setDetail((d) => (d && d.id && activeRecordId && d.id !== activeRecordId ? null : d));
  }, [activeRecordId]);

  // Expansion: what it links to, read, and arriving on rings around it. A filter from the menu takes just that link and kind.
  const expand = useCallback(async (key, filter) => {
    const n = all.nodes[key];
    if (!n?.record) return;
    setCtx(null);
    if (collapsed[key]) setCollapsed(({ [key]: _, ...rest }) => rest);
    try {
      const m = n.memoryId || mid;
      let got = await readGraph(m, { around: n.record.id, hops: 1 });
      if (filter) {
        const ex = exploreOf(mergeGraphs(merged, got));
        const keep = new Set([key]);
        ex.edges.forEach((e) => {
          if (e.from !== key && e.to !== key) return;
          const other = e.from === key ? e.to : e.from;
          const word = e.fact ? String(e.fact.attributes?.predicate || 'fact') : String(e.rel || '');
          if (word === filter.edge && ex.nodes[other]?.kind === filter.target) keep.add(other);
        });
        got = { ...got, nodes: got.nodes.filter((x) => keep.has(x.record.id) || !x.record || x.record.type === 'fact'), edges: got.edges };
      } else {
        anchors.current.set(n.record.id, m);
      }
      roots.current.add(key);
      const next = exploreOf(mergeGraphs(merged, got));
      if (Object.keys(next.nodes).length === Object.keys(all.nodes).length && next.edges.length === all.edges.length && !collapsed[key]) {
        toast('Nothing more links to this.');
        return;
      }
      reveal.current = true;
      seat(next);
      setExtra((x) => mergeGraphs(x, got));
    } catch { toast('What this links to could not be read just now.'); }
  }, [all, merged, collapsed, mid, seat]);

  const collapse = useCallback((key) => {
    setCtx(null);
    if (collapsed[key]) return;
    const res = computeCollapse(key, visible.edges, roots.current);
    if (res) setCollapsed((c) => ({ ...c, [key]: res }));
  }, [collapsed, visible.edges]);
  const restore = useCallback((key) => { setCtx(null); setCollapsed(({ [key]: _, ...rest }) => rest); }, []);

  // What "Expand by link" offers on a kind: the schema's relations where there is one, and the links seen on this kind where not.
  const edgeOptionsFor = useCallback((key) => {
    const n = all.nodes[key];
    if (!n) return [];
    const out = new Map();
    const add = (edge, target) => out.set(`${edge}|${target}`, { edge, target });
    const types = schema?.types || [];
    const nameOf = (id) => types.find((t) => t.id === id)?.name;
    (schema?.relations || []).forEach((r) => {
      if (nameOf(r.from) === n.kind && nameOf(r.to)) add(r.name, nameOf(r.to));
      else if (nameOf(r.to) === n.kind && nameOf(r.from)) add(r.name, nameOf(r.from));
    });
    all.edges.forEach((e) => {
      if (!e.available) return;
      const a = all.nodes[e.from], b = all.nodes[e.to];
      if (!a || !b) return;
      const word = e.fact ? String(e.fact.attributes?.predicate || 'fact') : String(e.rel || '');
      if (a.kind === n.kind) add(word, b.kind);
      else if (b.kind === n.kind) add(word, a.kind);
    });
    return [...out.values()];
  }, [all, schema]);
  const vertexColorByLabel = useMemo(() => Object.fromEntries(kinds.map(({ key, info }) => [key, info.color])), [kinds]);
  const vertexIconByLabel = useMemo(() => Object.fromEntries(kinds.map(({ key, info }) => [key, info.icon])), [kinds]);

  // ── search ────────────────────────────────────────────────────────────────────────────────
  // What is on the canvas first, then what the service finds, in the way this provider can look.
  const local = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return [];
    return recordsIn(all).filter(({ record }) => labelOf(record).toLowerCase().includes(t)).slice(0, 20);
  }, [q, all]);
  useEffect(() => {
    const words = q.trim();
    setHits([]);
    if (!words || !dropOpen) { setSearching(false); return undefined; }
    const signals = provider?.recall?.signals || [];
    const ask = signals.includes('query') ? { query: words } : signals.includes('text') ? { text: words } : null;
    if (!ask) { setSearching(false); return undefined; }
    setSearching(true);
    let alive = true;
    const t = setTimeout(() => {
      recall(mid, { ...ask, limit: 20 })
        .then((d) => { if (alive) setHits(d.results.map((x) => ({ record: x.record, memoryId: x.record.memory_id || mid }))); })
        .catch(() => { if (alive) setHits([]); })
        .finally(() => { if (alive) setSearching(false); });
    }, 300);
    return () => { alive = false; clearTimeout(t); };
  }, [q, dropOpen, provider, mid]);
  const results = useMemo(() => {
    const seen = new Set(), out = [];
    [...local, ...hits].forEach((r) => { if (!seen.has(r.record.id)) { seen.add(r.record.id); out.push(r); } });
    return out.slice(0, 30);
  }, [local, hits]);
  useEffect(() => { setDropIdx(-1); }, [results]);
  const pick = (r) => {
    setDropOpen(false);
    roots.current.add(r.record.id);
    jump(r.record.id, r.memoryId || undefined);
  };

  const ariaLabel = `Graph of ${memory.name}: ${shown} ${shown === 1 ? 'record' : 'records'} shown`;
  const empty = !read.loading && !read.failed && !Object.keys(all.nodes).length;
  const noLinks = !read.loading && !read.failed && Object.keys(visible.nodes).length > 0 && visible.edges.length === 0;
  const detailEdge = detail && (detail.el.startsWith('e:') || detail.el.startsWith('line:')) ? all.edges.find((e) => e.key === detail.el) : null;
  const detailNode = detail && !detailEdge ? all.nodes[detail.el] : null;

  return (
    <div className="mgv mgv-explorer">
      <div className="dg-body" ref={body}>
        <div className="dg-canvas" ref={box}>
          <div className="sp-explore-bar">
            {/* the panel folds to the right from its left edge, as a setup's Agent stack folds (Richard 11-09) */}
            {onFold ? <button type="button" className="pane-btn mgv-fold" aria-expanded={true} aria-label="Hide graph" title="Hide graph" onClick={onFold}>{I.chevronRight}</button> : null}
            <div className={`sbar${dropOpen ? ' is-open' : ''}`}>
              <span className="mgv-sic">{I.search}</span>
              <input className="sbar-input" value={q} placeholder="Search nodes" aria-label="Search nodes"
                role="combobox" aria-expanded={dropOpen} aria-autocomplete="list" aria-controls="mgv-found"
                aria-activedescendant={dropOpen && dropIdx >= 0 && results[dropIdx] ? `mgv-found-${dropIdx}` : undefined}
                onChange={(e) => { setQ(e.target.value); setDropOpen(true); }}
                onFocus={() => setDropOpen(true)} onBlur={() => setTimeout(() => setDropOpen(false), 180)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') { setDropOpen(false); return; }
                  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    if (!dropOpen || !results.length) return;
                    e.preventDefault();
                    const n = results.length;
                    setDropIdx((i) => (e.key === 'ArrowDown' ? (i + 1) % n : (i <= 0 ? n - 1 : i - 1)));
                    return;
                  }
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    const r = results[dropIdx >= 0 ? dropIdx : 0];
                    if (r) pick(r);
                  }
                }} />
              {dropOpen && q.trim() ? (
                <div className="sb-drop" id="mgv-found" role="listbox" aria-label="Matching nodes">
                  <div className="sb-drop-h">{results.length ? `${results.length} found` : searching ? 'Searching' : 'Nothing found'}</div>
                  {results.map((r, i) => {
                    const k = kindInfo(kindOf(r.record), schema);
                    return (
                      <button type="button" key={r.record.id} id={`mgv-found-${i}`} role="option" aria-selected={i === dropIdx} tabIndex={-1}
                        className={`sb-drop-item${i === dropIdx ? ' active' : ''}`}
                        onMouseDown={(e) => { e.preventDefault(); pick(r); }}>
                        <span className="dot" style={{ background: k.color }} />
                        <span className="mgv-ell">{labelOf(r.record) || 'Untitled'}</span>
                        <span className="stat-lbl mono" style={{ flexShrink: 0 }}>{k.one}</span>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
            <div className="seg mgv-depth" role="group" aria-label="How much to show">
              <button type="button" className={near ? '' : 'on'} aria-pressed={!near} title="Everything in this memory" onClick={() => setView('whole')}>All</button>
              {DEPTHS.map((n) => (
                <button key={n} type="button" className={near && view === n ? 'on' : ''} aria-pressed={near && view === n} disabled={!activeRecordId}
                  title={activeRecordId ? `Within ${n} ${n === 1 ? 'link' : 'links'} of the open record` : 'Open a record first'}
                  aria-label={`Within ${n} ${n === 1 ? 'link' : 'links'} of the open record`} onClick={() => setView(n)}>{n}</button>
              ))}
            </div>
          </div>
          <CytoscapeCanvas
            ref={canvas}
            elements={elements}
            layout="none"
            selectedId={detailEl || activeEl}
            onTapNode={(id) => {
              const n = all.nodes[id];
              setCtx(null);
              setDetail({ el: id, id: n?.record?.id || '' });
              if (n?.record) onOpenRecord(n.record.id, n.memoryId || undefined);
            }}
            onDblTapNode={(id) => { if (collapsed[id]) restore(id); else void expand(id); }}
            onContextMenuNode={(id, _d, pos) => { if (all.nodes[id]?.record) setCtx({ x: pos.x, y: pos.y, key: id }); }}
            onTapEdge={(id) => {
              const e = all.edges.find((x) => x.key === id);
              setCtx(null);
              setDetail({ el: id, id: e?.fact?.id || '' });
              if (e?.fact) onOpenRecord(e.fact.id, e.factMemoryId || undefined);
            }}
            onBackgroundTap={() => { setDetail(null); setCtx(null); }}
            onNodeDragEnd={savePositions}
            badges={badges}
            background="var(--surface)"
            ariaLabel={ariaLabel}
            onCanvasKeyDown={(e) => { if (e.key === 'Escape') { setDetail(null); setCtx(null); } }}
          />
          {ctx ? (
            <NodeContextMenu x={ctx.x} y={ctx.y} collapsed={!!collapsed[ctx.key]} edgeOptions={edgeOptionsFor(ctx.key)}
              edgeColorByLabel={{}} vertexColorByLabel={vertexColorByLabel} vertexIconByLabel={vertexIconByLabel}
              onClose={() => setCtx(null)}
              onExpandAll={() => void expand(ctx.key)}
              onExpandFiltered={(edge, target) => void expand(ctx.key, { edge, target })}
              onCollapse={() => collapse(ctx.key)} onReExpand={() => restore(ctx.key)} />
          ) : null}
          {read.loading ? <div className="dg-canvas-blank"><div className="dg-blank-quiet"><div className="dg-blank-quiet-line" role="status">Reading what this memory holds</div></div></div> : null}
          {read.failed && !Object.keys(all.nodes).length ? (
            <div className="dg-canvas-blank"><div className="dg-blank-quiet"><div className="dg-blank-quiet-line" role="alert">The graph could not be read just now.</div>
              <button type="button" className="btn sm" onClick={() => void load()}>Try again</button></div></div>
          ) : null}
          {empty ? <div className="dg-canvas-blank"><div className="dg-blank-quiet"><div className="dg-blank-quiet-line">Nothing is kept here yet.</div></div></div> : null}
          <div className="mgv-under">
            {read.failed && Object.keys(all.nodes).length ? (
              <p className="mgv-note" role="alert">The latest could not be read, so this may be behind. <button type="button" className="link-q inl" onClick={() => void load()}>Try again</button></p>
            ) : null}
            {all.truncated ? <p className="mgv-note">{`Only the first ${GRAPH_LIMIT} records are drawn. Search for one to see what is near it.`}</p> : null}
            {noLinks ? <p className="mgv-note">These records don’t link to each other.</p> : null}
            {kinds.length > 1 ? (
              <div className="mgv-legend" role="group" aria-label="Kinds of record">
                {kinds.map(({ key, n, info }) => (
                  <button key={key} type="button" className={hiddenKinds.has(key) ? 'off' : ''} aria-pressed={!hiddenKinds.has(key)}
                    title={hiddenKinds.has(key) ? `Show ${info.many}` : `Hide ${info.many}`}
                    onClick={() => setHiddenKinds((s) => { const x = new Set(s); if (x.has(key)) x.delete(key); else x.add(key); return x; })}>
                    <span className="mm-dot sm" style={{ background: info.color }} />{info.many}<small>{n}</small>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <div className="mgv-zoom" role="group" aria-label="Zoom">
            <button type="button" className="pane-btn" aria-label="Zoom in" title="Zoom in" onClick={() => { whole.current = false; zoomBy(canvas, 1.25); }}>+</button>
            <button type="button" className="pane-btn" aria-label="Zoom out" title="Zoom out" onClick={() => { whole.current = false; zoomBy(canvas, 0.8); }}>−</button>
            <button type="button" className="pane-btn" aria-label="Center" title="Center" onClick={fit}>{I.target}</button>
          </div>
        </div>
        {detailEdge ? <DataEdgeDetail edge={detailEdge} nodes={all.nodes} schema={schema} compact={compact} onJump={jump} onClose={() => setDetail(null)} /> : null}
        {detailNode ? (
          <DataNodeDetail node={detailNode} nodes={all.nodes} edges={all.edges} schema={schema} thisMemoryId={mid} compact={compact} collapsed={!!collapsed[detailNode.key]}
            links={linksFor && detailNode.record ? linksFor(detailNode.record.id) : null}
            onJump={jump} onExpand={(k) => void expand(k)} onCollapse={collapse} onRestore={restore} onClose={() => setDetail(null)} />
        ) : null}
      </div>
    </div>
  );
}

// Room around the graph for what lies over the canvas: the search above it, the types below it. A very small pane keeps its room for the graph.
function fitPadding(cy) {
  return Math.min(cy.width(), cy.height()) > 320 ? 56 : 32;
}

// Brings back into view anything the simulation or a new record left outside it.
function showAll(cy) {
  const e = cy.extent();
  const out = cy.nodes().some((n) => { const p = n.position(); return p.x < e.x1 || p.x > e.x2 || p.y < e.y1 || p.y > e.y2; });
  if (!out) return;
  try { cy.animate({ fit: { eles: cy.elements(), padding: fitPadding(cy) } }, { duration: reducedMotion() ? 0 : 420, easing: 'ease-out' }); } catch { /* gone */ }
}

function zoomBy(canvas, f) {
  const cy = canvas.current?.getCy?.();
  if (!cy) return;
  try {
    cy.animate({ zoom: { level: cy.zoom() * f, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } } }, { duration: reducedMotion() ? 0 : 120 });
  } catch { /* gone */ }
}
