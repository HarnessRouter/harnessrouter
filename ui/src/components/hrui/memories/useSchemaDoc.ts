'use client';
// One memory's schema while its page is open: read once, edited here, and written shortly after each
// change (the design has no Save). A draft the service would refuse waits with the reason, and a write
// it refused keeps the draft and says why.
import { useCallback, useEffect, useRef, useState } from 'react';
import { getSchema, putSchema, type Provider } from '@/lib/memories';
import { plain } from '../setup/settingsModel';
import { hasSchema, schemaWord } from './caps';
import { schemaIn, schemaOut, schemaProblem, type LSchema } from './schemaModel';

export type SaveState = 'idle' | 'saving' | 'saved' | 'error';
const WAIT_MS = 600;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

export interface SchemaDoc {
  schema: LSchema | null; failed: boolean; retry: () => void;
  state: SaveState; error: string;
  /** Change the draft; `save: false` while a type is being dragged, then saveNow when it lands. */
  update: (fn: (d: LSchema) => void, save?: boolean) => void;
  saveNow: () => void;
}

export function useSchemaDoc(mid: string, provider: Provider | null): SchemaDoc {
  const guided = hasSchema(provider);
  const [schema, setSchema] = useState<LSchema | null>(null);
  const [failed, setFailed] = useState(false);
  const [state, setState] = useState<SaveState>('idle');
  const [error, setError] = useState('');
  const cur = useRef<LSchema | null>(null);
  const dirty = useRef(false);
  const writing = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prov = useRef(provider);
  prov.current = provider;

  const read = useCallback(() => {
    setFailed(false);
    getSchema(mid).then((d) => { const s = schemaIn(d); cur.current = s; setSchema(s); }).catch(() => setFailed(true));
  }, [mid]);
  useEffect(() => { if (guided) read(); }, [guided, read]);

  const flush = useCallback(async () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    const s = cur.current;
    if (!s || !dirty.current || writing.current) return;
    const problem = schemaProblem(s, schemaWord(prov.current));
    if (problem) { setError(problem); setState('error'); return; }
    dirty.current = false;
    writing.current = true;
    setState('saving');
    try {
      await putSchema(mid, schemaOut(s, prov.current));
      writing.current = false;
      setError('');
      setState('saved');
      if (dirty.current) void flush();
    } catch (e) {
      writing.current = false;
      dirty.current = true;
      setError(plain(e, 'That was not saved. Try again.'));
      setState('error');
    }
  }, [mid]);

  const update = useCallback((fn: (d: LSchema) => void, save = true) => {
    if (!cur.current) return;
    const d = clone(cur.current);
    fn(d);
    cur.current = d;
    dirty.current = true;
    setSchema(d);
    if (!save) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { void flush(); }, WAIT_MS);
  }, [flush]);

  const saveNow = useCallback(() => { void flush(); }, [flush]);
  // leaving the page writes what was still waiting
  useEffect(() => () => { void flush(); }, [flush]);

  return { schema, failed, retry: read, state, error, update, saveNow };
}
