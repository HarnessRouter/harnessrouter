// What a memory's provider lets the console offer, read from the capability document and never from
// the provider's name. Every rule of the Memories pages that depends on a provider is here, so a page
// asks one question and draws the answer. A control a provider would answer `memory_unsupported` to is
// not drawn.
import type { Memory, MemoryRecord, Provider, Privilege } from '@/lib/memories';
import { vendorName } from './vendors';

// ── the schema ──────────────────────────────────────────────────────────────────────────────
/** A schema exists only where something reads it. */
export const hasSchema = (p?: Provider | null) => !!p?.schema?.mode && p.schema.mode !== 'none';
/** Types on a canvas, with properties and relations as the provider declares them. */
export const schemaGuides = (p?: Provider | null) => p?.schema?.mode === 'guides';
/** A flat list of names with descriptions: a vocabulary applied to facts, not a type on entities. */
export const schemaLabels = (p?: Provider | null) => p?.schema?.mode === 'labels';
export const hasProperties = (p?: Provider | null) => schemaGuides(p) && !!p?.schema?.properties;
export const hasRelations = (p?: Provider | null) => schemaGuides(p) && !!p?.schema?.relations;
/** What the schema is called here: its tab, and the word for one of its entries. */
export const schemaTab = (p?: Provider | null) => (schemaLabels(p) ? 'Labels' : 'Schema');
export const schemaWord = (p?: Provider | null) => (schemaLabels(p) ? 'label' : 'type');
/** The line near a schema, saying what reads it. */
export const guideLine = (p: Provider) => (schemaLabels(p)
  ? 'Facts pulled out of each task get the labels that fit them. What you write yourself is kept as you wrote it.'
  : `${vendorName(p.id)} uses these types to decide what to pull out of each task.`);
// What was measured on a provider that reads types and relations, said where someone edits them.
export const TYPES_LINE = 'Types work best for things with a name, like people, companies and products.';
export const RELATIONS_LINE = 'Relations you name replace the words we’d otherwise pick, so name every kind you care about. Anything else stays linked as related, with its sentence kept.';
export const NO_RELATIONS_LINE = 'Relations are optional. Without any, the words found in each task stay as they are.';

// ── how the tree is drawn ───────────────────────────────────────────────────────────────────
/** Real folders where the provider keeps files; everywhere else records are grouped by their type. */
export const hasFolders = (p?: Provider | null) => p?.layout === 'files';

// ── what a record lets a person do ──────────────────────────────────────────────────────────
const can = (m: Pick<Memory, 'privileges'> | null | undefined, x: Privilege) => !!m?.privileges?.includes(x);
export const isDerived = (r: Pick<MemoryRecord, 'written_by'>) => r.written_by?.kind === 'provider';
/** `revise` as a plain word (native, emulated) speaks of what a writer stated. A provider opens what
 *  it found itself only by saying so. */
export const revisesDerived = (p?: Provider | null) => typeof p?.revise === 'object' && !!p?.revise?.derived;
export const servesRevise = (p?: Provider | null) => !!p?.revise;
export const servesForget = (p?: Provider | null) => !!p?.forget;
export const servesErase = (p?: Provider | null) => !!p?.erase;
export const hasHistory = (p?: Provider | null) => !!p?.history?.content && p.history.content !== 'none';

/** May this person change what this record says? */
export function canEdit(r: MemoryRecord, p: Provider | null | undefined, m: Pick<Memory, 'privileges'> | null | undefined): boolean {
  if (!can(m, 'write') || !servesRevise(p) || r.status !== 'active' || r.follows || r.type === 'episode') return false;
  return !isDerived(r) || revisesDerived(p);
}
/** May this person forget it? A record a provider found can be wrong and must be removable, so this
 *  follows `forget`, not `revise`. An episode is what happened (it is erased, never forgotten), and an
 *  entity a provider derives is forgotten by forgetting what it came from. */
export function canForget(r: MemoryRecord, p: Provider | null | undefined, m: Pick<Memory, 'privileges'> | null | undefined): boolean {
  if (!can(m, 'write') || !servesForget(p) || r.status !== 'active' || r.follows || r.type === 'episode') return false;
  return !(isDerived(r) && r.type === 'entity' && p?.graph?.entities === 'derived');
}
export function canErase(r: MemoryRecord, p: Provider | null | undefined, m: Pick<Memory, 'privileges'> | null | undefined): boolean {
  return can(m, 'delete') && servesErase(p) && !r.follows;
}
/** Why a record is not open to change, where its writer's line does not already say it. */
export function readOnlyNote(r: MemoryRecord): string {
  if (r.follows) return `Follows ${r.follows.name || 'its source'}. It changes when that does.`;
  if (r.type === 'episode') return 'Kept from a finished task. Read only.';
  return '';
}

// ── connections ─────────────────────────────────────────────────────────────────────────────
/** Whether the provider keeps links at all. */
export const keepsLinks = (p?: Provider | null) => !!p?.graph && p.graph.entities !== 'none';
/** The connections panel goes where it would be empty and can't be added to. */
export const connectionsHidden = (p: Provider | null | undefined, links: number, canAdd: boolean) => !keepsLinks(p) && links === 0 && !canAdd;

// ── finished tasks ──────────────────────────────────────────────────────────────────────────
export const keepsTasks = (p?: Provider | null) => !!p?.observe;
/** What keeping a finished task does here. */
export const keepLine = (p: Provider | null | undefined, memory: string) => (p?.observe?.keeps_episodes === false
  ? `${vendorName(p.id)} pulls what matters out of each task and keeps it in ${memory}, so later tasks can recall it.`
  : `Each task is kept in ${memory} as an episode, so later tasks can recall it.`);

// ── a record's kind ─────────────────────────────────────────────────────────────────────────
/** The kind a record is drawn as: its schema type where it names one, else its record type. */
export const kindOf = (r: Pick<MemoryRecord, 'type' | 'attributes'>) => String(r.attributes?.entity_type || '') || r.type;
export const CORE: Record<string, { one: string; many: string; color: string; icon: string }> = {
  note: { one: 'Note', many: 'Notes', color: '#64748b', icon: 'note' },
  fact: { one: 'Fact', many: 'Facts', color: '#0ea5e9', icon: 'tag' },
  procedure: { one: 'Procedure', many: 'Procedures', color: '#8b5cf6', icon: 'rule' },
  entity: { one: 'Entity', many: 'Entities', color: '#3b82f6', icon: 'person' },
  episode: { one: 'Episode', many: 'Episodes', color: '#1f2937', icon: 'episode' },
  link: { one: 'Link', many: 'Links', color: '#14b8a6', icon: 'message' },
};
/** What a person can write here beside the schema's types: where types are drawn, a note for what
 *  fits none of them; elsewhere the kinds every memory has, and an entity where a writer states them. */
export function coreKindsToWrite(p?: Provider | null): string[] {
  if (schemaGuides(p)) return ['note'];
  return ['note', 'fact', 'procedure', ...(p?.graph?.entities === 'stated' ? ['entity'] : [])];
}
export const recordTypeOfSchemaKind = (p?: Provider | null) => (p?.graph?.entities === 'none' ? 'note' : 'entity');
/** A fact's labels, where the provider tags facts with them. */
export const labelsOf = (r: Pick<MemoryRecord, 'attributes'>): string[] => {
  const l = r.attributes?.labels;
  return Array.isArray(l) ? l.map(String) : [];
};
/** A fact whose sentence is the whole of it leads with that sentence. */
export const sentenceFirst = (r: Pick<MemoryRecord, 'type' | 'title'>) => r.type === 'fact' && !r.title;
const REL_WORDS: Record<string, string> = { relates_to: 'related to', related: 'related to', derived_from: 'came from', part_of: 'part of' };
/** A link's word as a person reads it; a link with no real name of its own is plainly "related to". */
export const relText = (rel?: string | null) => { const r = String(rel || ''); return r ? REL_WORDS[r.toLowerCase()] || r : 'related to'; };
