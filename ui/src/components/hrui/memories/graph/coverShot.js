'use client';
// A memory's cover: its schema exactly as the Schema tab's canvas draws it (Richard 11-09, "let the cover exactly follow
// what's on canvas"): the same elements (buildSchemaElements), the same names (schemaCaption), the same stylesheet
// (CANVAS_STYLE) at its own sizes, the same positions and the same straight links. One thing differs on purpose: a
// type's name says "Built in" as the canvas does, but not how many records are of it, which the canvas reads live and
// a stored picture couldn't keep true.
//
// It is drawn offscreen with nothing over it (no toolbar, panel or selection), on a clear background so it sits on the
// card's own in either theme, cropped to the graph and its names, and exported at the scale that makes it fill four
// fifths of a card's picture box (memories.css .mm-art) in the direction that limits it, twice that for sharp screens.
// Nothing is drawn larger or moved to read better: what the card shows is what the canvas shows. Loaded only when a
// cover is to be made.
import cytoscape from 'cytoscape';
import { CANVAS_STYLE } from './CytoscapeCanvas.jsx';
import { buildSchemaElements, schemaCaption } from './schemaElements';
import { loadCatalog, needsCatalog } from './graphIcons.jsx';

/** A card's picture box on a wide screen, and the part of it the graph fills. */
export const CARD = { w: 268, h: 236 };
export const FILL = 0.8;
/** The picture is exported at twice the size it is seen, for sharp screens. */
const SHARP = 2;
/** The most a cover may be (the service refuses more). */
const MOST = 512 * 1024;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** The cover's elements: the canvas's own, each type named as the canvas names it, less the live count. */
export const coverElements = (graph) => buildSchemaElements(graph, null, null, (label, d) => schemaCaption(graph, label, d, ''));
/** The cover's options for the canvas library: its stylesheet is the Schema tab's own. */
export const coverOptions = (container, elements) => ({
  container, elements, style: CANVAS_STYLE, layout: { name: 'preset' },
  autoungrabify: true, autounselectify: true, userZoomingEnabled: false, userPanningEnabled: false, boxSelectionEnabled: false,
  textureOnViewport: false, pixelRatio: 1, minZoom: 0.01, maxZoom: 8,
});
/** The export scale: the graph's own bounds (model units) filling FILL of the card box where it's limited. */
export const coverScale = (bb) => Math.min((CARD.w * FILL) / Math.max(1, bb.w), (CARD.h * FILL) / Math.max(1, bb.h));

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
  const box = document.createElement('div');
  box.setAttribute('aria-hidden', 'true');
  Object.assign(box.style, { position: 'fixed', left: '-10000px', top: '0', width: `${CARD.w}px`, height: `${CARD.h}px`, pointerEvents: 'none', opacity: '0', zIndex: '-1' });
  document.body.appendChild(box);
  const cy = cytoscape(coverOptions(box, coverElements(graph)));
  try {
    cy.fit(undefined, 0);
    // a first drawing asks for the icons; the picture is taken once they have come
    cy.png({ output: 'base64uri', scale: 0.1 });
    await iconsLoaded(cy);
    const bb = cy.elements().boundingBox();
    const seen = coverScale(bb);
    lastFrame = { seen, w: bb.w, h: bb.h, namePx: 10 * seen };
    // the whole graph and its names, nothing around them
    let pic = await cy.png({ output: 'blob-promise', full: true, scale: seen * SHARP });
    if (pic.size > MOST) pic = await cy.png({ output: 'blob-promise', full: true, scale: seen });
    return pic;
  } finally {
    cy.destroy();
    box.remove();
  }
}
