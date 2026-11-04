// This browser's side of a record open for editing together: a Y.Doc, who else is here, and two simple pipes. Updates
// arrive on an event stream and leave by POST. Sending one twice or late does no harm, which is what lets a dropped
// connection be nothing more than: reconnect, and exchange what's missing.
import { useEffect, useState, useSyncExternalStore } from 'react';
import * as Y from 'yjs';
import { applyAwarenessUpdate, Awareness, encodeAwarenessUpdate } from 'y-protocols/awareness';
import { keepPresenceAlive } from './presence';

const REMOTE = 'remote';
const FLUSH_MS = 40;
const enc = encodeURIComponent;
const toB64 = (u: Uint8Array) => { let s = ''; u.forEach((b) => { s += String.fromCharCode(b); }); return btoa(s); };
const fromB64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

// not randomUUID: a browser offers that only over https, and a self-hosted console is often on plain http
const connectionId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('');

export type Link = 'opening' | 'live' | 'lost';
export type Saving = 'saved' | 'saving' | 'unsaved' | 'refused';
export interface LiveState {
  link: Link; synced: boolean; canWrite: boolean; gone: boolean; denied: string;
  version: number | null; saving: Saving; refused: string; by: { kind?: string; id?: string; type?: string } | null;
  people: { id: number; name: string; color?: string; agent?: boolean }[];
}

export class LiveRecord {
  readonly doc = new Y.Doc();
  readonly awareness = new Awareness(this.doc);
  state: LiveState = { link: 'opening', synced: false, canWrite: false, gone: false, denied: '', version: null, saving: 'saved', refused: '', by: null, people: [] };
  private c = connectionId();
  private es: EventSource | null = null;
  private epoch = '';
  private pending: Uint8Array[] = [];
  private awarenessDue = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private sending = false;
  private stopAlive: () => void;
  private fns = new Set<() => void>();
  private dead = false;
  private url: string;

  constructor(mid: string, rid: string, private onRestart: () => void, private colorOf: (key: string) => string) {
    this.url = `/api/memlive/${enc(mid)}/${enc(rid)}`;
    this.doc.on('update', (u: Uint8Array, origin: unknown) => {
      if (origin === REMOTE) return;
      this.pending.push(u);
      this.flushSoon();
    });
    this.awareness.on('update', (_c: unknown, origin: unknown) => {
      if (origin === REMOTE) return;
      this.awarenessDue = true;
      this.flushSoon();
    });
    this.awareness.on('change', () => this.readPeople());
    this.stopAlive = keepPresenceAlive(this.awareness as never);
    this.connect();
  }

  subscribe = (fn: () => void) => { this.fns.add(fn); return () => { this.fns.delete(fn); }; };
  snapshot = () => this.state;
  private set(next: Partial<LiveState>) {
    this.state = { ...this.state, ...next };
    this.fns.forEach((f) => f());
  }

  private readPeople() {
    const me = this.doc.clientID;
    const people: LiveState['people'] = [];
    this.awareness.getStates().forEach((s, id) => {
      const u = (s as { user?: { id?: string; name?: string; agent?: boolean } }).user;
      if (id !== me && u?.name) people.push({ id, name: u.name, agent: u.agent, color: this.colorOf(u.id || u.name) });
    });
    this.set({ people });
  }

  private connect() {
    if (this.dead) return;
    const es = new EventSource(`${this.url}?c=${enc(this.c)}`);
    this.es = es;
    const on = <T,>(name: string, fn: (d: T) => void) => es.addEventListener(name, (e) => fn(JSON.parse((e as MessageEvent).data) as T));
    on<{ epoch: string; state: string; sv: string; awareness: string; version: number | null; canWrite: boolean; gone: boolean }>('hello', (d) => {
      if (this.epoch && this.epoch !== d.epoch) {
        // the server restarted, so this is a new document with the same words: merging would double them
        this.epoch = d.epoch;
        this.onRestart();
        return;
      }
      this.epoch = d.epoch;
      Y.applyUpdate(this.doc, fromB64(d.state), REMOTE);
      applyAwarenessUpdate(this.awareness, fromB64(d.awareness), REMOTE);
      this.set({ link: 'live', synced: true, version: d.version, canWrite: d.canWrite, gone: d.gone });
      // what this browser has and the server doesn't (typed while the connection was down)
      const missing = Y.encodeStateAsUpdate(this.doc, fromB64(d.sv));
      if (missing.length > 2) this.pending.push(missing);
      this.awarenessDue = true;
      this.flushSoon();
    });
    on<{ u: string }>('u', (d) => Y.applyUpdate(this.doc, fromB64(d.u), REMOTE));
    on<{ a: string }>('a', (d) => applyAwarenessUpdate(this.awareness, fromB64(d.a), REMOTE));
    on<object>('saving', () => this.set({ saving: 'saving' }));
    on<object>('unsaved', () => this.set({ saving: 'unsaved' }));
    on<{ version: number | null; by?: LiveState['by'] }>('saved', (d) => this.set({ saving: 'saved', refused: '', version: d.version ?? this.state.version, by: d.by ?? this.state.by }));
    on<{ message: string }>('refused', (d) => this.set({ saving: 'refused', refused: d.message }));
    on<{ canWrite: boolean }>('access', (d) => this.set({ canWrite: d.canWrite }));
    on<object>('gone', () => this.set({ gone: true }));
    es.onerror = () => {
      if (this.dead) return;
      if (es.readyState === EventSource.CLOSED) {
        // refused rather than dropped, or this browser gave up: ask again, and read why
        void fetch(`${this.url}?c=${enc(this.c)}`, { signal: AbortSignal.timeout(8000) }).then(async (r) => {
          if (r.ok) { await r.body?.cancel(); return; }
          if (r.status === 404 || r.status === 403) this.set({ denied: 'This record can’t be opened.', link: 'lost' });
        }).catch(() => undefined).finally(() => { if (!this.dead && !this.state.denied) setTimeout(() => this.connect(), 3000); });
      }
      this.set({ link: 'lost' });
    };
    es.onopen = () => { if (this.state.synced) this.set({ link: 'live' }); };
  }

  private flushSoon() {
    if (this.timer || this.sending) return;
    this.timer = setTimeout(() => { this.timer = null; void this.flush(); }, FLUSH_MS);
  }

  private async flush() {
    if (this.dead || this.sending || !this.state.synced) return;
    if (this.state.gone) { this.pending = []; this.awarenessDue = false; return; }   // nowhere left for it to go
    const ups = this.pending;
    const aw = this.awarenessDue;
    if (!ups.length && !aw) return;
    this.pending = [];
    this.awarenessDue = false;
    this.sending = true;
    const body: { c: string; u?: string; a?: string } = { c: this.c };
    if (ups.length) body.u = toB64(ups.length === 1 ? ups[0] : Y.mergeUpdates(ups));
    if (aw && this.awareness.getLocalState()) body.a = toB64(encodeAwarenessUpdate(this.awareness, [this.doc.clientID]));
    let failed = false;
    try {
      const r = await fetch(this.url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), keepalive: JSON.stringify(body).length < 60_000 });
      if (r.status === 403) this.set({ canWrite: false });
      // 409: the server has lost this connection for a moment; the stream's hello sends what it's missing
      failed = !r.ok && r.status !== 403 && r.status !== 409;
    } catch { failed = true; }
    this.sending = false;
    if (failed) {
      this.pending = [...ups, ...this.pending];
      this.awarenessDue = this.awarenessDue || aw;
      this.set({ saving: 'unsaved' });
      this.timer = setTimeout(() => { this.timer = null; void this.flush(); }, 2000);
    } else if (this.pending.length || this.awarenessDue) {
      this.flushSoon();
    }
  }

  destroy() {
    this.dead = true;
    if (this.timer) clearTimeout(this.timer);
    this.stopAlive();
    this.es?.close();
    void this.flush();
    this.awareness.destroy();
    this.doc.destroy();
  }
}

/** A record's live document for as long as the page shows it. `null` until it exists. */
export function useLiveRecord(mid: string, rid: string, colorOf: (key: string) => string): { live: LiveRecord | null; state: LiveState | null } {
  const [live, setLive] = useState<LiveRecord | null>(null);
  const [turn, setTurn] = useState(0);
  useEffect(() => {
    if (!rid) { setLive(null); return undefined; }
    const l = new LiveRecord(mid, rid, () => setTurn((n) => n + 1), colorOf);
    setLive(l);
    return () => { l.destroy(); setLive(null); };
  }, [mid, rid, turn, colorOf]);
  const state = useSyncExternalStore(live ? live.subscribe : noop, live ? live.snapshot : none, none);
  return { live, state };
}
const noop = () => () => {};
const none = () => null;

/** How much the open document says, as it changes. */
export function useLiveText(live: LiveRecord | null): string {
  const [text, setText] = useState('');
  useEffect(() => {
    if (!live) { setText(''); return undefined; }
    const frag = live.doc.getXmlFragment('default');
    const read = () => setText(frag.toString().replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim());
    read();
    live.doc.on('update', read);
    return () => live.doc.off('update', read);
  }, [live]);
  return text;
}
