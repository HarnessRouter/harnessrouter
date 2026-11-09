// What changes in this memory while its page is open. Whoever writes (a person elsewhere, an agent's tool, a turn the
// provider has finished deriving) the service says so on this stream, and the tree and the graph read what changed
// under this person's own privileges. The open record's words arrive through its live document instead.
import { useEffect, useRef } from 'react';

export interface MemoryEvent {
  type: string; record_id?: string; record_ids?: string[]; version?: number;
  written_by?: { kind?: string; id?: string; type?: string };
}

const KINDS = ['record.created', 'record.revised', 'record.forgotten', 'records.erased', 'records.changed', 'schema.changed', 'reset'];

export function useMemoryEvents(memoryId: string, on: (e: MemoryEvent) => void): void {
  const handler = useRef(on);
  handler.current = on;
  useEffect(() => {
    if (!memoryId || typeof EventSource === 'undefined') return undefined;
    const es = new EventSource(`/api/harness/v1/memories/${encodeURIComponent(memoryId)}/events`);
    const seen = (e: Event) => {
      try { handler.current(JSON.parse((e as MessageEvent).data) as MemoryEvent); } catch { /* nothing readable to act on */ }
    };
    KINDS.forEach((k) => es.addEventListener(k, seen));
    return () => es.close();
  }, [memoryId]);
}
