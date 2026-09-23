'use client';
// Harness Settings, the ONE place persistent harness configuration is edited (per the 2026-07-17
// IA review): General → Default model → Agent instructions → Tools → Skills → Runtime limits →
// Request headers, one Save. Built-in harnesses render read-only with a Clone action.
// Reuses the battle-tested SkillEditor + McpModal from the workbench.
import { useEffect, useMemo, useRef, useState } from 'react';
import { zipSync, strToU8 } from 'fflate';
import { SkelPage } from '@/components/Skel';
import { useRouter } from 'next/navigation';
import {
  OOB, oobById, oobDefaultModel, oobModels, useModelCatalog, modelAvailable, modelAvailability, availabilityNote, useBases, getCustom, saveCustom, deleteCustom, createCustom, getSkillFiles, storeMcpSecret, pluginSchemas,
  type CustomHarness, type OobHarness, type HarnessPlugin, getPluginFiles,
  useRuntimeDefaults,
} from '@/lib/harness';
import { HarnessLogo } from '@/components/HarnessLogo';
import { CopyId } from '@/components/CopyId';
import { SkillEditor, McpModal, readSkillUpload, type McpServer } from '@/components/HarnessEditors';
import { fetchTraceWindow, statsFor, p95Of, avgCreditsOf, timeAgo, type TraceCard } from '@/lib/revamp-data';
// Self-hosted only: publish a custom harness (instructions, model, skills, MCP wiring) to a
// hosted workspace. Hidden and inert on hosted builds.
import { SELF_HOSTED } from '@/lib/edition';
import { CloudUploadDialog } from '@/components/CloudUploadDialog';
import { statusOne, type CloudStatus } from '@/lib/cloud-upload';

type Skill = CustomHarness['skills'][number];
const isOwnSkill = (s: Skill) => Boolean((s.files && s.files.length) || (s as { content?: string }).content || s.blob);

/** Harness settings. `embedded`: rendered inside the Agent harnesses page, which owns the title
 *  row and the way back; navigation asks the host instead of pushing routes. */
export function HarnessSettings({ id, embedded = false, onNavigate }: {
  id: string; embedded?: boolean; onNavigate?: (to: 'tasks' | 'list') => void;
}) {
  const router = useRouter();
  const go = (to: 'tasks' | 'list') => {
    if (onNavigate) onNavigate(to);
    else router.push(to === 'tasks' ? `/harnesses?h=${encodeURIComponent(id)}` : '/harnesses');
  };
  const oob = oobById(id);
  const [saved, setSaved] = useState<CustomHarness | null>(null);
  const [draft, setDraft] = useState<CustomHarness | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // The environment as rows, so a half-typed name does not vanish from a map keyed by name.
  // The rows are re-derived whenever the SAVED harness changes (a new harness, a save, a discard),
  // never on every keystroke; and every change to the rows writes draft.env, so dirty state and
  // saving, which read the draft, see what the screen shows (#244).
  const [envRows, setEnvRows] = useState<{ name: string; value: string }[]>([]);
  const rowsOf = (env: Record<string, string> | undefined) => Object.entries(env || {}).map(([name, value]) => ({ name, value }));
  const envOf = (rows: { name: string; value: string }[]) => Object.fromEntries(rows.filter((r) => r.name).map((r) => [r.name, r.value]));
  useEffect(() => { setEnvRows(rowsOf(draft?.env)); }, [draft?.id, saved]);   // eslint-disable-line react-hooks/exhaustive-deps
  const setEnvRow = (idx: number, patch: Partial<{ name: string; value: string }>) => setEnvRows((rows) => {
    const next = rows.map((r, k) => (k === idx ? { ...r, ...patch } : r));
    upd({ env: envOf(next) });
    return next;
  });
  const dropEnvRow = (idx: number) => setEnvRows((rows) => {
    const next = rows.filter((_, k) => k !== idx);
    upd({ env: envOf(next) });
    return next;
  });
  const [editSkillIdx, setEditSkillIdx] = useState<number | null>(null);
  const [mcpModal, setMcpModal] = useState<{ idx: number | null } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  useEffect(() => {
    if (!SELF_HOSTED || !id) return;
    statusOne(id).then(setCloud).catch(() => setCloud(null));
  }, [id]);
  // Draft of a NEW skill being created in the SkillEditor popup (name edited in the same popup).
  const [newSkill, setNewSkill] = useState<{ name: string } | null>(null);
  // Plugins: which row is expanded (by name, so removing another row cannot move it), the folder
  // picker, the export in flight, and a notice that belongs to this section rather than to Save.
  const [pluginOpen, setPluginOpen] = useState<string | null>(null);
  const [pluginBusy, setPluginBusy] = useState(false);
  const [pluginNote, setPluginNote] = useState<{ kind: 'error' | 'info'; text: string } | null>(null);
  const pluginDirRef = useRef<HTMLInputElement>(null);
  // The gateway refuses a package over this size (its _PLUGIN_PACKAGE_MAX); refusing here first
  // spares reading a 30 MB folder into the draft only to be told no on Save.
  const PLUGIN_PACKAGE_MAX = 16 * 1024 * 1024;
  // A folder picked as a plugin package: every file under it, paths relative to the folder itself,
  // and the manifest read up front so the row can name what was picked before it is saved. The
  // server does the real validation on save and answers with what it derived and what it skipped.
  async function installPluginFolder(list: FileList | null) {
    if (!list || !list.length || !draft) return;
    setPluginBusy(true); setPluginNote(null);
    try {
      let total = 0;
      for (let i = 0; i < list.length; i++) total += list[i].size;
      if (total > PLUGIN_PACKAGE_MAX) throw new Error(`That folder is ${fmtMb(total)}; a plugin package can be at most ${fmtMb(PLUGIN_PACKAGE_MAX)}.`);
      const files: NonNullable<HarnessPlugin['files']> = [];
      for (let i = 0; i < list.length; i++) {
        const f = list[i];
        const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
        const path = rel.includes('/') ? rel.slice(rel.indexOf('/') + 1) : rel;   // drop the picked folder's own name
        if (!path || path.split('/').some((seg) => seg === 'node_modules' || seg === '.git')) continue;
        files.push(await readSkillUpload(f, path));
      }
      const manifestFile = files.find((f) => f.path === 'plugin.json');
      if (!manifestFile || manifestFile.content === undefined) throw new Error('That folder has no plugin.json at its root, so it is not a plugin package.');
      let manifest: (HarnessPlugin['manifest'] & { $schema?: string }) = {};
      try { manifest = JSON.parse(manifestFile.content) as typeof manifest; } catch { throw new Error('plugin.json is not valid JSON.'); }
      const name = String(manifest?.name || '');
      if (!name) throw new Error('plugin.json names no plugin.');
      if ((draft.plugins || []).some((p) => p.name === name)) throw new Error(`A plugin named ${name} is already installed on this Harness.`);
      // The server says which package versions it installs; a package for another one is
      // refused on Save, so say so now, while the folder is still in front of the person.
      const schemas = await pluginSchemas();
      if (schemas.length && !schemas.includes(String(manifest.$schema || ''))) {
        throw new Error(manifest.$schema
          ? `This package targets ${manifest.$schema}, which this server does not install (it installs ${schemas.join(', ')}).`
          : 'plugin.json names no $schema, which every package must.');
      }
      upd({ plugins: [...(draft.plugins || []), { name, enabled: true, files, manifest }] });
      setPluginNote({ kind: 'info', text: `${name} is added; it installs when you save the Harness.` });
    } catch (e) { setPluginNote({ kind: 'error', text: e instanceof Error ? e.message : String(e) }); }
    finally { setPluginBusy(false); if (pluginDirRef.current) pluginDirRef.current.value = ''; }
  }
  const fmtMb = (n: number) => `${(n / 1048576).toFixed(n < 10485760 ? 1 : 0)} MB`;
  // One installed plugin, byte for byte as the server holds it, zipped in the browser.
  async function downloadInstalledPlugin(p: HarnessPlugin) {
    if (!draft?.id || pluginBusy) return;
    setPluginBusy(true); setPluginNote(null);
    try {
      const files = await getPluginFiles(draft.id, p.name);
      const entries: Record<string, Uint8Array> = {};
      for (const f of files) {
        entries[f.path] = f.content_b64 !== undefined
          ? Uint8Array.from(atob(f.content_b64), (c) => c.charCodeAt(0))
          : strToU8(f.content || '');
      }
      const fname = `${p.name}${p.manifest?.version ? '-' + p.manifest.version : ''}.zip`;
      const blob = new Blob([zipSync(entries) as BlobPart], { type: 'application/zip' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = fname;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      setPluginNote({ kind: 'info', text: `Downloaded ${fname}: ${files.length} ${files.length === 1 ? 'file' : 'files'}, the package as installed.` });
    } catch (e) { setPluginNote({ kind: 'error', text: e instanceof Error ? e.message : String(e) }); }
    finally { setPluginBusy(false); }
  }
  const [cards, setCards] = useState<TraceCard[]>([]);

  useEffect(() => {
    let alive = true;
    fetchTraceWindow(id).then((cs) => { if (alive) setCards(cs); }).catch(() => { /* metrics show dashes */ });
    return () => { alive = false; };
  }, [id]);

  useEffect(() => {
    if (oob) { setLoaded(true); return; }
    let alive = true;
    getCustom(id).then((c) => { if (alive) { setSaved(c); setDraft(c); setLoaded(true); } });
    return () => { alive = false; };
  }, [id, oob]);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(saved), [draft, saved]);
  useModelCatalog();   // model list comes from the gateway, not a local copy
  const base = oob || oobById(draft?.base || '') || null;
  // Capabilities come from the server, never from the static table: it once advertised four
  // built-in skills that existed nowhere, with controls beside them that acted on nothing.
  const bases = useBases();
  // The limits that apply when a field is left empty, from the server: shown as the field's value
  // so a person sees the number that will actually stop a runaway task, not a grey example.
  const limits = useRuntimeDefaults();
  const srvBase = bases?.[base?.id || draft?.base || ''] || null;
  const baseTools = srvBase?.tools || [];
  const models = oobModels(base);
  const upd = (p: Partial<CustomHarness>) => setDraft((d) => (d ? { ...d, ...p } : d));

  async function save() {
    if (!draft || busy) return;
    setBusy(true); setErr(null);
    try {
      const s = await saveCustom(draft);
      setSaved(s); setDraft(s);
      // A plugin the server installed with parts it could not load is only visible on this
      // page; leaving now would hide it. Stay, open that row, and say so.
      const partial = (s.plugins || []).filter((p) => (p.skipped || []).length);
      if (partial.length) {
        setPluginOpen(partial[0].name);
        setPluginNote({ kind: 'info', text: `Saved. ${partial.map((p) => `${p.name}: ${(p.skipped || []).length} part${(p.skipped || []).length === 1 ? '' : 's'} not loaded`).join('; ')}. Open Details to see which.` });
        return;
      }
      // After a successful save, jump to Tasks with THIS harness selected so the user can
      // immediately run a task on the config they just changed.
      go('tasks');
    }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function openSkillEditor(idx: number) {
    if (!draft) return;
    const s = draft.skills[idx];
    if (!(s.files && s.files.length) && s.blob) {
      try {
        const files = await getSkillFiles(draft.id, s.id || s.name);
        upd({ skills: draft.skills.map((x, k) => (k === idx ? { ...x, files } : x)) });
      } catch { setErr('Could not load the skill folder, try again.'); return; }
    }
    setEditSkillIdx(idx);
  }

  if (!loaded) return <section className="view is-active" id="view-harness"><SkelPage /></section>;
  if (!oob && !draft) return <section className="view is-active"><div className="page"><div className="session-empty">Harness not found.</div></div></section>;

  const name = oob ? oob.name : draft!.name;
  const readOnly = Boolean(oob);
  const skills = draft?.skills || [];
  const ownSkills = skills.map((s, idx) => ({ s, idx })).filter(({ s }) => isOwnSkill(s));
  // Built-ins the harness has not replaced with one of its own. A built-in is implicit: the
  // harness stores an entry only when its answer differs from the image's default.
  const takesSkills = srvBase?.takesSkills !== false;
  const baseSkills = (takesSkills ? (srvBase?.builtinSkills || []) : []).filter((b) => !ownSkills.some(({ s }) => s.name === b.name));
  const disabledTools = new Set(draft?.disabledTools || []);

  const stats = statsFor(cards);
  const degraded = stats.success != null && stats.success < 0.9 && stats.tasks7d >= 3;
  const p95 = p95Of(cards);
  const creditsPerTask = avgCreditsOf(cards);

  return (
    <section className={'view is-active' + (embedded ? ' is-embedded' : '')} id="view-harness">
      <div className="page">
        {!embedded && (
        <div className="page-header detail-context">
          <div>
            <button className="back-link" type="button" onClick={() => go('list')}><iconify-icon icon="tabler:arrow-left"></iconify-icon><span>Harnesses</span></button>
            <div className="detail-header">
              <span className="detail-icon"><HarnessLogo id={(base?.id || draft?.base || '')} size={26} /></span>
              <div className="detail-title"><h1>{name}</h1>
                <p><span className={'status ' + (degraded ? 'warning' : 'healthy')}>{degraded ? 'Needs review' : 'Connected and healthy'}</span> · Base Harness: {base?.name || draft?.baseLabel}{readOnly ? ' · built-in' : ''}</p></div>
            </div>
          </div>
        </div>
        )}

        <div className="detail-metrics" aria-label="Selected Harness metrics">
          <div className="detail-metric"><span>Success rate</span><strong>{stats.success != null ? `${(stats.success * 100).toFixed(1)}%` : '—'}</strong><small>Last 7 days</small></div>
          <button className="detail-metric" type="button" onClick={() => go('tasks')}>
            <span>Tasks</span><strong>{stats.tasks7d.toLocaleString()}</strong><small>Last 7 days</small></button>
          <div className="detail-metric"><span>p95 duration</span><strong>{p95 ?? '—'}</strong><small>Recent tasks</small></div>
          <div className="detail-metric"><span>Credits / Task</span><strong>{creditsPerTask ?? '—'}</strong><small>Avg over priced runs</small></div>
        </div>

        <form id="hs-form" className="settings-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <div className="settings-form-head">
            <div><h2>Harness Settings</h2><p>Configure the instructions, capabilities, and execution limits inherited by every Task on this Harness.</p></div>
            <div className="header-actions">
              <span className="save-state">{readOnly ? 'Built-in · read-only' : dirty ? 'Unsaved changes' : 'No unsaved changes'}</span>
              {SELF_HOSTED && !readOnly && cloud?.uploaded && (
                <span className={'cloud-chip' + (cloud.changed ? ' changed' : '')} title={cloud.target || ''}>
                  <iconify-icon icon={cloud.changed ? 'tabler:cloud-up' : 'tabler:cloud-check'}></iconify-icon>
                  <span>{cloud.changed ? 'Changed since upload' : `Uploaded ${timeAgo(cloud.uploaded_at ?? null)}`}</span>
                </span>
              )}
            </div>
          </div>

          <section className="form-section">
            <div><h3>General</h3><p>Name this reusable agent configuration and review its runtime foundation.</p></div>
            <div className="field-stack">
              <div className="field"><label htmlFor="hsName">Name</label>
                <input id="hsName" value={name} disabled={readOnly} onChange={(e) => upd({ name: e.target.value })} /></div>
              <div className="field"><label>Base Harness</label>
                <div className="inline-value"><span>{base?.name || draft?.baseLabel || '—'}</span><span className="status healthy">Connected</span></div>
                <span className="field-help">The Base Harness defines compatible capabilities and cannot be changed after creation.</span></div>
              <div className="field"><label>Harness ID</label>
                <CopyId value={id} />
                <span className="field-help">Address this Harness from the API with this ID.</span></div>
            </div>
          </section>

          <section className="form-section">
            <div><h3>Default model</h3><p>The model used when a Task does not choose an override.</p></div>
            <div className="field-stack">
              <div className="field"><label htmlFor="hsModel">Model</label>
                <select id="hsModel" disabled={readOnly} value={oob ? oobDefaultModel(oob) : (draft?.defaultModel || oobDefaultModel(oobById(draft?.base || '')) || '')}
                  onChange={(e) => upd({ defaultModel: e.target.value })}>
                  {models.map((m) => (
                    <option key={m} value={m} disabled={!modelAvailable((oob?.backend || oobById(draft?.base || '')?.backend) || '', m)}>
                      {m}{availabilityNote(modelAvailability((oob?.backend || oobById(draft?.base || '')?.backend) || '', m)) ? ` (${availabilityNote(modelAvailability((oob?.backend || oobById(draft?.base || '')?.backend) || '', m))})` : ''}
                    </option>
                  ))}
                </select>
                <span className="field-help">Tasks may choose another compatible model at runtime.</span></div>
            </div>
          </section>

          <section className="form-section">
            <div><h3>Agent instructions</h3><p>Persistent role, conventions, constraints, and output contract loaded on every Task.</p></div>
            <div className="field-stack">
              <div className="field"><label htmlFor="hsInstructions">{(base?.id || draft?.base || '') === 'systemone' ? 'Instructions' : ['codex', 'hermes', 'omp', 'pi', 'opencode', 'dsh', 'qwen', 'cline', 'goose', 'kimi', 'aider', 'openhands'].includes(base?.id || draft?.base || '') ? 'AGENTS.md' : 'CLAUDE.md'}</label>
                <textarea id="hsInstructions" rows={7} disabled={readOnly}
                  value={oob ? oob.systemPrompt : (draft?.systemPrompt || '')}
                  onChange={(e) => upd({ systemPrompt: e.target.value })} />
                <span className="field-help">These Harness-specific instructions are loaded every turn; the Base Harness system prompt remains unchanged.</span></div>
            </div>
          </section>

          <section className="form-section">
            <div><h3>Tools</h3><p>Control inherited tools and add MCP servers for external capabilities.</p></div>
            <div className="field-stack">
              <div className="section-actions"><strong>{baseTools.length + (draft?.mcpServers?.length || 0)} configured tools</strong>
                {!readOnly && <button className="button small" type="button" onClick={() => setMcpModal({ idx: null })}><iconify-icon icon="tabler:plus"></iconify-icon>Add MCP</button>}</div>
              <div className="capability-list">
                {baseTools.map((t) => (
                  <div key={t.name} className="capability-row">
                    <span className="capability-icon"><iconify-icon icon="tabler:plug"></iconify-icon></span>
                    <div className="capability-copy"><strong>{t.label}</strong>
                      <span>Built into {base?.name}
                        {t.enforcement === 'instruction' && ' · disabling asks the agent not to use it'}</span></div>
                    <div className="capability-actions">
                      <button className="toggle-button" type="button" disabled={readOnly} aria-pressed={!disabledTools.has(t.name)}
                        onClick={() => upd({ disabledTools: disabledTools.has(t.name) ? (draft?.disabledTools || []).filter((x) => x !== t.name) : [...(draft?.disabledTools || []), t.name] })}>
                        {disabledTools.has(t.name) ? 'Disabled' : 'Enabled'}</button>
                    </div>
                  </div>
                ))}
                {(draft?.mcpServers || []).map((m, idx) => (
                  <div key={m.id || idx} className="capability-row">
                    <span className="capability-icon"><iconify-icon icon="tabler:world-www"></iconify-icon></span>
                    <div className="capability-copy"><strong>{m.name}</strong><span>Custom MCP · {m.url || 'endpoint'}</span></div>
                    <div className="capability-actions">
                      <button className="button quiet small" type="button" onClick={() => setMcpModal({ idx })}>Edit</button>
                      <button className="button quiet small" type="button" onClick={() => upd({ mcpServers: (draft?.mcpServers || []).filter((_, k) => k !== idx) })}>Delete</button>
                      <button className="toggle-button" type="button" aria-pressed={m.enabled !== false}
                        onClick={() => upd({ mcpServers: (draft?.mcpServers || []).map((x, k) => (k === idx ? { ...x, enabled: !(x.enabled !== false) } : x)) })}>
                        {m.enabled !== false ? 'Enabled' : 'Disabled'}</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {!takesSkills ? (
          <section className="form-section">
            <div><h3>Skills</h3><p>What this base can take.</p></div>
            <div className="field-stack">
              <div className="capability-list">
                <div className="capability-row">
                  <span className="capability-icon"><iconify-icon icon="tabler:bulb-off"></iconify-icon></span>
                  <div className="capability-copy"><strong>{base?.name} takes no Skills</strong>
                    <span>A Skill is guidance an agent reads and scripts it runs. This base chooses among the actions its environment offers and writes no text, so guidance goes in its instructions and scripts become actions of an MCP server.</span></div>
                </div>
              </div>
            </div>
          </section>
          ) : (
          <section className="form-section">
            <div><h3>Skills</h3><p>Add Harness-specific workflows, replace inherited Skills, or disable capabilities this agent should not use.</p></div>
            <div className="field-stack">
              <div className="section-actions"><strong>{ownSkills.length + baseSkills.length} configured Skills</strong>
                {!readOnly && <button className="button small" type="button" onClick={() => setNewSkill({ name: '' })}>
                  <iconify-icon icon="tabler:plus"></iconify-icon>Add Skill</button>}</div>
              <div className="capability-list">
                {ownSkills.map(({ s, idx }) => (
                  <div key={s.id || idx} className="capability-row">
                    <span className="capability-icon"><iconify-icon icon="tabler:sparkles"></iconify-icon></span>
                    <div className="capability-copy"><strong>{s.name}</strong><span>Custom Skill</span></div>
                    <div className="capability-actions">
                      <button className="button quiet small" type="button" onClick={() => void openSkillEditor(idx)}>Edit</button>
                      <button className="button quiet small" type="button" onClick={() => upd({ skills: skills.filter((_, k) => k !== idx) })}>Delete</button>
                      <button className="toggle-button" type="button" aria-pressed={s.enabled !== false}
                        onClick={() => upd({ skills: skills.map((x, k) => (k === idx ? { ...x, enabled: !(x.enabled !== false) } : x)) })}>
                        {s.enabled !== false ? 'Enabled' : 'Disabled'}</button>
                    </div>
                  </div>
                ))}
                {baseSkills.map((b) => {
                  const n = b.name;
                  const stored = skills.find((s) => s.name === n && !isOwnSkill(s));
                  // No stored entry means the image's default applies.
                  const off = stored ? stored.enabled === false : !b.defaultEnabled;
                  return (
                    <div key={'inh-' + n} className="capability-row">
                      <span className="capability-icon"><iconify-icon icon="tabler:bulb"></iconify-icon></span>
                      <div className="capability-copy"><strong>{b.title || n}</strong>
                        <span>{b.description || 'Built in'}</span></div>
                      <div className="capability-actions">
                        {!readOnly && <button className="button quiet small" type="button" onClick={() => {
                          if (!draft) return;
                          const rest = skills.filter((s) => s.name !== n);
                          const sid = 'skl_' + crypto.randomUUID().replace(/-/g, '');
                          const files = [{ path: 'SKILL.md', content: `---\nname: ${n}\ndescription: \n---\n\n# ${n}\n\nReplaces the built-in ${n} skill.\n` }];
                          upd({ skills: [...rest, { id: sid, name: n, enabled: true, files }] });
                          setEditSkillIdx(rest.length);
                        }}>Replace</button>}
                        <button className="toggle-button" type="button" disabled={readOnly} aria-pressed={!off}
                          onClick={() => {
                            const rest = skills.filter((s) => !(s.name === n && !isOwnSkill(s)));
                            // Store an entry only when the harness disagrees with the image's
                            // default; agreeing with it stores nothing, so the harness keeps
                            // following the image as the bundled set changes.
                            const want = off;   // clicking flips it to this
                            upd({ skills: want === b.defaultEnabled ? rest
                              : [...rest, { id: 'skl_' + crypto.randomUUID().replace(/-/g, ''), name: n, enabled: want }] });
                          }}>
                          {off ? 'Disabled' : 'Enabled'}</button>
                      </div>
                    </div>
                  );
                })}
                {ownSkills.length === 0 && baseSkills.length === 0 && (
                  <div className="capability-row">
                    <span className="capability-icon"><iconify-icon icon="tabler:bulb"></iconify-icon></span>
                    <div className="capability-copy"><strong>No Skills added yet</strong>
                      <span>{srvBase && !srvBase.builtinSkillsEnumerable
                        ? `${base?.name} brings its own Skills and discovers them when it runs, so they can't be listed here. Add a Skill to give this Harness something of your own.`
                        : 'Add a Skill to give this Harness a workflow of your own.'}</span></div>
                  </div>
                )}
              </div>
            </div>
          </section>
          )}

          <section className="form-section">
            <div><h3>Plugins</h3><p>A plugin is a package of tools and Skills in the Agent Plugins format. What it brings joins this Harness's own tools and Skills on every Task.</p></div>
            <div className="field-stack">
              <div className="section-actions plugin-head"><strong>{(draft?.plugins || []).length} installed {(draft?.plugins || []).length === 1 ? 'plugin' : 'plugins'}</strong>
                {!readOnly && <button className="button small" type="button" disabled={pluginBusy} onClick={() => pluginDirRef.current?.click()}>
                  <iconify-icon icon="tabler:plus"></iconify-icon>Install from folder</button>}
                <input ref={pluginDirRef} type="file" hidden onChange={(e) => void installPluginFolder(e.target.files)}
                  {...({ webkitdirectory: '', directory: '' } as Record<string, string>)} />
              </div>
              {pluginNote && <div className={'plugin-note is-' + pluginNote.kind} role={pluginNote.kind === 'error' ? 'alert' : 'status'}>{pluginNote.text}</div>}
              <div className="capability-list plugin-list">
                {(draft?.plugins || []).map((p, idx) => {
                  const servers = p.mcpServers || [], skls = p.skills || [], skipped = p.skipped || [];
                  const pending = Boolean(p.files && p.files.length && !p.blob);
                  const m = p.manifest || {};
                  const open = pluginOpen === p.name;
                  const facts = pending
                    ? ['Installs when you save the Harness']
                    : [`${skls.length} ${skls.length === 1 ? 'Skill' : 'Skills'}`, `${servers.length} ${servers.length === 1 ? 'tool' : 'tools'}`,
                       ...(m.author?.name ? [`by ${m.author.name}`] : []), ...(m.license ? [m.license] : [])];
                  return (
                    <div key={p.name} className={'capability-row plugin-row' + (open ? ' is-open' : '') + (p.enabled === false ? ' is-off' : '')}>
                      <span className="capability-icon"><iconify-icon icon="tabler:puzzle"></iconify-icon></span>
                      <div className="capability-copy">
                        <strong className="plugin-title">{p.name}{m.version ? <span className="plugin-version">v{m.version}</span> : null}</strong>
                        <span className="plugin-desc" title={m.description || undefined}>{m.description || 'Agent Plugins package'}</span>
                        <span className="plugin-facts">{facts.join(' \u00b7 ')}
                          {!pending && skipped.length > 0 && <em className="plugin-warn">{' \u00b7 '}{skipped.length} not loaded</em>}</span>
                      </div>
                      <div className="capability-actions">
                        {!pending && <button className="button quiet small" type="button" aria-expanded={open} onClick={() => setPluginOpen(open ? null : p.name)}>
                          <iconify-icon icon={open ? 'tabler:chevron-up' : 'tabler:chevron-down'}></iconify-icon>{open ? 'Hide' : 'Details'}</button>}
                        {!pending && draft?.id && <button className="button quiet small" type="button" disabled={pluginBusy} title="This package, as installed, as a zip"
                          onClick={() => void downloadInstalledPlugin(p)}><iconify-icon icon="tabler:download"></iconify-icon>Download</button>}
                        {!readOnly && <button className="button quiet small" type="button" onClick={() => upd({ plugins: (draft?.plugins || []).filter((_, k) => k !== idx) })}>Remove</button>}
                        <button className="toggle-button" type="button" disabled={readOnly} aria-pressed={p.enabled !== false}
                          onClick={() => upd({ plugins: (draft?.plugins || []).map((x, k) => (k === idx ? { ...x, enabled: !(x.enabled !== false) } : x)) })}>
                          {p.enabled !== false ? 'Enabled' : 'Disabled'}</button>
                      </div>
                      {open && !pending && (
                        <div className="plugin-details">
                          {skls.length > 0 && <div className="plugin-group"><b>Skills</b>
                            <ul>{skls.map((s) => <li key={s.name}><code>{s.name}</code>{s.description ? <span title={s.description}>{s.description}</span> : null}</li>)}</ul></div>}
                          {servers.length > 0 && <div className="plugin-group"><b>Tools</b>
                            <ul>{servers.map((s) => <li key={s.name}><code>{s.name}</code><span>{s.transport === 'stdio' ? `runs ${s.command}${(s.args || []).length ? ' ' + (s.args || []).join(' ') : ''}` : s.url}</span></li>)}</ul></div>}
                          {skipped.length > 0 && <div className="plugin-group is-warn"><b>Not loaded</b>
                            <ul>{skipped.map((s) => <li key={s.path}><code>{s.path}</code><span>{s.reason}</span></li>)}</ul></div>}
                          {(m.homepage || m.repository || (m.keywords || []).length > 0) && (
                            <div className="plugin-group"><b>About</b>
                              <ul>{m.homepage && <li><a href={m.homepage} target="_blank" rel="noreferrer">Homepage</a></li>}
                                {m.repository && <li><a href={m.repository} target="_blank" rel="noreferrer">Source</a></li>}
                                {(m.keywords || []).length > 0 && <li><span>{(m.keywords || []).join(', ')}</span></li>}</ul></div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
                {(draft?.plugins || []).length === 0 && (
                  <div className="capability-row">
                    <span className="capability-icon"><iconify-icon icon="tabler:puzzle"></iconify-icon></span>
                    <div className="capability-copy"><strong>No plugins installed</strong>
                      <span>{readOnly
                        ? 'A built-in Harness carries no plugins. Create a Harness of your own to install packages of tools and Skills.'
                        : 'A plugin is a folder with a plugin.json at its root, tools in mcp.json and Skills under skills. Install one to add all of it at once.'}</span></div>
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="form-section">
            <div><h3>Runtime limits</h3><p>Stop Tasks that run longer or take more agent steps than expected.</p></div>
            <div className="field-stack">
              <div className="two-column-fields">
                <div className="field"><label htmlFor="hsSteps">Max steps</label>
                  <input id="hsSteps" type="number" min={1} disabled={readOnly}
                    value={draft?.maxStep ?? limits?.maxStep ?? ''}
                    onChange={(e) => upd({ maxStep: e.target.value ? Math.max(1, Number(e.target.value)) : null })} />
                  <span className="field-help">Maximum agent steps before the Task stops.{limits ? ` Empty means the default, ${limits.maxStep}.` : ''}</span></div>
                <div className="field"><label htmlFor="hsTimeout">Timeout (minutes)</label>
                  <input id="hsTimeout" type="number" min={1} disabled={readOnly}
                    value={draft?.timeoutSeconds ? Math.round(draft.timeoutSeconds / 60) : (limits ? Math.round(limits.timeoutSeconds / 60) : '')}
                    onChange={(e) => upd({ timeoutSeconds: e.target.value ? Math.max(1, Number(e.target.value)) * 60 : null })} />
                  <span className="field-help">Maximum wall-clock execution time.{limits ? ` Empty means the default, ${Math.round(limits.timeoutSeconds / 60)} minutes.` : ''}</span></div>
              </div>
            </div>
          </section>

          <section className="form-section">
            <div><h3>Request headers</h3><p>Forward approved Task request context to MCP servers used by this Harness.</p></div>
            <div className="field-stack">
              <div className="section-actions"><strong>Dynamic header mappings</strong>
                {!readOnly && <button className="button small" type="button" onClick={() => upd({ additionalHeaders: [...(draft?.additionalHeaders || []), ''] })}><iconify-icon icon="tabler:plus"></iconify-icon>Add header</button>}</div>
              <div>
                {(draft?.additionalHeaders || []).map((h, idx) => (
                  <div key={idx} className="header-row">
                    <div className="field"><label>Header name</label>
                      <input value={h} placeholder="X-App-JWT" onChange={(e) => upd({ additionalHeaders: (draft?.additionalHeaders || []).map((x, k) => (k === idx ? e.target.value : x)) })} /></div>
                    <div className="field"><label>Value reference</label>
                      <input value={h ? `$headers.${h}` : ''} readOnly /></div>
                    <button className="icon-button" type="button" aria-label="Remove header"
                      onClick={() => upd({ additionalHeaders: (draft?.additionalHeaders || []).filter((_, k) => k !== idx) })}><iconify-icon icon="tabler:trash"></iconify-icon></button>
                  </div>
                ))}
                {!(draft?.additionalHeaders || []).length && <span className="field-help">No headers declared.</span>}
              </div>
              <span className="field-help">Values are resolved from the incoming Task request when the Harness calls an MCP server. Store credentials in a trusted secret manager; never enter literal secrets here.</span>
            </div>
          </section>

          <section className="form-section">
            <div><h3>Environment</h3><p>Variables every Task's shell and tools start with. Put a secret behind a request header or a stored secret, never as a literal; the agent never sees the value in its prompt, and anything it prints is redacted from the record.</p></div>
            <div className="field-stack">
              <div className="section-actions"><strong>{Object.keys(draft?.env || {}).length} variables</strong>
                {!readOnly && <button className="button small" type="button" onClick={() => setEnvRows((r) => [...r, { name: '', value: '' }])}><iconify-icon icon="tabler:plus"></iconify-icon>Add variable</button>}</div>
              <div>
                {envRows.map((row, idx) => (
                  <div key={idx} className="header-row">
                    <div className="field"><label>Name</label>
                      <input value={row.name} placeholder="API_KEY" disabled={readOnly} onChange={(e) => setEnvRow(idx, { name: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_') })} /></div>
                    <div className="field"><label>Value or reference</label>
                      <input value={row.value} placeholder="$headers.X-Api-Key or vault:my-secret" disabled={readOnly} onChange={(e) => setEnvRow(idx, { value: e.target.value })} /></div>
                    {!readOnly && <button className="icon-button" type="button" aria-label="Remove variable" onClick={() => dropEnvRow(idx)}><iconify-icon icon="tabler:trash"></iconify-icon></button>}
                  </div>
                ))}
                {!envRows.length && <span className="field-help">No variables set.</span>}
              </div>
              <span className="field-help">A reference like $headers.X-Api-Key takes the header a Task request sends (declare it above); vault:name takes a secret stored with the service. A shell in the Task reads the variable by name.</span>
            </div>
          </section>

          {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Save failed</strong>{err}</div></div>}
        </form>

        {/* The action bar lives OUTSIDE the form on purpose: the form is capped at 980px, and
            the bar must span the settings pane edge to edge, pinned to its bottom. The submit
            button still drives the form via the form attribute. */}
          {!readOnly && (
            <div className="settings-form-footer settings-footer-sticky">
              <button className="button danger" type="button" onClick={() => setConfirmDelete(true)}>Delete Harness</button>
              <span className="settings-footer-spacer" />
              {dirty && (
                <button className="button" type="button" disabled={busy} onClick={() => { setDraft(saved); setEnvRows(rowsOf(saved?.env)); }}>Discard Changes</button>
              )}
              {dirty ? (
                <button className="button primary" type="submit" form="hs-form" disabled={busy}>{busy ? 'Saving…' : 'Save Changes'}</button>
              ) : (<>
                {SELF_HOSTED && (
                  <button className="button" type="button" onClick={() => setUploading(true)}>
                    <iconify-icon icon="tabler:cloud-upload"></iconify-icon>Upload to Cloud</button>
                )}
                <button className="button primary" type="button"
                  onClick={() => go('tasks')}>
                  <iconify-icon icon="tabler:list-details"></iconify-icon>Run Task</button>
              </>)}
            </div>
          )}
          {/* Built-ins have nothing to save, but they still need somewhere to act — same bar,
              same corner, so the action never moves depending on which harness you opened. */}
          {readOnly && (
            <div className="settings-form-footer settings-footer-sticky">
              <span className="settings-footer-spacer" />
              <button className="button" type="button" disabled={busy} onClick={async () => {
                setBusy(true);
                try {
                  const c = await createCustom({ name: `${oob!.name} (custom)`, base: oob!.id, defaultModel: oobDefaultModel(oob), systemPrompt: oob!.systemPrompt });
                  router.push(`/harnesses/${encodeURIComponent(c.id)}`);
                } finally { setBusy(false); }
              }}><iconify-icon icon="tabler:git-fork"></iconify-icon>Fork and Customize</button>
              <button className="button primary" type="button"
                onClick={() => go('tasks')}>
                <iconify-icon icon="tabler:list-details"></iconify-icon>Run Task</button>
            </div>
          )}
      </div>

      {uploading && draft && (
        <CloudUploadDialog
          items={[{ id: draft.id, name: draft.name, uploaded: !!cloud?.uploaded,
                    includes: ['instructions', draft.defaultModel, (draft.skills || []).length ? `${draft.skills.length} skill${draft.skills.length === 1 ? '' : 's'}` : '',
                               (draft.mcpServers || []).length ? `${draft.mcpServers.length} MCP server${draft.mcpServers.length === 1 ? '' : 's'}` : ''].filter(Boolean).join(' · ') }]}
          onClose={() => setUploading(false)}
          onDone={() => { statusOne(draft.id).then(setCloud).catch(() => null); }} />
      )}
      {editSkillIdx !== null && draft?.skills?.[editSkillIdx] && (
        <SkillEditor skill={draft.skills[editSkillIdx]}
          onClose={() => setEditSkillIdx(null)}
          onSave={(files) => {
            upd({ skills: skills.map((x, k) => (k === editSkillIdx ? { ...x, files, blob: undefined } : x)) });
            setEditSkillIdx(null);
          }} />
      )}
      {newSkill && draft && (
        <SkillEditor skill={{ name: newSkill.name, files: [{ path: 'SKILL.md',
            content: `---\nname: \ndescription: \n---\n` }] }}
          nameEditable onName={(n) => setNewSkill({ name: n })}
          onClose={() => setNewSkill(null)}
          onSave={(files) => {
            const nm = newSkill.name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
            if (!nm) { setErr('Give the skill a name (kebab-case) at the top of the editor.'); return; }
            const sid = 'skl_' + crypto.randomUUID().replace(/-/g, '');
            upd({ skills: [...skills, { id: sid, name: nm, enabled: true, files }] });
            setNewSkill(null);
          }} />
      )}
      {mcpModal && draft && (
        <McpModal server={mcpModal.idx != null ? (draft.mcpServers[mcpModal.idx] as McpServer) : null}
          declaredHeaders={(draft.additionalHeaders || []).filter(Boolean)}
          onClose={() => setMcpModal(null)}
          onSave={async (srv) => {
            let auth = srv.auth;
            if (auth && !auth.startsWith('vault:') && !auth.startsWith('$headers.')) {
              try { auth = await storeMcpSecret(srv.name, auth); } catch { /* keep literal; gateway re-vaults */ }
            }
            const entry = { ...srv, auth };
            upd({ mcpServers: mcpModal.idx != null ? draft.mcpServers.map((x, k) => (k === mcpModal.idx ? entry : x)) : [...draft.mcpServers, entry] });
            setMcpModal(null);
          }} />
      )}
      {confirmDelete && draft && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header"><div><h2>Delete {draft.name}?</h2><p>Removes this Harness configuration. Existing task history stays readable.</p></div></div>
            <div className="modal-body">
              <div className="modal-actions">
                <button className="button" type="button" onClick={() => setConfirmDelete(false)}>Cancel</button>
                <button className="button primary" type="button" style={{ background: 'var(--red)', borderColor: 'var(--red)' }}
                  onClick={async () => { await deleteCustom(draft.id); go('list'); }}>Delete</button>
              </div>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
