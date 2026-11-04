// Lucide icon catalog — 1700+ icons.
//
// Public surface:
//   ICON_KEYS       — sorted PascalCase keys (e.g. "Workflow", "Bell")
//   IconByName      — React component that renders a Lucide icon by name
//   getIconUrl      — returns a data:image/svg+xml URI for the named icon
//                     with the stroke color INLINED (so Cytoscape can use
//                     it as a background-image; currentColor wouldn't
//                     resolve once the SVG is detached from the DOM)
//   searchIcons     — case-insensitive token-prefix search over a
//                     human-readable form of each key

import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { icons as LucideIcons } from 'lucide-react';

export const ICON_KEYS = Object.keys(LucideIcons).sort();

// PascalCase -> "pascal case" so search can match on whole words.
function humanize(key) {
  return key
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .toLowerCase();
}

// Pre-compute the searchable form for every key.
const SEARCH_INDEX = ICON_KEYS.map((k) => [k, humanize(k)]);

export function searchIcons(query, limit = 80) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return ICON_KEYS.slice(0, limit);
  const tokens = q.split(/\s+/).filter(Boolean);
  const out = [];
  for (const [key, human] of SEARCH_INDEX) {
    if (tokens.every((t) => human.includes(t) || key.toLowerCase().includes(t))) {
      out.push(key);
      if (out.length >= limit) break;
    }
  }
  return out;
}

// Accept both PascalCase ("FileText") and lucide kebab/lowercase ("file-text")
// names: a schema written elsewhere may use lucide's kebab ids, and resolves to the same glyph.
function resolveIconKey(name) {
  if (!name || LucideIcons[name]) return name;
  const pascal = String(name).split(/[-_\s]+/)
    .map((p) => (p ? p[0].toUpperCase() + p.slice(1) : ''))
    .join('');
  return LucideIcons[pascal] ? pascal : name;
}

export function IconByName({ name, size = 16, color, strokeWidth = 2, ...rest }) {
  const Comp = LucideIcons[resolveIconKey(name)];
  if (!Comp) return null;
  return <Comp size={size} color={color} strokeWidth={strokeWidth} {...rest}/>;
}

// Cache of fully-rendered SVG data URIs per (name|color).
const URL_CACHE = new Map();

export function getIconUrl(rawName, color = '#FFFFFF') {
  if (!rawName) return null;
  const name = resolveIconKey(rawName);
  const cacheKey = `${name}|${color}`;
  const hit = URL_CACHE.get(cacheKey);
  if (hit) return hit;
  const Comp = LucideIcons[name];
  if (!Comp) return null;
  // Render to SVG markup. Lucide accepts `color` and emits the stroke
  // attribute inline -- but the React server renderer doesn't run CSS
  // inheritance, so we still belt-and-suspenders any `currentColor` that
  // survives by substituting the literal color.
  // Render at 24px (Lucide's native viewBox) with a slightly thinner
  // stroke so the glyph reads cleanly when scaled down inside small
  // canvas nodes. Stroke-width 1.75 keeps it crisp without looking heavy.
  const markup = renderToStaticMarkup(
    <Comp size={24} color={color} strokeWidth={1.75}/>
  );
  const inlined = markup.replace(/currentColor/g, color);
  const url = `data:image/svg+xml;utf8,${encodeURIComponent(inlined)}`;
  URL_CACHE.set(cacheKey, url);
  return url;
}
