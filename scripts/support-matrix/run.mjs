// Support matrix runner: harness x model x provider x {first, followup, switch, artifact, recycle}.
// Drives the console as one user; one task at a time per worker; resumable (pairs already complete
// in the results file are skipped). Env: BASE, HR_USER, HR_PASS, HARNESSES (comma), PROVIDER
// (a label for the column), RESULTS (json path), LOG (append log), MODELS (optional comma filter of the
// pairs to run), PROVIDER_MODELS (the column's own model table, which bounds the switch partner),
// IGNORE_TLS=1 for a self-signed instance.
import { chromium } from 'playwright';
import fs from 'node:fs';
const BASE = process.env.BASE, PROVIDER = process.env.PROVIDER, RESULTS = process.env.RESULTS, LOG = process.env.LOG;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (s) => { const line = `${new Date().toISOString()} ${s}`; console.log(line); fs.appendFileSync(LOG, line + '\n'); };
const load = () => { try { return JSON.parse(fs.readFileSync(RESULTS, 'utf8')); } catch { return {}; } };
const save = (r) => fs.writeFileSync(RESULTS, JSON.stringify(r, null, 1));
const key = (h, m) => `${PROVIDER}|${h}|${m}`;
async function rt(p, s, v) { await p.$eval(s, (el, x) => { const P = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement; Object.getOwnPropertyDescriptor(P.prototype, 'value').set.call(el, x); el.dispatchEvent(new Event('input', { bubbles: true })); }, v); }
const b = await chromium.launch({ headless: true });
const page = await (await b.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: process.env.IGNORE_TLS === '1' })).newPage();
const pill = () => page.evaluate(() => document.querySelector('.hx-pill')?.textContent?.trim().toLowerCase() || '');
const transcript = () => page.evaluate(() => (document.querySelector('.wbx-conv-msgs')?.innerText || '').replace(/\s+/g, ' '));
const files = () => page.evaluate(() => [...document.querySelectorAll('.wbx-filecard-name')].map((x) => x.textContent.trim()));
// a modal that took over the page mid-turn (an in-app alert); the first-visit welcome is dismissed at login
const door = () => page.evaluate(() => document.querySelector('[role=dialog]:not(.welcome-overlay)')?.innerText?.replace(/\s+/g, ' ').trim() || '');
const dismissWelcome = async () => { for (let i = 0; i < 4 && (await page.locator('.welcome-overlay').count()); i++) { await page.locator('.welcome-overlay .welcome-wide-close').click().catch(() => {}); await sleep(600); } };
const TERMINAL = new Set(['done', 'completed', 'failed', 'error', 'cancelled', 'incomplete', 'max_turns', 'timeout']);
const LIVE = new Set(['running', 'starting', 'in_progress', 'queued']);
const sidOf = () => new URL(page.url()).searchParams.get('sid') || '';
// the server's own record, read through the console's proxy (same cookie). The session detail is
// the cheap read (vertex plus card) and is what the wait polls; the turns feed rebuilds a live turn
// from its trace chunks on every read, so it is read only once the turn has settled.
const detailOf = (sid) => page.evaluate(async (s) => { const r = await fetch(`/api/harness/v1/sessions/${s}`); return r.ok ? await r.json() : null; }, sid).catch(() => null);
const turnsOf = (sid) => page.evaluate(async (s) => { const r = await fetch(`/api/harness/v1/sessions/${s}/turns`); return r.ok ? ((await r.json()).turns || []) : null; }, sid).catch(() => null);
// send one message on the open session and wait for it to settle; returns the outcome. The turn
// settles on the server's word, not on the task pill: the pill reads the task card, which lands a
// while after the turn does, and a turn scored off it was scored off the previous turn.
async function turn(text, { maxS = 420, expectFiles = false } = {}) {
  const t0 = Date.now(); const secs = () => Math.round((Date.now() - t0) / 10) / 100;
  const mark = text.slice(0, 60);
  // the composer refuses a message while the previous turn's stream is still open (its Send is
  // disabled): wait for it to take input again, or the message is dropped on the floor
  const ready = () => page.evaluate(() => { const b = document.querySelector('.wbx-composer .wbx-send, .wbx-composer .uic-send'); const ta = document.querySelector('.wbx-composer textarea'); return !!ta && !ta.disabled && !!b && !b.disabled; });
  const sid0 = sidOf(); const n0 = sid0 ? ((await turnsOf(sid0)) || []).length : 0;
  const before = await transcript(); const sentAt = () => transcript().then((t) => t.lastIndexOf(mark));
  // send, and see the message land in the transcript (the console shows it at once); a message a
  // re-render swallowed (a model pick rebuilds the composer) is typed and sent once more
  let shown = false;
  for (let attempt = 0; attempt < 2 && !shown; attempt++) {
    await page.fill('.wbx-composer textarea, textarea', text);
    let canSend = await ready(); for (let i = 0; i < 90 && !canSend; i++) { await sleep(1000); canSend = await ready(); }
    if (!canSend) return { ok: false, s: secs(), tail: '', why: 'the composer stayed busy for 90 s after the previous turn settled' };
    await page.keyboard.press('Enter');
    for (let i = 0; i < 10 && !shown; i++) { await sleep(1000); shown = (await sentAt()) >= before.lastIndexOf(mark) + 1 || ((await sentAt()) >= 0 && before.lastIndexOf(mark) < 0); }
  }
  if (!shown) return { ok: false, s: secs(), tail: '', why: 'the message never appeared in the transcript after two sends' };
  // taken: the server opened a turn for it (a new task gets its session id in the URL first)
  let sid = sid0, d = null, taken = false, n1 = n0;
  for (let i = 0; i < 60 && !taken; i++) { await sleep(2000); sid = sid || sidOf(); if (!sid) continue; d = await detailOf(sid); if (LIVE.has(String(d?.turn_status || d?.status || ''))) taken = true; else if (i % 5 === 4) { const ts = await turnsOf(sid); n1 = ts ? ts.length : n1; taken = n1 > n0; } }
  if (!taken) return { ok: false, s: secs(), tail: '', why: 'the message was not taken: the session never opened a turn in 120 s' };
  // settle on the session's status; then the turns feed, until the new turn's answer (or reason)
  // and the produced files are stored: the status lands a moment before the output does
  let st = '';
  for (let i = 0; i < maxS / 3; i++) { await sleep(3000); const dr = await door(); if (dr) return { ok: false, s: secs(), tail: '', why: 'door: ' + dr.slice(0, 160) }; d = await detailOf(sid); st = String(d?.turn_status || d?.status || ''); if (TERMINAL.has(st)) break; }
  let last = null, turns = null;
  // the record must be THIS message's: a send refused at the door leaves the previous turn's record in place
  for (let i = 0; i < 10; i++) { turns = await turnsOf(sid); last = turns && turns.length > n0 && String((turns[turns.length - 1] || {}).user || '').trim() === text.trim() ? turns[turns.length - 1] : null; const stored = !!(last && TERMINAL.has(String(last.status)) && (last.assistant || last.error || last.incomplete_reason || (last.files || []).length)); if (stored && (!expectFiles || (last.files || []).length)) break; await sleep(3000); }
  // then let the console render what the server stored
  const head = String(last?.assistant || '').replace(/\s+/g, ' ').trim().slice(0, 40);
  for (let i = 0; i < 12; i++) { const t = await transcript(); const from = t.lastIndexOf(mark); if (!/Working…/.test(t.slice(from)) && (!head || t.slice(from).includes(head))) break; await sleep(1500); }
  await sleep(1500);
  const t = await transcript(); const from = t.lastIndexOf(mark); const tail = t.slice(from >= 0 ? from : before.length).trim().slice(-400);
  const status = String(last?.status || (turns && turns.length > n0 ? st : 'none'));
  const ok = status === 'done' || status === 'completed';
  return { ok, status, pill: await pill(), s: secs(), tail, turn_files: (last?.files || []).map((f) => f.filename || f.name || ''), why: ok ? '' : (last?.error || last?.incomplete_reason || tail.slice(-220) || `status ${status}`) };
}
const expectWord = (r, word) => r.ok && (r.tail || '').includes(word) ? r : { ...r, ok: false, why: r.why || `answered without ${word}: ${(r.tail || '').slice(-200)}` };
try {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2500);
  if (page.url().includes('/login')) {
    await rt(page, '#sh-user', process.env.HR_USER || 'harnessrouter'); await rt(page, '#sh-pass', process.env.HR_PASS);
    await page.click('button[type=submit]'); await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000 });
  }
  await sleep(1500); await dismissWelcome();
  for (const h of process.env.HARNESSES.split(',')) {
    await page.goto(`${BASE}/harnesses?h=${h}`, { waitUntil: 'domcontentloaded' }); await sleep(3500); await dismissWelcome();
    for (let i = 0; i < 10 && !(await page.locator('.wbx-conv-main.is-hero').count()); i++) { await page.click('button:has-text("New task")').catch(() => {}); await sleep(800); }
    // the menu starts from the console's placeholder list and takes the gateway's catalog when it
    // lands: the catalog says how many models this harness serves, so wait until the menu has them
    const backend = h === 'claude-code' ? 'claude' : h;
    const served = await page.evaluate(async (b) => { const r = await fetch('/api/harness/v1/models'); const j = await r.json(); return ((((j || {}).backends || {})[b] || {}).models || []).length; }, backend).catch(() => 0);
    const readMenu = () => page.evaluate(() => [...document.querySelectorAll('.wbx-model-opt')].map((o) => ({ id: o.querySelector('span')?.textContent.trim(), ok: !o.disabled })));
    await page.click('.ar2-chip'); await sleep(600);
    let models = await readMenu();
    for (let i = 0; i < 40 && models.length < served; i++) { await page.keyboard.press('Escape'); await sleep(1500); await page.click('.ar2-chip'); await sleep(400); models = await readMenu(); }
    if (models.length < served) log(`MENU ${h} shows ${models.length} of ${served} served models after 60 s`);
    await page.keyboard.press('Escape'); await sleep(300);
    // MODELS pins which PAIRS run (a re-run of the missing ones); the switch scenario still needs another
    // model this harness can run, so the switch target comes from the whole runnable list, not the pinned one.
    // PROVIDER_MODELS is the column's own table: a switch partner outside it would run on another
    // provider through the map's fallback, and a session that changes provider is not what any row measures
    const scope = process.env.PROVIDER_MODELS ? new Set(process.env.PROVIDER_MODELS.split(',')) : null;
    const runnableAll = models.filter((m) => m.ok && (!scope || scope.has(m.id))).map((m) => m.id);
    const enabled = runnableAll.filter((id) => !process.env.MODELS || process.env.MODELS.split(',').includes(id));
    log(`HARNESS ${h} models ${models.length} runnable ${enabled.length}: ${enabled.join(',')}`);
    for (const m of enabled) {
      const res = load(); const k = key(h, m);
      if (res[k] && res[k].recycle && !res[k].error) { log(`SKIP ${k} (done)`); continue; }   // a runner error is not a result
      const rec = res[k] || { provider: PROVIDER, harness: h, model: m, at: new Date().toISOString() };
      try {
        await page.goto(`${BASE}/harnesses?h=${h}`, { waitUntil: 'domcontentloaded' }); await sleep(3000);
        for (let i = 0; i < 10 && !(await page.locator('.wbx-conv-main.is-hero').count()); i++) { await page.click('button:has-text("New task")').catch(() => {}); await sleep(800); }
        await page.click('.ar2-chip'); await sleep(500); await page.locator('.wbx-model-opt', { hasText: m }).first().click(); await sleep(300);
        rec.first = expectWord(await turn(`Reply with exactly: M1-${m}`), `M1-${m}`); rec.sid = new URL(page.url()).searchParams.get('sid') || '';
        log(`FIRST ${k} ${rec.first.ok ? 'ok' : 'FAIL'} ${rec.first.s}s ${rec.first.why}`);
        if (rec.first.ok) {
          rec.followup = expectWord(await turn(`Reply with exactly: M2-${m}`), `M2-${m}`);
          log(`FOLLOWUP ${k} ${rec.followup.ok ? 'ok' : 'FAIL'} ${rec.followup.s}s ${rec.followup.why}`);
          // the partner must be one Codex can carry on with: gpt-5.3-codex and the gpt-5.6 line refuse each
          // other's threads by design (#73), and that rule is not what the switch row measures
          // Codex refuses gpt-5.3-codex after any other model (measured after gpt-5.5 and after the gpt-5.6
          // line), so a switch away and back can only fail by design: that row is n/a, not a measurement
          const conflicts = (a, c) => a === 'gpt-5.3-codex' || c === 'gpt-5.3-codex';
          const other = runnableAll.find((x) => x !== m && !conflicts(m, x)) || null;
          if (other) { await page.click('.ar2-chip'); await sleep(500); await page.locator('.wbx-model-opt', { hasText: other }).first().click(); await sleep(300); rec.switch = { to: other, ...expectWord(await turn(`Reply with exactly: M3-${other}`), `M3-${other}`) }; }
          else rec.switch = { to: null, ok: null, why: 'only one model' };
          log(`SWITCH ${k} -> ${other} ${rec.switch.ok ? 'ok' : rec.switch.ok === null ? 'n/a' : 'FAIL'} ${rec.switch.s || ''}s ${rec.switch.why || ''}`);
          if (other) { await page.click('.ar2-chip'); await sleep(500); await page.locator('.wbx-model-opt', { hasText: m }).first().click(); await sleep(300); }
          const a = await turn(`Create a file named hello-${h}.txt containing exactly the word HELLO, then reply DONE.`, { expectFiles: true });
          // the file cards render from the settled read, a moment after the answer
          let fl = await files(); for (let i = 0; i < 10 && fl.length < (a.turn_files || []).length; i++) { await sleep(1500); fl = await files(); }
          rec.artifact = { ...a, files: fl, ok: a.ok && fl.some((f) => f.includes(`hello-${h}.txt`)), why: a.ok && !fl.some((f) => f.includes(`hello-${h}.txt`)) ? `no file card (files: ${fl.join(',') || 'none'}); ${a.tail.slice(-160)}` : a.why };
          log(`ARTIFACT ${k} ${rec.artifact.ok ? 'ok' : 'FAIL'} ${rec.artifact.s}s ${rec.artifact.why}`);
          // the sandbox is let go on purpose (what the pool does between visits) and the next turn must
          // carry on from the durable checkpoint: the history, the files, the resume id
          // the route refuses with 409 while the previous turn is still settling: ask again a few times
          let rc = { code: 0, body: '' };
          for (let i = 0; i < 6; i++) { rc = await page.evaluate(async (sid) => { const r = await fetch(`/api/harness/internal/sessions/${sid}/recycle`, { method: 'POST' }); return { code: r.status, body: (await r.text()).slice(0, 200) }; }, rec.sid); if (rc.code !== 409) break; await sleep(5000); }
          if (rc.code === 200) {
            await sleep(2000);
            const r5 = await turn('What exact word did I ask you to reply with in my very first message of this task? Reply with just that word.');
            rec.recycle = expectWord(r5, `M1-${m}`); rec.recycle.recycled = rc;
          } else rec.recycle = { ok: false, s: 0, why: `recycle refused: HTTP ${rc.code} ${rc.body}`, recycled: rc };
          log(`RECYCLE ${k} ${rec.recycle.ok ? 'ok' : 'FAIL'} ${rec.recycle.s}s ${rec.recycle.why}`);
        } else { rec.followup = { ok: null, why: 'first turn failed' }; rec.switch = { ok: null, why: 'first turn failed' }; rec.artifact = { ok: null, why: 'first turn failed' }; rec.recycle = { ok: null, why: 'first turn failed' }; }
      } catch (e) { rec.error = String(e).slice(0, 300); log(`ERROR ${k} ${rec.error}`); if (/has been closed/.test(rec.error)) throw e; }   // a closed browser ends the worker; the next launch resumes
      // the record is complete: stamp the connection that served it, then let the session go. Its
      // workspace, checkpoint and trace are of no further use, and 170 of them per provider filled
      // a 62 GB disk (hr-oss-test, 2026-09-06).
      if (rec.sid) {
        const d = await page.evaluate(async (sid) => { const r = await fetch(`/api/harness/v1/sessions/${sid}`); return r.ok ? await r.json() : null; }, rec.sid).catch(() => null);
        if (d && d.last_connection) rec.connection = String(d.last_connection);
        // every turn record's own stamp, so a pair served by more than one connection is visible: when
        // EXPECT_CONNECTION names the connection under test, any other one is a finding of its own
        const ts = await page.evaluate(async (sid) => { const r = await fetch(`/api/harness/v1/sessions/${sid}/turns`); return r.ok ? await r.json() : null; }, rec.sid).catch(() => null);
        const turnsList = Array.isArray(ts) ? ts : (ts && Array.isArray(ts.turns) ? ts.turns : []);
        rec.connections = [...new Set(turnsList.map((t) => t && t.connection).filter(Boolean).map(String))];
        // the model each turn record says the CLI actually ran (gemini-cli reports it; it rewrites some
        // requested ids): a served model other than the pair's id is a substitution, a finding of its own
        rec.served = [...new Set(turnsList.map((t) => t && t.served_model).filter(Boolean).map(String))];
        // judged per turn against what THAT turn asked for: the switch scenario runs a partner model on
        // purpose, and its served name is not a substitution of this pair's id. A feed without the
        // per-turn model (older gateways) falls back to the pair's id never being served at all.
        const withModel = turnsList.filter((t) => t && t.served_model && t.model);
        rec.substituted = withModel.length
          ? [...new Set(withModel.filter((t) => t.model === m && String(t.served_model).split(',').some((x) => x && x !== m)).map((t) => String(t.served_model)))]
          : (rec.served.length && !rec.served.some((sm) => sm.split(',').includes(m)) ? rec.served : []);
        if (process.env.EXPECT_CONNECTION) rec.foreign = rec.connections.filter((c) => c !== process.env.EXPECT_CONNECTION);
        rec.deleted = await page.evaluate(async (sid) => { const r = await fetch(`/api/harness/v1/sessions/${sid}`, { method: 'DELETE' }); return r.status; }, rec.sid).catch(() => 0);
      }
      const all = load(); all[k] = rec; save(all); log(`PAIR_DONE ${k} connection=${rec.connection || '?'} turns=${(rec.connections || []).join('+') || '?'}${(rec.foreign || []).length ? ' FOREIGN=' + rec.foreign.join('+') : ''}${(rec.served || []).length ? ' served=' + rec.served.join('+') : ''}${(rec.substituted || []).length ? ' SUBSTITUTED=' + rec.substituted.join('+') : ''} deleted=${rec.deleted || '?'}`);
    }
  }
} catch (e) { log(`FATAL ${String(e).slice(0, 300)}`); }
await b.close(); log(`WORKER_DONE ${process.env.HARNESSES}`);
