'use client';
// Add-ons › Skills (docs/uxuidesign/console-91: libraryView's skills tab, libUsed, skillEdHtml, skSave).
// A skill lives inside a setup (CustomHarness.skills): each row is one setup's own skill, with the
// setup it is in. Create is two steps (Richard, 2026-10-18): the skill editor (skills/SkillEditor, the
// one a setup's Settings opens too), then Add to setups (AddToSheet), which writes each chosen setup's
// skills through the server, one setup at a time. Name and description are kept in SKILL.md's
// frontmatter, the name as skillSlug writes it.
import { useMemo, useState } from 'react';
import { getCustom, saveCustom, getSkillFiles, useBases, type CustomHarness } from '@/lib/harness';
import { partIcon } from '../bricks';
import { toast } from '../toast';
import { ConfirmSheet } from '../Sheet';
import { PLUS, plural, usedText, ReadFailed } from './shared';
import { Skel, SkRows } from '../Skel';
import { SkillEditor } from '../skills/SkillEditor';
import { AddToSheet, type AddResult, type AddTarget } from './AddToSheet';
import { skillDraft, skillFiles, skillSlug, splitSkillMd, type SkillDraft, type SkillFile } from '../skills/skillMd';

type Skill = CustomHarness['skills'][number];
const isOwn = (s: Skill) => Boolean((s.files && s.files.length) || (s as { content?: string }).content || s.blob);

interface Row { h: CustomHarness; s: Skill; desc: string }

/** The editor's draft, with the setup the skill is in ('' for a new one, whose setups come next). */
type Ed = SkillDraft & { hid: string; setup: string };

/** How many skills Add-ons counts: every setup's own. */
export function skillCount(setups: CustomHarness[] | null): number {
  return (setups || []).reduce((n, h) => n + (h.skills || []).filter(isOwn).length, 0);
}

/** `failed`: the setups could not be read (lib/settle.ts); the tab says so, with `retry`. */
export function SkillsTab({ setups, reload, failed = false, retry }: {
  setups: CustomHarness[] | null; reload: () => Promise<void>; failed?: boolean; retry?: () => void;
}) {
  const [ed, setEd] = useState<Ed | null>(null);
  const [step2, setStep2] = useState(false);     // a new skill, made: the setups it goes in
  const bases = useBases();
  const [del, setDel] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const loading = setups === null;

  const rows = useMemo<Row[]>(() => (setups || []).flatMap((h) => (h.skills || []).filter(isOwn).map((s) => {
    const md = (s.files || []).find((f) => f.path === 'SKILL.md' || f.path.endsWith('/SKILL.md'));
    return { h, s, desc: md?.content ? splitSkillMd(md.content).description : '' };
  })), [setups]);

  async function open(r: Row) {
    let files = r.s.files || [];
    if (!files.length && r.s.blob) {
      try { files = await getSkillFiles(r.h.id, r.s.id || r.s.name); }
      catch { toast('The skill could not be opened. Try again.'); return; }
    }
    if (!files.length && (r.s as { content?: string }).content) files = [{ path: 'SKILL.md', content: (r.s as { content?: string }).content }];
    setEd({ ...skillDraft(r.s.id || r.s.name, r.s.name, files), hid: r.h.id, setup: r.h.name });
  }

  /** A skill of this setup, by its stored name, other than the one being edited. */
  const clash = (h: CustomHarness, nm: string, id: string | null) => (h.skills || []).some((x) => isOwn(x) && (x.id || x.name) !== id && skillSlug(x.name) === nm);
  /** Write one setup's skills on its newest record: an edit of its own skill, or a new one added.
   *  '' once saved, else why not. */
  async function write(hid: string, e: Ed, nm: string): Promise<string> {
    const h = await getCustom(hid);
    if (!h) return 'No longer in this workspace';
    // names compared as they are stored, so "Weekly Report" and weekly-report are the same skill
    if (clash(h, nm, e.id)) return `Already has a skill named ${nm}`;
    const files: SkillFile[] = skillFiles(e, nm);
    const skills = h.skills || [];
    const next = e.id
      ? skills.map((x) => ((x.id || x.name) === e.id ? { id: x.id, name: nm, enabled: x.enabled !== false, files } : x))
      : [...skills, { id: 'skl_' + crypto.randomUUID().replace(/-/g, ''), name: nm, enabled: true, files }];
    await saveCustom({ ...h, skills: next as CustomHarness['skills'] });
    return '';
  }

  // the editor's main button: Save for a skill there is; Next for a new one, whose setups come next
  async function save(e: Ed) {
    const nm = skillSlug(e.name);
    if (!nm) { toast('Give the skill a name with letters or numbers.'); return; }
    if (!e.id) { setStep2(true); return; }
    setBusy(true);
    try {
      const err = await write(e.hid, e, nm);
      if (err) { toast(`Not saved. ${err}.`); return; }
      toast('Skill saved.');
      setEd(null);
      await reload();
    } catch { toast('The skill could not be saved. Check SKILL.md and try again.'); }
    finally { setBusy(false); }
  }

  // the second step: every setup, one that cannot take it shown with why
  const nm = ed ? skillSlug(ed.name) : '';
  const targets: AddTarget[] = (setups || []).map((h) => ({
    id: h.id, name: h.name, base: h.base,
    off: bases?.[h.base]?.takesSkills === false ? `${h.baseLabel || h.base} takes no skills`
      : nm && clash(h, nm, null) ? `Already has a skill named ${nm}` : undefined,
  }));
  const open1 = targets.filter((t) => !t.off);
  async function addTo(ids: string[]): Promise<AddResult> {
    const e = ed;
    const r: AddResult = { done: [], failed: [] };
    if (!e) return r;
    for (const id of ids) {
      try { const err = await write(id, e, nm); if (err) r.failed.push({ id, why: err }); else r.done.push(id); }
      catch { r.failed.push({ id, why: '' }); }
    }
    await reload();
    return r;
  }
  function added(ids: string[]) {
    const names = ids.map((id) => setups?.find((h) => h.id === id)?.name || id);
    setStep2(false); setEd(null);
    if (names.length) toast(`Skill created and added to ${names.length === 1 ? names[0] : plural(names.length, 'setup')}.`);
  }

  async function remove(r: Row) {
    setBusy(true);
    try {
      const h = await getCustom(r.h.id);
      if (!h) throw new Error('gone');
      const id = r.s.id || r.s.name;
      await saveCustom({ ...h, skills: (h.skills || []).filter((x) => (x.id || x.name) !== id) });
      setDel(null);
      toast('Skill deleted. 1 setup updated.');
      await reload();
    } catch { toast('The skill could not be deleted. Try again.'); }
    finally { setBusy(false); }
  }
  const empty = !loading && !rows.length;
  return (
    <>
      <div className="lib-form"><button type="button" className="btn primary" disabled={loading} onClick={() => { setStep2(false); setEd({ ...skillDraft(null, '', []), hid: '', setup: '' }); }}>{PLUS}Create a skill</button></div>
      <div className="rows">
        {failed ? <ReadFailed what="skills" retry={retry || (() => void reload())} /> : null}
        {loading && !failed ? <Skel label="Loading your skills"><SkRows n={4} /></Skel> : null}
        {empty ? (
          <div className="empty-list es"><span className="es-art" aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon('empty', 'skill') }} /><span>No skills yet.</span></div>
        ) : null}
        {!loading ? rows.map((r) => (
          <div key={`${r.h.id}:${r.s.id || r.s.name}`} className="row lib-g">
            <span className="t lib-t">
              <span className="lib-ic" aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon('built', 'skill') }} />
              <span>
                <b>{r.s.name}</b>
                {r.desc ? <small className="sub2">{r.desc}</small> : null}
                <small className="lib-used">{usedText([r.h.name])}{r.s.enabled === false ? ' (off)' : ''}</small>
              </span>
            </span>
            <span className="lib-act">
              <button type="button" className="btn small line" disabled={busy} onClick={() => void open(r)}>Edit</button>
              <button type="button" className="link-q danger" disabled={busy} onClick={() => setDel(r)}>Delete</button>
            </span>
          </div>
        )) : null}
      </div>

      {ed && !step2 ? <SkillEditor ed={ed} setEd={setEd} busy={busy} onSave={(e) => void save(e)} onClose={() => setEd(null)} setup={ed.setup}
        primary={ed.id ? undefined : 'Next'} /> : null}
      {ed && step2 ? (
        <AddToSheet item={nm} targets={targets} initial={open1.length === 1 ? [open1[0].id] : []}
          onAdd={addTo} onBack={() => setStep2(false)} onDone={added} />
      ) : null}
      {del ? (
        <ConfirmSheet id="sdl" title={`Delete skill · ${del.s.name}`} confirmLabel="Delete skill" busy={busy}
          onClose={() => setDel(null)} onConfirm={() => void remove(del)}
          body={<><b>{del.h.name}</b> uses it. This can’t be undone.</>} />
      ) : null}
    </>
  );
}
