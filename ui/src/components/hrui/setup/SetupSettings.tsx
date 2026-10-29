'use client';
// A setup's Settings tab (docs/uxuidesign/console-91: settingsHtml, layerStack, field, partRows,
// savebarHtml, setDirty). One layer open at a time, listed in Richard's order (2026-10-18):
// Instructions, Agent harness (the agent harness, then its model), Capabilities, Environment &
// limits. The layers list takes the task list's column and the open layer the task's, each under a
// 56 px bar (the open layer's carries Save). The layer is in the address (?layer=), so a brick of the
// Agent stack opens it. Delete setup is the last row: under the layers in the rail, at the foot of the
// open layer where the rail folds to chips (one of the two is drawn at any width).
//
// Two kinds of change, as the design draws them: fields edit a draft that Save writes (name,
// model, thinking, instructions, tools, MCP servers, variables, headers, limits), while skills,
// plugins and the environment apply at once ("Plugin and skill changes apply right away"). Each
// Capabilities tab counts the ones on of one of setupParts.ts's lists (setupPlugins, setupSkills,
// setupTools); Skills and Tools list it, Plugins lists the workspace's connected plugins with a switch
// each, beside what the setup includes (PluginSwitches.tsx); the layers list's Capabilities line counts
// what a person added, as the Agent stack and Studio's card do. Under the layers: Delete setup, and
// Duplicate beside it.
// (Deploy to Cloud is the page bar's, beside Connect your app: DeployCloud.tsx.)
// Every value, list, default and ceiling shown is read from the services: the setup's record, the
// bases document (tools, built-in skills, thinking levels, runtime defaults), the model catalog,
// and the workspace's plugins and environments. What is not read yet shows nothing.
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  getCustom, saveCustom, getSkillFiles, pluginSchemas, getHarnessPlugs, setHarnessPlugs, PLUGS_ENTRY_ID,
  oobById, oobDefaultModel, oobModels, modelAvailability, availabilityNote, useBases, useModelCatalogRead, useRuntimeDefaults,
  type CustomHarness, type HarnessPlugin, type HarnessPlugs, type McpServer,
} from '@/lib/harness';
import { listEnvironments, type Environment } from '@/lib/environments';
import { useModelProviders } from '@/lib/providers';
import { useWorkspace } from '@/lib/workspace';
import { harnessLogoSrc } from '@/components/HarnessLogo';
import { readSkillUpload } from '@/components/HarnessEditors';
import { partIcon } from '../bricks';
import { tabKeys } from '../tabKeys';
import { toast } from '../toast';
import { ConfirmSheet } from '../Sheet';
import { McpSheet, authFor, newMcpId } from '../mcp/McpSheet';
import { AddPluginSheet } from '../ext/AddPluginSheet';
import { usePlugins } from '../ext/pluginParts';
import type { SetupRow } from '../setups';
import {
  SET_LAYERS, LAYER_KEYS, layerOf, isCapTab, cfgOf, dirtyKeys, draftOf, keepDraft, isServiceEntry, storeRef, mdName, plain, plural, cutWords, addedLine,
  type Cfg, type CfgKey, type CapTab, type LayerKey,
} from './settingsModel';
import {
  countOn, isOwnSkill, setupPlugins, setupSkills, setupTools,
} from './setupParts';
import { PluginSwitches, pluginLines, type PluginsIn } from './PluginSwitches';
import { openNewSetup } from '../start/open';
import { SkillSheet, skillDraft, skillFiles, skillSlug, splitSkillMd, type SkillDraft } from './SkillSheet';
import {
  DeleteSetupSheet, EnvPickSheet, PackageSheet, DuplicateSheet,
} from './settingsSheets';

type Skill = CustomHarness['skills'][number];
const isOwn = isOwnSkill;
const idOf = (s: Skill) => s.id || s.name;
const newSkillId = () => 'skl_' + crypto.randomUUID().replace(/-/g, '');
/** What each thinking level is called; the levels themselves are the server's, per model. */
const THINKING: Record<string, string> = { none: 'Off', minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high' };
/** the input each validated field is, so a refused Save can point at it */
const FIELD_OF: Partial<Record<CfgKey, string>> = { name: 'setName', turns: 'setTurns', mins: 'setMins' };
const PLUGIN_PACKAGE_MAX = 16 * 1024 * 1024;   // the gateway's own cap on one package
const fmtMb = (n: number) => `${(n / 1048576).toFixed(n < 10485760 ? 1 : 0)} MB`;

const LOCK = <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>;
const COPY = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h8" /></svg>;

/** Copy the Harness ID: the clipboard when the browser allows it, else the person is told how. */
async function copyId(hid: string) {
  try { await navigator.clipboard.writeText(hid); toast('Copied'); }
  catch { toast('Text selected. Press Cmd or Ctrl + C.'); }
}
const PLUS = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>;
const X = <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>;

const brick = (on: boolean) => ({ __html: partIcon(on ? 'built' : 'empty', 'backend') });
/** An address that may break after each slash (the design's urlBreaks). */
const urlBreaks = (u: string) => u.split('/').flatMap((p, i, a) => (i < a.length - 1 ? [p + '/', <wbr key={i} />] : [p]));
/** Capabilities' tabs: the kind, its name, its brick's colour */
const CAP_TABS: [CapTab, string, string][] = [['plugin', 'Plugins', 'plugin'], ['skill', 'Skills', 'skill'], ['tool', 'Tools', 'mcp']];
const CAP_WORD: Record<CapTab, string> = { plugin: 'plugins', skill: 'skills', tool: 'tools' };
/** the layers' keys, in the list's order (the arrow keys move through them) */
const LAYER_ORDER = SET_LAYERS.map(([k]) => k);

type Pop =
  | { k: 'mcp'; i: number | null } | { k: 'delmcp'; i: number } | { k: 'plugin' } | { k: 'env' } | { k: 'pkg'; name: string }
  | { k: 'skill'; ed: SkillDraft } | { k: 'delskill'; s: Skill } | { k: 'del' } | { k: 'dup' };

export function SetupSettings({ r, onSaved, layer, cap, onLayer, onDirty, onNewTask }: {
  r: SetupRow;
  /** the record changed on the server: read the setup again */
  onSaved: () => void;
  /** the open layer, from the address */
  layer?: string | null;
  /** Capabilities' open tab, from the address */
  cap?: string | null;
  onLayer: (k: LayerKey, cap?: CapTab) => void;
  onDirty?: (dirty: boolean) => void;
  /** after a save: a new task on the saved setup (the Tasks tab, its New task) */
  onNewTask?: () => void;
}) {
  const router = useRouter();
  const [rec, setRec] = useState<CustomHarness>(r.h);
  useEffect(() => { setRec(r.h); }, [r.h]);
  const id = rec.id;

  const catalog = useModelCatalogRead();   // the server's model list: the picker offers nothing else
  const providers = useModelProviders();
  const bases = useBases();
  const limits = useRuntimeDefaults();
  const srv = bases?.[oobById(rec.base)?.id || rec.base] || null;
  const oob = oobById(rec.base);
  // ── the draft ──────────────────────────────────────────────────────────────────────────────
  // a setup with no model of its own keeps none ('' : the server runs it on its harness's default)
  const base = useMemo(() => cfgOf(rec), [rec]);
  const [patch, setPatch] = useState<Partial<Cfg>>(() => draftOf(r.h.id));
  const c: Cfg = { ...base, ...patch };
  const changed = dirtyKeys(patch, base);
  const dirty = changed.length > 0;
  const dirtyL = (k: LayerKey) => LAYER_KEYS[k].some((x) => changed.includes(x));
  const [justSaved, setJustSaved] = useState(false);
  const onDirtyRef = useRef(onDirty);
  onDirtyRef.current = onDirty;
  useEffect(() => { keepDraft(id, patch, dirty); onDirtyRef.current?.(dirty); }, [id, patch, dirty]);

  // the field a refused Save points at: marked, and focused once its layer is open
  const [bad, setBad] = useState('');
  const focusNext = useRef('');      // a field to focus once it is drawn (a refused field, a new row)
  const point = (fid: string) => { focusNext.current = fid; setBad(fid); };
  const set = <K extends CfgKey>(k: K, v: Cfg[K]) => {
    setPatch((p) => ({ ...p, [k]: v }));
    setJustSaved(false);
    if (bad && bad === FIELD_OF[k]) setBad('');
  };

  const Ly: LayerKey = layerOf(layer);
  const layerName = SET_LAYERS.find(([k]) => k === Ly)![1];
  useEffect(() => {
    const want = focusNext.current;
    if (!want) return;
    const el = document.getElementById(want);
    if (el) { el.focus(); focusNext.current = ''; }
  }, [bad, Ly, c.vars.length, c.headers.length]);

  const [busy, setBusy] = useState<'' | 'save' | 'apply'>('');
  const [pop, setPop] = useState<Pop | null>(null);

  // ── what the services say around the record ──────────────────────────────────────────────
  // a list that could not be read is not an empty one: it stays unread, and says so with Try again
  const [envs, setEnvs] = useState<Environment[] | null>(null);
  const [envsFailed, setEnvsFailed] = useState(false);
  const [envsRead, setEnvsRead] = useState(0);
  useEffect(() => {
    let alive = true;
    setEnvsFailed(false);
    listEnvironments().then((e) => { if (alive) setEnvs(e); }).catch(() => { if (alive) setEnvsFailed(true); });
    return () => { alive = false; };
  }, [envsRead]);
  const readEnvs = () => setEnvsRead((n) => n + 1);
  const { current: wsCurrent, defaultId: wsDefault } = useWorkspace();
  const wsId = wsCurrent.id || wsDefault;
  // the workspace's plugins, each with its state here (lib/plugs, read again after one is connected)
  const ws = usePlugins(wsId, { counts: false });
  // the record says whether it has a plugins binding at all: asking for an absent one is a 404
  const hasPlugs = (rec.mcpServers || []).some((m) => m.id === PLUGS_ENTRY_ID);
  const [included, setIncluded] = useState<HarnessPlugs | null | undefined>(undefined);
  const [plugsLost, setPlugsLost] = useState(false);   // the binding could not be read
  const [plugsRead, setPlugsRead] = useState(0);
  useEffect(() => {
    setPlugsLost(false);
    if (!hasPlugs) { setIncluded(null); return; }
    let alive = true;
    getHarnessPlugs(id).then((p) => { if (alive) setIncluded(p); }).catch(() => { if (alive) { setIncluded(null); setPlugsLost(true); } });
    return () => { alive = false; };
  }, [id, hasPlugs, plugsRead]);

  // ── changes that apply at once ─────────────────────────────────────────────────────────────
  /** Write one change on the newest record (never the draft), then read the setup again. */
  async function apply(change: (h: CustomHarness) => Partial<CustomHarness>, fallback: string): Promise<CustomHarness | null> {
    setBusy('apply');
    try {
      const h = await getCustom(id);
      if (!h) throw new Error('');
      const s = await saveCustom({ ...h, ...change(h) });
      setRec(s); onSaved();
      return s;
    } catch (e) { toast(plain(e, fallback)); return null; }
    finally { setBusy(''); }
  }

  const plugs = included?.plugs || [];
  /** Set the plugins the setup includes (none left detaches the binding), then read the record again. */
  async function setPlugs(next: string[]): Promise<boolean> {
    setBusy('apply');
    try {
      setIncluded(await setHarnessPlugs(id, next));
      // including plugins adds or removes the binding on the record: read it again
      const h = await getCustom(id);
      if (h) setRec(h);
      onSaved();
      return true;
    } catch (e) { toast(plain(e, 'The plugins were not changed. Try again.')); return false; }
    finally { setBusy(''); }
  }

  async function pickEnv(envId: string) {
    const next = rec.environment === envId ? '' : envId;
    const s = await apply(() => ({ environment: next }), 'The environment was not changed. Try again.');
    if (s && next) setPop(null);
  }

  const dirRef = useRef<HTMLInputElement | null>(null);
  // A folder picked as a plugin package: every file under it, the manifest read first so a wrong
  // folder is refused before anything is sent. The server checks the rest on save.
  async function installFolder(list: File[]) {
    if (!list.length) return;
    try {
      const total = list.reduce((n, f) => n + f.size, 0);
      if (total > PLUGIN_PACKAGE_MAX) throw new Error(`That folder is ${fmtMb(total)}; a plugin package can be at most ${fmtMb(PLUGIN_PACKAGE_MAX)}.`);
      const files: NonNullable<HarnessPlugin['files']> = [];
      for (const f of list) {
        const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
        const path = rel.includes('/') ? rel.slice(rel.indexOf('/') + 1) : rel;
        if (!path || path.split('/').some((seg) => seg === 'node_modules' || seg === '.git')) continue;
        files.push(await readSkillUpload(f, path));
      }
      const mf = files.find((f) => f.path === 'plugin.json');
      if (!mf || mf.content === undefined) throw new Error('That folder has no plugin.json at its root, so it is not a plugin package.');
      let manifest: HarnessPlugin['manifest'] & { $schema?: string } = {};
      try { manifest = JSON.parse(mf.content) as typeof manifest; } catch { throw new Error('Its plugin.json is not valid JSON.'); }
      const name = String(manifest?.name || '');
      if (!name) throw new Error('Its plugin.json names no plugin.');
      if ((rec.plugins || []).some((p) => p.name === name)) throw new Error(`A plugin named ${name} is already installed on this setup.`);
      const schemas = await pluginSchemas();
      if (schemas.length && !schemas.includes(String(manifest.$schema || ''))) {
        throw new Error(manifest.$schema ? `This package targets ${manifest.$schema}, which is not installed here (it installs ${schemas.join(', ')}).` : 'Its plugin.json names no $schema, which every package must.');
      }
      const s = await apply((h) => ({ plugins: [...(h.plugins || []), { name, enabled: true, files, manifest }] }), 'The plugin was not installed. Try again.');
      if (!s) return;
      const left = (s.plugins || []).find((p) => p.name === name)?.skipped?.length || 0;
      setPop(null);
      toast(left ? `Saved. ${name}: ${plural(left, 'part')} not loaded. Open Manage to see which.` : `${name} is installed.`);
    } catch (e) { toast(e instanceof Error ? e.message : 'The plugin was not installed. Try again.'); }
  }

  // skills: this setup's own, and the ones bundled with every agent harness (listed by setupSkills)
  const skills = rec.skills || [];
  const ownSkills = skills.filter(isOwn);
  const takesSkills = srv?.takesSkills !== false;
  const builtinOff = (b: { name: string; defaultEnabled: boolean }) => {
    const stored = skills.find((s) => s.name === b.name && !isOwn(s));
    return stored ? stored.enabled === false : !b.defaultEnabled;
  };
  function toggleBuiltin(b: { name: string; defaultEnabled: boolean }) {
    const want = builtinOff(b);   // a click turns it to this
    // an entry is stored only where the setup disagrees with the default
    void apply((h) => {
      const rest = (h.skills || []).filter((s) => !(s.name === b.name && !isOwn(s)));
      return { skills: want === b.defaultEnabled ? rest : [...rest, { id: newSkillId(), name: b.name, enabled: want }] };
    }, 'The skill was not changed. Try again.');
  }
  async function openSkill(s: Skill) {
    let files = s.files || [];
    if (!files.length && s.blob) {
      try { files = await getSkillFiles(id, idOf(s)); } catch { toast('The skill could not be opened. Try again.'); return; }
    }
    const content = (s as { content?: string }).content;
    if (!files.length && content) files = [{ path: 'SKILL.md', content }];
    setPop({ k: 'skill', ed: skillDraft(idOf(s), s.name, files) });
  }
  async function saveSkill(e: SkillDraft) {
    const nm = skillSlug(e.name);
    if (!nm) { toast('Give the skill a name with letters or numbers.'); return; }
    const s = await apply((h) => {
      const list = h.skills || [];
      if (list.some((x) => isOwn(x) && idOf(x) !== e.id && skillSlug(x.name) === nm)) throw new Error(`A skill named ${nm} already exists.`);
      const files = skillFiles(e, nm);
      return { skills: e.id
        ? list.map((x) => (idOf(x) === e.id ? { id: x.id, name: nm, enabled: x.enabled !== false, files } : x))
        // a skill of its own under a built-in's name replaces that built-in, and its switch goes
        : [...list.filter((x) => !(x.name === nm && !isOwn(x))), { id: newSkillId(), name: nm, enabled: true, files }] };
    }, 'The skill was not saved. Check SKILL.md and try again.');
    if (!s) return;
    setPop(null);
    toast(e.id ? 'Skill saved.' : 'Skill created.');
  }

  // ── Save and Discard ───────────────────────────────────────────────────────────────────────
  async function save() {
    if (busy) return;
    if (!c.name.trim()) { onLayer('harness'); point('setName'); toast('Give the setup a name.'); return; }
    const badL = (fid: string, msg: string) => { onLayer('runtime'); point(fid); toast(msg); };
    const turns = c.turns.trim(), mins = c.mins.trim();
    if (turns && !(/^\d+$/.test(turns) && +turns >= 1)) { badL('setTurns', 'Max steps must be a whole number, 1 or more.'); return; }
    if (mins && !(+mins >= 1)) { badL('setMins', 'Timeout must be 1 minute or more.'); return; }
    setBusy('save');
    const has = (k: CfgKey) => changed.includes(k);
    try {
      const h = await getCustom(id);
      if (!h) throw new Error('');
      // only what was changed here goes over the newest record
      const next: CustomHarness = { ...h };
      if (has('name')) next.name = c.name.trim();
      if (has('model')) next.defaultModel = c.model;
      if (has('thinking')) next.reasoningEffort = c.thinking;
      if (has('agentsMd')) next.systemPrompt = c.agentsMd;
      if (has('turns')) next.maxStep = turns ? parseInt(turns, 10) : null;
      if (has('mins')) next.timeoutSeconds = mins ? Math.max(1, Math.round(+mins)) * 60 : null;
      if (has('tools')) next.disabledTools = c.tools;
      if (has('mcp')) next.mcpServers = [...(h.mcpServers || []).filter(isServiceEntry), ...c.mcp.filter((m) => m.name || m.url)];
      if (has('vars')) next.env = Object.fromEntries(c.vars.filter((v) => v.name.trim()).map((v) => [v.name.trim(), storeRef(v.value.trim())]));
      if (has('headers')) next.additionalHeaders = c.headers.map((x) => x.trim()).filter(Boolean);
      setRec(await saveCustom(next));
      setPatch({});
      setJustSaved(true); toast('Saved.');
      onSaved();
    } catch (e) { toast(plain(e, 'The changes were not saved. Try again.')); }
    finally { setBusy(''); }
  }
  const discard = () => { setPatch({}); setBad(''); toast('Changes discarded'); };

  // ── what each layer says about itself ──────────────────────────────────────────────────────
  // Each tab lists everything the setup can use, built-ins included (scope 'all'), and counts the
  // ones on; the layers list's line counts only what a person added, as the Agent stack beside it
  // does (scope 'added'). The tools as this draft has them (a tool turned off, an MCP server added,
  // before Save).
  const draftRec = { ...rec, disabledTools: c.tools, mcpServers: [...(rec.mcpServers || []).filter(isServiceEntry), ...c.mcp] };
  const toolList = setupTools(draftRec, srv, 'all');
  const toolsOn = countOn(toolList);
  const skillList = setupSkills(rec, srv, 'all');
  const words = c.agentsMd.trim().split(/\s+/).filter(Boolean).length;
  const envX = rec.environment ? envs?.find((e) => e.id === rec.environment) || null : null;
  const pkgs = rec.plugins || [];
  const skillsOn = countOn(skillList);
  // This setup's plugins (setupPlugins.ts), the list every count reads: the workspace plugins it
  // includes, then installed packages. A binding not read yet (or that could not be read) counts as one.
  const mine = setupPlugins(rec, plugsLost || included === undefined ? undefined : included, 'all');
  // what the Plugins tab lists (PluginSwitches.tsx): the workspace's connected plugins, each with its
  // switch, and what this setup includes besides
  const plugIn: PluginsIn = {
    plugs: ws.plugs,
    binding: plugsLost || included === undefined ? undefined : plugs,
    packages: pkgs.map((p) => ({ name: p.name, on: p.enabled !== false, desc: p.manifest?.description || '', left: (p.skipped || []).length })),
  };
  const thinkingLabel = (v: string) => THINKING[v] || v;

  // Capabilities' open tab: the address's, else the first kind it has (plugins, then skills), else tools
  const plugCount = countOn(mine);
  // an agent harness that takes no skills has no Skills tab (one with skills of its own from before
  // keeps it, so they can be deleted)
  const skillTab = takesSkills || ownSkills.length > 0;
  const capTabs = CAP_TABS.filter(([k]) => k !== 'skill' || skillTab);
  const capT: CapTab = isCapTab(cap) && (cap !== 'skill' || skillTab) ? cap : plugCount ? 'plugin' : ownSkills.length ? 'skill' : 'tool';
  const capN: Record<CapTab, number> = { plugin: plugCount, skill: skillsOn, tool: toolsOn };
  const capRows: Record<CapTab, number> = { plugin: pluginLines(plugIn).length, skill: skillList.length, tool: toolList.length };
  const [capQ, setCapQ] = useState('');
  const pickCap = (k: CapTab) => { setCapQ(''); onLayer('caps', k); };
  const capQl = capQ.trim().toLowerCase();
  let capHits = 0;
  /** a row of the open tab is shown when the search finds it (always, with no search) */
  const found = (...text: (string | null | undefined)[]) => {
    const hit = !capQl || text.some((t) => (t || '').toLowerCase().includes(capQl));
    if (hit) capHits++;
    return hit;
  };
  const capEmpty = (fam: string, say: string) => (
    <div className="empty-list es cap-empty"><span className="es-art" aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon('empty', fam) }} /><span>{say}</span></div>
  );
  const SUM: Record<LayerKey, string> = {
    instructions: plural(words, 'word'),
    harness: [r.baseName, c.model, c.thinking ? thinkingLabel(c.thinking) : ''].filter(Boolean).join(' · '),
    caps: addedLine({ plugin: plugCount, skill: countOn(setupSkills(rec, srv, 'added')), tool: countOn(setupTools(draftRec, srv, 'added')) }),
    runtime: [envX?.name || '', c.vars.length ? plural(c.vars.length, 'variable') : '', c.headers.length ? plural(c.headers.length, 'header') : '',
      c.turns ? c.turns + ' steps' : '', c.mins ? c.mins + ' min' : ''].filter(Boolean).join(' · ') || 'Defaults',
  };
  // a layer says something about itself only where a person needs it (Richard 10-19): Capabilities
  // mixes changes that apply at once with ones Save writes
  const DESC: Partial<Record<LayerKey, ReactNode>> = {
    caps: 'Plugin and skill changes apply right away.',
  };

  // ── the pieces the layers are made of (plain functions, so a field keeps its focus) ──────────
  const field = (fid: string, label: ReactNode, ctrl: ReactNode, help?: ReactNode) => (
    <div className="set-f"><label htmlFor={fid}>{label}</label>{ctrl}{help ? <p className="set-help">{help}</p> : null}</div>
  );
  const sub = (title: string, note: ReactNode, act: ReactNode, body: ReactNode) => (
    <div className="lg-sub" key={title}><div className="lg-sub-h"><h3>{title}{note ? <span className="muted">{note}</span> : null}</h3>{act}</div>{body}</div>
  );
  const tog = (on: boolean, label: string, onClick: () => void, disabled = false) => (
    <button type="button" className={`tog${on ? ' on' : ''}`} aria-pressed={on} aria-label={label} disabled={disabled} onClick={onClick}><i />{on ? 'On' : 'Off'}</button>
  );
  const addBtn = (label: string, onClick: () => void, disabled = false) => (
    <button type="button" className="btn small" disabled={disabled} onClick={onClick}>{PLUS}{label}</button>
  );
  const inv = (fid: string) => (bad === fid ? true : undefined);

  // ── the model's options and thinking levels ────────────────────────────────────────────────
  const keyOf = (m: string) => !!providers.connectionFor(m);
  const modelIds = oobModels(oob);
  // the models that can run now, and the one chosen (said when it has no provider); one that can't is
  // left out, never listed disabled (Richard 10-19). A setup with no model of its own has the harness
  // default as its choice: '' on the record, and the server runs it on the catalog's default.
  const modelList = [...(c.model && !modelIds.includes(c.model) ? [c.model] : []),
    ...modelIds.filter((m) => m === c.model || modelAvailability(oob?.backend, m) === 'yes')];
  const harnessDefault = oobDefaultModel(oob);
  const levels = srv?.models.find((m) => m.id === c.model)?.reasoning || [];
  const keptLevel = !!c.thinking && !levels.includes(c.thinking);

  const logo = harnessLogoSrc(rec.base);
  const BODY: Record<LayerKey, ReactNode> = {
    // the agent harness first, then its model (the models are this harness's own, so they follow it)
    harness: <>
      {/* the Harness ID first, read only: what a task names to reach this setup (it left the page's bar) */}
      <div className="set-f">
        <span className="set-lb" id="setHidL">Harness ID</span>
        <div className="set-ro set-hid" role="group" aria-labelledby="setHidL">
          <code className="mono" title={id}>{id}</code>
          <button type="button" className="icon-btn xs" aria-label="Copy Harness ID" title="Copy Harness ID" onClick={() => void copyId(id)}>{COPY}</button>
        </div>
      </div>
      {field('setName', 'Name', <input id="setName" className="set-in" value={c.name} aria-invalid={inv('setName')} onChange={(e) => set('name', e.target.value)} />)}
      {field('setHarness', 'Agent harness',
        <div className="set-ro" id="setHarness"><span>{logo ? <img className="h-logo" src={logo} alt="" /> : null}{r.baseName}</span><span className="set-lock">{LOCK}Fixed once saved</span></div>)}
      {sub('Model', '', null, <>
        {field('setModel', 'Default model',
          <select id="setModel" className="set-in" value={c.model} onChange={(e) => set('model', e.target.value)}>
            {!rec.defaultModel || !c.model ? <option value="">{`The harness default${harnessDefault ? ` (${harnessDefault})` : ''}`}</option> : null}
            {modelList.map((m) => {
              const av = modelAvailability(oob?.backend, m), note = av === 'no' ? availabilityNote(av) : '';
              return <option key={m} value={m}>{m}{keyOf(m) ? ' · your key' : ''}{note ? ` · ${note}` : ''}</option>;
            })}
          </select>,
          catalog.failed ? <>The models could not be read just now.{' '}<button type="button" className="link-q inl" onClick={catalog.retry}>Try again</button></> : undefined)}
        {levels.length || c.thinking ? field('setThinking', 'Reasoning effort',
          <select id="setThinking" className="set-in" value={c.thinking} onChange={(e) => set('thinking', e.target.value)}>
            <option value="">Model default</option>
            {(keptLevel ? [...levels, c.thinking] : levels).map((lv) => <option key={lv} value={lv}>{thinkingLabel(lv)}</option>)}
          </select>,
          keptLevel ? 'This model does not have that level. Its tasks get the nearest one it has.' : undefined) : null}
      </>)}
    </>,
    instructions: field('setMd', mdName(rec.base),
      <textarea id="setMd" className="set-in md" rows={14} value={c.agentsMd} onChange={(e) => set('agentsMd', e.target.value)} />),
    // Capabilities: one tab per kind, in Extensions order. A company's lists get long: each tab shows
    // only its own list, with its one action on the right, and a search field once the list passes six.
    caps: <>
      <div className="cap-head">
        <div className="tabs inline cap-tabs" role="tablist" aria-label="Capabilities" onKeyDown={(e) => tabKeys(e, capTabs.map(([k]) => k), capT, pickCap)}>
          {capTabs.map(([k, label, fam]) => (
            <button key={k} type="button" role="tab" aria-selected={k === capT} tabIndex={k === capT ? 0 : -1} className={k === capT ? 'on' : ''} onClick={() => pickCap(k)}>
              <span className="tab-brick" aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon('built', fam) }} />{label} <span className="count">{capN[k]}</span>
            </button>
          ))}
        </div>
        {/* the Plugins tab has no button up here: Connect another plugin sits under its list */}
        {capT === 'plugin' ? null
          : capT === 'skill' ? (takesSkills ? addBtn('Add skill', () => setPop({ k: 'skill', ed: skillDraft(null, '', []) })) : null)
            : addBtn('Add MCP', () => setPop({ k: 'mcp', i: null }))}
      </div>
      {capRows[capT] > 6 ? (
        <div className="cap-find">
          <input className="set-in slim" type="search" placeholder={`Search ${capRows[capT]} ${CAP_WORD[capT]}`} aria-label={`Search ${CAP_WORD[capT]}`} autoComplete="off"
            value={capQ} onChange={(e) => setCapQ(e.target.value)} />
        </div>
      ) : null}
      <div className="cap-pane" role="tabpanel" aria-label={CAP_WORD[capT]}>
        {capT === 'plugin' ? <>
          {/* the workspace's connected plugins, a switch each for this setup (PluginSwitches.tsx) */}
          <PluginSwitches input={plugIn} setup={rec.name} q={capQ} busy={!!busy}
            failed={ws.plugs === null && ws.failed ? { retry: ws.retry } : null}
            lost={plugsLost ? { retry: () => setPlugsRead((n) => n + 1) } : null}
            onSet={setPlugs}
            onPackage={(name, on) => apply((h) => ({ plugins: (h.plugins || []).map((x) => (x.name === name ? { ...x, enabled: on } : x)) }), 'The plugin was not changed. Try again.').then((x) => !!x)}
            onManagePackage={(name) => setPop({ k: 'pkg', name })} onConnect={() => setPop({ k: 'plugin' })}
            reload={ws.reload} />
        </> : capT === 'skill' ? (
          !takesSkills ? <p className="set-help" style={{ margin: 0 }}>{r.baseName} doesn’t use skills.</p>
            : skillList.length ? (
              <div className="cap-list">
                {skillList.map((x) => {
                  if (x.kind === 'builtin') {
                    const b = x.builtin, on = x.on;
                    return (
                      <div key={x.key} className={`cap-row${on ? '' : ' off'}`} hidden={!found(x.name, b.description)}>
                        <span className="cap-ic" dangerouslySetInnerHTML={brick(on)} />
                        <span className="grow"><b>{x.name}</b><small>{b.description || `Built into ${r.baseName}`}</small></span>
                        <button type="button" className="link-q" disabled={!!busy}
                          onClick={() => setPop({ k: 'skill', ed: skillDraft(null, b.name, [{ path: 'SKILL.md', content: `---\nname: ${b.name}\ndescription: ${JSON.stringify(b.description || '')}\n---\n\n` }]) })}>Replace</button>
                        {tog(on, x.name, () => toggleBuiltin(b), !!busy)}
                      </div>
                    );
                  }
                  const s = x.skill, on = x.on;
                  const md = (s.files || []).find((f) => f.path === 'SKILL.md');
                  const sp = md?.content ? splitSkillMd(md.content) : null;
                  const small = sp ? sp.description || cutWords(sp.body, 80) : '';
                  // three actions, as an MCP row has: the design's narrow rule (cap-mcp) wraps them the same way
                  return (
                    <div key={x.key} className={`cap-row cap-mcp${on ? '' : ' off'}`} hidden={!found(s.name, small)}>
                      <span className="cap-ic" dangerouslySetInnerHTML={brick(on)} />
                      <span className="grow"><b>{s.name}</b>{small ? <small>{small}</small> : null}</span>
                      <button type="button" className="link-q" data-editmcp="" disabled={!!busy} onClick={() => void openSkill(s)}>Edit</button>
                      <button type="button" className="link-q danger" data-delrow="" aria-label={`Delete ${s.name}`} disabled={!!busy} onClick={() => setPop({ k: 'delskill', s })}>Delete</button>
                      {tog(on, s.name, () => void apply((h) => ({ skills: (h.skills || []).map((x) => (idOf(x) === idOf(s) ? { ...x, enabled: !on } : x)) }), 'The skill was not changed. Try again.'), !!busy)}
                      <i className="cap-br" aria-hidden="true" />
                    </div>
                  );
                })}
              </div>
            ) : capEmpty('skill', 'No skills on this setup yet.')
        ) : (
          <div className="cap-list">
            {toolList.map((x) => {
              const on = x.on;
              if (x.kind === 'builtin') {
                const t = x.tool;
                return (
                <div key={x.key} className={`cap-row${on ? '' : ' off'}`} hidden={!found(t.name)}>
                  <span className="cap-ic" dangerouslySetInnerHTML={brick(on)} />
                  <span className="grow"><b className="mono">{t.name}</b>{t.enforcement === 'instruction' ? <small>Off asks the agent not to use it.</small> : null}</span>
                  {tog(on, t.name, () => set('tools', on ? [...c.tools, t.name] : c.tools.filter((n) => n !== t.name)))}
                </div>
                );
              }
              const m = x.server, i = x.index, nm = x.name;
              return (
                <div key={x.key} className={`cap-row cap-mcp${on ? '' : ' off'}`} hidden={!found(nm, m.url)}>
                  <span className="cap-ic" dangerouslySetInnerHTML={brick(on)} />
                  <span className="grow"><b>{nm}</b><small>Custom MCP · <span className="mono">{urlBreaks(m.url || 'endpoint')}</span></small></span>
                  <button type="button" className="link-q" data-editmcp={i} onClick={() => setPop({ k: 'mcp', i })}>Edit</button>
                  <button type="button" className="link-q danger" data-delrow={`mcp:${i}`} aria-label={`Delete ${nm}`} onClick={() => setPop({ k: 'delmcp', i })}>Delete</button>
                  {tog(on, nm, () => set('mcp', c.mcp.map((x, k) => (k === i ? { ...x, enabled: !on } : x))))}
                  <i className="cap-br" aria-hidden="true" />
                </div>
              );
            })}
          </div>
        )}
        {capQ.trim() && !capHits && capT !== 'plugin' ? <p className="set-help cap-none">Nothing matches.</p> : null}
      </div>
    </>,
    runtime: <>
      {/* an agent harness that can't open an environment has no Environment section, unless one is
          set from before: then it says so, with Remove (Richard 10-19: an edge case only when it happens) */}
      {srv?.takesEnvironments === false && !rec.environment ? null : sub('Environment', '', null,
        <div className="cap-list"><div className="cap-row">
          <span className="cap-ic" dangerouslySetInnerHTML={brick(!!envX)} />
          <span className="grow">
            <b>{envX ? envX.name : rec.environment ? (envs === null ? (envsFailed ? 'Environment' : '') : 'Not found') : 'None'}</b>
            {srv?.takesEnvironments === false
              ? <small className="warn">{r.baseName} can’t use an environment. Remove it, or every task on this setup is refused.</small>
              : envX ? (envX.status === 'ready' ? (envX.description ? <small>{envX.description}</small> : null)
                : <small className="warn">It has no built version yet, so tasks on this setup are refused until it is built.</small>)
                : rec.environment ? (envs === null ? (envsFailed ? <small className="warn">Your environments could not be read just now.</small> : null)
                  : <small className="warn">This environment is no longer there. Choose another or none.</small>)
                  : null}
          </span>
          {envsFailed && envs === null ? <button type="button" className="link-q" onClick={readEnvs}>Try again</button> : null}
          {srv?.takesEnvironments === false
            ? <button type="button" className="btn small line" disabled={!!busy} onClick={() => void apply(() => ({ environment: '' }), 'The environment was not changed. Try again.')}>Remove</button>
            : <button type="button" className="btn small line" onClick={() => setPop({ k: 'env' })}>{rec.environment ? 'Change' : 'Choose'}</button>}
        </div></div>)}
      {sub('Environment variables', c.vars.length ? String(c.vars.length) : '', addBtn('Add variable', () => { focusNext.current = `setVar${c.vars.length}`; set('vars', [...c.vars, { name: '', value: '' }]); }),
        <>
          {c.vars.length ? (
            <div className="kv">
              {c.vars.map((v, i) => (
                <div key={i} className="kv-r">
                  <input id={`setVar${i}`} className="set-in mono" placeholder="API_KEY" aria-label="Variable name" value={v.name}
                    onChange={(e) => {
                      const el = e.target, pos = el.selectionStart;
                      const nv = el.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_');
                      set('vars', c.vars.map((x, k) => (k === i ? { ...x, name: nv } : x)));
                      if (nv !== el.value && pos != null) requestAnimationFrame(() => { try { el.setSelectionRange(pos, pos); } catch { /* gone */ } });
                    }} />
                  <input className="set-in mono" placeholder="$headers.X-Api-Key or secret:my-secret" aria-label="Variable value" value={v.value}
                    onChange={(e) => set('vars', c.vars.map((x, k) => (k === i ? { ...x, value: e.target.value } : x)))} />
                  <button type="button" className="icon-btn sm" aria-label="Remove variable" onClick={() => set('vars', c.vars.filter((_, k) => k !== i))}>{X}</button>
                </div>
              ))}
            </div>
          ) : null}
          {c.vars.length ? <p className="set-help">Use a reference, never the secret itself: <code>$headers.X-Api-Key</code> or <code>secret:name</code>.</p> : null}
        </>)}
      {sub('Request headers', c.headers.length ? String(c.headers.length) : '', addBtn('Add header', () => { focusNext.current = `setHdr${c.headers.length}`; set('headers', [...c.headers, '']); }),
        <>
          {c.headers.length ? (
            <div className="kv">
              {c.headers.map((hd, i) => (
                <div key={i} className="kv-r one">
                  <input id={`setHdr${i}`} className="set-in mono" placeholder="X-User-Id" aria-label="Header name" value={hd}
                    onChange={(e) => set('headers', c.headers.map((x, k) => (k === i ? e.target.value : x)))} />
                  <button type="button" className="icon-btn sm" aria-label="Remove header" onClick={() => set('headers', c.headers.filter((_, k) => k !== i))}>{X}</button>
                </div>
              ))}
            </div>
          ) : null}
        </>)}
      {sub('Limits', '', null,
        <>
          <div className="two-f">
            {field('setTurns', 'Max steps',
              <input id="setTurns" className="set-in" type="number" min={1} placeholder={limits ? String(limits.maxStep) : undefined} value={c.turns} aria-invalid={inv('setTurns')}
                onChange={(e) => set('turns', e.target.value)} />)}
            {field('setMins', 'Timeout (minutes)',
              <input id="setMins" className="set-in" type="number" min={1} placeholder={limits ? String(Math.round(limits.timeoutSeconds / 60)) : undefined} value={c.mins} aria-invalid={inv('setMins')}
                onChange={(e) => set('mins', e.target.value)} />)}
          </div>
        </>)}
    </>,
  };

  const stack = (
    <>
      <div className="ly ly-list" role="tablist" aria-orientation="vertical" aria-label={`Layers of ${rec.name}`}
        onKeyDown={(e) => tabKeys(e, LAYER_ORDER, Ly, onLayer, { orientation: 'vertical' })}>
        {SET_LAYERS.map(([k, label]) => (
          <button key={k} type="button" className={`ly-n${k === Ly ? ' on' : ''}`} role="tab" aria-selected={k === Ly} tabIndex={k === Ly ? 0 : -1} aria-controls="lgEd" onClick={() => onLayer(k)}>
            <b>{label}{dirtyL(k) ? <span className="brk-dot" title="Unsaved changes" /> : null}</b><small>{SUM[k]}</small>
          </button>
        ))}
      </div>
      <div className="ly-chips" role="tablist" aria-label="Layers" onKeyDown={(e) => tabKeys(e, LAYER_ORDER, Ly, onLayer)}>
        {SET_LAYERS.map(([k, label]) => (
          <button key={k} type="button" className={k === Ly ? 'on' : ''} role="tab" aria-selected={k === Ly} tabIndex={k === Ly ? 0 : -1} onClick={() => onLayer(k)}>
            {label}{dirtyL(k) ? <span className="brk-dot" /> : null}
          </button>
        ))}
      </div>
    </>
  );

  // the save bar sits in the open layer's 56 px bar, on the right of its name (savebarHtml)
  const savebar = dirty ? (
    <div className="savebar" id="savebar"><span className="sv-st"><i aria-hidden="true" />Unsaved changes</span>
      <button type="button" className="btn small sv-b" disabled={busy === 'save'} onClick={discard}>Discard</button>
      <button type="button" className="btn small sv-ink" disabled={busy === 'save'} onClick={() => void save()}>Save</button>
    </div>
  ) : justSaved ? (
    <div className="savebar" id="savebar"><span className="sv-st ok"><i aria-hidden="true" />Saved</span>
      {onNewTask ? <button type="button" className="btn small sv-b" onClick={onNewTask}>New task</button> : null}
    </div>
  ) : <div className="savebar-none" id="savebar" />;

  const pkg = pop?.k === 'pkg' ? pkgs.find((p) => p.name === pop.name) || null : null;
  const mcpEdit = pop?.k === 'mcp' && pop.i != null ? c.mcp[pop.i] || null : null;

  // Delete setup: the settings' last row, a layer row's anatomy, past a hairline and outside the
  // layers' tablist; red, its name alone (the sheet says what deleting does). Duplicate shares its
  // row at the right, blue (as on the hosted console; its sheet picks the other agent harness).
  // Drawn at any width (hrui-console.css): `rail` under the layers, else at the foot of the open
  // layer.
  const delRow = (where: 'rail' | 'foot') => (
    <div className="lg-dz" data-where={where}>
      <button type="button" className="ly-n" aria-haspopup="dialog" onClick={() => setPop({ k: 'del' })}><b>Delete setup</b></button>
      <button type="button" className="ly-n lg-dup" aria-haspopup="dialog" title="Duplicate with another agent harness"
        onClick={() => setPop({ k: 'dup' })}><b>Duplicate</b></button>
    </div>
  );

  // Settings in the Tasks tab's place (settingsHtml): the layers where the task list was, each under
  // one 56 px bar, the open layer where the task was, the Agent stack beside it (the page draws it)
  return (
    <div className="lg-set">
      <div className="lg-left">
        <div className="lg-lbar"><span>These settings apply to every task.</span></div>
        <div className="lg-rows">{stack}{delRow('rail')}</div>
      </div>
      <div className="lg-ed" id="lgEd" role="tabpanel" aria-label={layerName}>
        <div className="lg-bar"><div className="lg-col"><h2>{layerName}</h2>{savebar}</div></div>
        <div className="lg-scroll"><div className="lg-col">
          {DESC[Ly] ? <p className="lg-desc">{DESC[Ly]}</p> : null}
          {BODY[Ly]}
          {delRow('foot')}
        </div></div>
      </div>
      <input ref={dirRef} type="file" hidden {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
        onChange={(e) => { const picked = Array.from(e.target.files || []); e.target.value = ''; void installFolder(picked); }} />

      {/* the shared MCP sheet: what it saves goes into this setup's draft, written with Save (a token
          is stored securely first, only its reference goes into the draft) */}
      {pop?.k === 'mcp' ? (
        <McpSheet server={mcpEdit} keptAuth={mcpEdit?.auth} headers={c.headers} onClose={() => setPop(null)}
          nameTaken={(n) => (c.mcp.some((x, k) => k !== pop.i && (x.name || '').toLowerCase() === n.toLowerCase()) ? `This setup already has an MCP server named ${n}.` : '')}
          onSave={async (v) => {
            const id = mcpEdit?.id || newMcpId();
            let auth: string | undefined;
            try { auth = await authFor(id, v.token, mcpEdit?.auth); } catch { return 'The token could not be stored. Try again.'; }
            const m: McpServer = { ...(mcpEdit || { transport: 'http', enabled: true }), id, name: v.name, url: v.url };
            if (auth) m.auth = auth; else delete m.auth;
            set('mcp', pop.i != null ? c.mcp.map((x, k) => (k === pop.i ? m : x)) : [...c.mcp, m]);
            setPop(null);
            return '';
          }}
          onRemove={pop.i != null ? async () => { const i = pop.i; set('mcp', c.mcp.filter((_, k) => k !== i)); setPop(null); return ''; } : undefined} />
      ) : null}
      {pop?.k === 'delmcp' && c.mcp[pop.i] ? (
        <ConfirmSheet id="dmc" title="Remove MCP server?" confirmLabel="Remove" focusConfirm
          body={<><b>{c.mcp[pop.i].name || 'This MCP server'}</b> comes off this setup when you save.</>}
          onClose={() => setPop(null)} onConfirm={() => { const i = pop.i; set('mcp', c.mcp.filter((_, k) => k !== i)); setPop(null); }} />
      ) : null}
      {pop?.k === 'plugin' && included !== undefined ? (
        // Add plugin (the tab's Connect another plugin): every plugin of Add-ons › Plugins, opened at
        // what can still be connected
        <AddPluginSheet workspace={wsId} setup={rec.name} binding={{ plugs }} busy={!!busy} focus="available"
          onSet={setPlugs} onInstall={() => dirRef.current?.click()}
          onChanged={() => { void ws.reload(); }}
          onClose={() => setPop(null)} />
      ) : null}
      {pop?.k === 'env' ? <EnvPickSheet envs={envs} failed={envsFailed} retry={readEnvs} current={rec.environment || ''} busy={!!busy} onPick={(eid) => void pickEnv(eid)} onClose={() => setPop(null)} /> : null}
      {pop?.k === 'pkg' && pkg ? (
        <PackageSheet p={pkg} hid={id} busy={!!busy} onClose={() => setPop(null)}
          onToggle={() => void apply((h) => ({ plugins: (h.plugins || []).map((x) => (x.name === pkg.name ? { ...x, enabled: x.enabled === false } : x)) }), 'The plugin was not changed. Try again.')}
          onDetach={() => { void apply((h) => ({ plugins: (h.plugins || []).filter((x) => x.name !== pkg.name) }), 'The plugin was not detached. Try again.').then((s) => { if (s) setPop(null); }); }} />
      ) : null}
      {pop?.k === 'skill' ? (
        <SkillSheet ed={pop.ed} busy={!!busy} setEd={(ed) => setPop({ k: 'skill', ed })} onClose={() => setPop(null)} onSave={(ed) => void saveSkill(ed)} setup={rec.name} />
      ) : null}
      {pop?.k === 'delskill' ? (
        <ConfirmSheet id="sdl" title={`Delete skill · ${pop.s.name}`} confirmLabel="Delete skill" busy={!!busy} onClose={() => setPop(null)}
          body={<>From its next task, <b>{rec.name}</b> stops following it. This can’t be undone.</>}
          onConfirm={() => { const s = pop.s; void apply((h) => ({ skills: (h.skills || []).filter((x) => idOf(x) !== idOf(s)) }), 'The skill was not deleted. Try again.').then((ok) => { if (ok) { setPop(null); toast('Skill deleted.'); } }); }} />
      ) : null}
      {pop?.k === 'del' ? (
        <DeleteSetupSheet h={rec} onClose={() => setPop(null)}
          onDeleted={() => { keepDraft(id, {}, false); onDirtyRef.current?.(false); toast(`${rec.name} deleted`); router.push('/studio'); }} />
      ) : null}
      {pop?.k === 'dup' ? (
        <DuplicateSheet h={rec} bases={bases} plugs={included} onClose={() => setPop(null)}
          onDone={(cp) => { setPop(null); openNewSetup(router, { id: cp.id }); }} />
      ) : null}
    </div>
  );
}
