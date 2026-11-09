'use client';
// A memory's cover: its schema drawn as the Schema tab draws it, with the same canvas and stylesheet, then exported as
// a picture. It is drawn offscreen, in a hidden box the size of a card's picture, with nothing over it (no toolbar, no
// panel, no selection), framed to the graph with a little margin and exported at twice that size, on a clear
// background so it sits on the card's own in either theme. Loaded only when a cover is to be made.
import cytoscape from 'cytoscape';
import { CANVAS_STYLE } from './CytoscapeCanvas.jsx';
import { buildSchemaElements } from './schemaElements';
import { loadCatalog, needsCatalog } from './graphIcons.jsx';

// The box a card shows its picture in (memories.css .mm-art), so the drawing is framed at the size it is seen.
const W = 340, H = 236, PAD = 16, SCALE = 2;
// As the Schema tab (fitCanvas), a type is drawn larger where the frame makes it small, so its name stays readable, and
// a relation's name with it, so it isn't cut.
const BASE = { node: 38, font: 10, icon: 18, text: 140, edge: 1.4, edgeText: 120 };
/** The most a cover may be (the service refuses more). */
const MOST = 512 * 1024;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function sizeFor(cy, k) {
  cy.batch(() => {
    cy.nodes().style({ width: BASE.node * k, height: BASE.node * k, 'font-size': BASE.font * k, 'background-width': BASE.icon * k, 'background-height': BASE.icon * k, 'text-max-width': BASE.text * k });
    cy.edges().style({ width: BASE.edge * k, 'font-size': BASE.font * k, 'text-max-width': BASE.edgeText * k });
  });
}

/** Fit the graph to the frame, as the Schema tab does: never zoomed past 1.3, and every type drawn large enough to read
 *  at the size the frame is seen. A few rounds, since larger names make the graph larger. */
function frame(cy) {
  let k = 1;
  for (let i = 0; i < 4; i++) {
    sizeFor(cy, k);
    cy.fit(undefined, PAD);
    if (cy.zoom() > 1.3) { cy.zoom(1.3); cy.center(); }
    const next = Math.max(1, Math.min(3.2, 1.25 / cy.zoom()));
    if (Math.abs(next - k) < 0.04) break;
    k = next;
  }
}

/** Until every icon the drawing names is loaded, or a second has gone. */
async function iconsLoaded(cy) {
  const r = cy.renderer && cy.renderer();
  for (let i = 0; i < 20; i++) {
    const cache = (r && r.imageCache) || {};
    const all = Object.values(cache);
    if (all.length && all.every((c) => c.image && (c.image.complete || c.image.error))) return;
    if (!cy.nodes('[iconUrl]').length) return;
    await sleep(50);
  }
}

/** The cover of `graph` (a schema as the Schema tab draws it, the provider's own types included), as a PNG. */
export async function drawCover(graph) {
  const icons = (graph?.vertex_types || []).map((v) => v.ui && v.ui.icon);
  if (needsCatalog(icons)) await loadCatalog();
  // each type by its title, as the tab names it; no record counts, which change and would date the picture
  const captionOf = (label, d) => (graph.titles && graph.titles[label]) || String((d && d.name) || label).replace(/_/g, ' ');
  const box = document.createElement('div');
  box.setAttribute('aria-hidden', 'true');
  Object.assign(box.style, { position: 'fixed', left: '-10000px', top: '0', width: `${W}px`, height: `${H}px`, pointerEvents: 'none', opacity: '0', zIndex: '-1' });
  document.body.appendChild(box);
  const cy = cytoscape({
    container: box, elements: buildSchemaElements(graph, null, null, captionOf), style: CANVAS_STYLE, layout: { name: 'preset' },
    autoungrabify: true, autounselectify: true, userZoomingEnabled: false, userPanningEnabled: false, boxSelectionEnabled: false,
    textureOnViewport: false, pixelRatio: 1, minZoom: 0.05, maxZoom: 4,
  });
  try {
    frame(cy);
    // the frame takes the graph's own shape: cropped to it, with the margin around
    const bb = cy.elements().renderedBoundingBox();
    const w = Math.max(48, Math.min(W, Math.ceil(bb.w + 2 * PAD))), h = Math.max(48, Math.min(H, Math.ceil(bb.h + 2 * PAD)));
    box.style.width = `${w}px`; box.style.height = `${h}px`;
    cy.resize();
    cy.center();
    // a first drawing asks for the icons; the picture is taken once they have come
    cy.png({ output: 'base64uri', scale: 0.1 });
    await iconsLoaded(cy);
    let pic = await cy.png({ output: 'blob-promise', scale: SCALE });
    if (pic.size > MOST) pic = await cy.png({ output: 'blob-promise', scale: 1 });
    return pic;
  } finally {
    cy.destroy();
    box.remove();
  }
}
