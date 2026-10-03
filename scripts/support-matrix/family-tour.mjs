// The model-family tour: ONE conversation, one deliverable, every model family in turn.
//
// What it proves (docs/harness-verification.md, "The family tour"): a harness keeps a working
// session while the model under it changes family after family. The first turn builds a small
// deliverable (a one-page .pptx); each following turn switches the composer's model to the next
// family and asks for one more change to the same deck. A turn passes when it completes and the
// deck is produced again; the tour passes when every family passes. This is the failure Richard
// found by hand on 2026-09-27 (a muse-spark turn misjudged after the CLI compacted its history),
// made a scenario, and it is required of every base in the matrix from here on.
//
// Drives the console as a person does: the composer, the model chip, Send; settles on the server's
// own turn record read through the console's proxy (the pill lags the record, run.mjs's lesson).
//
// Env: BASE, HR_USER, HR_PASS, HARNESS (a base id such as cheetahclaws, or a harness id), SID
// (optional: continue an existing conversation instead of starting one), FAMILIES (optional comma
// list of model ids, one per family; default below), RESULTS (json path), IGNORE_TLS=1.
import fs from 'node:fs';
import { chromium } from 'playwright';

const BASE = process.env.BASE, USER = process.env.HR_USER, PASS = process.env.HR_PASS;
const HARNESS = process.env.HARNESS || 'cheetahclaws';
const SID = process.env.SID || '';
const RESULTS = process.env.RESULTS || `family-tour-${HARNESS}.json`;
// A family's turn gets this long to settle. One that does not is stopped (the console's own Stop, then the
// API's cancel if the button is not there) and recorded as failed with what it had done by then, and
// the tour goes on: a model that cannot finish one small edit inside the cap fails its family, and it
// must not hold the conversation for the families after it (muse-spark-1.1 ran 95 tool calls in
// eleven minutes on 2026-09-27 and the tour stalled behind it).
const TURN_CAP_S = Number(process.env.TURN_CAP_S || 600);
// One model per family the catalog offers, cheapest member first where there is a choice.
const DEFAULT_FAMILIES = ['gpt-5.4-mini', 'claude-sonnet-5', 'gemini-3.5-flash', 'grok-4.5', 'muse-spark-1.1', 'llama-3.3-70b',
  'deepseek-v4-flash', 'kimi-k3', 'qwen3.8-flash', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash',
  'hunyuan-4-preview', 'nemotron-3.5-lightning'];
const FAMILIES = (process.env.FAMILIES || DEFAULT_FAMILIES.join(',')).split(',').map((s) => s.trim()).filter(Boolean);
const FIRST = 'Build a one-page PowerPoint file named tour.pptx: a title "Hello, World." and one line of code print("Hello, world!") under it. Reply with one line saying what you made.';
const EDITS = [
  'Change the title to bold and make it dark blue.', 'Add a subtitle under the title: "Where every developer\'s journey begins".',
  'Move the code line into a rounded light-grey box.', 'Change the slide background to a warm off-white.',
  'Make the code line monospace and slightly larger.', 'Add a small footer with today\'s date on the right.',
  'Put a thin blue bar across the top of the slide.', 'Change the title colour to dark green.',
  'Add a second line of code below the first: print("Bye, world!").', 'Center the whole content block vertically.',
  'Make the subtitle italic.', 'Give the code box a soft shadow.', 'Change the footer text to "Slide 1 of 1".', 'Make the title larger.',
];
const log = (...a) => console.log(new Date().toISOString(), ...a);
const H = { 'content-type': 'application/json', 'x-harness-org': 'local', 'x-harness-member': 'local@localhost', 'x-harness-workspace': 'default', 'x-harness-workspace-default': '1' };

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: process.env.IGNORE_TLS === '1' })).newPage();
const api = (method, path, body) => page.evaluate(async ({ method, path, body, H }) => {
  const r = await fetch('/api/harness' + path, { method, headers: H, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, j: await r.json().catch(() => null) };
}, { method, path, body, H });

await page.goto(BASE + '/login', { waitUntil: 'load' });
await page.fill('#sh-user', USER); await page.fill('#sh-pass', PASS);
await page.waitForSelector('button.sh-login-go:not([disabled])'); await page.click('button.sh-login-go');
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30000 });

let sid = SID;
await page.goto(`${BASE}/harnesses?h=${encodeURIComponent(HARNESS)}${sid ? '&sid=' + sid : ''}`, { waitUntil: 'load' });
await page.waitForSelector('textarea.wbx-composer-input', { timeout: 30000 });

/** The last turn's server record, once it has settled. */
// `done` is the live record's word for a turn that has just finished and may still be half-written (the
// gateway maps it to completed on the response); a record read at that instant is not settled yet.
const RUNNING = ['running', 'starting', 'in_progress', 'queued', 'done'];
async function lastTurn(sidNow) { const r = await api('GET', `/v1/sessions/${sidNow}/turns`); const turns = r.j?.turns || []; return { turns, last: turns[turns.length - 1], rid: r.j?.last_response_id }; }
async function settle(sidNow, turnsBefore, timeoutS = TURN_CAP_S) {
  const t0 = Date.now();
  while ((Date.now() - t0) / 1000 < timeoutS) {
    const { turns, last } = await lastTurn(sidNow);
    if (turns.length > turnsBefore && last && !RUNNING.includes(last.status)) return { last, count: turns.length, seconds: Math.round((Date.now() - t0) / 10) / 100, timedOut: false };
    await page.waitForTimeout(3000);
  }
  // over the cap: stop it, then read what it had done
  const stop = page.locator('button.wbx-stop, button:has-text("Stop")').first();
  if (await stop.count()) await stop.click().catch(() => undefined);
  else { const { rid } = await lastTurn(sidNow); if (rid) await api('POST', `/v1/responses/${rid}/cancel`, {}); }
  for (let i = 0; i < 30; i++) { const { last } = await lastTurn(sidNow); if (last && !RUNNING.includes(last.status)) break; await page.waitForTimeout(2000); }
  await page.locator('textarea.wbx-composer-input:not([disabled])').waitFor({ timeout: 60000 }).catch(() => undefined);
  const { turns, last } = await lastTurn(sidNow);
  return { last, count: turns.length, seconds: timeoutS, timedOut: true };
}
async function chooseModel(model) {
  await page.locator('button.ar2-chip[aria-haspopup="listbox"]').first().click();
  const opt = page.locator('button.wbx-model-opt', { hasText: new RegExp('^' + model.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\s|$)') }).first();
  // a model the picker does not offer at all (not mapped on this instance) is "not offered", the
  // same as a disabled one; the tour goes on and keeps what it has measured
  try { await opt.waitFor({ timeout: 10000 }); } catch { await page.keyboard.press('Escape'); return false; }
  const disabled = await opt.isDisabled();
  if (disabled) { await page.keyboard.press('Escape'); return false; }
  await opt.click();
  return true;
}
async function sendTurn(text) {
  const turnsBefore = sid ? ((await api('GET', `/v1/sessions/${sid}/turns`)).j?.turns || []).length : 0;
  await page.fill('textarea.wbx-composer-input', text);
  await page.locator('button.wbx-send').click();
  if (!sid) { await page.waitForURL((u) => u.searchParams.get('sid'), { timeout: 30000 }); sid = new URL(page.url()).searchParams.get('sid'); }
  return settle(sid, turnsBefore);
}

const results = { harness: HARNESS, session: '', started: new Date().toISOString(), turns: [] };
let editIdx = Number(process.env.EDIT_START || 0);
if (!SID) {
  log('FIRST', HARNESS);
  const s = await sendTurn(FIRST);
  results.session = sid;
  const ok = !s.timedOut && s.last?.status === 'completed' && (s.last.files || []).some((f) => /\.pptx$/i.test(f.filename || f.name || ''));
  results.turns.push({ family: 'first', model: s.last?.model, served: s.last?.served_model, status: s.last?.status, seconds: s.seconds, files: (s.last?.files || []).map((f) => f.filename || f.name), ok, error: s.last?.error || '' });
  log('FIRST', ok ? 'ok' : 'FAIL', s.last?.status, s.seconds + 's', s.last?.error || '');
  if (!ok) { fs.writeFileSync(RESULTS, JSON.stringify(results, null, 1)); log('TOUR_ABORTED the first turn did not produce the deck'); await browser.close(); process.exit(2); }
} else { results.session = sid; }

// What this harness's composer will actually offer, from the per-harness view the composer itself
// renders. /v1/bases is the wrong source: it answers "a configured integration could serve this id"
// without applying the effective model map, so on a vercel-only instance it reported
// llama-4-maverick available while the picker had no such option (2026-09-29) and a tour pointed at
// it waited ten seconds for an option that could never appear. A family this instance does not offer
// is recorded as "not offered" BEFORE the picker is opened, rather than by timing out inside it.
const offered = await (async () => {
  try {
    const r = await page.evaluate(async (h) => {
      const res = await fetch(`/api/harness/v1/harnesses/${encodeURIComponent(h)}/models`);
      return res.ok ? await res.json() : null;
    }, HARNESS);
    const ids = ((r && (r.models || r.items)) || []).filter((m) => m && m.available !== false)
      .map((m) => String(m.id || m));
    return ids.length ? new Set(ids) : null;   // null = could not read it; fall back to the picker
  } catch { return null; }
})();

for (const model of FAMILIES) {
  if (offered && !offered.has(model)) {
    results.turns.push({ family: model, model, status: 'not offered', ok: false, seconds: 0 });
    log('SKIP', model, 'not offered by this harness'); continue;
  }
  const picked = await chooseModel(model);
  if (!picked) { results.turns.push({ family: model, model, status: 'not offered', ok: false, seconds: 0 }); log('SKIP', model, 'not available on this instance'); continue; }
  // Every edit carries a stamp no earlier turn could have made, so "already done, no change
  // needed" is never a correct answer and a completed turn must write the deck: on 2026-09-27 two
  // families were asked for changes earlier families had made and rightly wrote nothing.
  const stamp = `tour ${model} ${++editIdx}`;
  const edit = `${EDITS[(editIdx - 1) % EDITS.length]} Also set the slide's footer text to exactly "${stamp}". Keep it in tour.pptx.`;
  const s = await sendTurn(edit);
  const ok = !s.timedOut && s.last?.status === 'completed' && (s.last.files || []).some((f) => /\.pptx$/i.test(f.filename || f.name || ''));
  const deck = (s.last?.files || []).some((f) => /\.pptx$/i.test(f.filename || f.name || ''));
  const row = { family: model, model: s.last?.model, served: s.last?.served_model,
    status: s.timedOut ? `not settled in ${TURN_CAP_S}s, stopped (${s.last?.status})` : (s.last?.status === 'completed' && !deck ? 'completed, deck not produced' : s.last?.status),
    seconds: s.seconds, edit, tool_calls: (s.last?.tools || []).length, files: (s.last?.files || []).map((f) => f.filename || f.name), ok, error: s.last?.error || '' };
  results.turns.push(row);
  log(ok ? 'PASS' : 'FAIL', model, '->', row.status, s.seconds + 's', 'served', s.last?.served_model || '', 'tool calls', row.tool_calls, s.last?.error ? '| ' + s.last.error.slice(0, 160) : '', ok ? '' : '| files ' + JSON.stringify(row.files));
  fs.writeFileSync(RESULTS, JSON.stringify(results, null, 1));
}
const passed = results.turns.filter((t) => t.family !== 'first' && t.ok).length, ran = results.turns.filter((t) => t.family !== 'first' && t.status !== 'not offered').length;
results.summary = `${passed} of ${ran} families passed in one conversation (${results.session})`;
fs.writeFileSync(RESULTS, JSON.stringify(results, null, 1));
log('TOUR_DONE', results.summary);
await browser.close();
// a tour in which no family ran proved nothing: every id skipped as "not offered" is a failure to measure
process.exit(ran > 0 && passed === ran ? 0 : 1);
