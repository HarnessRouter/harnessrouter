'use client';
// Add-ons › Tools (docs/uxuidesign/console-79: wsTools, libraryView's tools tab, mcpHtml). An MCP
// server belongs to a setup, so the list is every server the workspace's setups connect to, one row
// per address, with who uses it. Add MCP is two steps (Richard, 2026-10-18): the MCP sheet
// (mcp/McpSheet) makes it, then Add to setups (AddToSheet) picks the setups that get it, one copy
// each, written one setup at a time as adding it to one setup does; that step needs a setup. A row's
// Edit opens the same sheet on every copy at that address; Remove takes it off every setup that has
// it, asked in the sheet.
//
// Each write reads the setup's record fresh and changes only its MCP servers. A token is stored
// securely first, under each copy's own id, and only its reference is kept on the setup.
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { getCustom, saveCustom, type CustomHarness, type McpServer } from '@/lib/harness';
import { partIcon } from '../bricks';
import { toast } from '../toast';
import { PLUS, setupHref, ReadFailed } from './shared';
import { Skel, SkRows } from '../Skel';
import { isServiceEntry } from '../setup/settingsModel';
import { McpSheet, addrKey, authFor, isHeaderRef, newMcpId, HEADER_REF, type McpSaveInput, type McpTarget } from '../mcp/McpSheet';
import { AddToSheet, type AddResult, type AddTarget } from './AddToSheet';

interface Tool { key: string; name: string; url: string; on: boolean; by: { id: string; name: string; on: boolean }[]; first: McpServer }

/** Every MCP server the setups connect to, one per address (trailing slashes and case ignored). The
 *  console's own entries (plugins, media) are not the person's servers and are left out. */
export function wsTools(setups: CustomHarness[] | null): Tool[] {
  const m: Record<string, Tool> = {}, out: Tool[] = [];
  for (const a of setups || []) {
    for (const t of a.mcpServers || []) {
      if (!t.url || isServiceEntry(t)) continue;
      const k = addrKey(t.url);
      let x = m[k];
      if (!x) { x = m[k] = { key: k, name: t.name || t.url, url: t.url, on: false, by: [], first: t }; out.push(x); }
      if (t.enabled !== false) x.on = true;
      if (!x.by.some((b) => b.id === a.id)) x.by.push({ id: a.id, name: a.name, on: t.enabled !== false });
    }
  }
  return out;
}

/** An address may break after a slash, never inside a word. */
function UrlBreaks({ url }: { url: string }) {
  const parts = url.split('/');
  return <>{parts.map((p, i) => <span key={i}>{p}{i < parts.length - 1 ? <>/<wbr /></> : null}</span>)}</>;
}

const atAddr = (k: string) => (m: McpServer) => !isServiceEntry(m) && !!m.url && addrKey(m.url) === k;
const sayNames = (names: string[]) => (names.length <= 2 ? names.join(' and ') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`);

/** How many MCP servers Add-ons counts: the setups' own, one per address. */
export function toolCount(setups: CustomHarness[] | null): number {
  return wsTools(setups).length;
}

/** `failed`: the setups could not be read (lib/settle.ts); the tab says so, with `retry`. */
export function ToolsTab({ setups, reload, failed = false, retry }: {
  setups: CustomHarness[] | null; reload: () => Promise<void>; failed?: boolean; retry?: () => void;
}) {
  const tools = useMemo(() => wsTools(setups), [setups]);
  const loading = setups === null;
  // the sheet: adding (no tool) or editing every copy at one address
  const [open, setOpen] = useState<{ tool: Tool | null } | null>(null);
  // adding: what the first step made, once its Next is pressed (the second step chooses the setups)
  const [made, setMade] = useState<{ name: string; url: string; token: string } | null>(null);
  const [step2, setStep2] = useState(false);

  const targets: McpTarget[] = useMemo(() => (setups || []).map((h) => ({
    id: h.id, name: h.name, base: h.base,
    headers: h.additionalHeaders || [], has: !!open?.tool && (h.mcpServers || []).some(atAddr(open.tool.key)),
  })), [setups, open]);

  /** Another server already called this in a chosen setup (the one being edited aside). */
  const nameTaken = (n: string, to: string[]) => {
    const k = open?.tool?.key, low = n.toLowerCase();
    const clash = (setups || []).filter((h) => to.includes(h.id) && (h.mcpServers || []).some((m) => !isServiceEntry(m) && (m.name || '').toLowerCase() === low && !(k && m.url && addrKey(m.url) === k)));
    return clash.length ? `${sayNames(clash.map((h) => h.name))} already ${clash.length === 1 ? 'has' : 'have'} an MCP server named ${n}.` : '';
  };

  /** Write each setup's change on its newest record; says which did not take. */
  async function each(ids: string[], change: (h: CustomHarness) => Promise<McpServer[] | null>): Promise<{ done: string[]; failed: string[] }> {
    const done: string[] = [], failed: string[] = [];
    for (const id of ids) {
      const name = setups?.find((h) => h.id === id)?.name || id;
      try {
        const h = await getCustom(id);
        if (!h) throw new Error('gone');
        const next = await change(h);
        if (next) await saveCustom({ ...h, mcpServers: next });
        done.push(name);
      } catch { failed.push(name); }
    }
    return { done, failed };
  }

  // ── adding, the second step: the setups that get it ─────────────────────────────────────────
  /** Why a setup cannot take the server just made: it connects to that endpoint already, or has
   *  another server by that name. '' when it can. */
  const cannot = (h: CustomHarness, m: { name: string; url: string }) => {
    const list = (h.mcpServers || []).filter((x) => !isServiceEntry(x));
    if (list.some(atAddr(addrKey(m.url)))) return 'Already connects to this endpoint';
    if (list.some((x) => (x.name || '').toLowerCase() === m.name.toLowerCase())) return `Already has an MCP server named ${m.name}`;
    return '';
  };
  const hdr = made && isHeaderRef(made.token) ? made.token.trim().slice(HEADER_REF.length) : '';
  const addTargets: AddTarget[] = made ? (setups || []).map((h) => ({
    id: h.id, name: h.name, base: h.base,
    off: cannot(h, made) || undefined,
    warn: hdr && !(h.additionalHeaders || []).includes(hdr) ? `Takes no ${hdr} header yet, so the server gets no token here` : undefined,
  })) : [];
  const open1 = addTargets.filter((t) => !t.off);
  async function addTo(ids: string[]): Promise<AddResult> {
    const m = made;
    const r: AddResult = { done: [], failed: [] };
    if (!m) return r;
    for (const id of ids) {
      try {
        const h = await getCustom(id);
        if (!h) { r.failed.push({ id, why: 'No longer in this workspace' }); continue; }
        const why = cannot(h, m);
        if (why) { r.failed.push({ id, why }); continue; }
        // each copy keeps its own stored token, under its own id
        const mid = newMcpId();
        const auth = await authFor(mid, m.token, undefined);
        await saveCustom({ ...h, mcpServers: [...(h.mcpServers || []), { id: mid, name: m.name, url: m.url, transport: 'http', enabled: true, ...(auth ? { auth } : {}) }] });
        r.done.push(id);
      } catch { r.failed.push({ id, why: '' }); }
    }
    await reload();
    return r;
  }
  function added(ids: string[]) {
    const names = ids.map((id) => setups?.find((h) => h.id === id)?.name || id);
    if (made && names.length) toast(`${made.name} added to ${sayNames(names)}.`);
    setStep2(false); setMade(null); setOpen(null);
  }

  /** Every header the setups take, offered as a token reference while their choice is still to come. */
  const allHeaders = useMemo(() => Array.from(new Set((setups || []).flatMap((h) => h.additionalHeaders || []))), [setups]);

  // ── editing every copy at one address ─────────────────────────────────────────────────────────
  async function save(v: McpSaveInput): Promise<string> {
    const tool = open?.tool || null;
    if (!tool) return '';
    const users = tool.by.map((b) => b.id);
    const ids = Array.from(new Set([...v.to, ...users]));
    // a copy added to another setup with no token typed keeps the same stored token's reference
    const borrowed = (setups || []).flatMap((h) => h.mcpServers || []).find(atAddr(tool.key))?.auth;
    const r = await each(ids, async (h) => {
      const list = h.mcpServers || [];
      const mine = list.filter(atAddr(tool.key));
      if (!v.to.includes(h.id)) return list.filter((m) => !mine.includes(m));          // taken off this setup
      if (mine.length) {
        const out: McpServer[] = [];
        for (const m of list) {
          if (!mine.includes(m)) { out.push(m); continue; }
          const auth = await authFor(m.id, v.token, m.auth);
          const kept: McpServer = { ...m, name: v.name, url: v.url };
          if (auth) kept.auth = auth; else delete kept.auth;
          out.push(kept);
        }
        return out;
      }
      const id = newMcpId();
      const auth = await authFor(id, v.token, borrowed);
      return [...list, { id, name: v.name, url: v.url, transport: 'http', enabled: true, ...(auth ? { auth } : {}) }];
    });
    await reload();
    if (r.failed.length) {
      return `It could not be saved to ${sayNames(r.failed)}${r.done.length ? `. ${sayNames(r.done)} ${r.done.length === 1 ? 'has' : 'have'} it now` : ''}. Try again.`;
    }
    const more = v.to.filter((id) => !users.includes(id)).length, dropped = users.filter((id) => !v.to.includes(id)).length;
    toast(more || dropped ? `${v.name} saved. ${v.to.length === 1 ? '1 setup uses' : `${v.to.length} setups use`} it.` : `${v.name} saved.`);
    setOpen(null);
    return '';
  }

  async function remove(): Promise<string> {
    const tool = open?.tool;
    if (!tool) return '';
    const r = await each(tool.by.map((b) => b.id), async (h) => (h.mcpServers || []).filter((m) => !atAddr(tool.key)(m)));
    await reload();
    if (r.failed.length) return `It could not be removed from ${sayNames(r.failed)}. Try again.`;
    toast(`${tool.name} removed from ${sayNames(r.done)}.`);
    setOpen(null);
    return '';
  }

  return (
    <>
      <div className="lib-form"><button type="button" className="btn primary" disabled={loading} onClick={() => { setMade(null); setStep2(false); setOpen({ tool: null }); }}>{PLUS}Add MCP</button></div>
      {failed ? <ReadFailed what="tools" retry={retry || (() => void reload())} /> : null}
      {loading ? (failed ? null : <div className="rows"><Skel label="Loading your tools"><SkRows n={4} /></Skel></div>)
        : tools.length ? (
          <div className="rows">
            {tools.map((x) => (
              <div key={x.key} className="row lib-g">
                <span className="t lib-t">
                  <span className="lib-ic" aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon(x.on ? 'built' : 'empty', 'mcp') }} />
                  <span>
                    <b>{x.name}</b>
                    <small className="sub2 mono"><UrlBreaks url={x.url} /></small>
                    <small className="lib-used">Used by {x.by.map((b, i) => (
                      <span key={b.id + i}>{i ? ', ' : ''}<Link className="link-q inl" href={setupHref(b.id)}>{b.name}</Link>{b.on ? '' : ' (off)'}</span>
                    ))}</small>
                  </span>
                </span>
                <span className="lib-act"><button type="button" className="btn small line" onClick={() => setOpen({ tool: x })}>Edit</button></span>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-list es"><span className="es-art" aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon('empty', 'mcp') }} /><span>No MCP servers yet.</span></div>
        )}

      {open?.tool && setups ? (
        <McpSheet server={{ ...open.tool.first, name: open.tool.name, url: open.tool.url }}
          keptAuth={open.tool.first.auth} targets={targets} initialTo={open.tool.by.map((b) => b.id)}
          nameTaken={nameTaken} onSave={save} onRemove={remove} onClose={() => setOpen(null)} />
      ) : null}
      {open && !open.tool && setups && !step2 ? (
        // adding, the first step: what the server is; its setups come next
        <McpSheet server={null} draft={made || undefined} next="Next" headers={allHeaders} nameTaken={() => ''}
          onSave={async (v) => { setMade({ name: v.name, url: v.url, token: v.token }); setStep2(true); return ''; }}
          onClose={() => { setOpen(null); setMade(null); }} />
      ) : null}
      {open && !open.tool && made && step2 ? (
        <AddToSheet item={made.name} targets={addTargets} initial={open1.length === 1 ? [open1[0].id] : []}
          onAdd={addTo} onBack={() => setStep2(false)} onDone={added} />
      ) : null}
    </>
  );
}
