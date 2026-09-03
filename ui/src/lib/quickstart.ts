// Quickstart progress: four steps, kept per browser so the page and the sidebar badge agree and a
// reload does not start the person over. Nothing secret lives here: the API key's last four
// characters only, never the key.
import { useCallback, useEffect, useState } from 'react';

export interface QuickstartState {
  copied: boolean;      // AGENTS.md went to the clipboard
  pasted: boolean;      // step 1: they confirmed the paste
  asked: boolean;       // step 2: they sent a build request to their agent
  keyCreated: boolean;  // step 3: a workspace key was created here
  keyHint: string;      // the created key's head and tail (sk-hr-••••1a2b), for the "Key created" label
  agent: string;        // which coding agent they chose (codex | claude-code | cursor)
}
export const QUICKSTART_EMPTY: QuickstartState = { copied: false, pasted: false, asked: false, keyCreated: false, keyHint: '', agent: 'codex' };
const KEY = 'hr:quickstart:v1';
const EVT = 'hr:quickstart';

export function readQuickstart(): QuickstartState {
  let s = QUICKSTART_EMPTY;
  try { const raw = localStorage.getItem(KEY); s = raw ? { ...QUICKSTART_EMPTY, ...JSON.parse(raw) } : QUICKSTART_EMPTY; }
  catch { return QUICKSTART_EMPTY; }
  // A key is only created once the agent asked for it, which only happens after the guide was
  // pasted and a build was requested. The two confirmations are easy to skip; the key is proof.
  return s.keyCreated ? { ...s, copied: true, pasted: true, asked: true } : s;
}
function writeQuickstart(next: QuickstartState): void {
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage blocked: the page still works for this visit */ }
  window.dispatchEvent(new Event(EVT));
}
/** Steps done out of four. The fourth (manage your harnesses) is the destination: it lights once the three setup steps are done. */
export function quickstartDone(s: QuickstartState): number {
  const three = [s.pasted, s.asked, s.keyCreated].filter(Boolean).length;
  return three + (three === 3 ? 1 : 0);
}
export function useQuickstart(): [QuickstartState, (patch: Partial<QuickstartState>) => void] {
  const [s, setS] = useState<QuickstartState>(QUICKSTART_EMPTY);
  useEffect(() => {
    const sync = () => setS(readQuickstart());
    sync();
    window.addEventListener(EVT, sync); window.addEventListener('storage', sync);
    return () => { window.removeEventListener(EVT, sync); window.removeEventListener('storage', sync); };
  }, []);
  const update = useCallback((patch: Partial<QuickstartState>) => { const next = { ...readQuickstart(), ...patch }; writeQuickstart(next); setS(next); }, []);
  return [s, update];
}
