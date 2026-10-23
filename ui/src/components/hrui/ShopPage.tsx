'use client';
// The Shop (docs/uxuidesign/console-79, view `harbor`: harborView, kitCard, shopFilter): the starter
// kits this instance serves (GET /v1/kits), searchable. Every card is a kit from the server's catalog,
// in the catalog's own order; Try it opens the kit's page (shop/KitTry), where it is set up and used.
import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useWorkspace } from '@/lib/workspace';
import { Skel, SkLine } from './Skel';
import { fetchKits, partsOf, runtimeOf, type Kit } from './shop/kits';
import { HLogo, KitIc, Pieces } from './shop/parts';

function KitCard({ k }: { k: Kit }) {
  const rt = runtimeOf(k);
  const parts = partsOf(k);
  return (
    <article className="kc set">
      <span className="kc-studs" aria-hidden="true"><i /><i /><i /></span>
      <div className="kc-top">
        <KitIc kit={k} />
        <div className="kc-ttl"><h3>{k.title}</h3></div>
      </div>
      <p className="kc-tag" title={k.description || k.tagline}>{k.tagline}</p>
      {rt ? (
        <div className="kc-meta" title={`${rt.suggested ? 'Suggested' : 'Runs on'}: ${rt.label}${rt.model ? ' · ' + rt.model : ''}`}>
          <HLogo base={rt.base} /><span className="kc-h">{rt.label}</span>
          {rt.model ? <><span className="kc-dot" aria-hidden="true">·</span><span className="kc-m">{rt.model}</span></> : null}
        </div>
      ) : null}
      {parts.length ? <Pieces parts={parts} /> : null}
      <div className="kc-act">
        <span />
        <Link className="btn small kc-launch" href={`/shop/${encodeURIComponent(k.id)}`}>Try it</Link>
      </div>
    </article>
  );
}

/** Cards loading, drawn as cards (Richard, 2026-10-18): the icon tile, the title, the line, the actions. */
function SkKitCards({ n }: { n: number }) {
  return (
    <>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="kc set hrui-skel-card" aria-hidden="true">
          <div className="kc-top">
            <SkLine w={38} h={38} r={10} />
            <div className="kc-ttl"><SkLine w="62%" h={14} /><SkLine w="38%" h={10} style={{ marginTop: 8 }} /></div>
          </div>
          <SkLine w="94%" h={12} style={{ marginTop: 16 }} />
          <SkLine w="68%" h={12} style={{ marginTop: 8 }} />
          <SkLine w="52%" h={12} style={{ marginTop: 16 }} />
          <div className="kc-act"><SkLine w={92} h={12} /><SkLine w={64} h={30} r={9} /></div>
        </div>
      ))}
    </>
  );
}

/** What a search matches on a kit card: its name, its line and its chips (the design's data-q). */
function haystack(k: Kit): string {
  const rt = runtimeOf(k);
  return [k.title, k.tagline, rt?.label || '', rt?.model || '', ...partsOf(k).map((p) => p[1])].join(' ').toLowerCase();
}

export function ShopPage() {
  const { current, loading } = useWorkspace();
  // null until read; a read that fails leaves it null and says so (`kitsErr`), never an empty Shop
  const [kits, setKits] = useState<Kit[] | null>(null);
  const [kitsErr, setKitsErr] = useState(false);
  const [q, setQ] = useState('');

  // what is launched is a fact about the current workspace, so the catalog is read for it
  const kitsFor = useRef(0);
  const loadKits = useCallback(() => {
    const n = ++kitsFor.current;
    setKitsErr(false); setKits(null);
    fetchKits().then((k) => { if (kitsFor.current === n) setKits(k); })
      .catch(() => { if (kitsFor.current === n) setKitsErr(true); });
  }, []);
  useEffect(() => {
    if (loading) return;
    loadKits();
    return () => { kitsFor.current++; };
  }, [loading, current.id, loadKits]);

  const needle = q.trim().toLowerCase();
  const allKits = kits || [];
  const shownKits = needle ? allKits.filter((k) => haystack(k).includes(needle)) : allKits;
  // "Nothing in the Shop matches that" only once the kits were read: a read that failed keeps its error
  // whatever is typed, as what it holds is not known
  const nothing = !!needle && kits !== null && !kitsErr && !shownKits.length && allKits.length > 0;

  return (
    <div className="scroll">
      <div className="list-wrap">
        <div className="list-top">
          <div>
            <h1>Shop</h1>
          </div>
        </div>
        <div className="kc-q">
          <input id="shopQ" className="dd-q" type="search" placeholder="Search the Shop" value={q} autoComplete="off" spellCheck={false}
            aria-label="Search the Shop" onChange={(e) => setQ(e.target.value)} />
        </div>

        <div className="hb-sec"><h2>Starter kits</h2></div>
        {kitsErr ? (
          <p className="kc-nomatch" role="alert">The starter kits could not be read just now.{' '}
            <button type="button" className="link-q inl" onClick={loadKits}>Try again</button></p>
        ) : null}
        {kits !== null && !allKits.length ? <div className="empty-list">No starter kits are available right now.</div> : null}
        {kits === null && !kitsErr ? (
          <div className="kgrid"><Skel label="Loading the starter kits" className="hrui-skel-contents"><SkKitCards n={3} /></Skel></div>
        ) : shownKits.length ? (
          <div className="kgrid">{shownKits.map((k) => <KitCard key={k.id} k={k} />)}</div>
        ) : null}
        <p className="kc-nomatch" hidden={!nothing}>Nothing in the Shop matches that.</p>
      </div>
    </div>
  );
}
