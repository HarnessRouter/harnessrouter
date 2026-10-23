'use client';
// The save card (docs/uxuidesign/console-91: backendShow in its bs-save form, bsTop, buildSeq): the
// setup New setup composed, put together brick by brick, at the top of its first task's
// conversation. A brick lands when the call that saves it has answered, never on a timer of its own:
// the agent harness, the model and the instructions with the harness itself; the skills with it too
// (they are saved in the same record); each plugin when its attach answers. HarnessRouter's included
// parts are the platform's own features, the same for every harness, so they are on as soon as the
// harness exists; they land one after another only so the eye can follow (a few tenths of a second,
// after the save that made them true). Reopened later, the card is drawn from the setup's record
// (assemblyOfRow), settled: nothing lands again.
import { useEffect, useState, type ReactNode } from 'react';
import { listPlugs } from '@/lib/plugs';
import { partIcon } from '../bricks';
import { SUBS } from '../tower';
import type { SetupRow } from '../setups';
import { pluginName } from '../setup/setupParts';
import { slabIcon } from './art';
import type { Composed, Part } from './compose';

const CHECK_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M5 12l5 5L20 7"/></svg>';
const STAGGER_MS = 70;

/** Where one attach stands: being saved, saved, or refused. */
export type Attach = 'now' | 'on' | 'off';

export interface AssemblyState {
  cfg: Composed;
  /** the harness record has been created (the time it answered, for the stagger) */
  savedAt: number | null;
  /** each plugin's attach, by the composer's id */
  plugins: Record<string, Attach>;
  /** everything has answered */
  done: boolean;
  /** what a person added that is on, from the setup's record once it is read (withRecord,
   *  assemblyOfRow): the skills and tools the card names, never a built-in */
  added?: { skills: Part[]; tools: Part[] };
}

const onParts = (l: { key: string; name: string; on: boolean }[]) => l.filter((x) => x.on).map((x) => ({ id: x.key, name: x.name }));
const count = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

/** The skills a card names as added before the setup's record is read: a template's own skills,
 *  saved with the setup. The composer's skill picks are the agent harness's built-ins, which no one
 *  added, so none. (The Agent stack counts the same while the save lands, buildStack.) */
export const addedSkillsOf = (cfg: Composed): Part[] => (cfg.ownSkills?.length ? cfg.skills : []);

/** What the card names besides its plugins: what a person added that is on (setupParts.ts, scope
 *  'added'), the same as the Agent stack beside it; never a built-in skill or tool. */
export function cardParts(s: AssemblyState): { skills: Part[]; tools: Part[] } {
  return s.added || { skills: addedSkillsOf(s.cfg), tools: [] };
}

/** The card once the setup is saved: its skills and tools are the ones its record says a person
 *  added. Its plugins land as each attach answers. */
export function withRecord(s: AssemblyState, r: SetupRow | null | undefined): AssemblyState {
  if (!r || s.savedAt == null) return s;
  return { ...s, added: { skills: onParts(r.added.skills), tools: onParts(r.added.tools) } };
}

/** The card a saved setup's record draws, settled: its agent harness, model and instructions, the
 *  parts HarnessRouter runs, and what a person added that is on (its skills, tools and plugins,
 *  setup/setupParts.ts scope 'added', plugins by their names where they are known: `labels`, the
 *  workspace plugins' names by type). */
export function assemblyOfRow(r: SetupRow, labels: Record<string, string> = {}): AssemblyState {
  const h = r.h;
  const plugins = r.added.plugins.filter((p) => p.on).map((p) => ({ id: p.key, name: pluginName(p, labels) }));
  const added = { skills: onParts(r.added.skills), tools: onParts(r.added.tools) };
  const cfg: Composed = {
    name: h.name, instructions: h.systemPrompt || '', exampleTask: '', base: h.base, baseName: r.baseName, model: h.defaultModel || '',
    skills: added.skills, plugins, connectionsNeeded: [],
  };
  return { cfg, savedAt: h.createdAt || 0, plugins: Object.fromEntries(plugins.map((p) => [p.id, 'on' as Attach])), done: true, added };
}

type Look = 'on' | 'now' | 'wait' | 'lock';

function Chip({ fam, lab, name, tip, look, delay, note, still }: { fam: string; lab?: string; name: string; tip: string; look: Look; delay?: number; note?: string; still?: boolean }) {
  const on = look === 'on', pop = on && !still;
  const html = partIcon(on ? 'built' : 'empty', fam) + (on ? '<span class="bs-ok">' + CHECK_SVG + '</span>' : '');
  return (
    <div className={`bs-t ${look}${pop ? ' pop' : ''}`} style={pop && delay ? { animationDelay: `${delay}ms` } : undefined} title={tip}>
      <span className="bs-c" dangerouslySetInnerHTML={{ __html: html }} />
      <span className="bs-x">{note || lab ? <small>{note || lab}</small> : null}<b>{name}</b></span>
    </div>
  );
}

/** The instructions as the brick names them (the design's cutWords): their opening words, cut at a
 *  word, the whole of them in the brick's tooltip. */
function cutWords(s: string, n = 44): string {
  const t = s.replace(/\s+/g, ' ').trim();
  if (t.length <= n) return t;
  const cut = t.slice(0, n), at = cut.lastIndexOf(' ');
  return `${(at > n / 2 ? cut.slice(0, at) : cut).replace(/[\s.,;:]+$/, '')}…`;
}

/** A card saved this long ago is drawn settled: its bricks are in place, none lands again. */
const SETTLED_MS = 4000;

export function Assembly({ s }: { s: AssemblyState }) {
  const { cfg } = s;
  const saved = s.savedAt != null;
  const still = s.done && saved && Date.now() - (s.savedAt as number) > SETTLED_MS;
  const g1: ReactNode[] = [
    <Chip still={still} key="h" fam="harness" lab="Agent harness" name={cfg.baseName} tip={`Agent harness: ${cfg.baseName}`} look={saved ? 'on' : 'now'} />,
    <Chip still={still} key="m" fam="model" lab="Model" name={cfg.model} tip={`Model: ${cfg.model}`} look={saved ? 'on' : 'now'} delay={saved ? STAGGER_MS : 0} />,
    <Chip still={still} key="i" fam="task" lab="Instructions" name={cutWords(cfg.instructions)} tip={`Instructions: ${cfg.instructions}`} look={saved ? 'on' : 'now'} delay={saved ? 2 * STAGGER_MS : 0} />,
  ];
  const included = SUBS.map(([k, , label], i) => (
    <Chip still={still} key={k} fam="backend" name={label} tip={`${label}, run by HarnessRouter`} look={saved ? 'on' : 'wait'} delay={(3 + i) * STAGGER_MS} />
  ));
  const late = (3 + SUBS.length) * STAGGER_MS;
  const g3: ReactNode[] = [];
  const { skills, tools } = cardParts(s);
  if (skills.length) {
    const names = skills.map((x) => x.name).join(', ');
    g3.push(<Chip still={still} key="skill" fam="skill" lab={count(skills.length, 'skill')} name={names} tip={`Skills: ${names}`} look={saved ? 'on' : 'wait'} delay={late} />);
  }
  if (tools.length) {
    const names = tools.map((x) => x.name).join(', ');
    g3.push(<Chip still={still} key="tool" fam="mcp" lab={count(tools.length, 'tool')} name={names} tip={`Tools: ${names}`} look={saved ? 'on' : 'wait'} delay={late} />);
  }
  cfg.plugins.forEach((p, i) => {
    const st = s.plugins[p.id];
    const look: Look = st === 'on' ? 'on' : st === 'now' ? 'now' : st === 'off' ? 'lock' : 'wait';
    g3.push(<Chip still={still} key={`p-${p.id}`} fam="plugin" lab="Plugin" name={p.name} tip={`Plugin: ${p.name}`} look={look}
      note={st === 'off' ? 'Not added' : undefined} delay={st === 'on' ? (i + 1) * STAGGER_MS : 0} />);
  });
  cfg.connectionsNeeded.forEach((p) => {
    g3.push(<Chip still={still} key={`n-${p.id}`} fam="plugin" name={p.name} tip={`${p.name} is not connected yet`} look={s.done ? 'lock' : 'wait'}
      note={s.done ? 'Not connected' : 'Plugin'} />);
  });
  return (
    <div className="bs-wrap"><section className={`bs bs-compact bs-save ${s.done ? 'done' : 'building'}`} aria-label="Your setup">
      <div className="bs-h">
        <span className="bs-ic" aria-hidden="true">
          <span style={{ display: 'block' }} dangerouslySetInnerHTML={{ __html: slabIcon() }} />
          {s.done ? <span className="bs-done" dangerouslySetInnerHTML={{ __html: CHECK_SVG }} /> : null}
        </span>
        <span className="bs-tt" role="status"><span className="bs-k">{cfg.name}</span><b>{s.done ? 'Setup saved.' : 'Saving your setup…'}</b></span>
      </div>
      <div className="bs-board">
        <div className="bs-grid bs-g1">{g1}</div>
        <span className="bs-gl">HarnessRouter · included</span>
        <div className="bs-grid">{included}</div>
        {g3.length ? <div className="bs-grid bs-g3">{g3}</div> : null}
      </div>
    </section></div>
  );
}

/** The card of a setup's first task reopened later: drawn from the setup's record, settled. The
 *  workspace plugins it includes are named from the plugin catalog once it is read. */
export function RecordCard({ r }: { r: SetupRow }) {
  const wants = r.added.plugins.some((p) => p.kind === 'plug');
  const [labels, setLabels] = useState<Record<string, string> | null>(wants ? null : {});
  useEffect(() => {
    if (!wants) { setLabels({}); return; }
    let alive = true;
    listPlugs().then((c) => { if (alive) setLabels(Object.fromEntries(c.plugs.map((p) => [p.type, p.label]))); })
      .catch(() => { if (alive) setLabels({}); });
    return () => { alive = false; };
  }, [wants]);
  if (labels === null) return null;
  return <Assembly s={assemblyOfRow(r, labels)} />;
}
