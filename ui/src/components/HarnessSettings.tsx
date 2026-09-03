'use client';
// Harness Settings, the ONE place persistent harness configuration is edited (per the 2026-07-17
// IA review): General → Default model → Agent instructions → Tools → Skills → Runtime limits →
// Request headers, one Save. Built-in harnesses render read-only with a Clone action.
// Reuses the battle-tested SkillEditor + McpModal from the workbench.
import { useEffect, useMemo, useState } from 'react';
import { SkelPage } from '@/components/Skel';
import { useRouter } from 'next/navigation';
import {
  OOB, oobById, oobDefaultModel, oobModels, useModelCatalog, modelAvailable, useBases, getCustom, saveCustom, deleteCustom, createCustom, getSkillFiles, storeMcpSecret,
  type CustomHarness, type OobHarness,
} from '@/lib/harness';
import { HarnessLogo } from '@/components/HarnessLogo';
import { CopyId } from '@/components/CopyId';
import { SkillEditor, McpModal, type McpServer } from '@/components/HarnessEditors';
import { fetchTraceWindow, statsFor, p95Of, avgCreditsOf, type TraceCard } from '@/lib/revamp-data';

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
  const [editSkillIdx, setEditSkillIdx] = useState<number | null>(null);
  const [mcpModal, setMcpModal] = useState<{ idx: number | null } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Draft of a NEW skill being created in the SkillEditor popup (name edited in the same popup).
  const [newSkill, setNewSkill] = useState<{ name: string } | null>(null);
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
  const baseSkills = (srvBase?.builtinSkills || []).filter((b) => !ownSkills.some(({ s }) => s.name === b.name));
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

        <form className="settings-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <div className="settings-form-head">
            <div><h2>Harness Settings</h2><p>Configure the instructions, capabilities, and execution limits inherited by every Task on this Harness.</p></div>
            <div className="header-actions"><span className="save-state">{readOnly ? 'Built-in · read-only' : dirty ? 'Unsaved changes' : 'No unsaved changes'}</span></div>
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
                      {m}{modelAvailable((oob?.backend || oobById(draft?.base || '')?.backend) || '', m) ? '' : ' (no provider)'}
                    </option>
                  ))}
                </select>
                <span className="field-help">Tasks may choose another compatible model at runtime.</span></div>
            </div>
          </section>

          <section className="form-section">
            <div><h3>Agent instructions</h3><p>Persistent role, conventions, constraints, and output contract loaded on every Task.</p></div>
            <div className="field-stack">
              <div className="field"><label htmlFor="hsInstructions">{['codex', 'hermes'].includes(base?.id || draft?.base || '') ? 'AGENTS.md' : 'CLAUDE.md'}</label>
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

          <section className="form-section">
            <div><h3>Runtime limits</h3><p>Stop Tasks that run longer or take more agent steps than expected.</p></div>
            <div className="field-stack">
              <div className="two-column-fields">
                <div className="field"><label htmlFor="hsSteps">Max steps</label>
                  <input id="hsSteps" type="number" min={1} placeholder="400" disabled={readOnly}
                    value={draft?.maxStep ?? ''} onChange={(e) => upd({ maxStep: e.target.value ? Math.max(1, Number(e.target.value)) : null })} />
                  <span className="field-help">Maximum agent steps before the Task stops.</span></div>
                <div className="field"><label htmlFor="hsTimeout">Timeout (minutes)</label>
                  <input id="hsTimeout" type="number" min={1} placeholder="120" disabled={readOnly}
                    value={draft?.timeoutSeconds ? Math.round(draft.timeoutSeconds / 60) : ''}
                    onChange={(e) => upd({ timeoutSeconds: e.target.value ? Math.max(1, Number(e.target.value)) * 60 : null })} />
                  <span className="field-help">Maximum wall-clock execution time.</span></div>
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

          {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Save failed</strong>{err}</div></div>}
          {!readOnly && (
            <div className="settings-form-footer settings-footer-sticky">
              <button className="button danger" type="button" onClick={() => setConfirmDelete(true)}>Delete Harness</button>
              <span className="settings-footer-spacer" />
              {dirty && (
                <button className="button" type="button" disabled={busy} onClick={() => setDraft(saved)}>Discard Changes</button>
              )}
              {dirty ? (
                <button className="button primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save Changes'}</button>
              ) : (
                <button className="button primary" type="button"
                  onClick={() => go('tasks')}>
                  <iconify-icon icon="tabler:list-details"></iconify-icon>Run Task</button>
              )}
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
        </form>
      </div>

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
