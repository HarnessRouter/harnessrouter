// Minimal shared store for the Traces app (mirrors tasks/store.js shape): the selected
// session id drives the right pane; the sidebar owns the paginated list + search.
import { useSyncExternalStore } from 'react';

let state = { selected: null };
const subs = new Set();
const emit = () => subs.forEach((f) => f());

export const traceStore = {
  select(sid) { state = { ...state, selected: sid }; emit(); },
  get() { return state; },
};

export function useTraces() {
  return useSyncExternalStore(
    (f) => { subs.add(f); return () => subs.delete(f); },
    () => state,
    () => state,
  );
}
