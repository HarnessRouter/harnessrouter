// The open records. Server only, one per console process.
//
// The memory is the truth; this is where people edit it together. A record someone has open is a Y.Doc here,
// seeded from the record. Each browser reads updates over one event stream and sends its own with a POST, and
// because the document is a CRDT the transport has nothing to get right: an update may arrive twice or late, and
// a reconnect just exchanges what's missing. What people write is written back to the memory after a pause, as a
// new version, under whoever last typed. And what an agent or anyone else writes through the API comes in the other
// way: the gateway tells us, we read the record, and write the difference into the document, so everyone who has
// it open sees it arrive like a colleague's edit.
//
// Nothing here is kept: a document that nobody has open is dropped, and a record is its own save file. A browser
// that reconnects to a new process is told so by the epoch and starts again from the record.
import * as Y from 'yjs';
import { applyAwarenessUpdate, Awareness, encodeAwarenessUpdate, removeAwarenessStates } from 'y-protocols/awareness';
import { normal, readBody, readTitle, writeBody, writeTitle } from './convert';
import { mergeText, mergeTitle } from './merge';

const SAVE_IDLE_MS = 1500;       // a pause in typing
const SAVE_MAX_MS = 10_000;      // and no longer than this behind someone who never pauses
const DROP_AFTER_MS = 60_000;    // a document nobody has open
const RECHECK_MS = 60_000;       // a privilege taken away ends the connection within this
const HEARTBEAT_MS = 15_000;
const AGENT_SHOWN_MS = 5_000;
export const MAX_UPDATE_BYTES = 2 * 1024 * 1024;
const MAX_TEXT = 1024 * 1024;
const SERVER = 'server';

export interface Who { headers: Record<string, string>; member: string }
export class Refused extends Error {
  constructor(public status: number, message = '') { super(message); }
}

const GATEWAY = (process.env.HARNESS_GATEWAY_URL || process.env.NEXT_PUBLIC_HARNESS_GATEWAY_URL || 'http://127.0.0.1:8080').replace(/\/$/, '');
const enc = encodeURIComponent;
const b64 = (u: Uint8Array) => Buffer.from(u).toString('base64');

async function gw(who: Who, method: string, path: string, body?: unknown, signal?: AbortSignal, extra?: Record<string, string>): Promise<Response> {
  return fetch(`${GATEWAY}${path}`, {
    method, signal, cache: 'no-store',
    headers: { ...who.headers, ...extra, ...(body !== undefined ? { 'content-type': 'application/json' } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

async function words(r: Response): Promise<string> {
  try {
    const d = await r.json() as { error?: { message?: string }; detail?: string };
    return d?.error?.message || (typeof d?.detail === 'string' ? d.detail : '') || '';
  } catch { return ''; }
}

interface RecordRead {
  id: string; title?: string; version?: number; status?: string;
  content?: { type: string; text?: string }[];
  written_by?: { kind?: string; id?: string; type?: string };
}
const bodyOf = (r: RecordRead) => (r.content || []).filter((p) => p.type === 'text').map((p) => p.text || '').join('\n\n');
const stated = (r: RecordRead) => ({ title: (r.title || '').trim(), body: normal(bodyOf(r)) });

interface Conn {
  id: string; who: Who; canWrite: boolean; clients: Set<number>;
  send: (event: string, data: unknown) => void; close: () => void;
  beat: ReturnType<typeof setInterval>; check: ReturnType<typeof setInterval>;
}

class LiveDoc {
  doc = new Y.Doc();
  awareness = new Awareness(this.doc);
  epoch = crypto.randomUUID();
  conns = new Map<string, Conn>();
  base = { title: '', body: '' };     // what the memory holds, as far as this document knows
  record: RecordRead | null = null;
  gone = false;
  private editor: Who | null = null;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private retry = 0;
  private dirtySince = 0;
  private dropTimer: ReturnType<typeof setTimeout> | null = null;
  private agentTimer: ReturnType<typeof setTimeout> | null = null;
  private queue: Promise<unknown> = Promise.resolve();

  constructor(public mid: string, public rid: string, private opener: Who, private drop: (d: LiveDoc) => void) {
    this.awareness.setLocalState(null);
    this.doc.on('update', (u: Uint8Array, origin: unknown) => {
      this.tell('u', { u: b64(u) }, typeof origin === 'string' ? origin : undefined);
      if (origin !== SERVER) this.touched(typeof origin === 'string' ? origin : '');
    });
    this.awareness.on('update', ({ added, updated, removed }: { added: number[]; updated: number[]; removed: number[] }, origin: unknown) => {
      const from = typeof origin === 'string' ? this.conns.get(origin) : undefined;
      if (from) { added.forEach((c) => from.clients.add(c)); removed.forEach((c) => from.clients.delete(c)); }
      this.tell('a', { a: b64(encodeAwarenessUpdate(this.awareness, [...added, ...updated, ...removed])) }, typeof origin === 'string' ? origin : undefined);
    });
  }

  private serial<T>(work: () => Promise<T>): Promise<T> {
    const run = this.queue.then(work, work);
    this.queue = run.catch(() => undefined);
    return run;
  }

  tell(event: string, data: unknown, except?: string) {
    for (const c of this.conns.values()) if (c.id !== except) c.send(event, data);
  }

  async seed() {
    const r = await gw(this.opener, 'GET', `/v1/memories/${enc(this.mid)}/records/${enc(this.rid)}`);
    if (!r.ok) throw new Refused(r.status, await words(r));
    const rec = await r.json() as RecordRead;
    const s = stated(rec);
    this.record = rec;
    writeTitle(this.doc, s.title, SERVER);
    writeBody(this.doc, s.body, SERVER);
    // what the document says now, under the editor's schema: comparing to this can't mistake a formatting
    // round trip for someone's edit
    this.base = { title: readTitle(this.doc), body: readBody(this.doc) };
  }

  private touched(connId: string) {
    const c = this.conns.get(connId);
    if (c) this.editor = c.who;
    if (!this.dirtySince) this.dirtySince = Date.now();
    this.schedule();
  }

  private schedule(wait?: number) {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    const left = SAVE_MAX_MS - (Date.now() - this.dirtySince);
    this.saveTimer = setTimeout(() => { void this.save(); }, wait ?? Math.max(0, Math.min(SAVE_IDLE_MS, left)));
  }

  /** Write what people typed back to the memory, as one new version. */
  save(): Promise<void> {
    if (this.saveTimer) { clearTimeout(this.saveTimer); this.saveTimer = null; }
    return this.serial(async () => {
      if (this.gone) return;
      const title = readTitle(this.doc).replace(/\s+/g, ' ').trim();
      const body = readBody(this.doc);
      const same = title === this.base.title.replace(/\s+/g, ' ').trim() && body === this.base.body;
      if (same) { this.dirtySince = 0; this.retry = 0; this.tell('saved', { version: this.record?.version ?? null }); return; }
      if (body.length > MAX_TEXT) { this.tell('refused', { message: 'This record is too long to save.' }); return; }
      const patch: Record<string, unknown> = {};
      if (title !== this.base.title) patch.title = title;
      if (body !== this.base.body) {
        const keep = (this.record?.content || []).filter((p) => p.type !== 'text');
        patch.content = [...(body.trim() ? [{ type: 'text', text: body }] : []), ...keep];
      }
      this.tell('saving', {});
      const who = this.editor || this.opener;
      let r: Response;
      try {
        const version = this.record?.version;
        r = await gw(who, 'PATCH', `/v1/memories/${enc(this.mid)}/records/${enc(this.rid)}`, patch, undefined, version != null ? { 'if-match': String(version) } : undefined);
      } catch {
        this.unsaved();
        return;
      }
      if (r.status >= 500) { this.unsaved(); return; }
      if (r.status === 412) {
        // someone wrote while this was on its way: take theirs in with what's being typed, and save the two together
        const fresh = await gw(this.opener, 'GET', `/v1/memories/${enc(this.mid)}/records/${enc(this.rid)}`);
        if (fresh.ok) this.takeIn(await fresh.json() as RecordRead, null);
        this.touchedAfterSave();
        return;
      }
      if (!r.ok) {
        // a verdict: trying again won't change it. It stands on the page until someone changes what they wrote.
        this.dirtySince = 0;
        this.tell('refused', { message: await words(r) || 'This change could not be saved.' });
        return;
      }
      const rec = await r.json() as RecordRead;
      this.retry = 0;
      this.dirtySince = 0;
      this.base = { title, body };
      this.record = rec;
      this.tell('saved', { version: rec.version ?? null, by: rec.written_by ?? null });
      // a provider may keep its own wording: what it holds now is what the page should say
      this.takeIn(rec, null);
      if (readTitle(this.doc).replace(/\s+/g, ' ').trim() !== title || readBody(this.doc) !== body) this.touchedAfterSave();
    });
  }

  private touchedAfterSave() {
    if (!this.dirtySince) this.dirtySince = Date.now();
    this.schedule();
  }

  private unsaved() {
    this.retry = Math.min(this.retry + 1, 6);
    this.tell('unsaved', {});
    this.schedule(1000 * 2 ** this.retry);
  }

  /** Someone else wrote (or may have): read the record and bring the document to it, keeping unsaved typing. */
  changed(written_by?: RecordRead['written_by']): Promise<void> {
    return this.serial(async () => {
      if (this.gone) return;
      const r = await gw(this.opener, 'GET', `/v1/memories/${enc(this.mid)}/records/${enc(this.rid)}`);
      if (r.status === 404) { this.ended(); return; }
      if (!r.ok) return;
      const rec = await r.json() as RecordRead;
      if (rec.status && rec.status !== 'active') { this.ended(); return; }
      this.takeIn(rec, written_by ?? rec.written_by ?? null);
    });
  }

  private takeIn(rec: RecordRead, by: RecordRead['written_by'] | null) {
    const theirs = stated(rec);
    this.record = rec;
    if (theirs.title === this.base.title && theirs.body === this.base.body) return;
    const ours = { title: readTitle(this.doc), body: readBody(this.doc) };
    const body = mergeText(ours.body, this.base.body, theirs.body);
    const title = mergeTitle(ours.title, this.base.title, theirs.title);
    writeTitle(this.doc, title, SERVER);
    const { text } = writeBody(this.doc, body, SERVER);
    this.base = theirs;
    if (by) {
      this.show(by, text);
      this.tell('saved', { version: rec.version ?? null, by });
    }
    if (body !== theirs.body || title !== theirs.title) this.touchedAfterSave();
  }

  /** Whoever wrote stands in the document for a moment, at what they changed, as anyone editing would. */
  private show(by: NonNullable<RecordRead['written_by']>, text: Y.XmlText | null) {
    const name = by.type === 'agent' ? 'Agent' : (by.id === 'local@localhost' ? 'Operator' : (by.id || 'Someone'));
    const at = text ? Y.relativePositionToJSON(Y.createRelativePositionFromTypeIndex(text, text.length)) : null;
    this.awareness.setLocalState({
      user: { id: `${by.kind || 'writer'}:${by.id || ''}`, name, agent: by.type === 'agent' },
      ...(at ? { cursor: { anchor: at, head: at } } : {}),
    });
    if (this.agentTimer) clearTimeout(this.agentTimer);
    this.agentTimer = setTimeout(() => this.awareness.setLocalState(null), AGENT_SHOWN_MS);
  }

  ended() {
    this.gone = true;
    this.tell('gone', {});
  }

  join(conn: Conn) {
    if (this.dropTimer) { clearTimeout(this.dropTimer); this.dropTimer = null; }
    this.conns.set(conn.id, conn);
    conn.send('hello', {
      epoch: this.epoch, state: b64(Y.encodeStateAsUpdate(this.doc)), sv: b64(Y.encodeStateVector(this.doc)),
      awareness: b64(encodeAwarenessUpdate(this.awareness, [...this.awareness.getStates().keys()])),
      version: this.record?.version ?? null, canWrite: conn.canWrite, gone: this.gone,
    });
  }

  leave(id: string) {
    const c = this.conns.get(id);
    if (!c) return;
    this.conns.delete(id);
    clearInterval(c.beat);
    clearInterval(c.check);
    if (c.clients.size) removeAwarenessStates(this.awareness, [...c.clients], 'left');
    if (!this.conns.size) {
      void this.save();
      this.dropTimer = setTimeout(() => this.drop(this), DROP_AFTER_MS);
    }
  }

  apply(connId: string, update?: Uint8Array, aw?: Uint8Array) {
    if (update) Y.applyUpdate(this.doc, update, connId);
    if (aw) applyAwarenessUpdate(this.awareness, aw, connId);
  }

  destroy() {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    if (this.dropTimer) clearTimeout(this.dropTimer);
    if (this.agentTimer) clearTimeout(this.agentTimer);
    this.awareness.destroy();
    this.doc.destroy();
  }
}

/** One read of a memory's events from the gateway, while anything in that memory is open. */
class Watch {
  private stop = new AbortController();
  private after: number | null = null;
  constructor(private mid: string, private who: () => Who | null, private docs: () => LiveDoc[]) { void this.run(); }
  end() { this.stop.abort(); }

  private async run() {
    let wait = 1000;
    while (!this.stop.signal.aborted) {
      const who = this.who();
      if (!who) return;
      try {
        const r = await gw(who, 'GET', `/v1/memories/${enc(this.mid)}/events${this.after !== null ? `?after=${this.after}` : ''}`, undefined, this.stop.signal);
        if (r.status === 401 || r.status === 403 || r.status === 404) return;
        if (r.ok && r.body) {
          wait = 1000;
          await this.read(r.body);
        }
      } catch { /* the gateway restarted: read again below */ }
      if (this.stop.signal.aborted) return;
      await new Promise((go) => setTimeout(go, wait));
      wait = Math.min(wait * 2, 15_000);
    }
  }

  private async read(body: ReadableStream<Uint8Array>) {
    const reader = body.getReader();
    const text = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buf += text.decode(value, { stream: true });
      let i = buf.indexOf('\n\n');
      while (i >= 0) {
        this.event(buf.slice(0, i));
        buf = buf.slice(i + 2);
        i = buf.indexOf('\n\n');
      }
    }
  }

  private event(frame: string) {
    const data = frame.split('\n').find((l) => l.startsWith('data: '));
    if (!data) return;
    let ev: { id?: number; type?: string; record_id?: string; record_ids?: string[]; written_by?: RecordRead['written_by'] };
    try { ev = JSON.parse(data.slice(6)); } catch { return; }
    if (typeof ev.id === 'number') this.after = ev.id;
    const open = this.docs();
    const near = (d: LiveDoc) => {
      if (ev.type === 'record.revised' || ev.type === 'record.forgotten') return ev.record_id === d.rid;
      if (ev.type === 'records.erased') return !!ev.record_ids?.includes(d.rid);
      return ev.type === 'records.changed' || ev.type === 'reset';
    };
    for (const d of open) if (near(d)) void d.changed(ev.written_by);
  }
}

class Hub {
  docs = new Map<string, LiveDoc>();
  opening = new Map<string, Promise<LiveDoc>>();
  watches = new Map<string, Watch>();
  whoFor = new Map<string, Who>();

  private key = (mid: string, rid: string) => `${mid}/${rid}`;

  private async open(mid: string, rid: string, who: Who): Promise<LiveDoc> {
    const k = this.key(mid, rid);
    const have = this.docs.get(k);
    if (have) return have;
    let p = this.opening.get(k);
    if (!p) {
      p = (async () => {
        const d = new LiveDoc(mid, rid, who, (x) => this.dropDoc(x));
        try {
          await d.seed();
        } catch (e) {
          d.destroy();
          throw e;
        }
        this.docs.set(k, d);
        return d;
      })().finally(() => this.opening.delete(k));
      this.opening.set(k, p);
    }
    return p;
  }

  private dropDoc(d: LiveDoc) {
    if (d.conns.size) return;
    this.docs.delete(this.key(d.mid, d.rid));
    d.destroy();
    if (![...this.docs.values()].some((x) => x.mid === d.mid)) {
      this.watches.get(d.mid)?.end();
      this.watches.delete(d.mid);
      this.whoFor.delete(d.mid);
    }
  }

  private async privileges(mid: string, who: Who): Promise<string[]> {
    const r = await gw(who, 'GET', `/v1/memories/${enc(mid)}`);
    if (!r.ok) throw new Refused(r.status, await words(r));
    return (await r.json() as { privileges?: string[] }).privileges || [];
  }

  async join(mid: string, rid: string, connId: string, who: Who, send: Conn['send'], close: () => void): Promise<() => void> {
    const privs = await this.privileges(mid, who);
    if (!privs.includes('read')) throw new Refused(404);
    const d = await this.open(mid, rid, who);
    this.whoFor.set(mid, who);
    if (!this.watches.has(mid)) {
      this.watches.set(mid, new Watch(mid, () => this.whoFor.get(mid) || null, () => [...this.docs.values()].filter((x) => x.mid === mid)));
    }
    const conn: Conn = {
      id: connId, who, canWrite: privs.includes('write'), clients: new Set(), send, close,
      beat: setInterval(() => send('', null), HEARTBEAT_MS),
      check: setInterval(() => {
        void this.privileges(mid, who).then((p) => {
          if (!p.includes('read')) { d.leave(connId); close(); return; }
          const can = p.includes('write');
          if (can !== conn.canWrite) { conn.canWrite = can; send('access', { canWrite: can }); }
        }).catch((e) => {
          // a verdict ends it; a gateway that's restarting doesn't
          if (e instanceof Refused && e.status < 500) { d.leave(connId); close(); }
        });
      }, RECHECK_MS),
    };
    d.join(conn);
    return () => d.leave(connId);
  }

  update(mid: string, rid: string, connId: string, update?: Uint8Array, aw?: Uint8Array) {
    const d = this.docs.get(this.key(mid, rid));
    const c = d?.conns.get(connId);
    if (!d || !c) {
      if (!update) return;     // only who's here, from a page that's gone or still connecting: nothing is lost
      throw new Refused(409, 'reconnect');
    }
    if (update && !c.canWrite) throw new Refused(403);
    if (update && d.gone) throw new Refused(409, 'gone');
    d.apply(connId, update, aw);
  }
}

// One hub whatever bundling does: a second would be a second copy of every open document.
const g = globalThis as unknown as { __hrMemLive?: Hub };
export const hub: Hub = g.__hrMemLive || (g.__hrMemLive = new Hub());
