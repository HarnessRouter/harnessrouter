'use client';
// The sheets Settings opens (docs/uxuidesign/console-79: delAgentHtml, popHtml's env picker), plus
// the ones the design has no drawing for but the setup needs: a copy on another agent harness (the
// design hands this to its New setup sheet) and an installed plugin package.
import Link from 'next/link';
import { useRef, useState } from 'react';
import { strToU8, zipSync } from 'fflate';
import {
  createCustom, deleteCustom, getPluginFiles, getSkillFiles, offeredOob, oobById, oobDefaultModel, oobModels, modelAvailability, setHarnessPlugs, useModelCatalogRead, PLUGS_ENTRY_ID,
  type BaseInfo, type CustomHarness, type HarnessPlugin, type HarnessPlugs,
} from '@/lib/harness';
import type { Environment } from '@/lib/environments';
import { Sheet, SheetTop } from '../Sheet';
import { toast } from '../toast';
import { ReadFailed } from '../ext/shared';
import { plain, plural } from './settingsModel';

export const CHECK = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} aria-hidden="true"><path d="M5 12l5 5L20 7" /></svg>;

// ── Delete setup: type its name (delAgentHtml) ────────────────────────────────────────────────────
// The design's layout and keys (Cancel Esc, Delete ⌘↵ once the name is typed). What a person types is
// the setup's name, as they call it, never its Harness ID, which is not for people to read (Richard,
// 2026-10-18): trimmed, exactly as saved, case and all. A setup with no name asks for "delete". Its
// sentence is what the gateway does: the setup stops at once and tasks sent to its Harness ID are
// refused; its tasks stay readable; it is kept 30 days (the instance's operator can restore it until
// then) and removed after, so it does not say "can't be undone".
export function DeleteSetupSheet({ h, onClose, onDeleted }: { h: CustomHarness; onClose: () => void; onDeleted: () => void }) {
  const [v, setV] = useState('');
  const [busy, setBusy] = useState(false);
  const inRef = useRef<HTMLInputElement | null>(null);
  const [mac] = useState(() => typeof navigator !== 'undefined' && /Mac|iP(hone|ad|od)/.test(navigator.platform || navigator.userAgent || ''));
  const name = (h.name || '').trim();
  const want = name || 'delete';
  const ok = v.trim() === want;
  async function go() {
    if (!ok || busy) return;
    setBusy(true);
    try { await deleteCustom(h.id); onDeleted(); }
    catch (e) { setBusy(false); toast(plain(e, 'The setup could not be deleted. Try again.')); }
  }
  return (
    <Sheet onClose={onClose} labelledBy="dlh" describedBy="dlp" className="small-sheet del-sheet" alert busy={busy} initialFocus={inRef}>
      <SheetTop id="dlh" title="Delete setup" onClose={onClose} />
      <p className="del-p" id="dlp"><b>{name || 'This setup'}</b> stops working at once, and tasks sent to its Harness ID are refused. Its past tasks stay readable. It is removed for good after 30 days.</p>
      <label className="del-l nm" htmlFor="delConfirm">Type <b>{want}</b> to confirm.</label>
      <input id="delConfirm" ref={inRef} className="set-in" autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false}
        value={v} onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); if (e.metaKey || e.ctrlKey) void go(); } }} />
      <div className="del-act">
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel<kbd>Esc</kbd></button>
        <button type="button" className="btn del-go" id="delGo" disabled={!ok || busy} onClick={() => void go()}>Delete<kbd>{mac ? '⌘' : 'Ctrl '}↵</kbd></button>
      </div>
    </Sheet>
  );
}

// ── the Environment picker (popHtml) ─────────────────────────────────────────────────────────────────
export function EnvPickSheet({ envs, failed = false, retry, current, busy, onPick, onClose }: {
  envs: Environment[] | null; failed?: boolean; retry?: () => void; current: string; busy: boolean; onPick: (id: string) => void; onClose: () => void;
}) {
  return (
    <Sheet onClose={onClose} labelledBy="eh" className="small-sheet">
      <SheetTop id="eh" title="Environment" onClose={onClose} />
      {envs === null && failed ? <ReadFailed what="environments" retry={() => retry?.()} />
        : envs === null ? <div className="empty-list" role="status" style={{ padding: '16px 0' }}>Reading your environments…</div>
        : !envs.length ? <div className="empty-list" style={{ padding: '16px 0' }}>No environments yet. <Link className="link-q inl" href="/extensions?tab=envs">Add one in Add-ons</Link></div>
          : (
            <div className="pick-list">
              {envs.map((x) => {
                const on = x.id === current;
                const note = x.status === 'ready' ? x.description : [x.description, 'Not built yet'].filter(Boolean).join(' · ');
                return (
                  <button key={x.id} type="button" className={`opt${on ? ' sel' : ''}`} aria-pressed={on} disabled={busy} onClick={() => onPick(x.id)}>
                    <span className="chk">{on ? CHECK : null}</span><span>{x.name}{note ? <small>{note}</small> : null}</span>
                  </button>
                );
              })}
            </div>
          )}
      <div className="sheet-actions"><Link className="btn" href="/extensions?tab=envs">Open Add-ons</Link></div>
    </Sheet>
  );
}

// ── An installed plugin package: what it brings, on or off, its files ─────────────────────────────
export function PackageSheet({ p, hid, busy, onToggle, onDetach, onClose }: {
  p: HarnessPlugin; hid: string; busy: boolean; onToggle: () => void; onDetach: () => void; onClose: () => void;
}) {
  const m = p.manifest || {};
  const on = p.enabled !== false;
  const pending = Boolean(p.files && p.files.length && !p.blob);
  const [dl, setDl] = useState(false);
  async function download() {
    setDl(true);
    try {
      const files = await getPluginFiles(hid, p.name);
      const entries: Record<string, Uint8Array> = {};
      for (const f of files) entries[f.path] = f.content_b64 !== undefined ? Uint8Array.from(atob(f.content_b64), (c) => c.charCodeAt(0)) : strToU8(f.content || '');
      const fname = `${p.name}${m.version ? '-' + m.version : ''}.zip`;
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([zipSync(entries) as BlobPart], { type: 'application/zip' }));
      a.download = fname;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) { toast(plain(e, 'The package could not be downloaded. Try again.')); }
    finally { setDl(false); }
  }
  const skills = p.skills || [], servers = p.mcpServers || [], skipped = p.skipped || [];
  return (
    <Sheet onClose={onClose} labelledBy="pkh" className="small-sheet">
      <SheetTop id="pkh" title={<>{p.name}{m.version ? <span className="muted"> v{m.version}</span> : null}</>} sub={m.description || undefined} onClose={onClose} />
      <div className="cap-list">
        <div className={`cap-row${on ? '' : ' off'}`}>
          <span className="grow"><b>{on ? 'Plugin is on' : 'Plugin is off'}</b>
            <small>{[plural(skills.length, 'skill'), plural(servers.length, 'tool'), ...(m.author?.name ? [`by ${m.author.name}`] : []), ...(m.license ? [m.license] : [])].join(' · ')}</small></span>
          <button type="button" className={`tog${on ? ' on' : ''}`} aria-pressed={on} aria-label={p.name} disabled={busy} onClick={onToggle}><i />{on ? 'On' : 'Off'}</button>
        </div>
        {skills.map((s) => <div key={'s' + s.name} className="cap-row"><span className="grow"><b className="mono">{s.name}</b>{s.description ? <small>Skill · {s.description}</small> : <small>Skill</small>}</span></div>)}
        {servers.map((s) => <div key={'t' + s.name} className="cap-row"><span className="grow"><b className="mono">{s.name}</b><small>Tool · {s.transport === 'stdio' ? `runs ${s.command || ''}${(s.args || []).length ? ' ' + (s.args || []).join(' ') : ''}` : s.url}</small></span></div>)}
        {skipped.map((s) => <div key={'x' + s.path} className="cap-row off"><span className="grow"><b className="mono">{s.path}</b><small className="warn">Not loaded · {s.reason}</small></span></div>)}
      </div>
      {m.homepage || m.repository ? (
        <p className="set-help">{m.homepage ? <a className="link-q inl" href={m.homepage} target="_blank" rel="noreferrer">Homepage</a> : null}
          {m.homepage && m.repository ? ' · ' : null}{m.repository ? <a className="link-q inl" href={m.repository} target="_blank" rel="noreferrer">Source</a> : null}</p>
      ) : null}
      <div className="sheet-actions">
        {!pending ? <button type="button" className="btn" disabled={dl} onClick={() => void download()}>Download</button> : null}
        <button type="button" className="btn line" disabled={busy} onClick={onDetach}>Detach</button>
      </div>
    </Sheet>
  );
}

// ── A copy on another agent harness: same skills, plugins and instructions, new Harness ID ────────
// The copy takes its instructions, skills, plugins, environment, built-in tool choices, limits and
// request headers. Not its MCP servers or variables: the secrets they name belong to the original
// (deleting it removes them), so the copy gets them added again in its own Settings.
export function DuplicateSheet({ h, bases, plugs, onClose, onDone }: {
  h: CustomHarness; bases: Record<string, BaseInfo> | null; plugs: HarnessPlugs | null | undefined;
  onClose: () => void; onDone: (c: CustomHarness) => void;
}) {
  const offered = offeredOob(bases);
  const catalog = useModelCatalogRead();
  const [name, setName] = useState(`${h.name} copy`);
  const [base, setBase] = useState(h.base);
  // the copy keeps the setup's own model ('' : the harness default) on whichever harness it moves to;
  // one the new harness cannot run is said, and Save waits for another choice (never swapped for a default)
  const [model, setModel] = useState(h.defaultModel || '');
  const [busy, setBusy] = useState(false);
  const o = oobById(base);
  const listed = oobModels(o);
  const models = listed.filter((m) => modelAvailability(o?.backend, m) === 'yes' || m === model);
  const cantRun = !!model && !!catalog.value && (!listed.includes(model) || modelAvailability(o?.backend, model) === 'no');
  const harnessDefault = oobDefaultModel(o);
  const srv = bases?.[base] || null;
  const takesSkills = srv?.takesSkills !== false, takesEnv = srv?.takesEnvironments !== false;
  const ownSkills = (h.skills || []).filter((s) => (s.files && s.files.length) || s.blob);
  const notes = [
    !takesSkills && ownSkills.length ? `${o?.name || base} takes no skills, so the copy has none.` : '',
    !takesEnv && h.environment ? `${o?.name || base} can’t open an environment, so the copy has none.` : '',
    (h.mcpServers || []).some((m) => m.id !== PLUGS_ENTRY_ID) || Object.keys(h.env || {}).length
      ? 'Its MCP servers and environment variables are not copied: add them in the copy’s Settings.' : '',
  ].filter(Boolean);

  async function save() {
    const nm = name.trim();
    if (!nm) { toast('Give the setup a name.'); return; }
    setBusy(true);
    try {
      // the copy gets its own files: a skill or package shared by handle would go when the original drops it
      const skills = takesSkills ? await Promise.all((h.skills || []).map(async (s) => (
        s.blob && !(s.files && s.files.length) ? { id: 'skl_' + crypto.randomUUID().replace(/-/g, ''), name: s.name, enabled: s.enabled !== false, files: await getSkillFiles(h.id, s.id || s.name) }
          : { ...s, id: 'skl_' + crypto.randomUUID().replace(/-/g, '') }))) : [];
      const plugins = await Promise.all((h.plugins || []).map(async (p) => ({
        name: p.name, enabled: p.enabled !== false, manifest: p.manifest, files: p.files && p.files.length ? p.files : await getPluginFiles(h.id, p.name),
      })));
      const c = await createCustom({
        name: nm, base, defaultModel: model, systemPrompt: h.systemPrompt, skills, plugins, environment: takesEnv ? h.environment || '' : '',
        disabledTools: h.disabledTools, maxStep: h.maxStep, timeoutSeconds: h.timeoutSeconds, reasoningEffort: h.reasoningEffort,
        additionalHeaders: h.additionalHeaders,
      });
      // its workspace plugins are its binding, written through their own route
      if (plugs && plugs.plugs.length) {
        try { await setHarnessPlugs(c.id, plugs.plugs); }
        catch { toast(`Saved as ${c.name}. Its workspace plugins were not added; add them in its Settings.`); onDone(c); return; }
      }
      toast(`Saved as ${c.name}`);
      onDone(c);
    } catch (e) { setBusy(false); toast(plain(e, 'The copy was not saved. Try again.')); }
  }

  return (
    <Sheet onClose={onClose} labelledBy="duh" className="small-sheet" busy={busy}>
      <SheetTop id="duh" title="Duplicate setup" sub="Same skills, plugins and instructions, new Harness ID." onClose={onClose} />
      <div className="set-f"><label htmlFor="duName">Name</label>
        <input id="duName" className="set-in" value={name} onChange={(e) => setName(e.target.value)} /></div>
      <div className="set-f"><label htmlFor="duBase">Agent harness</label>
        <select id="duBase" className="set-in" value={base} onChange={(e) => setBase(e.target.value)}>
          {offered.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          {offered.some((x) => x.id === h.base) ? null : <option value={h.base}>{h.baseLabel || h.base}</option>}
        </select>
        <p className="set-help">Fixed once saved.</p></div>
      <div className="set-f"><label htmlFor="duModel">Model</label>
        <select id="duModel" className="set-in" value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">{`The harness default${harnessDefault ? ` (${harnessDefault})` : ''}`}</option>
          {(models.includes(model) ? models : [model, ...models]).filter(Boolean).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        {cantRun ? <p className="set-help warn">{`${o?.name || base} does not run ${model}. Choose a model for the copy.`}</p> : null}
        {catalog.failed ? <p className="set-help">The models could not be read just now. <button type="button" className="link-q inl" onClick={catalog.retry}>Try again</button></p> : null}
        {notes.length ? <p className="set-help">{notes.join(' ')}</p> : null}</div>
      <div className="sheet-actions">
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={busy || !name.trim() || cantRun} onClick={() => void save()}>Save setup</button>
      </div>
    </Sheet>
  );
}
