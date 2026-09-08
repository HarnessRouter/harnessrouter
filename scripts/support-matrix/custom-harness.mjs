// The custom-harness dimension: a harness a person configured, rather than a built-in one.
//
// The five per-model scenarios measure routing: the right connection, the right model, a session
// that survives a switch and a recycle. They say nothing about the configuration a person actually
// builds, which is where this product's own promise lives: your own skill, carrying your own
// script, and control over the tools the runtime brought with it. A harness that answers on every
// model and ignores the skill you wrote is not working.
//
//   BASE=https://your-instance HR_USER=… HR_PASS=… BASES=codex,claude-code,pi node custom-harness.mjs
//
// One turn per base, not per model: this tests what the harness carries, not where the turn routed.
// Costs one short turn each.
import { chromium } from 'playwright';
import crypto from 'node:crypto';

const BASE = process.env.BASE;
const BASES = (process.env.BASES || 'codex,claude-code,hermes,pi,dsh,opencode,omp').split(',');
const RESULTS = process.env.RESULTS || 'results-custom.json';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TERMINAL = new Set(['done', 'completed', 'failed', 'incomplete', 'cancelled']);
const log = (s) => console.log(`${new Date().toISOString()} ${s}`);

// The token lives ONLY inside the script, never in SKILL.md and never in the prompt, so an answer
// that carries it came from the bundle rather than from the model's imagination.
const token = 'STAMP-' + crypto.randomBytes(6).toString('hex');
const SKILL = (name) => ({
  name,
  files: [
    { path: 'SKILL.md', content: [
        `---`, `name: ${name}`,
        `description: Report this harness's build stamp. Use it whenever a stamp is asked for.`,
        `---`, ``,
        `# Build stamp`, ``,
        `From the task's working directory, WITHOUT changing directory first, run this skill's`,
        `own \`stamp.py\` with python3, giving its full path:`, ``,
        '```bash', `python3 <this skill's directory>/stamp.py`, '```', ``,
        `It prints one line and writes \`stamp.txt\` beside the task's other outputs, which is why`,
        `it must run from the task's working directory rather than from this skill's.`, ``,
        `Reply with exactly the line it printed, and nothing else.`,
      ].join('\n') },
    { path: 'stamp.py', content: [
        `# Writes the stamp beside the task's other outputs and prints it.`,
        `import pathlib`,
        `stamp = ${JSON.stringify(token)}`,
        `pathlib.Path('stamp.txt').write_text(stamp + '\\n')`,
        `print(stamp)`,
      ].join('\n') },
  ],
});

const b = await chromium.launch({ ignoreHTTPSErrors: !!process.env.IGNORE_TLS });
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: !!process.env.IGNORE_TLS });
const page = await ctx.newPage();
const api = (path, init) => page.evaluate(async ([p, i]) => {
  const r = await fetch(p, i || {}); let j = null; try { j = await r.json(); } catch { /* not json */ }
  return { status: r.status, json: j };
}, [path, init]);
const results = {};

try {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2000);
  if (page.url().includes('/login')) {
    const set = async (sel, v) => page.$eval(sel, (el, x) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, x);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }, v);
    await set('#sh-user', process.env.HR_USER || 'harnessrouter');
    await set('#sh-pass', process.env.HR_PASS);
    await page.click('button[type=submit]');
    await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000 });
  }
  await sleep(1500);

  for (const base of BASES) {
    const rec = { base, at: new Date().toISOString() };
    let hid = null;
    try {
      // A harness a person would build: its own skill (with its own script), and one inherited
      // tool switched off, which is the other half of what the Tools panel offers.
      const created = await api('/api/harness/v1/harnesses', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          name: `matrix custom ${base}`, base,
          system_prompt: 'You follow your skills exactly.',
          skills: [SKILL('matrix-stamp')],
          disabled_tools: ['WebSearch'],
        }),
      });
      rec.created = created.status;
      hid = created.json && (created.json.id || created.json.harness_id);
      if (!hid) { rec.why = `create failed: HTTP ${created.status}`; results[base] = rec; log(`CUSTOM ${base} FAIL ${rec.why}`); continue; }

      // the skill and the disabled tool must be what the server stored, not just what was sent
      const back = await api(`/api/harness/v1/harnesses/${hid}`);
      const h = back.json || {};
      rec.skill_stored = ((h.skills || []).some((s) => (s.name || s.id) === 'matrix-stamp'));
      rec.tool_disabled_stored = (h.disabledTools || h.disabled_tools || []).includes('WebSearch');

      const t0 = Date.now();
      const turn = await api('/api/harness/v1/responses', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ input: 'Report this harness build stamp.', stream: false, store: true,
                               metadata: { harness_id: hid } }),
      });
      rec.turn_status = turn.status;
      const sid = turn.json && (turn.json.session_id || (turn.json.metadata || {}).session_id);
      rec.sid = sid || null;
      if (!sid) { rec.why = `no session: HTTP ${turn.status}`; results[base] = rec; log(`CUSTOM ${base} FAIL ${rec.why}`); continue; }

      let last = null;
      for (let i = 0; i < 140; i++) {
        await sleep(3000);
        const feed = await api(`/api/harness/v1/sessions/${sid}/turns`);
        const turns = (feed.json && feed.json.turns) || [];
        const t = turns[turns.length - 1];
        if (t && TERMINAL.has(String(t.status)) && (t.assistant || t.error)) { last = t; break; }
      }
      // produced files are attached a few seconds AFTER the turn goes terminal
      for (let i = 0; i < 12 && last && !(last.files || []).length; i++) {
        await sleep(3000);
        const feed = await api(`/api/harness/v1/sessions/${sid}/turns`);
        const turns = (feed.json && feed.json.turns) || [];
        last = turns[turns.length - 1] || last;
      }
      rec.s = Math.round((Date.now() - t0) / 1000);
      rec.status = last && last.status;
      const answer = String((last && last.assistant) || '');
      const files = ((last && last.files) || []).map((f) => f.filename || f.name || '');
      const tools = ((last && last.tools) || []).map((t) => String(t.name || ''));
      rec.files = files; rec.tools = tools;
      // a failed turn has to say why, or the row teaches nothing
      rec.error = String((last && (last.error || last.incomplete_reason)) || '').slice(0, 300);
      // the three claims, each read from the stored record
      rec.skill_reached = answer.includes(token);              // the bundle got to the agent
      rec.script_ran = files.some((f) => f.includes('stamp.txt'));  // its script actually executed
      rec.disabled_tool_unused = !tools.some((t) => /websearch/i.test(t));
      rec.ok = !!(rec.skill_stored && rec.tool_disabled_stored && rec.skill_reached && rec.script_ran && rec.disabled_tool_unused);
      rec.why = rec.ok ? '' : [
        rec.skill_stored ? '' : 'the skill was not stored on the harness',
        rec.tool_disabled_stored ? '' : 'the disabled tool was not stored',
        rec.skill_reached ? '' : `the answer does not carry the skill's stamp: ${answer.slice(-160)}`,
        rec.script_ran ? '' : `the skill's script left no file (files: ${files.join(',') || 'none'})`,
        rec.disabled_tool_unused ? '' : `a disabled tool was called: ${tools.join(',')}`,
        rec.error ? `the turn ended: ${rec.error}` : '',
      ].filter(Boolean).join('; ');
      log(`CUSTOM ${base} ${rec.ok ? 'ok' : 'FAIL'} ${rec.s}s ${rec.why}`);
      if (sid) await api(`/api/harness/v1/sessions/${sid}`, { method: 'DELETE' });
    } catch (e) {
      rec.error = String(e).slice(0, 300); log(`CUSTOM ${base} ERROR ${rec.error}`);
    } finally {
      if (hid) await api(`/api/harness/v1/harnesses/${hid}`, { method: 'DELETE' }).catch(() => {});
      results[base] = rec;
      await page.evaluate(([p, r]) => fetch(p, { method: 'POST' }).catch(() => r), ['/noop', null]).catch(() => {});
    }
  }
  const fs = await import('node:fs');
  fs.writeFileSync(RESULTS, JSON.stringify(results, null, 1));
  const ok = Object.values(results).filter((r) => r.ok).length;
  log(`CUSTOM_DONE ${ok} of ${Object.keys(results).length} bases carried their own skill, script and tool policy`);
} finally { await b.close(); }
