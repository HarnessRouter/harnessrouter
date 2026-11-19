import type { AppPagination } from './app-api';

export function mergePage<T extends { id: number }>(current: T[], incoming: T[]): T[] {
  const rows = new Map(current.map(row => [row.id, row]));
  incoming.forEach(row => rows.set(row.id, row));
  return [...rows.values()];
}

export function nextOffset(page?: AppPagination): number | null {
  return page?.has_more ? page.offset + page.limit : null;
}
