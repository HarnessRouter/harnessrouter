'use client';
// The skill editor as a setup's Settings › Capabilities opens it, for one of this setup's own
// skills. The editor itself (a skill's folder, SKILL.md's header, uploads) is skills/SkillEditor,
// the same one Extensions › Skills opens; the helpers that read and write SKILL.md are
// skills/skillMd. Both are re-exported here for the code that imports them from this module.
import { SkillEditor } from '../skills/SkillEditor';
import type { SkillDraft } from '../skills/skillMd';

export { splitSkillMd, joinSkillMd, skillSlug, skillDraft, skillFiles, type SkillDraft } from '../skills/skillMd';

export function SkillSheet({ ed, setEd, busy, onSave, onClose, setup }: {
  ed: SkillDraft; setEd: (e: SkillDraft) => void; busy: boolean; onSave: (e: SkillDraft) => void; onClose: () => void; setup?: string;
}) {
  return <SkillEditor ed={ed} setEd={setEd} busy={busy} onSave={onSave} onClose={onClose} setup={setup} />;
}
