'use client';

import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import edgehandles from 'cytoscape-edgehandles';

// Register extensions once. Cytoscape stores extensions on its module-level
// prototype, so calling register twice is a no-op but we guard anyway.
let _ehRegistered = false;
if (!_ehRegistered) {
  try { cytoscape.use(edgehandles); _ehRegistered = true; } catch {}
}

// Honor the OS reduced-motion preference: layout/glide animations become
// instant placements. Module-level (read once) — the preference rarely flips
// mid-session, and every layout config below reads this same constant.
const REDUCED_MOTION = typeof window !== 'undefined'
  && typeof window.matchMedia === 'function'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * Shared Cytoscape canvas used by both schema and data graphs.
 *
 * - `elements` is a plain array of `{ data, position?, classes? }`.
 * - `layout` is either:
 *     - `"preset"` — honors `position` on each node (the schema view, where positions are saved).
 *     - `"none"` — the host places every element and moves it (the data graph, see layout.ts).
 *
 * Lifecycle:
 *   - mount cy once (empty)
 *   - diff-sync elements on prop change
 *   - persist drag positions to a ref-held Map
 *   - ResizeObserver -> cy.resize() so parent split-pane drags don't clip
 *   - on unmount: stop running layout, stop cy, destroy
 */

const FALLBACK_PALETTE = [
  { fill: '#E7E3F5', ring: '#7C3AED' },
  { fill: '#DBEAFE', ring: '#3B82F6' },
  { fill: '#D1FAE5', ring: '#059669' },
  { fill: '#FEF3C7', ring: '#D97706' },
  { fill: '#FCE7F3', ring: '#EC4899' },
  { fill: '#F1F5F9', ring: '#475569' },
];
function hash(s) {
  let h = 0; for (let i = 0; i < s.length; i++) { h = ((h << 5) - h + s.charCodeAt(i)) | 0; } return Math.abs(h);
}
export function colorFor(label) {
  return FALLBACK_PALETTE[hash(String(label || '')) % FALLBACK_PALETTE.length];
}

// Stylesheet, light surface. A memory's cover is drawn with it too (coverShot.js), so it looks as the Schema tab does.
export const CANVAS_STYLE = [
  {
    selector: 'node',
    style: {
      // The whole disk is the stored color; no default border. Selection
      // is the only thing that draws a border.
      'background-color': 'data(color)',
      'border-width': 0,
      label: 'data(caption)',
      // Slate-600 -- matches the edge label color so node and edge text
      // read at the same visual weight.
      color: '#475569',
      // Node + edge labels MUST share font-size AND min-zoomed-font-size so they
      // appear/disappear at the exact same zoom (threshold = min-zoomed/font =
      // 6/10 = 0.6). Any divergence makes one fade before the other.
      'font-size': 10,
      'font-weight': 600,
      'font-family': '-apple-system, BlinkMacSystemFont, Inter, "Segoe UI", Roboto, sans-serif',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'text-margin-y': 6,
      'text-wrap': 'wrap',
      'text-max-width': 140,
      'line-height': 1.25,
      'text-background-color': '#FFFFFF',
      'text-background-opacity': 0.8,
      'text-background-padding': 4,
      'text-background-shape': 'roundrectangle',
      // No border on labels -- the soft white background is enough.
      'text-border-width': 0,
      width: 38,
      height: 38,
      'min-zoomed-font-size': 6,
    },
  },
  {
    // Only apply the icon image to nodes that actually carry an iconUrl
    // -- mappers on an empty/undefined value throw at parse time.
    selector: 'node[iconUrl]',
    style: {
      'background-image': 'data(iconUrl)',
      'background-fit': 'none',
      'background-clip': 'node',
      'background-image-opacity': 1,
      'background-image-containment': 'inside',
      'background-position-x': '50%',
      'background-position-y': '50%',
      // Use fixed px width so the glyph sits comfortably inside the
      // 38px disk regardless of how Cytoscape interprets percentages.
      'background-width': 18,
      'background-height': 18,
    },
  },
  {
    // Cytoscape's default :active state paints a grey overlay disc on press —
    // off-brand noise; selection styling is the only press feedback we want.
    selector: ':active',
    style: { 'overlay-opacity': 0 },
  },
  {
    selector: 'node:selected',
    style: {
      // Selection ring sits OUTSIDE the disk so the colored fill stays
      // intact. Brand color so it's unambiguous which node is selected.
      'border-width': 3,
      'border-color': '#285aff',
      'border-opacity': 1,
    },
  },
  {
    selector: 'node[size]',
    style: { width: 'data(size)', height: 'data(size)' },
  },
  // The active record's neighbourhood stays lit and the rest steps back; a hover steps it back further.
  { selector: 'node.act-dim', style: { opacity: 0.45, 'text-opacity': 0.55 } },
  { selector: 'edge.act-dim', style: { opacity: 0.25, 'text-opacity': 0.4 } },
  { selector: 'node.dim', style: { opacity: 0.15, 'text-opacity': 0.2 } },
  { selector: 'edge.dim', style: { opacity: 0.08, 'text-opacity': 0.1 } },
  { selector: 'node.hov', style: { 'font-size': 11, 'z-index': 20, 'min-zoomed-font-size': 0 } },
  { selector: 'edge.hov', style: { width: 2.2, opacity: 1, 'min-zoomed-font-size': 0 } },
  // A record the reader may not open: a plain grey disc, with no name of its own.
  { selector: 'node.closed', style: { 'border-width': 1.5, 'border-style': 'dashed', 'border-color': '#94A3B8' } },
  { selector: 'edge.closed', style: { 'line-style': 'dashed', 'line-dash-pattern': [4, 4], label: '' } },
  { selector: 'edge.plain', style: { 'target-arrow-shape': 'none' } },
  // Something just changed here.
  { selector: 'node.pulse', style: { 'underlay-color': '#285aff', 'underlay-opacity': 0.32, 'underlay-padding': 12, 'underlay-shape': 'ellipse' } },
  { selector: 'edge.pulse', style: { width: 3.2, 'line-color': '#285aff', 'target-arrow-color': '#285aff', opacity: 1 } },
  {
    // Full-perimeter connect affordance: hovering the rim lights the WHOLE
    // border with a soft brand glow (drawn as an underlay ring behind the
    // disk, so the fill/icon stay intact). Signals "press anywhere on this
    // rim and drag to link".
    selector: 'node.eh-rim',
    style: {
      'underlay-color': '#285aff',
      'underlay-opacity': 0.18,
      'underlay-padding': 7,
      'underlay-shape': 'ellipse',
    },
  },
  {
    selector: 'edge',
    style: {
      width: 1.4,
      // Color is sourced from edge data so live preview / saved edits
      // flow through. buildSchemaElements always sets `lineColor` (grey
      // when no override exists) so the data() mapper never resolves to
      // null. Using a selector-matched override fails to re-evaluate
      // when the attribute is added after mount.
      'line-color': 'data(lineColor)',
      'target-arrow-color': 'data(lineColor)',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.9,
      'curve-style': 'bezier',
      'control-point-step-size': 40,
      opacity: 0.85,
      label: 'data(caption)',
      // Match node labels exactly (font-size + min-zoomed-font-size) so node and
      // edge captions hide/show at the identical zoom threshold (0.6).
      'font-size': 10,
      'min-zoomed-font-size': 6,
      'font-weight': 500,
      color: '#475569',
      'text-background-color': '#FFFFFF',
      'text-background-opacity': 0.92,
      'text-background-padding': 2,
      'text-background-shape': 'roundrectangle',
      'text-rotation': 'autorotate',
      // Long relationship names ellipsize (native "…") instead of running long
      // under the rotated edge or hard-clipping. Matches the node-label intent.
      'text-wrap': 'ellipsis',
      'text-max-width': 120,
    },
  },
  {
    // Draft (not-yet-saved) schema connection — dashed + brand tint so the
    // pending edge reads as a preview until the user clicks Save.
    selector: 'edge.preview',
    style: {
      'line-style': 'dashed',
      'line-dash-pattern': [6, 4],
      'line-color': '#285aff',
      'target-arrow-color': '#285aff',
      opacity: 0.9,
    },
  },
  {
    selector: 'edge:selected',
    style: {
      width: 2.4,
      'line-color': '#285aff',
      'target-arrow-color': '#285aff',
      color: '#1641d8',
      opacity: 1,
    },
  },
  // ── Drag-to-connect (cytoscape-edgehandles) ─────────────────────────────
  // The in-flight ghost edge + the snapped preview read as a pending link:
  // dashed brand line, no caption yet (the label is asked for on drop).
  // These selectors sit AFTER the base edge rules so they override the
  // data(lineColor)/data(caption) mappers, which the ghost edge lacks.
  //
  // CRITICAL: every edge-preview rule is EDGE-scoped (`edge.eh-*`). In a
  // SELF-LOOP draw (drag a node's rim back onto itself) edgehandles puts the
  // `eh-preview` / `eh-preview-active` classes on the SOURCE NODE too — a
  // class-only `.eh-preview` selector would then apply the edge's `width: 1.6`
  // to the node, collapsing the disk to a 1.6px vertical bar. Scoping to
  // `edge.` keeps the node a full circle while its loop preview draws.
  {
    selector: 'edge.eh-ghost-edge, edge.eh-preview',
    style: {
      width: 1.6,
      'line-style': 'dashed',
      'line-dash-pattern': [6, 4],
      'line-color': '#285aff',
      'target-arrow-color': '#285aff',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      label: '',
      opacity: 0.9,
    },
  },
  // Once the preview snaps onto a target, hide the free-floating ghost.
  {
    selector: 'edge.eh-ghost-edge.eh-preview-active',
    style: { opacity: 0 },
  },
  // Endpoints of the in-flight draw get the brand ring (node-scoped).
  {
    selector: 'node.eh-source, node.eh-target, node.eh-presumptive-target',
    style: { 'border-width': 3, 'border-color': '#285aff', 'border-opacity': 1 },
  },
  // Edgehandles' own invisible helper node (it anchors the ghost edge).
  {
    selector: 'node.eh-ghost-node',
    style: { 'background-opacity': 0, 'border-width': 0, width: 1, height: 1, label: '' },
  },
];

const CytoscapeCanvas = forwardRef(function CytoscapeCanvas({
  elements,
  layout = 'preset',
  selectedId,
  onTapNode,
  onTapEdge,
  onDblTapNode,
  onDblTapEdge,
  onContextMenuNode,
  onBackgroundTap,
  onNodeDragEnd,
  onNodeGrab,          // optional: user pressed a node (start of a drag)
  onNodeDrag,          // optional: coarse in-drag positions (throttled ~120ms)
  onNodeFree,          // optional: user released a node (fires even without movement)
  edgeDrawEnabled = false,   // drag-to-connect: hovering a node arms its whole rim
  onEdgeDraw,          // (sourceId, targetId, renderedPos) after a successful draw
  animatePositions = false,   // glide existing nodes to incoming positions (collab)
  badges,              // { [nodeId]: number } — render a count badge top-right of each
  frozen = false,
  background = '#FAFBFD',
  className,
  style,
  // Optional accessibility hooks (additive — omitted props change nothing):
  ariaLabel,           // the outer element gets role="img" + this label (content summary)
  onCanvasKeyDown,     // the outer element becomes tabbable and forwards keydown events
}, ref) {
  const containerRef = useRef(null);
  const cyRef = useRef(null);
  // The latest handlers: the listeners below are attached once, at mount, and must not call a stale one.
  const handlers = useRef({});
  handlers.current = { onTapNode, onTapEdge, onDblTapNode, onDblTapEdge, onBackgroundTap };
  const layoutRef = useRef(null);
  const positionsRef = useRef(new Map());
  const hasFitRef = useRef(false);
  // Mirrors the `frozen` prop on a ref so the long-lived ResizeObserver
  // callback can read the latest value without being re-registered.
  const frozenRef = useRef(frozen);
  // ── Drag-to-connect (edgehandles) state ─────────────────────────────────
  // Full-perimeter model: hovering a node lights its whole rim (a glow ring),
  // and pressing on the rim band + dragging starts the edgehandles draw from
  // ANY point on the border — not a single top dot. Pressing the inner body
  // still moves the node. The eh instance is created once at mount and stays
  // inert until eh.start() fires from the rim mousedown. Refs mirror the
  // in-draw flag + the currently-armed rim node so the long-lived cy listeners
  // read fresh state without re-registering.
  const ehRef = useRef(null);
  const ehDrawingRef = useRef(false);
  const rimNodeRef = useRef(null);   // cy node whose rim the pointer is over (armed to draw)

  // Mount the cy instance once.
  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: CANVAS_STYLE,
      layout: { name: 'preset' },
      wheelSensitivity: 0.25,
      minZoom: 0.1,
      maxZoom: 4,
      // Don't pixelate labels when zoomed out.
      textureOnViewport: false,
      pixelRatio: window.devicePixelRatio || 1,
    });
    cyRef.current = cy;

    // Debounce single-tap so a dbltap can cancel it. Cytoscape fires
    // `tap` AND `dbltap` on a double-click — without this guard, double-
    // clicking would both open the detail panel (from tap) and expand
    // neighbors (from dbltap). 250ms matches the OS double-click window.
    const TAP_DELAY_MS = 250;
    let pendingTap = null;
    const cancelPendingTap = () => {
      if (pendingTap) { clearTimeout(pendingTap); pendingTap = null; }
    };
    cy.on('tap', 'node', (e) => {
      const id = e.target.id();
      const data = e.target.data();
      cancelPendingTap();
      pendingTap = setTimeout(() => {
        pendingTap = null;
        handlers.current.onTapNode && handlers.current.onTapNode(id, data);
      }, TAP_DELAY_MS);
    });
    cy.on('tap', 'edge', (e) => {
      const id = e.target.id();
      const data = e.target.data();
      cancelPendingTap();
      pendingTap = setTimeout(() => {
        pendingTap = null;
        handlers.current.onTapEdge && handlers.current.onTapEdge(id, data);
      }, TAP_DELAY_MS);
    });
    cy.on('dbltap', 'node', (e) => {
      cancelPendingTap();
      handlers.current.onDblTapNode && handlers.current.onDblTapNode(e.target.id(), e.target.data());
    });
    cy.on('dbltap', 'edge', (e) => {
      cancelPendingTap();
      handlers.current.onDblTapEdge && handlers.current.onDblTapEdge(e.target.id(), e.target.data());
    });
    cy.on('tap', (e) => {
      if (e.target === cy) {
        cancelPendingTap();
        handlers.current.onBackgroundTap && handlers.current.onBackgroundTap();
      }
    });
    // Right-click on a node — emit screen coords so the page can render
    // a context menu absolutely positioned over the canvas.
    cy.on('cxttap', 'node', (e) => {
      cancelPendingTap();
      const fn = cy.scratch('_onContextMenuNode');
      if (!fn) return;
      const id = e.target.id();
      const data = e.target.data();
      // originalEvent gives us viewport coords; fall back to cy renderedPos.
      const oe = e.originalEvent;
      let x, y;
      if (oe && typeof oe.clientX === 'number') {
        x = oe.clientX; y = oe.clientY;
      } else {
        const r = containerRef.current.getBoundingClientRect();
        const rp = e.target.renderedPosition();
        x = r.left + rp.x; y = r.top + rp.y;
      }
      fn(id, data, { x, y });
    });
    // Suppress the browser context menu inside the canvas.
    if (containerRef.current) {
      containerRef.current.addEventListener('contextmenu', (ev) => ev.preventDefault());
    }
    cy.on('dragfree', 'node', (e) => {
      const n = e.target;
      const p = n.position();
      positionsRef.current.set(n.id(), p);
      // Always call the latest handler — the ref bypasses the stale-closure
      // problem from registering the listener once on mount.
      const fn = cy.scratch('_onNodeDragEnd');
      if (fn) fn(n.id(), { x: p.x, y: p.y }, n.data());
    });
    // Drag presence hooks (collab hosts): grab = drag start, drag = coarse
    // in-flight positions (throttled), free = release (fires even when the
    // node never moved, so a held awareness state always clears).
    cy.on('grab', 'node', (e) => {
      const fn = cy.scratch('_onNodeGrab');
      if (fn) { const p = e.target.position(); fn(e.target.id(), { x: p.x, y: p.y }); }
    });
    let lastDragEmit = 0;
    cy.on('drag', 'node', (e) => {
      const fn = cy.scratch('_onNodeDrag');
      if (!fn) return;
      const now = Date.now();
      if (now - lastDragEmit < 120) return;
      lastDragEmit = now;
      const p = e.target.position();
      fn(e.target.id(), { x: p.x, y: p.y });
    });
    cy.on('free', 'node', (e) => {
      const fn = cy.scratch('_onNodeFree');
      if (fn) { const p = e.target.position(); fn(e.target.id(), { x: p.x, y: p.y }); }
    });

    // Drag-to-connect. The extension is inert until the rim mousedown calls
    // eh.start(node): from there it draws the dashed ghost edge, snaps onto
    // candidate targets, and completes on mouseup over one. Self-loops are
    // allowed (canConnect always true — the schema popover decides validity),
    // and releasing over empty canvas cancels cleanly (ehcancel → no-op).
    let eh = null;
    try {
      eh = cy.edgehandles({
        canConnect: () => true,
        edgeParams: () => ({ data: {} }),
        snap: true,
        snapThreshold: 28,
        snapFrequency: 15,
        noEdgeEventsInDraw: true,
        disableBrowserGestures: true,
      });
    } catch { /* extension unavailable — the dialog path still works */ }
    ehRef.current = eh;
    cy.on('ehstart', () => { ehDrawingRef.current = true; });
    cy.on('ehstop', () => { ehDrawingRef.current = false; });
    cy.on('ehcomplete', (e, sourceNode, targetNode, addedEdge) => {
      // The drawn edge is a placeholder — remove it; the caller persists the
      // schema change and the element sync re-renders the real edge.
      try { addedEdge && addedEdge.remove(); } catch {}
      const fn = cy.scratch('_onEdgeDraw');
      if (!fn) return;
      const rp = targetNode.renderedPosition();
      fn(sourceNode.id(), targetNode.id(), { x: rp.x, y: rp.y });
    });
    // The draw starts on a cy mousedown, and a mouseup that never crosses the
    // canvas (released off-node on empty space, or outside the graph) would
    // otherwise leave the gesture hanging — end it from the window.
    const onWinMouseUp = () => { try { eh && eh.stop(); } catch {} };
    window.addEventListener('mouseup', onWinMouseUp);

    // On container resize: when the parent signals `frozen` (e.g. the
    // user is dragging the middle divider) we skip cy.resize() AND
    // cy.fit() entirely — even cy.resize() costs a layout pass and
    // visibly stutters at high frame rates. The frozen→unfrozen
    // transition is handled in a separate useEffect below: that's when
    // we do a single resize + fit to catch up to the final geometry.
    const ro = new ResizeObserver(() => {
      if (frozenRef.current) return;
      try { cy.resize(); } catch {}
    });
    ro.observe(containerRef.current);

    return () => {
      window.removeEventListener('mouseup', onWinMouseUp);
      try { ro.disconnect(); } catch {}
      try { eh && eh.destroy(); } catch {}
      try { layoutRef.current && layoutRef.current.stop(); } catch {}
      try { cy.stop(true, true); } catch {}
      try { cy.destroy(); } catch {}
      cyRef.current = null;
      ehRef.current = null;
      layoutRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync elements + run layout when props change.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const incomingIds = new Set((elements || []).map((e) => e.data.id));
    let removed = 0;
    cy.elements().forEach((el) => {
      if (!incomingIds.has(el.id())) { el.remove(); removed += 1; }
    });

    const presentIds = new Set(cy.elements().map((el) => el.id()));
    const toAdd = [];
    const newNodeIds = new Set();
    (elements || []).forEach((el) => {
      if (presentIds.has(el.data.id)) {
        // Already present — update mutable data + position (the parent
        // owns positions so Discard can snap nodes back to saved state).
        const node = cy.getElementById(el.data.id);
        if (node && node.length) {
          node.data(el.data);
          if (el.position) {
            const cur = node.position();
            if (Math.abs(cur.x - el.position.x) > 0.5 || Math.abs(cur.y - el.position.y) > 0.5) {
              // Collab hosts glide nodes to incoming (peer-moved) positions
              // instead of teleporting — 0.5s eased. Never animate the node
              // the LOCAL user is holding (their drag owns it), and never
              // before the first fit (initial paint must be instant).
              if (animatePositions && !REDUCED_MOTION && hasFitRef.current && !node.grabbed()) {
                try { node.stop(); } catch {}
                node.animate({ position: { x: el.position.x, y: el.position.y } },
                             { duration: 500, easing: 'ease-in-out-cubic' });
              } else if (!node.grabbed()) {
                node.position(el.position);
              }
            }
          }
        }
      } else {
        toAdd.push(el);
        if (!el.data.source) newNodeIds.add(el.data.id);
      }
    });
    if (toAdd.length) cy.add(toAdd);

    // Apply pinned positions ONLY to nodes being added this sync.
    // Existing nodes are NEVER re-positioned by this loop — once a
    // node is on the canvas, its current cy position is the source of
    // truth and the sync must not stomp it. (Previously this loop
    // iterated every entry in positionsRef, which moved any node that
    // had ever been pinned/dragged back to its recorded position on
    // every render — the user kept seeing existing nodes 'snap' or
    // 'drag' on each expand. Limit application to fresh adds.)
    toAdd.forEach((el) => {
      if (el.data.source) return; // edge
      const pos = positionsRef.current.get(el.data.id);
      if (!pos) return;
      const n = cy.getElementById(el.data.id);
      if (n && n.length) n.position(pos);
    });

    // If nothing was added OR removed, skip the layout entirely. This is
    // the path taken after a drag (only data + position mutate) so the
    // viewport stays put instead of refitting and jumping the camera.
    const structuralChange = removed > 0 || toAdd.length > 0;
    if (!structuralChange) return;

    // The caller may pre-position nodes (e.g. restore from a collapsed
    // snapshot at concentric ring offsets) and request that we don't
    // run a layout pass on top of them. Honor that, consume the flag.
    if (cy.scratch('_skipNextLayout')) {
      cy.scratch('_skipNextLayout', false);
      return;
    }

    // 'preset' honours each element's position, fitting only on first paint. 'none' is a host that places every
    // element itself and runs its own simulation.
    if (layout === 'preset') {
      const firstPaint = !hasFitRef.current;
      cy.layout({ name: 'preset', fit: firstPaint, padding: 60 }).run();
      hasFitRef.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements, layout]);

  // Selection sync
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().unselect();
    if (selectedId) {
      const el = cy.getElementById(selectedId);
      if (el && el.length) el.select();
    }
  }, [selectedId]);

  // Stash the latest drag-end handler on cy.scratch so the dragfree
  // listener (registered once on mount) always calls the current one
  // instead of capturing a stale closure.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.scratch('_onNodeDragEnd', onNodeDragEnd || null);
  }, [onNodeDragEnd]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.scratch('_onContextMenuNode', onContextMenuNode || null);
  }, [onContextMenuNode]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.scratch('_onNodeGrab', onNodeGrab || null);
    cy.scratch('_onNodeDrag', onNodeDrag || null);
    cy.scratch('_onNodeFree', onNodeFree || null);
  }, [onNodeGrab, onNodeDrag, onNodeFree]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.scratch('_onEdgeDraw', onEdgeDraw || null);
  }, [onEdgeDraw]);

  // ── Drag-to-connect: full-perimeter rim activation ───────────────────────
  // Hovering a node lights its ENTIRE border (a glow ring — the `.eh-rim`
  // class), signalling "this whole rim is draggable". A pointer inside the
  // rim BAND (an annulus hugging the border, ~0.62r..1.3r) arms the node:
  // its center-drag move is suspended (ungrabify) and user-panning is paused
  // so a press-and-drag there starts an edge draw from that exact point on
  // the border instead of moving the node or panning. The INNER body stays
  // grabbable, so pressing the center still repositions the node — the
  // standard graph-editor gesture (rim = draw, center = move).
  //
  // Always on for the schema canvas — connecting types is a first-class
  // canvas action, never gated on the inspector toggle (a compact pane
  // floats the inspector over the whole canvas, which would make it
  // unreachable). Pointer-driven, so desktop-only by nature — narrow / touch
  // flows go through the New-type dialog, which creates the same link.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return undefined;
    const container = containerRef.current;
    if (!edgeDrawEnabled) return undefined;

    // Disarm: re-grabify the armed node, restore panning + cursor, drop the ring.
    const disarm = () => {
      const n = rimNodeRef.current;
      if (n) { try { n.grabify(); n.removeClass('eh-rim'); } catch {} }
      rimNodeRef.current = null;
      try { cy.userPanningEnabled(true); } catch {}
      if (container) container.style.cursor = '';
    };
    // Arm node `n`: light its rim, suspend its move + panning so the next
    // press-drag draws an edge rather than moving/panning.
    const arm = (n) => {
      if (rimNodeRef.current === n) return;
      disarm();
      rimNodeRef.current = n;
      try { n.ungrabify(); n.addClass('eh-rim'); } catch {}
      try { cy.userPanningEnabled(false); } catch {}
      if (container) container.style.cursor = 'crosshair';
    };

    // Nearest node to the pointer whose rim band contains it. Model coords, so
    // the r*factor thresholds are zoom-independent (both are model units).
    const rimHit = (pos) => {
      let best = null, bestD = Infinity;
      cy.nodes().forEach((n) => {
        if (n.hasClass('eh-ghost-node')) return;
        const p = n.position();
        const r = Math.max(n.outerWidth(), n.outerHeight()) / 2;
        const d = Math.hypot(pos.x - p.x, pos.y - p.y);
        // Band hugs the border: from just inside (center-move zone ends at
        // 0.62r) out to a hair beyond the rim (1.3r). Inside 0.62r → move.
        if (d >= r * 0.62 && d <= r * 1.3 && d < bestD) { bestD = d; best = n; }
      });
      return best;
    };

    // Cytoscape's core `mousemove` does not reliably carry `.position` (the
    // model-space cursor) across builds — it can be undefined. Derive it from
    // `.renderedPosition` (screen space) through the live pan/zoom when it is,
    // and only bail if neither is available. Without this the hit-test threw
    // on every move and the rim never armed.
    const modelPos = (e) => {
      if (e.position && typeof e.position.x === 'number') return e.position;
      const rp = e.renderedPosition || (e.originalEvent && (() => {
        const b = container && container.getBoundingClientRect();
        return b ? { x: e.originalEvent.clientX - b.left, y: e.originalEvent.clientY - b.top } : null;
      })());
      if (!rp) return null;
      const pan = cy.pan(), z = cy.zoom() || 1;
      return { x: (rp.x - pan.x) / z, y: (rp.y - pan.y) / z };
    };
    const onMouseMove = (e) => {
      if (ehDrawingRef.current) return;   // a draw owns the pointer
      const pos = modelPos(e);
      if (!pos) return;
      let hit = null;
      try { hit = rimHit(pos); } catch { hit = null; }
      if (hit) arm(hit); else disarm();
    };
    // Press on an armed rim → start the draw from here. Bound at CAPTURE on the
    // container so it runs before edgehandles' own tapstart wiring; the node is
    // ungrabified and panning paused, so nothing competes with the draw.
    const onMouseDownCapture = () => {
      const n = rimNodeRef.current;
      const eh = ehRef.current;
      if (!n || !eh || ehDrawingRef.current) return;
      try { eh.start(n); } catch {}
    };

    cy.on('mousemove', onMouseMove);
    cy.on('ehstop', disarm);
    if (container) container.addEventListener('mousedown', onMouseDownCapture, true);
    return () => {
      cy.off('mousemove', onMouseMove);
      cy.off('ehstop', disarm);
      if (container) container.removeEventListener('mousedown', onMouseDownCapture, true);
      disarm();
    };
  }, [edgeDrawEnabled]);

  // ── Badge overlay ───────────────────────────────────────────────────
  // Renders absolutely-positioned count chips on collapsed nodes. Tracks
  // cy pan/zoom/position events to keep badges glued to their nodes,
  // and scales the badge by cy.zoom() so it stays proportional to the
  // circle as the user zooms in/out.
  const [badgePositions, setBadgePositions] = useState({});
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const ids = Object.keys(badges || {});
    if (ids.length === 0) {
      setBadgePositions({});
      return undefined;
    }
    const recompute = () => {
      const next = {};
      for (const id of ids) {
        const n = cy.getElementById(id);
        if (!n || !n.length) continue;
        // The circle's actual box (ignore the caption below it AND the
        // selection/active overlay — otherwise selecting a node expands the
        // box and the badge drifts up-and-right off the circle). Top-right
        // corner is where the badge anchors, half-on / half-off the stroke.
        const bb = n.renderedBoundingBox({ includeLabels: false, includeOverlays: false });
        next[id] = { x: bb.x2, y: bb.y1 };
      }
      setBadgePositions(next);
      setZoom(cy.zoom());
    };
    recompute();
    cy.on('pan zoom position render layoutstop', recompute);
    return () => { cy.off('pan zoom position render layoutstop', recompute); };
  }, [badges]);

  // When `frozen` toggles, mirror it onto the ref so the long-lived
  // ResizeObserver respects the latest value. On the unfreeze edge,
  // catch up: resize the renderer to the now-final container size and
  // refit so the camera lines up.
  useEffect(() => {
    const wasFrozen = frozenRef.current;
    frozenRef.current = frozen;
    if (wasFrozen && !frozen) {
      const cy = cyRef.current;
      if (!cy) return;
      try {
        cy.resize();
        cy.fit(undefined, 40);
      } catch {}
    }
  }, [frozen]);

  // Imperative escape hatch for callers that need fine-grained
  // control — e.g. seeding new nodes at specific positions, locking
  // existing nodes, then running an incremental the simulation pass.
  useImperativeHandle(ref, () => ({
    getCy: () => cyRef.current,
    fit() {
      const cy = cyRef.current;
      if (cy) try { cy.fit(undefined, 40); } catch {}
    },
    // Pre-stash SEED positions for nodes that are about to be added.
    // The sync useEffect will set each new node to its seeded
    // position before the the simulation-incremental pass runs, so the simulation
    // starts from those positions rather than scattering. Existing
    // nodes are not touched (the sync only applies positionsRef to
    // toAdd ids). For callers that want ZERO iterations (e.g.
    // restore-from-collapse), pass skipLayout=true and the next
    // sync will return before dispatching the simulation.
    pinPositionsAndSkipLayout(positionsByKey, skipLayout = false) {
      const cy = cyRef.current;
      if (!cy) return;
      for (const [k, pos] of Object.entries(positionsByKey || {})) {
        positionsRef.current.set(k, pos);
      }
      if (skipLayout) cy.scratch('_skipNextLayout', true);
    },
    // Anchor position (in cy coordinates) for an existing node, plus
    // its radius. Lets the page compute a concentric-ring layout
    // around it before pinning the neighbors back.
    anchorMetrics(id) {
      const cy = cyRef.current;
      if (!cy) return null;
      const n = cy.getElementById(id);
      if (!n || !n.length) return null;
      const p = n.position();
      const w = n.outerWidth();
      const h = n.outerHeight();
      return { x: p.x, y: p.y, radius: Math.max(w, h) / 2 };
    },
    // Centroid of every node currently on canvas EXCEPT the given
    // anchor — used to derive the "outward" direction so new neighbors
    // can be biased away from existing clusters instead of being
    // dropped into the middle of them.
    nodeCentroidExcluding(excludeId) {
      const cy = cyRef.current;
      if (!cy) return null;
      let sx = 0, sy = 0, n = 0;
      cy.nodes().forEach((node) => {
        if (excludeId && node.id() === excludeId) return;
        const p = node.position();
        sx += p.x; sy += p.y; n += 1;
      });
      if (n === 0) return null;
      return { x: sx / n, y: sy / n };
    },
  }), []);

  return (
    <div
      style={{ position: 'relative', width: '100%', height: '100%', ...style }}
      className="cy-canvas-wrap"
      {...(ariaLabel ? { role: 'img', 'aria-label': ariaLabel } : {})}
      {...(onCanvasKeyDown ? { tabIndex: 0, onKeyDown: onCanvasKeyDown } : {})}
    >
      <div
        ref={containerRef}
        className={className}
        style={{
          background,
          width: '100%',
          height: '100%',
        }}
      />
      {Object.entries(badgePositions).map(([id, pos]) => {
        const n = badges && badges[id];
        if (!n) return null;
        return (
          <div
            key={id}
            className="cy-badge"
            style={{
              position: 'absolute',
              // translate(-50%, -50%) centers the badge on the corner so
              // it sits half-on / half-off the node's stroke. scale(zoom)
              // keeps the badge proportional to the circle as the viewport
              // zooms; both transforms compose around the badge's center
              // (transform-origin defaults to 50% 50%).
              left: pos.x,
              top:  pos.y,
              transform: `translate(-50%, -50%) scale(${zoom})`,
              pointerEvents: 'none',
            }}
          >
            {n}
          </div>
        );
      })}
    </div>
  );
});

export default CytoscapeCanvas;
