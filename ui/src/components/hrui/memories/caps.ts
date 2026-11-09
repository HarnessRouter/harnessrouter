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
/** What a provider makes itself, if it says. */
export const builtinOf = (p?: Provider | null) => p?.schema?.builtin || null;
export const schemaWord = (p?: Provider | null) => (schemaLabels(p) ? 'label' : 'type');
// Measured on Graphiti: a type renamed leaves the records already kept under the old name, and no vendor here rewrites what
// it kept. So a schema steers what comes next, and the page says so rather than implying more than a vendor does.
const FROM_NOW_ON = 'A change applies from here on: what’s already kept stays as it is.';
/** The line near a schema, saying what reads it. */
export const guideLine = (p: Provider) => (schemaLabels(p)
  ? `Facts pulled out of each task get the labels that fit them. What you write yourself is kept as you wrote it. ${FROM_NOW_ON}`
  : `${vendorName(p.id)} uses these types to decide what to pull out of each task. ${FROM_NOW_ON}`);
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

// ── standing instructions ───────────────────────────────────────────────────────────────────
// A standing instruction (`attributes.standing` true) is given to every agent that uses the memory at the start of each
// task. Since 0.40.4 it is a person's to set: an agent's tools never set one, and one an agent set before is given to
// agents as a note, not as an instruction. These read the service's own rules (its drawn_by_the_engine
// and set_by_a_person); the service enforces them where the write lands.
type Stands = Pick<MemoryRecord, 'type' | 'attributes' | 'references' | 'written_by' | 'follows'>;
/** Set to stand. */
export const isStanding = (r: Pick<MemoryRecord, 'attributes'>) => r.attributes?.standing === true;
/** Whether a record can stand at all: a conversation kept as it happened can't here, nor anything an engine drew from
 *  another record or kept itself, nor a record that follows a source it changes with. */
export function canStand(r: Stands): boolean {
  if (r.type === 'episode' || r.follows) return false;
  if ((r.references || []).some((x) => x.rel === 'derived_from')) return false;
  const w = r.written_by;
  return !(w?.kind === 'provider' && !w.on_behalf_of);
}
/** An API key with no person behind it: what the service stamps on a write made with one. */
export const isKeyWriter = (w: Pick<MemoryRecord, 'written_by'>['written_by'] | undefined) => w?.kind === 'x.service' || w?.kind === 'service';
/** How a record stands: `person`, set by a person and given to agents as an instruction; `agent`, set by an agent (or a
 *  key an agent holds for someone), `service`, set with an API key no person holds, and `other`, last changed by the
 *  service itself, each given to agents only as a note until a person sets it again; '' for a record that doesn't
 *  stand, or can't. */
export function standingOf(r: Stands): '' | 'person' | 'agent' | 'service' | 'other' {
  if (!isStanding(r) || !canStand(r)) return '';
  const w = r.written_by;
  if (isKeyWriter(w)) return 'service';
  if (w?.kind === 'member' && w.type !== 'agent' && !w.delegated) return 'person';
  return w?.kind === 'member' ? 'agent' : 'other';
}
/** What a standing record no person set says, as its tag and in a line. */
export const NOTED: Record<'agent' | 'service' | 'other', { tag: string; line: string }> = {
  agent: { tag: 'Noted by an agent as standing', line: 'An agent set this, so agents get it as a note, not as an instruction.' },
  service: { tag: 'Noted by an API key as standing', line: 'An API key set this, so agents get it as a note, not as an instruction.' },
  other: { tag: 'Noted as standing', line: 'It was last changed automatically, so agents get it as a note, not as an instruction.' },
};
/** Whether this person may make a record stand, or stop it: someone signed in to the console (a person, never an
 *  agent's key), who may write the memory, on a record that can stand and that the engine lets be changed. */
export function mayStand(r: Stands & Pick<MemoryRecord, 'id' | 'status'>, p: Provider | null | undefined, m: Pick<Memory, 'privileges'> | null | undefined, person: boolean): boolean {
  if (!person || !can(m, 'write') || !canStand(r)) return false;
  return !r.id || (r.status === 'active' && servesRevise(p));
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

// ── choosing a service ──────────────────────────────────────────────────────────────────────
/** What sets one service apart when a memory is created, read from its capability document: the
 *  rows a person compares before a choice that is fixed once made. */
export function serviceFacts(p: Provider): { label: string; value: string }[] {
  const schema = schemaGuides(p) ? (hasRelations(p) ? 'Types and relations' : 'Types')
    : schemaLabels(p) ? 'Labels' : hasFolders(p) ? 'Folders' : 'None';
  const entities = p.graph?.entities === 'derived' ? 'Found for you' : p.graph?.entities === 'stated' ? 'Only what you write' : 'None';
  const finds = ({ write_time: 'As it writes', background: 'In the background', agent: 'Its own agent' } as Record<string, string>)[String(p.derivation)] || 'Keeps what you write';
  return [{ label: 'Schema', value: schema }, { label: 'Entities', value: entities }, { label: 'Pulls out facts', value: finds }];
}

/** The shape a memory takes with this service, for the pictures drawn before it holds anything. */
export const shapeOf = (p?: Provider | null): 'schema' | 'labels' | 'files' | 'records' | null =>
  (!p ? null : hasFolders(p) ? 'files' : schemaLabels(p) ? 'labels' : hasSchema(p) ? 'schema' : 'records');
