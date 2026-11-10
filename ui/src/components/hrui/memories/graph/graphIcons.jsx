'use client';
// Icons on the graph. The glyphs the panels themselves use are imported one by one. A type's own icon is either one
// of the console's few, drawn at once, or any name in the full catalogue, which is its own chunk: it holds every
// icon there is, and nothing on the page pays for it until a schema names one or someone opens the picker.
import { useEffect, useState } from 'react';
import { ArrowRight, Check, Trash2, Undo2 } from 'lucide-react';
import { MM_ICONS } from '../schemaModel';

const Icon = ({ d, size = 16, stroke = 1.6, style }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={style}>
    {d}
  </svg>
);
export const I = {
  search: <Icon d={<><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4-4" /></>} />,
  close: <Icon d={<><path d="M6 6l12 12M18 6L6 18" /></>} />,
  pencil: <Icon d={<><path d="M16 4l4 4-11 11H5v-4z" /><path d="M13 7l4 4" /></>} />,
  info: <Icon d={<><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5" /><path d="M12 8v.01" /></>} />,
  cornersOut: <Icon d={<><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></>} />,
  cornersIn: <Icon d={<><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" /></>} />,
  // Center (Richard 11-09: "a target icon"): a ring, its centre and four ticks
  target: <Icon d={<><circle cx="12" cy="12" r="6.5" /><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" /><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3" /></>} />,
  chevronRight: <Icon d={<path d="M9 6l6 6-6 6" />} />,
};

const OWN = { ArrowRight, Check, Trash2, Undo2 };
let catalog = null;
let loading = null;
const waiting = new Set();

/** The full catalogue, once. */
export function loadCatalog() {
  if (!loading) {
    loading = import('./iconCatalog.jsx').then((m) => {
      catalog = m;
      waiting.forEach((f) => f(m));
      return m;
    });
  }
  return loading;
}
/** The catalogue when it has come, and a render when it does. Asked for only when `wanted`. */
export function useIconCatalog(wanted = true) {
  const [got, setGot] = useState(catalog);
  useEffect(() => {
    if (got || !wanted) return undefined;
    if (catalog) { setGot(catalog); return undefined; }
    waiting.add(setGot);
    void loadCatalog();
    return () => waiting.delete(setGot);
  }, [got, wanted]);
  return got;
}
const isOwn = (name) => !!OWN[name] || !!MM_ICONS[name];

export function IconByName({ name, size = 16, color, strokeWidth = 2, ...rest }) {
  const cat = useIconCatalog(!!name && !isOwn(name));
  if (OWN[name]) { const C = OWN[name]; return <C size={size} color={color} strokeWidth={strokeWidth} {...rest} />; }
  if (MM_ICONS[name]) {
    return (
      <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke={color || 'currentColor'} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={MM_ICONS[name]} />
      </svg>
    );
  }
  return cat ? <cat.IconByName name={name} size={size} color={color} strokeWidth={strokeWidth} {...rest} /> : null;
}

/** A type's icon for the canvas: the stroke colour written into the SVG, because a data URI is detached from the
 *  page and `currentColor` would resolve to nothing there. Null until the catalogue has come, for a name in it. */
export function iconUrl(key, color = '#FFFFFF') {
  if (!key) return null;
  const d = MM_ICONS[key];
  if (d) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
    return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  }
  return catalog ? catalog.getIconUrl(key, color) : null;
}
/** Whether a set of icon names needs the catalogue to draw. */
export const needsCatalog = (names) => names.some((n) => !!n && !MM_ICONS[n]);
