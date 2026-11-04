// The four memory services by name, for what only a name can give: how the service is called, one
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
