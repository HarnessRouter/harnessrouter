// A schema as the Schema tab edits it: each type and relation with an id that outlives a rename (on
// the wire a relation names its types by name), and every type with a place on the canvas. Reading
// fills what a stored schema leaves out (a place, a colour, an icon), so a schema written through the
// API draws as well as one drawn here. Writing leaves out what the provider does not read.
import type { MemorySchema, PropType, Provider, SchemaProperty } from '@/lib/memories';
import { hasProperties, hasRelations, schemaLabels } from './caps';

export const MM_COLORS = ['#4f46e5', '#8b5cf6', '#a78bfa', '#3b82f6', '#0ea5e9', '#14b8a6', '#22a35a', '#f59e0b', '#ef4444', '#ec4899', '#64748b', '#1f2937'];
export const MM_ICONS: Record<string, string> = {
  building: 'M4 20.5V4.5h9v16M13 9h6.5v11.5M7 8h3M7 11.5h3M7 15h3M16 13h1M16 16.5h1M2.5 20.5h19',
  box: 'M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5zM3.5 7.5 12 12l8.5-4.5M12 12v9',
  rule: 'M4 6h16M4 12h10M4 18h13M18 15l3 3-3 3',
  image: 'M3.5 5h17v14h-17zM3.5 15.5l5-5 4 4 2.5-2.5 5.5 5.5M15.5 9.2a1.2 1.2 0 1 0 0-.01',
  person: 'M12 11.5a3.8 3.8 0 1 0 0-7.6 3.8 3.8 0 0 0 0 7.6M4.5 20.5c.8-4 3.8-6.2 7.5-6.2s6.7 2.2 7.5 6.2',
  message: 'M4 5h16v11H9.5L5 19.5V16H4z',
  note: 'M6 3.5h9l3.5 3.5v13.5H6zM9 10h6.5M9 13.5h6.5M9 17h4',
  episode: 'M3.5 5.5h17v10h-9l-5 4v-4h-3zM8 10.5h.01M12 10.5h.01M16 10.5h.01',
  tag: 'M3.5 12.5V4h8.5l8.5 8.5-8.5 8.5zM8 8.2h.01',
  star: 'M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.3-4.1 5.9-.8z',
  bolt: 'M13 2.5 5 13.5h6l-1 8 8-11h-6z',
  flag: 'M5 21V4M5 4h11l-2 4 2 4H5',
};
export const MM_PTYPES: [PropType, string][] = [['text', 'Text'], ['number', 'Number'], ['date', 'Date'], ['yesno', 'Yes / no'], ['choice', 'Choice']];
export const VB: [number, number] = [940, 640];

export interface LProp { id: string; name: string; type: PropType; description: string; options: string }
export interface LType { id: string; name: string; description: string; properties: LProp[]; color: string; icon: string; x: number; y: number; caption: string }
export interface LRel { id: string; name: string; description: string; from: string; to: string }
export interface LSchema { types: LType[]; relations: LRel[] }

let seq = 0;
export const uid = (p: string) => `${p}${++seq}`;

/** A type's name as a person reads it, and as the service keeps it (one word). */
export const typeLabel = (name: string) => name.replace(/_/g, ' ');
export const typeNameOf = (v: string) => v.replace(/\s/g, '_').replace(/[^\p{L}\p{N}_]/gu, '');
export const propNameOf = (v: string) => v.replace(/\s+/g, '_').replace(/[^\p{L}\p{N}_]/gu, '').toLowerCase();
export const relNameOf = (v: string) => v.toUpperCase().replace(/[^\p{L}\p{N}_]+/gu, '_');

/** Places around a circle, for types that have none. */
export function circle(n: number): [number, number][] {
  return Array.from({ length: n }, (_, k) => {
    const a = -Math.PI / 2 + (k * 2 * Math.PI) / Math.max(1, n);
    return [Math.round(470 + 250 * Math.cos(a)), Math.round(320 + 225 * Math.sin(a))];
  });
}
/** The first free place, for a new type. */
export function freeSpot(s: LSchema): [number, number] {
  const spots: [number, number][] = [[470, 330], [300, 330], [640, 330], [470, 150], [470, 500], [180, 180], [760, 180], [180, 480], [760, 480]];
  const free = spots.find(([x, y]) => s.types.every((t) => Math.hypot(t.x - x, t.y - y) > 90));
  if (free) return free;
  const k = s.types.length;
  return [470 + ((k * 37) % 120) - 60, 330 + ((k * 53) % 120) - 60];
}

const num = (v: unknown, or: number) => (typeof v === 'number' && Number.isFinite(v) ? v : or);
const propIn = (p: SchemaProperty): LProp => ({ id: uid('p'), name: p.name, type: p.type, description: p.description || '', options: (p.options || []).join(', ') });

export function schemaIn(doc: Partial<MemorySchema> | null | undefined): LSchema {
  const raw = doc?.types || [];
  const spots = circle(raw.length);
  const types: LType[] = raw.map((t, i) => ({
    id: uid('t'), name: t.name, description: t.description || '', properties: (t.properties || []).map(propIn),
    color: t.color || MM_COLORS[i % MM_COLORS.length], icon: t.icon && MM_ICONS[t.icon] ? t.icon : 'tag',
    x: num(t.x, spots[i][0]), y: num(t.y, spots[i][1]), caption: t.caption || 'title',
  }));
  const idOf = (name: string) => types.find((t) => t.name === name)?.id;
  const relations: LRel[] = (doc?.relations || []).flatMap((r) => {
    const from = idOf(r.from), to = idOf(r.to);
    return from && to ? [{ id: uid('r'), name: r.name, description: r.description || '', from, to }] : [];
  });
  return { types, relations };
}

/** The schema as the service takes it, holding only what this provider reads. */
export function schemaOut(s: LSchema, p: Provider | null | undefined): MemorySchema {
  if (schemaLabels(p)) return { types: s.types.map((t) => ({ name: t.name, description: t.description })) };
  const props = hasProperties(p), rels = hasRelations(p);
  const nameOf = (id: string) => s.types.find((t) => t.id === id)?.name || '';
  return {
    types: s.types.map((t) => ({
      name: t.name, description: t.description, color: t.color, icon: t.icon, x: t.x, y: t.y, caption: t.caption,
      properties: props ? t.properties.map((x) => ({
        name: x.name, type: x.type, description: x.description,
        ...(x.type === 'choice' ? { options: choicesOf(x.options) } : {}),
      })) : [],
    })),
    relations: rels ? s.relations.map((r) => ({ name: r.name, description: r.description, from: nameOf(r.from), to: nameOf(r.to) })) : [],
  };
}
export const choicesOf = (o: string) => o.split(',').map((x) => x.trim()).filter(Boolean);

const ONE_WORD = /^[\p{L}_][\p{L}\p{N}_]*$/u;
/** What is wrong with a draft, in a sentence, or ''. A draft in this state waits here: the service
 *  would refuse the whole of it. */
export function schemaProblem(s: LSchema, word = 'type'): string {
  const seen = new Set<string>();
  for (const t of s.types) {
    if (!ONE_WORD.test(t.name)) return t.name ? `${typeLabel(t.name)} can’t be a name for a ${word}: start it with a letter.` : `Give every ${word} a name.`;
    if (seen.has(t.name)) return `Two ${word}s are called ${typeLabel(t.name)}.`;
    seen.add(t.name);
    for (const x of t.properties) {
      if (!ONE_WORD.test(x.name)) return `${typeLabel(t.name)}: give every property a name that starts with a letter.`;
    }
  }
  for (const r of s.relations) {
    if (!r.name.replace(/_/g, '')) return 'Give every relation a name.';
  }
  return '';
}

// ── starting points ─────────────────────────────────────────────────────────────────────────
// Things with a name, because those are what extraction was measured to pick up (an issue or a fix
// was not), and no relations: a relation named replaces the word extraction would have chosen, so
// naming them is a person's choice, never a template's.
export const MM_STARTS: [string, string][] = [['Customers', 'Company, person, product'], ['Team', 'Person, team, project'], ['Research', 'Company, person, paper']];
const STARTS: MemorySchema[] = [
  { types: [
    { name: 'Company', color: '#ec4899', icon: 'building', x: 470, y: 150, properties: [{ name: 'website', type: 'text' }] },
    { name: 'Person', color: '#3b82f6', icon: 'person', x: 260, y: 430, properties: [{ name: 'role', type: 'text' }, { name: 'email', type: 'text' }] },
    { name: 'Product', color: '#f59e0b', icon: 'box', x: 680, y: 430, properties: [{ name: 'sku', type: 'text' }] },
  ] },
  { types: [
    { name: 'Person', color: '#3b82f6', icon: 'person', x: 470, y: 150, properties: [{ name: 'role', type: 'text' }] },
    { name: 'Team', color: '#8b5cf6', icon: 'flag', x: 260, y: 430, properties: [] },
    { name: 'Project', color: '#14b8a6', icon: 'star', x: 680, y: 430, properties: [{ name: 'status', type: 'text' }] },
  ] },
  { types: [
    { name: 'Company', color: '#4f46e5', icon: 'building', x: 470, y: 150, properties: [{ name: 'website', type: 'text' }] },
    { name: 'Person', color: '#3b82f6', icon: 'person', x: 260, y: 430, properties: [{ name: 'role', type: 'text' }] },
    { name: 'Paper', color: '#64748b', icon: 'note', x: 680, y: 430, properties: [{ name: 'url', type: 'text' }] },
  ] },
];
/** A starting point, as much of it as this provider reads. */
export function startSchema(i: number, p: Provider | null | undefined): LSchema {
  const s = schemaIn(STARTS[i]);
  if (!hasProperties(p)) s.types.forEach((t) => { t.properties = []; });
  return s;
}
