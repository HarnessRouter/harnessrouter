// The four memory engines by name, for what only a name can give: how the engine is called, one
// honest line about what kind of memory it is, and whether its connection form needs an address
// (the service keeps that to itself). Nothing else in this folder may read a provider's id: what a
// memory can do comes from the capability document (caps.ts), and memories.names.test.ts holds that.
export interface Vendor { name: string; line: string; address: 'required' | 'optional' }
export const VENDORS: Record<string, Vendor> = {
  mem0: { name: 'Mem0', line: 'Pulls facts out of what it reads.', address: 'optional' },
  graphiti: { name: 'Graphiti', line: 'A graph of people, things and how they connect, tracked over time.', address: 'required' },
  hindsight: { name: 'Hindsight', line: 'Facts, entities and links, with its own background learning.', address: 'required' },
  reme: { name: 'ReMe', line: 'Plain Markdown files you can read and edit.', address: 'required' },
};
export const vendorName = (id: string) => VENDORS[id]?.name || id;
/** Bringing a service: the self-hosting guide's own section. */
export const GUIDE = 'https://github.com/HarnessRouter/harnessrouter/blob/main/docs/self-hosting-guide.md#memories';
/** Known services in the order they are offered, any other after them as the service lists it. */
export function inVendorOrder<T extends { id: string }>(list: T[]): T[] {
  const order = Object.keys(VENDORS);
  const at = (id: string) => { const i = order.indexOf(id); return i < 0 ? order.length : i; };
  return [...list].sort((a, b) => at(a.id) - at(b.id));
}

// ── choosing the engine for a new memory ────────────────────────────────────────────────────
// The reading the service gives an agent (the memories spec, B; gateway memory_choice.py), applied to what a person
// calls a memory and says it holds: the line whose words it uses most, ties to the earlier line. It needs no answer from
// anywhere, so New memory shows its choice as the name is typed. A memory always gets an engine: "none" is an agent's
// choice, never a memory's.
const NATURE: { id: string; words: RegExp; why: string }[] = [
  { id: 'mem0', words: /\b(assistants?|support|customers?|clients?|tutors?|coach(es|ing)?|concierge|sales|onboarding|companions?|personal|preferences?|users?|people|person)\b/gi,
    why: 'It is about people, so it keeps each person’s facts and preferences.' },
  { id: 'graphiti', words: /\b(research|accounts?|crm|projects?|investigations?|monitoring|competitors?|timelines?|entities|relationships?|companies)\b/gi,
    why: 'It tracks people, things and how they relate over time.' },
  { id: 'hindsight', words: /\b(coding|code|ops|automation|pipelines?|agents?|debugging|deploy(ment)?s?|incidents?|lessons?|experience)\b/gi,
    why: 'It learns from work, consolidating experience into lessons.' },
  { id: 'reme', words: /\b(docs?|documents?|writing|knowledge ?base|notes?|wiki|handbooks?|journal(ing)?|playbooks?)\b/gi,
    why: 'It holds notes people read and edit.' },
];
export interface EngineChoice { id: string; why: string }
/** The engine for a memory with this name and description, among those connected: the best fit, else the next best
 *  that is connected (and the reason says so), else the first connected. Null with nothing connected. */
export function chooseEngine(text: string, connected: string[]): EngineChoice | null {
  const live = inVendorOrder(connected.map((id) => ({ id }))).map((x) => x.id);
  if (!live.length) return null;
  const scored = NATURE.map((n, i) => ({ ...n, i, n: (text.match(n.words) || []).length })).filter((n) => n.n > 0)
    .sort((a, b) => b.n - a.n || a.i - b.i);
  const best = scored[0];
  if (!best) return { id: live[0], why: VENDORS[live[0]]?.line || '' };
  if (live.includes(best.id)) return { id: best.id, why: best.why };
  const next = scored.find((n) => live.includes(n.id))?.id || live[0];
  return { id: next, why: `${vendorName(best.id)} fits best; it isn’t running here, so ${vendorName(next)} keeps it for now.` };
}
/** What a person reads for how an agent's memory is kept apart. */
export const scopeWord = (scope: string | null | undefined) => (scope === 'per_user' ? 'Separately for each person' : 'Shared');
