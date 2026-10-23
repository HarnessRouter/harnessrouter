'use client';
// Bring your own key (docs/uxuidesign/console-79, view `byok`: providersView, pvRow, byokDelHtml), on
// this instance's routing document as the server keeps it (byok/doc.ts says its rules). Every model
// call runs on a key added here: a model no key serves cannot be chosen.
//
// - Each provider the server's catalog lists is a row as the design draws it, grouped (direct, your
//   cloud, model gateways, custom endpoints), and the keys at that provider are listed under it:
//   several per provider, each under its own name, each edited or removed on its own (byok/KeyForm).
// - A HarnessRouter API key can be pasted, or fetched with Get a key: this instance opens the hand-off
//   with its own server (POST /v1/admin/connect), the person finishes it on the page that opens, and
//   the key arrives here by polling the code (GET /v1/admin/connect/{code}); it is saved at once.
// - "Which key serves each model" is the model map in the person's words, for chat models and, apart
//   from them, image models: for every model one of the keys can serve, the key that does, or Off. A
//   key added at the maker itself takes the models a gateway key was serving (direct, then your
//   cloud, then a gateway); after that each choice is the person's.
// - Video, speech and music run down an ordered list per capability: the first model whose provider
//   is connected runs. Each list can be reordered, and a model switched off.
// "Who uses it" is read from every workspace's setups and the model map; when that read fails the
// sentence is left out.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { harnessFetch } from '@/lib/hfetch';
import { track } from '@/lib/analytics';
import { gwHeaders } from '@/lib/harness';
import { useWorkspace } from '@/lib/workspace';
import type { Provider } from '@/lib/providers';
import { toast } from './toast';
import { ConfirmSheet } from './Sheet';
import { Skel, SkRows, SkLine } from './Skel';
import {
  HOSTED, claimsFor, getDoc, imageMapFor, isEntra, look, mapFor, nameFor, pollHandoff, putDoc, servable, servableImages, startHandoff,
  type CatalogEntry, type Doc, type Integration, type MediaChain, type MediaCandidate, type PutBody,
} from './byok/doc';
import { KeyForm } from './byok/KeyForm';

const GROUPS: { key: Provider['group']; title: string }[] = [
  { key: 'direct', title: 'Direct provider' }, { key: 'cloud', title: 'Your cloud' }, { key: 'gateway', title: 'Model gateway' }, { key: 'custom', title: 'Custom endpoint' }];
const CAP_TITLE: Record<string, string> = {
  text_to_video: 'Video, from text', image_to_video: 'Video, from a picture', text_to_image: 'Pictures',
  image_to_image: 'Picture edits', text_to_speech: 'Speech', text_to_music: 'Music', export: 'Film assembly',
};
/** How long between reads of an open HarnessRouter key hand-off. */
export const HANDOFF_POLL_MS = 2000;
const mono = (p: Provider) => p.name.charAt(0).toUpperCase() + (p.name.charAt(1) || '').toLowerCase();
/** A provider's tile: its own mark on white, so a dark mark reads in dark mode too; else a monogram. */
function PvIc({ p }: { p: Provider }) {
  // eslint-disable-next-line @next/next/no-img-element -- the provider's own mark, a static asset
  if (p.logo) return <span className="pv-ic pv-logo" aria-hidden="true"><img src={p.logo} alt="" /></span>;
  return <span className="pv-ic" aria-hidden="true">{mono(p)}</span>;
}
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;
const listNames = (u: string[]) => u.slice(0, 3).join(', ') + (u.length > 3 ? ` and ${u.length - 3} more` : '');
const ROUTES_SHOWN = 12;

interface SetupLite { name: string; model: string }

/** Every workspace's setups, name and model: who a key serves. null while reading, 'failed' when any read
 *  failed, or when the workspaces could not be listed (one workspace's setups are never read as everyone's). */
export function useAllSetups(): SetupLite[] | null | 'failed' {
  const { workspaces, defaultId, loading } = useWorkspace();
  const [out, setOut] = useState<SetupLite[] | null | 'failed'>(null);
  useEffect(() => {
    if (loading) return;
    let alive = true;
    const ids = workspaces.map((w) => w.id).filter(Boolean);
    if (!ids.length) { setOut('failed'); return; }
    Promise.all(ids.map(async (id) => {
      const def = id === defaultId;
      const q = new URLSearchParams({ workspace: id });
      if (def) q.set('workspace_default', '1');
      const r = await harnessFetch(`/api/harness/v1/harnesses?${q}`, {
        headers: { ...gwHeaders(), 'x-harness-workspace': id, ...(def ? { 'x-harness-workspace-default': '1' } : {}) }, cache: 'no-store',
      });
      if (!r.ok) throw new Error(String(r.status));
      const d = await r.json() as { harnesses?: { name?: string; defaultModel?: string }[] } | null;
      if (!d || !Array.isArray(d.harnesses)) throw new Error('unreadable list');
      return d.harnesses.map((h) => ({ name: String(h.name || ''), model: String(h.defaultModel || '') }));
    }))
      .then((lists) => { if (alive) setOut(lists.flat()); })
      .catch(() => { if (alive) setOut('failed'); });
    return () => { alive = false; };
  }, [workspaces, defaultId, loading]);
  return out;
}

/** One model routing list (chat or image): every model a key can serve, and the key that serves it. */
function Routes({ id, title, routes, busy, provName, onRoute }: {
  id: string; title: string; routes: { m: string; opts: Integration[]; at: string }[]; busy: boolean;
  provName: (id: string) => string; onRoute: (model: string, to: string) => void;
}) {
  const [q, setQ] = useState('');
  const [all, setAll] = useState(false);
  const needle = q.trim().toLowerCase();
  const shown = routes.filter((r) => !needle || r.m.toLowerCase().includes(needle));
  const off = routes.filter((r) => !r.at).length;
  return (
    <section className="pv-g" id={id}>
      <header><h2>{title}</h2><span className="kicker">{plural(routes.length, 'model')}{off ? ` · ${off} off` : ''}</span></header>
      <div className="pv-routes">
        <p className="set-help">When several of your keys can serve a model, choose the one that does. A model set to Off cannot be chosen anywhere.</p>
        {routes.length > ROUTES_SHOWN ? (
          <>
            <label className="sr" htmlFor={`${id}Q`}>Find a model</label>
            <input id={`${id}Q`} className="dd-q" placeholder="Find a model" autoComplete="off" spellCheck={false} value={q} onChange={(e) => setQ(e.target.value)} />
          </>
        ) : null}
      </div>
      {(needle || all ? shown : shown.slice(0, ROUTES_SHOWN)).map((r) => (
        <div key={r.m} className="pv-route">
          <span className="mono">{r.m}</span>
          <select className="set-in slim" aria-label={`Which key serves ${r.m}`} disabled={busy} value={r.at} onChange={(e) => onRoute(r.m, e.target.value)}>
            {r.opts.map((i) => <option key={i.name} value={i.name}>{provName(i.provider)} · {i.name}</option>)}
            <option value="">Off: no key serves it</option>
          </select>
        </div>
      ))}
      {!needle && shown.length > ROUTES_SHOWN ? (
        <div className="pv-routes"><button type="button" className="link-q inl" onClick={() => setAll(!all)}>{all ? 'Show fewer' : `Show all ${shown.length} models`}</button></div>
      ) : null}
      {needle && !shown.length ? <div className="pv-routes"><p className="set-help">No model matches that.</p></div> : null}
    </section>
  );
}

/** One media capability's list: tried in this order, the first whose provider is connected and can do
 *  what was asked runs. Each row's facts are the reason to prefer one over another. */
function Chain({ chain, busy, onMove, onToggle }: { chain: MediaChain; busy: boolean; onMove: (from: number, to: number) => void; onToggle: (model: string) => void }) {
  const facts = (c: MediaCandidate) => {
    const out: string[] = [];
    if (c.resolution) out.push(c.resolution);
    if (typeof c.seconds === 'number') out.push(`${c.seconds} s measured`);
    if (c.duration_ignored) out.push('ignores the length you ask for');
    if (c.accepts_input_image === false) out.push('text only');
    if (typeof c.usd === 'number') out.push(`$${c.usd.toFixed(2)} a ${chain.unit || 'run'}`);
    return out;
  };
  const n = chain.candidates.length;
  return (
    <section className="pv-g" data-capability={chain.capability}>
      <header><h2>{CAP_TITLE[chain.capability] || chain.capability}</h2><span className="kicker">{plural(n, 'model')}</span></header>
      <div className="pv-routes"><p className="set-help">Tried in this order. The first one whose provider is connected, and that can do what was asked, runs.</p></div>
      {chain.candidates.map((c, i) => (
        <div key={c.model} className="pv-route pv-chain">
          <span>
            <span className="mono">{i + 1}. {c.model}</span>
            {/* never colour alone: the state is a word */}
            {c.off ? <span className="muted"> · switched off</span> : !c.connected ? <span className="muted"> · no key</span> : c.unavailable ? <span className="muted"> · unavailable</span> : null}
            <small className="sub2">{[c.provider, ...facts(c)].join(' · ')}</small>
          </span>
          <span className="pv-act">
            <button type="button" className="link-q" disabled={busy || i === 0} aria-label={`Move ${c.model} up`} onClick={() => onMove(i, i - 1)}>Up</button>
            <button type="button" className="link-q" disabled={busy || i === n - 1} aria-label={`Move ${c.model} down`} onClick={() => onMove(i, i + 1)}>Down</button>
            <button type="button" className="link-q" disabled={busy} onClick={() => onToggle(c.model)}>{c.off ? 'Switch on' : 'Switch off'}</button>
          </span>
        </div>
      ))}
    </section>
  );
}

type Handoff = { code: string; url: string; state: 'waiting' | 'failed'; note: string };

export function ByokPage() {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<{ provider: string; editing?: string } | null>(null);
  const [removing, setRemoving] = useState<Integration | null>(null);
  const [models, setModels] = useState<Record<string, boolean>>({});      // a provider's full model list, opened
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  const setups = useAllSetups();
  // the document as it is now, for work that lands later (a key arriving from the hand-off)
  const docRef = useRef(doc);
  docRef.current = doc;

  const reload = useCallback(async () => {
    try { setDoc(await getDoc()); setErr(''); }
    catch { setErr('Your keys could not be read just now.'); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  const keysOf = useCallback((id: string) => (doc?.integrations || []).filter((i) => i.provider === id), [doc]);
  const metaOf = useCallback((id: string) => doc?.catalog.find((c) => c.id === id), [doc]);
  const provName = useCallback((id: string) => { const c = metaOf(id); return c ? look(c).name : id; }, [metaOf]);
  const hosted = doc?.catalog.find((c) => c.id === HOSTED) || null;
  const total = (doc?.integrations || []).length;
  const servedBy = (i: Integration) => Object.values(doc?.model_map || {}).filter((v) => v === i.name).length;
  const usersOf = (i: Integration): string[] | null => {
    if (!doc || setups === null || setups === 'failed') return null;
    return setups.filter((h) => h.model && doc.model_map?.[h.model] === i.name).map((h) => h.name);
  };

  /** Write the document and read it again; false (and said) when the server refused. */
  const write = useCallback(async (body: PutBody, failed: string) => {
    const res = await putDoc(body);
    if (!res.ok) { toast(failed); return res; }
    await reload();
    return res;
  }, [reload]);

  async function submit(meta: CatalogEntry, entry: Integration, editing?: string) {
    const doc = docRef.current;
    if (!doc) return { ok: false as const, detail: '' };
    setBusy(true);
    try {
      const integrations = editing ? doc.integrations.map((i) => (i.name === editing ? entry : i)) : [...doc.integrations, entry];
      const claims = editing ? {} : claimsFor(doc, meta.id, entry.name, entry.models.map((m) => m.canonical));
      const res = await putDoc({ integrations, model_map: mapFor(doc, integrations, claims) });
      if (res.ok) {
        track('byok_key_added', { provider: meta.id });
        setForm(null);
        const moved = Object.keys(claims).length;
        toast(`${look(meta).name} ${editing ? 'connection saved' : 'key saved'}${moved ? `. It now serves ${plural(moved, 'model')} another key was serving.` : ''}`);
        await reload();
      }
      return res;
    } finally { setBusy(false); }
  }

  async function remove(i: Integration) {
    if (!doc) return;
    setBusy(true);
    try {
      const integrations = doc.integrations.filter((x) => x.name !== i.name);
      // every map that can name a connection drops it, or the server refuses the whole write
      const res = await putDoc({ integrations, model_map: mapFor(doc, integrations), image_model_map: imageMapFor(doc, integrations) });
      if (!res.ok) { toast('The key could not be removed. Try again.'); return; }
      track('byok_key_removed', { provider: i.provider });
      setRemoving(null);
      toast(`Your ${provName(i.provider)} ${isEntra(i) ? 'connection' : 'key'} is removed.`);
      await reload();
    } finally { setBusy(false); }
  }

  async function route(model: string, to: string, image: boolean) {
    if (!doc) return;
    setBusy(true);
    try {
      const body: PutBody = image
        ? { integrations: doc.integrations, image_model_map: imageMapFor(doc, doc.integrations, { [model]: to }) }
        : { integrations: doc.integrations, model_map: mapFor(doc, doc.integrations, { [model]: to }) };
      const res = await write(body, 'That could not be changed. Try again.');
      if (!res.ok) return;
      const i = doc.integrations.find((x) => x.name === to);
      toast(i ? `${model} now runs on ${provName(i.provider)} · ${i.name}.` : `${model} is off: no key serves it.`);
    } finally { setBusy(false); }
  }

  async function media(capability: string, order: string[], disabled: string[]) {
    if (!doc) return;
    setBusy(true);
    try {
      await write({ integrations: doc.integrations, media_policy: { ...(doc.media_policy || {}), [capability]: { order, disabled } } }, 'That could not be changed. Try again.');
    } finally { setBusy(false); }
  }

  // the HarnessRouter key hand-off: the page it names opens in a new tab, and the code is read until
  // the key is ready, which is then saved as a connection at once
  async function getKey() {
    setHandoff(null);
    try {
      const h = await startHandoff();
      setHandoff({ ...h, state: 'waiting', note: 'Finish in the HarnessRouter tab. The key lands here on its own.' });
      window.open(h.url, '_blank', 'noopener');
    } catch {
      setHandoff({ code: '', url: '', state: 'failed', note: 'HarnessRouter could not be reached just now. Try again.' });
    }
  }
  useEffect(() => {
    if (!handoff || handoff.state !== 'waiting' || !handoff.code) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      const r = await pollHandoff(handoff.code);
      if (!alive) return;
      if (r === 'waiting') { timer = setTimeout(() => void tick(), HANDOFF_POLL_MS); return; }
      if (r === 'failed') { setHandoff({ ...handoff, state: 'failed', note: 'That key hand-off ended without a key. Get a key again.' }); return; }
      const d = docRef.current;
      const meta = d?.catalog.find((c) => c.id === HOSTED);
      setHandoff(null);
      if (!d || !meta) return;
      const entry: Integration = {
        name: nameFor(d, HOSTED, (r.name || '').trim() || 'HarnessRouter API'), provider: HOSTED, models: [],
        config: { api_key: r.api_key, ...(r.endpoint ? { base_url: r.endpoint } : {}), ...(r.models_url ? { models_url: r.models_url } : {}), ...(r.balance_url ? { balance_url: r.balance_url } : {}) },
      };
      await submit(meta, entry);
    };
    timer = setTimeout(() => void tick(), HANDOFF_POLL_MS);
    return () => { alive = false; if (timer) clearTimeout(timer); };
  // the document is read through docRef at the moment the key lands
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handoff]);

  function keyLine(meta: CatalogEntry, i: Integration) {
    const n = servedBy(i);
    const bal = i.balance;
    return (
      <div key={i.name} className="pv-key">
        <span className="pv-k">
          <i className="pv-dot" />Connected · <b>{i.name}</b>
          {isEntra(i) ? <> · Microsoft Entra</> : null}
          <span className="pv-serves"> · {n ? `serves ${plural(n, 'model')}` : 'serves no model now'}</span>
          {bal ? <span className="pv-serves"> · {bal.usd <= 0 ? '$0.00 left' : `$${bal.usd.toFixed(2)} left`} <a className="link-q inl" href={`${doc?.hosted_console || 'https://app.harnessrouter.ai'}/billing`} target="_blank" rel="noopener noreferrer">Add credit ↗</a></span> : null}
        </span>
        <span className="pv-act">
          <button type="button" className="link-q" disabled={busy} onClick={() => setRemoving(i)}>Remove</button>
          <button type="button" className="btn small line" disabled={busy} onClick={() => setForm({ provider: meta.id, editing: i.name })}>Edit</button>
        </span>
      </div>
    );
  }

  function row(meta: CatalogEntry) {
    const p = look(meta);
    const mine = keysOf(meta.id);
    const list = (meta.models || []).map((m) => m.canonical);
    const opened = !!models[meta.id];
    const f = form?.provider === meta.id ? form : null;
    return (
      <div key={meta.id} className={`pv-r${mine.length ? ' on' : ''}`} data-provider={meta.id}>
        <PvIc p={p} />
        <span className="pv-x">
          <b>{p.name}</b>
          {meta.id === HOSTED ? <small>One key for every model on its list, at its listed price.</small> : null}
          {list.length ? (
            <small>{plural(list.length, 'model')} · {opened ? list.join(', ') : list.slice(0, 2).join(', ')}
              {list.length > 2 ? <> <button type="button" className="link-q inl" aria-expanded={opened}
                onClick={() => setModels({ ...models, [meta.id]: !opened })}>{opened ? 'Show fewer' : `+${list.length - 2}`}</button></> : null}
            </small>
          ) : meta.id === 'custom' ? <small>Any endpoint that speaks the OpenAI or Anthropic API.</small> : null}
        </span>
        <span className="pv-act">
          {meta.id === HOSTED ? <button type="button" className="btn small line" disabled={busy || handoff?.state === 'waiting'} onClick={() => void getKey()}>Get a key</button> : null}
          {!f || f.editing ? (
            <button type="button" className="btn small line" disabled={busy} onClick={() => setForm({ provider: meta.id })}>{mine.length ? 'Add another' : meta.id === 'custom' ? 'Add endpoint' : 'Add key'}</button>
          ) : null}
        </span>
        {meta.id === HOSTED && handoff ? (
          <p className={`pv-form set-help${handoff.state === 'failed' ? ' kl-bad' : ''}`} role="status">
            {handoff.note}{handoff.url && handoff.state === 'waiting' ? <> <a className="link-q inl" href={handoff.url} target="_blank" rel="noopener noreferrer">Open HarnessRouter ↗</a></> : null}
          </p>
        ) : null}
        {mine.length ? <div className="pv-keys">{mine.map((i) => keyLine(meta, i))}</div> : null}
        {f && doc ? (
          <KeyForm key={`${meta.id}:${f.editing || ''}`} meta={meta} name={p.name} doc={doc} busy={busy}
            editing={f.editing ? mine.find((i) => i.name === f.editing) : undefined}
            onCancel={() => setForm(null)} onSubmit={(entry) => submit(meta, entry, f.editing)} />
        ) : null}
      </div>
    );
  }

  // which key serves each model: every model one of the keys can serve (chat, then image models)
  const routesOf = (of: (i: Integration) => string[], map: Record<string, string>) => {
    if (!doc) return [];
    const opts: Record<string, Integration[]> = {};
    for (const i of doc.integrations) for (const m of of(i)) (opts[m] ||= []).push(i);
    return Object.keys(opts).sort().map((m) => ({ m, opts: opts[m], at: map[m] || '' }));
  };
  const chatRoutes = useMemo(() => routesOf(servable, doc?.model_map || {}), [doc]); // eslint-disable-line react-hooks/exhaustive-deps
  const imageRoutes = useMemo(() => routesOf(servableImages, doc?.image_model_map || {}), [doc]); // eslint-disable-line react-hooks/exhaustive-deps
  const chains = (doc?.media_chains || []).filter((c) => c.candidates.length > 0);

  const rm = removing ? usersOf(removing) : null;
  // what its models run on once it is gone: another of the keys that can serve them, else nothing
  const rmModels = removing && doc ? Object.entries(doc.model_map || {}).filter(([, v]) => v === removing.name).map(([m]) => m) : [];
  const rmCovered = removing && doc ? rmModels.filter((m) => doc.integrations.some((x) => x.name !== removing.name && servable(x).includes(m))).length : 0;
  const rmAfter = !rmModels.length ? ''
    : rmCovered === rmModels.length ? 'Its models run on your other keys that serve them. '
      : rmCovered ? `${plural(rmCovered, 'model')} run${rmCovered === 1 ? 's' : ''} on your other keys; ${plural(rmModels.length - rmCovered, 'model')} no other key serves cannot be chosen until one does. `
        : `${plural(rmModels.length, 'model')} no other key serves cannot be chosen until one does. `;
  const rmWhat = removing && isEntra(removing) ? 'connection' : 'key';
  const rmMany = removing ? (doc?.integrations || []).filter((i) => i.provider === removing.provider).length > 1 : false;
  return (
    <div className="scroll">
      <div className="list-wrap prov">
        <div className="list-top">
          <div>
            <h1>Bring your own key</h1>
            <p className="sub">Every model call runs on a key you add here, through your own account at that provider, which bills you directly.</p>
            <p className="prov-note">Not the same as <Link className="link-q inl" href="/keys">API keys</Link>, which your app uses to send tasks to this instance.</p>
          </div>
          {doc ? <span className="kicker prov-count">{total ? plural(total, 'key') : 'No keys yet'}</span> : null}
        </div>

        {err ? <p className="sub" role="alert">{err}{' '}<button type="button" className="link-q inl" onClick={() => void reload()}>Try again</button></p> : null}
        {!doc && !err ? (
          // shaped like what lands: a group of providers, each a mark, a name and its models, and a button
          <Skel label="Loading your keys">
            {[4, 3].map((n, g) => (
              <section key={g} className="pv-g" aria-hidden="true">
                <header><SkLine w={130} h={14} /><SkLine w={52} h={10} /></header>
                <div style={{ padding: '0 12px' }}><SkRows n={n} cols={1} /></div>
              </section>
            ))}
          </Skel>
        ) : null}
        {doc && hosted ? (
          <section className="pv-g" id="pvHosted">
            <header><h2>HarnessRouter API</h2><span className="kicker">{keysOf(HOSTED).length ? plural(keysOf(HOSTED).length, 'key') : 'No keys'}</span></header>
            {row(hosted)}
          </section>
        ) : null}
        {doc ? GROUPS.map((g) => {
          const list = doc.catalog.filter((c) => c.id !== HOSTED && look(c).group === g.key);
          if (!list.length) return null;
          const n = list.reduce((a, c) => a + keysOf(c.id).length, 0);
          return (
            <section key={g.key} className="pv-g" data-group={g.key}>
              <header><h2>{g.title}</h2><span className="kicker">{n ? plural(n, 'key') : 'No keys'}</span></header>
              {list.map(row)}
            </section>
          );
        }) : null}

        {chatRoutes.length ? <Routes id="pvRoutes" title="Which key serves each model" routes={chatRoutes} busy={busy} provName={provName} onRoute={(m, to) => void route(m, to, false)} /> : null}
        {imageRoutes.length ? <Routes id="pvImageRoutes" title="Which key serves each image model" routes={imageRoutes} busy={busy} provName={provName} onRoute={(m, to) => void route(m, to, true)} /> : null}
        {chains.map((c) => {
          const order = c.candidates.map((x) => x.model);
          const off = new Set(doc?.media_policy?.[c.capability]?.disabled || c.candidates.filter((x) => x.off).map((x) => x.model));
          return (
            <Chain key={c.capability} chain={c} busy={busy}
              onMove={(from, to) => { if (to < 0 || to >= order.length) return; const next = [...order]; const [x] = next.splice(from, 1); next.splice(to, 0, x); void media(c.capability, next, [...off]); }}
              onToggle={(m) => { const d = new Set(off); if (d.has(m)) d.delete(m); else d.add(m); void media(c.capability, order, [...d]); }} />
          );
        })}
      </div>

      {removing ? (
        <ConfirmSheet id="bd" title={`Remove your ${provName(removing.provider)} ${rmWhat}${rmMany ? ` · ${removing.name}` : ''}`}
          confirmLabel={`Remove ${rmWhat}`} busy={busy} focusConfirm
          onClose={() => setRemoving(null)} onConfirm={() => void remove(removing)}
          body={<>{rm === null ? rmAfter
            : rm.length ? <><b>{listNames(rm)}</b> {rm.length === 1 ? 'uses' : 'use'} it. {rmAfter}</>
              : `No setup uses it right now. ${rmAfter}`}Usage so far stays billed by {provName(removing.provider)}.</>} />
      ) : null}
    </div>
  );
}
