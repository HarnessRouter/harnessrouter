export interface HistoryNode { id: string; name: string; deps: string[] }
export interface HistoryEvent { nodeId: string; status: string; label: string }
export function replayStates(nodes: HistoryNode[], events: HistoryEvent[], step: number): Record<string, string> {
  const states = Object.fromEntries(nodes.map(node => [node.id, 'pending']));
  const count = Number.isFinite(step) ? Math.max(0, Math.min(events.length, Math.floor(step))) : 0;
  for (const event of events.slice(0, count)) {
    if (event.nodeId in states) states[event.nodeId] = event.status;
  }
  return states;
}
export function layoutRunNodes(nodes: HistoryNode[]): Array<HistoryNode & { x: number; y: number }> {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const getDepth = (id: string): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const node = byId.get(id);
    const parents = node?.deps.filter(dep => byId.has(dep)) || [];
    const value = parents.length ? Math.max(...parents.map(getDepth)) + 1 : 0;
    visiting.delete(id); depth.set(id, value); return value;
  };
  for (const node of nodes) getDepth(node.id);
  const occupied = new Map<number, number>();
  return nodes.map(node => {
    const x = depth.get(node.id) || 0;
    const row = occupied.get(x) || 0;
    occupied.set(x, row + 1);
    return { ...node, x, y: row };
  });
}
