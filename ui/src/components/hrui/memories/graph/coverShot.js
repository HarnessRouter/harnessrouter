'use client';
// A memory's cover: its schema drawn as the Schema tab draws it, with the same canvas, stylesheet, positions and links
// set clear of what they'd cross (untangle.ts), then exported as a picture. It is drawn offscreen, with nothing over it
// (no toolbar, panel or selection), on a clear background so it sits on the card's own in either theme, and cropped
// tight to the graph and its names.
//
// Sized for the card it is shown on (memories.css .mm-art, a card on a wide screen): the graph fills four fifths of the
// box in the direction that limits it, and its names read at 11 px or more there. As the Schema tab does on a narrow
// pane, the types and names are drawn larger than the positions alone would make them, but never so large that
// anything lands on anything else. Loaded only when a cover is to be made.
import cytoscape from 'cytoscape';
import { CANVAS_STYLE } from './CytoscapeCanvas.jsx';
import { buildSchemaElements } from './schemaElements';
import { loadCatalog, needsCatalog } from './graphIcons.jsx';
import { untangleCanvas } from './untangle';

/** A card's picture box on a wide screen, the part of it the graph fills, and how large its names read there. */
export const CARD = { w: 268, h: 236 };
export const FILL = 0.8;
export const MIN_NAME_PX = 11.5;
/** The picture is exported at twice the size it is seen, for sharp screens. */
const SHARP = 2;
const MOST_K = 4;
// the stylesheet's sizes, as the Schema tab scales them (fitCanvas)
const BASE = { node: 38, font: 10, icon: 18, text: 140, edge: 1.4, edgeText: 120 };
/** The most a cover may be (the service refuses more). */
const MOST = 512 * 1024;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** The drawing at `k` times its stylesheet sizes, its links set clear: how large it would be seen, and its clashes. */
function drawnAt(cy, k) {
  cy.batch(() => {
    cy.nodes().style({ width: BASE.node * k, height: BASE.node * k, 'font-size': BASE.font * k, 'background-width': BASE.icon * k, 'background-height': BASE.icon * k, 'text-max-width': BASE.text * k });
    cy.edges().style({ width: BASE.edge * k, 'font-size': BASE.font * k, 'text-max-width': BASE.edgeText * k });
  });
  const clashes = untangleCanvas(cy, k);
  const bb = cy.elements().boundingBox();
  const seen = Math.min((CARD.w * FILL) / Math.max(1, bb.w), (CARD.h * FILL) / Math.max(1, bb.h));
  return { k, seen, clashes, namePx: BASE.font * k * seen, w: bb.w, h: bb.h };
}

/** The size to draw at: the smallest that makes the names read at MIN_NAME_PX on the card, or else the largest that puts
 *  nothing on anything that wasn't already. */
function settle(cy) {
  let best = drawnAt(cy, 1);
  for (let k = 1.1; best.namePx < MIN_NAME_PX && k <= MOST_K + 1e-9; k = Math.round(k * 110) / 100) {
    const at = drawnAt(cy, k);
    if (at.clashes > best.clashes) break;
    best = at;
  }
  return drawnAt(cy, best.k);
}

/** Until every icon the drawing names is loaded, or a second has gone. */
async function iconsLoaded(cy) {
  const r = cy.renderer && cy.renderer();
  for (let i = 0; i < 20; i++) {
    const all = Object.values((r && r.imageCache) || {});
    if (all.length && all.every((c) => c.image && (c.image.complete || c.image.error))) return;
    if (!cy.nodes('[iconUrl]').length) return;
    await sleep(50);
  }
}

/** How the last cover was framed (for checking it against a card). */
export let lastFrame = null;

/** The cover of `graph` (a schema as the Schema tab draws it, the provider's own types included), as a PNG. */
export async function drawCover(graph) {
  const icons = (graph?.vertex_types || []).map((v) => v.ui && v.ui.icon);
  if (needsCatalog(icons)) await loadCatalog();
  // each type by its title, as the tab names it; no record counts, which change and would date the picture
  const captionOf = (label, d) => (graph.titles && graph.titles[label]) || String((d && d.name) || label).replace(/_/g, ' ');
  const box = document.createElement('div');
  box.setAttribute('aria-hidden', 'true');
  Object.assign(box.style, { position: 'fixed', left: '-10000px', top: '0', width: `${CARD.w}px`, height: `${CARD.h}px`, pointerEvents: 'none', opacity: '0', zIndex: '-1' });
  document.body.appendChild(box);
  const cy = cytoscape({
    container: box, elements: buildSchemaElements(graph, null, null, captionOf), style: CANVAS_STYLE, layout: { name: 'preset' },
    autoungrabify: true, autounselectify: true, userZoomingEnabled: false, userPanningEnabled: false, boxSelectionEnabled: false,
    textureOnViewport: false, pixelRatio: 1, minZoom: 0.01, maxZoom: 8,
  });
  try {
    cy.fit(undefined, 0);
    // a first drawing asks for the icons; the picture is taken once they have come
    cy.png({ output: 'base64uri', scale: 0.1 });
    await iconsLoaded(cy);
    const at = settle(cy);
    lastFrame = at;
    // the whole graph and its names, nothing around them, at twice the size it is seen
    let pic = await cy.png({ output: 'blob-promise', full: true, scale: at.seen * SHARP });
    if (pic.size > MOST) pic = await cy.png({ output: 'blob-promise', full: true, scale: at.seen });
    return pic;
  } finally {
    cy.destroy();
    box.remove();
  }
}
