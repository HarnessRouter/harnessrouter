import type { TemplateNode } from './app-types.ts';

export const NODE_WIDTH = 190;
export const NODE_HEIGHT = 92;

export type ConnectionIssue = 'self' | 'duplicate' | 'cycle' | null;

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function graphBounds(nodes: TemplateNode[]) {
  if (!nodes.length) return { left: 0, top: 0, width: 1, height: 1 };
  const left = Math.min(...nodes.map(node => node.x));
  const top = Math.min(...nodes.map(node => node.y));
  const right = Math.max(...nodes.map(node => node.x + NODE_WIDTH));
  const bottom = Math.max(...nodes.map(node => node.y + NODE_HEIGHT));
  return { left, top, width: Math.max(1, right - left), height: Math.max(1, bottom - top) };
}

export function nodeRole(nodes: TemplateNode[], node: TemplateNode) {
  if (!node.deps.length) return '起点';
  return nodes.some(item => item.deps.includes(node.id)) ? 'Agent' : '总结';
}

export function dependsOn(nodes: TemplateNode[], id: string, targetId: string, seen = new Set<string>()): boolean {
  if (seen.has(id)) return false;
  seen.add(id);
  const node = nodes.find(item => item.id === id);
  return Boolean(node?.deps.some(dep => dep === targetId || dependsOn(nodes, dep, targetId, seen)));
}

export function connectionIssue(nodes: TemplateNode[], sourceId: string, targetId: string): ConnectionIssue {
  if (sourceId === targetId) return 'self';
  const target = nodes.find(node => node.id === targetId);
  if (!target) return null;
  if (target.deps.includes(sourceId)) return 'duplicate';
  if (dependsOn(nodes, sourceId, targetId)) return 'cycle';
  return null;
}

export function edgePath(source: TemplateNode, target: TemplateNode) {
  const x1 = source.x + NODE_WIDTH;
  const y1 = source.y + NODE_HEIGHT / 2;
  const x2 = target.x;
  const y2 = target.y + NODE_HEIGHT / 2;
  const curve = Math.max(70, Math.abs(x2 - x1) * 0.45);
  return `M ${x1} ${y1} C ${x1 + curve} ${y1}, ${x2 - curve} ${y2}, ${x2} ${y2}`;
}
