// The recorded first runs a demo saved unchanged plays (start/replay.ts, start/recorded.ts): what each
// one is, the setup a demo is saved as from it, the marker that setup carries, and its files as their
// kept copies. And, since this repository is public, that the recordings name nothing of the hosted
// service's own (its internal names, addresses, people or ids). The fixture run is a test's: no page
// ever shows one.
import fs from 'fs';
import path from 'path';
import { loadRecording, markOf, recordedFile, recordedMark, REPLAY_MAX_MS, replaySpeed, runOfMark, SKIPPED_PLUGINS, templateOf, type RecordedRun } from './replay';
import { DEMOS } from './demos';

const RUN: RecordedRun = {
  demo: 0, ranAt: 0, base: 'hermes', model: 'gpt-5.4', request: 'A matte black ceramic mug with a bamboo lid.', durMs: 7000, status: 'completed',
  events: [{ t: 0, ev: { type: 'response.created' } }],
  files: [{ name: 'mug.png', mime: 'image/png', bytes: 10, src: '/demos/product/mug.png' }],
  template: {
    demo: 0, name: 'Product images', base: 'hermes', model: 'gpt-5.4', instructions: DEMOS[0].instr,
    skills: [{ id: 'product-shot-style', name: 'Product shot style', body: 'Square.', skill: { name: 'product-shot-style', enabled: true, files: [{ path: 'SKILL.md', content: 'x' }] } }],
    plugins: [{ id: 'media', name: 'Image generation' }],
  },
};

describe('a recorded first run', () => {
  test('a demo with no recording has none (it runs live)', async () => {
    expect(await loadRecording(1, [RUN])).toBeNull();
    expect(await loadRecording(null, [RUN])).toBeNull();
  });
  test('only a run with events and a request counts', async () => {
    expect(await loadRecording(0, [{ ...RUN, events: [] }])).toBeNull();
    expect(await loadRecording(0, [{ ...RUN, request: '' }])).toBeNull();
    expect(await loadRecording(0, [RUN])).toBe(RUN);
  });
  test('the recordings here are each a demo’s, on the demo’s own pair, with the files they made kept here', async () => {
    let n = 0;
    for (let i = 0; i < DEMOS.length; i++) {
      const r = await loadRecording(i);
      if (!r) continue;
      n += 1;
      expect(r.template.demo).toBe(i);
      expect(r.template.instructions).toBe(DEMOS[i].instr);
      // the setup it plays in is the one it ran on: the demo opens on the pair the recording ran on
      expect({ base: r.base, model: r.model }).toEqual({ base: DEMOS[i].base, model: DEMOS[i].model });
      expect(r.status).toBe('completed');
      for (const f of r.files) {
        expect(f.src).toMatch(/^\/demos\//);
        const kept = path.join(__dirname, '../../../../public', f.src);
        expect(fs.statSync(kept).size).toBe(f.bytes);
      }
      // the setups made from them are ones this console can save
      expect(templateOf(i, r)).not.toBeNull();
    }
    expect(n).toBe(DEMOS.length);
  });
  test('the setup: what the recording ran on, its own skills saved under fresh ids, without the hosted image tools', () => {
    const c = templateOf(0, RUN);
    expect(c).toMatchObject({ name: 'Product images', instructions: DEMOS[0].instr, base: 'hermes', model: 'gpt-5.4' });
    expect(c?.skills).toHaveLength(1);
    expect(c?.skills[0]).toMatchObject({ name: 'product-shot-style', enabled: true, files: [{ path: 'SKILL.md', content: 'x' }] });
    expect(c?.skills[0].id).toMatch(/^skl_[a-z0-9]+$/i);
    expect(templateOf(0, RUN)?.skills[0].id).not.toBe(c?.skills[0].id);
    expect(SKIPPED_PLUGINS).toEqual(['media']);
    expect(c).not.toHaveProperty('plugins');
  });
  test('a recording that ran on a plugin this console cannot add is not saved as one: that demo runs live', () => {
    const other = { ...RUN, template: { ...RUN.template, plugins: [...RUN.template.plugins, { id: 'github', name: 'GitHub' }] } };
    expect(templateOf(0, other)).toBeNull();
  });
  test('it plays in proportion, at most REPLAY_MAX_MS long; a short run at the pace it ran', () => {
    expect(REPLAY_MAX_MS).toBe(15_000);
    expect(replaySpeed({ ...RUN, durMs: 105_166 })).toBeCloseTo(7.01, 2);
    expect(replaySpeed({ ...RUN, durMs: 21_700 })).toBeCloseTo(1.45, 2);
    expect(replaySpeed({ ...RUN, durMs: 14_300 })).toBe(1);
  });
  test('a setup names the run it was saved from on its record, and its list finds that run', () => {
    const mark = recordedMark({ ...RUN, ranAt: 1792378362430 });
    expect(mark).toBe('demo:0@1792378362430');
    expect(mark.length).toBeLessThanOrEqual(200);   // the record keeps 200 characters of it
    expect(markOf(mark)).toEqual({ demo: 0, ranAt: 1792378362430 });
    expect(markOf('selfhost')).toBeNull();
    expect(markOf(undefined)).toBeNull();
    expect(runOfMark(recordedMark(RUN), [RUN])).toBe(RUN);
    // a run no longer kept (re-recorded since) is shown as nothing
    expect(runOfMark('demo:0@1', [RUN])).toBeNull();
  });
  test('its files are its own kept copies, by name; one it kept none of is left out', () => {
    expect(recordedFile(RUN, { container_id: 'c', file_id: 'f', filename: 'out/mug.png' })).toMatchObject({ url: '/demos/product/mug.png', filename: 'out/mug.png' });
    expect(recordedFile(RUN, { container_id: 'c', file_id: 'g', filename: 'other.png' })).toBeNull();
  });
});

describe('what the recordings carry, in a public repository', () => {
  const text = fs.readFileSync(path.join(__dirname, 'recorded.ts'), 'utf8');
  test('none of the hosted service’s own names, people or places', () => {
    for (const w of [/agent\s?studio/i, /vector\s?graph/i, /cosmos/i, /gremlin/i, /azure/i, /epsilla/i, /vault/i, /tenant/i,
      /spanner/i, /postgres/i, /readily/i, /wrapper\.work/i, /harnessrouter\.ai/i, /\borg[._][a-z0-9]/i, /\bstaff\b/i]) {
      expect(text).not.toMatch(w);
    }
    // no e-mail address, and no address but the provider page a skill the run read links to
    expect(text).not.toMatch(/[a-z0-9._%+-]+@[a-z0-9-]+\.[a-z]{2,}/i);
    const hosts = new Set(Array.from(text.matchAll(/https?:\/\/([^/\s"'\\)]+)/g), (m) => m[1]));
    expect([...hosts]).toEqual(['platform.openai.com']);
  });
  test('none of the recorded run’s own ids: its task, response and files read as recorded', () => {
    expect(text).not.toMatch(/hsess[a-z0-9_]+/i);
    expect(text).not.toMatch(/cfile_[a-z0-9]+/i);
    expect(text).not.toMatch(/"sessionId"|sessionId:|responseId:/);
    expect(text).toMatch(/"container_id":"recorded"/);
  });
});
