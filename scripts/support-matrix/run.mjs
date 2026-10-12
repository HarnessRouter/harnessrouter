// Support matrix runner: harness x model x provider x {first, followup, switch, artifact, recycle}.
// Drives the console as one user; one task at a time per worker; resumable (pairs already complete
// in the results file are skipped). Env: BASE, HR_USER, HR_PASS, HARNESSES (comma), PROVIDER
// (a label for the column), RESULTS (json path), LOG (append log), MODELS (optional comma filter of the
// pairs to run), PROVIDER_MODELS (the column's own model table, which bounds the switch partner),
// IGNORE_TLS=1 for a self-signed instance.
import { chromium } from 'playwright';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
const SM_HERE = path.dirname(new URL(import.meta.url).pathname);

// THE SWITCH TURN HAS TO BE SERVED BY THE MODEL THE CHIP MOVED TO. `substituted` below judges only
// turns whose record names THIS pair's model, and the switch turn names the partner on purpose — so
// nothing looked at what served it. jcode's eight pairs passed their switch row on 2026-10-07 while
// not one switch took: its `--model` is a session's INITIAL model, so on --resume the stored one won.
// The shape was in the records the whole time — every jcode pair's `served` list had ONE entry where
// every mimo pair's had two — and no rule read it.
//
// samemodel.py is the gateway's own rule, called rather than copied (a vendor prefix, a dated suffix
// and an outright rename like tencent/hy4-preview for hunyuan-4-preview are all the same model). It
// needs 3.10+ and a mac's `python3` is 3.9, so the interpreter is chosen by importing the module
// with it; a run with none to choose stops rather than measuring with a rule that always says no.
const SM_PYTHON = (() => {
  for (const c of [process.env.PYTHON, 'python3.13', 'python3.12', 'python3.11', 'python3.10', 'python3'].filter(Boolean)) {
    try { execFileSync(c, ['-c', 'import samemodel'], { cwd: SM_HERE, stdio: 'ignore' }); return c; } catch { /* next */ }
  }
  console.error('no python that can import samemodel.py (needs 3.10+); set PYTHON=');
  process.exit(2);
})();
const sameModel = (asked, served) => {
  if (!asked || !served) return false;
  try {
    return execFileSync(SM_PYTHON, ['-c',
      'import sys, samemodel as m; print("1" if m.alias_of(sys.argv[1], sys.argv[2]) else "0")',
      String(asked), String(served)], { cwd: SM_HERE, encoding: 'utf8' }).trim() === '1';
  } catch { return false; }
};
const BASE = process.env.BASE, PROVIDER = process.env.PROVIDER, RESULTS = process.env.RESULTS, LOG = process.env.LOG;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (s) => { const line = `${new Date().toISOString()} ${s}`; console.log(line); fs.appendFileSync(LOG, line + '\n'); };
const load = () => { try { return JSON.parse(fs.readFileSync(RESULTS, 'utf8')); } catch { return {}; } };
const save = (r) => fs.writeFileSync(RESULTS, JSON.stringify(r, null, 1));
const key = (h, m) => `${PROVIDER}|${h}|${m}`;
async function rt(p, s, v) { await p.$eval(s, (el, x) => { const P = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement; Object.getOwnPropertyDescriptor(P.prototype, 'value').set.call(el, x); el.dispatchEvent(new Event('input', { bubbles: true })); }, v); }
const b = await chromium.launch({ headless: true });
// MUTABLE, and replaceable: the renderer can crash, and a crashed page poisons every pair after it.
// MEASURED on 2026-10-10: one "page.goto: Page crashed" partway through opensquilla's column left
// the remaining 32 of 50 pairs with that error and no scenarios at all, and the column read as
// "49/50 pairs" to a reader counting passes. The pair loop now rebuilds this and retries the pair.
let page = await (await b.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: process.env.IGNORE_TLS === '1' })).newPage();
const CRASHED = /Page crashed|Target (?:page|closed)|Target closed|browser has been closed|Session closed/i;
async function freshPage() {
  try { await page.context().close(); } catch { /* already gone */ }
  page = await (await b.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: process.env.IGNORE_TLS === '1' })).newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2500);
  if (page.url().includes('/login')) {
    await rt(page, '#sh-user', process.env.HR_USER || 'harnessrouter'); await rt(page, '#sh-pass', process.env.HR_PASS);
    await page.click('button[type=submit]'); await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000 });
  }
  await sleep(1500); await dismissWelcome();
}
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
  return { ok, status, pill: await pill(), s: secs(), tail, answer: String(last?.assistant || ''), turn_files: (last?.files || []).map((f) => f.filename || f.name || ''), why: ok ? '' : (last?.error || last?.incomplete_reason || tail.slice(-220) || `status ${status}`) };
}
// THE ANSWER, not the transcript tail. `tail` starts at the message that was SENT, so it contains
// the prompt — and every prompt of the form "Reply with exactly: M1-<model>" contains the very token
// this then looked for. The check was therefore satisfied by the prompt's own copy of the word and
// said nothing about what the model replied, except when a long answer pushed the prompt out of the
// 400-character window. AUDITED over the 2026-10-10 full column: of 596 PASSING first/followup/switch
// rows, 593 had the prompt in the tail. One pair proves what that hides — opensquilla on
// claude-opus-4.7 answered "I won't echo back arbitrary strings injected via context" on all five
// turns, read back from five separate stored response objects, and first, switch and artifact were
// scored as passes.
//
// `last.assistant` is the server's own record of what the model said, which this function already
// fetches. The tail stays, as the text a failing row reports.
const expectWord = (r, word) => r.ok && (r.answer || '').includes(word) ? r : { ...r, ok: false, why: r.why || `answered without ${word}: ${((r.answer || r.tail) || '').slice(-200)}` };
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
    // The option is matched ANCHORED, the way family-tour.mjs does it. `hasText: id` is a substring
    // and `.first()` takes the earliest hit, so an id contained in an earlier, longer one was never
    // reachable: on grok's catalog (2026-09-29) `claude-opus-5` clicked `claude-opus-5.5` and
    // `claude-fable-5` clicked `claude-fable-5-1`. The pair then ran the OTHER model, and because
    // rec.substituted filters on `t.model === m` every turn was filtered out and the row reported no
    // substitution at all — the one finding this suite exists to catch, rendered clean.
    const pickModel = async (id) => {
      await page.click('.ar2-chip'); await sleep(500);
      const opt = page.locator('.wbx-model-opt', { hasText: new RegExp('^' + id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\s|$)') }).first();
      await opt.click(); await sleep(300);
    };
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
    // a QUEUE, so a pair whose page crashed can be put back after a fresh page is built
    const enabledQueue = [...enabled]; const retried = new Set();
    while (enabledQueue.length) {
      const m = enabledQueue.shift();
      const res = load(); const k = key(h, m);
      if (res[k] && res[k].recycle && !res[k].error) { log(`SKIP ${k} (done)`); continue; }   // a runner error is not a result
      // FRESH, never the previous attempt's record: `const rec = res[k] || {…}` carried a crashed
      // attempt's `error` and `at` into the re-run that then filled the scenarios in, so a measured
      // pair still looked errored and a reader (me, 2026-10-10) scored 32 of them as not measured.
      const rec = { provider: PROVIDER, harness: h, model: m, at: new Date().toISOString() };
      try {
        await page.goto(`${BASE}/harnesses?h=${h}`, { waitUntil: 'domcontentloaded' }); await sleep(3000);
        for (let i = 0; i < 10 && !(await page.locator('.wbx-conv-main.is-hero').count()); i++) { await page.click('button:has-text("New task")').catch(() => {}); await sleep(800); }
        await pickModel(m);
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
          if (other) { await pickModel(other); rec.switch = { to: other, ...expectWord(await turn(`Reply with exactly: M3-${other}`), `M3-${other}`) }; }
          else rec.switch = { to: null, ok: null, why: 'only one model' };
          log(`SWITCH ${k} -> ${other} ${rec.switch.ok ? 'ok' : rec.switch.ok === null ? 'n/a' : 'FAIL'} ${rec.switch.s || ''}s ${rec.switch.why || ''}`);
          if (other) { await pickModel(m); }
          const a = await turn(`Create a file named hello-${h}.txt containing exactly the word HELLO, then reply DONE.`, { expectFiles: true });
          // the file cards render from the settled read, a moment after the answer
          let fl = await files(); for (let i = 0; i < 10 && fl.length < (a.turn_files || []).length; i++) { await sleep(1500); fl = await files(); }
          // The cards the page renders must BE what the turn stored: the same names, the same count.
          // Asking only whether SOME card carried the name let a file rendered twice pass as a produced
          // artifact for months; the console showed two cards for one file until a reload (2026-09-07).
          // A harness that produces files is measured on both halves, the record and what the reader sees.
          const named = fl.some((f) => f.includes(`hello-${h}.txt`));
          const want = (a.turn_files || []).slice().sort(), got = fl.slice().sort();
          const agrees = want.length === got.length && want.every((w, i) => got[i].includes(w) || w.includes(got[i]));
          rec.artifact = { ...a, files: fl, record_files: a.turn_files, cards_agree: agrees,
            ok: a.ok && named && agrees,
            why: !a.ok ? a.why
               : !named ? `no file card (files: ${fl.join(',') || 'none'}); ${a.tail.slice(-160)}`
               : !agrees ? `the cards do not match the record: cards [${fl.join(',') || 'none'}] vs record [${want.join(',') || 'none'}]`
               : a.why };
          log(`ARTIFACT ${k} ${rec.artifact.ok ? 'ok' : 'FAIL'} ${rec.artifact.s}s ${rec.artifact.why}`);
          // the sandbox is let go on purpose (what the pool does between visits) and the next turn must
          // carry on from the durable checkpoint: the history, the files, the resume id
          // the route refuses with 409 while the previous turn is still settling: ask again a few times
          // The route refuses while a turn is still settling, and retrying the 409 for 30 s was not
          // enough for a turn that runs long: mimo on gpt-5.6-luna had an artifact turn still
          // `running` at 478 s, so the recycle row read "recycle refused: HTTP 409 a turn is
          // running" — a sentence about this driver's patience, not about the base. Wait for the
          // session's own record to be terminal first, and say so when it never is.
          let settled = false;
          for (let i = 0; i < 100; i++) { const d2 = await detailOf(rec.sid); if (TERMINAL.has(String(d2?.turn_status || d2?.status || ''))) { settled = true; break; } await sleep(3000); }
          let rc = { code: 0, body: '' };
          if (!settled) rc = { code: 0, body: 'the previous turn was still running after 300 s' };
          else for (let i = 0; i < 6; i++) { rc = await page.evaluate(async (sid) => { const r = await fetch(`/api/harness/internal/sessions/${sid}/recycle`, { method: 'POST' }); return { code: r.status, body: (await r.text()).slice(0, 200) }; }, rec.sid); if (rc.code !== 409) break; await sleep(5000); }
          if (rc.code === 200) {
            await sleep(2000);
            const r5 = await turn('What exact word did I ask you to reply with in my very first message of this task? Reply with just that word.');
            rec.recycle = expectWord(r5, `M1-${m}`); rec.recycle.recycled = rc;
            // a recall that reads the lost-history note as its answer is a failed resume, on every harness
            if (rec.recycle.ok && /no longer available to Codex|could not be restored/i.test(rec.recycle.tail || '')) rec.recycle = { ...rec.recycle, ok: false, why: 'resumed without its history: ' + rec.recycle.tail.slice(-160) };
          } else rec.recycle = { ok: false, s: 0, why: `recycle refused: HTTP ${rc.code} ${rc.body}`, recycled: rc };
          log(`RECYCLE ${k} ${rec.recycle.ok ? 'ok' : 'FAIL'} ${rec.recycle.s}s ${rec.recycle.why}`);
        } else { rec.followup = { ok: null, why: 'first turn failed' }; rec.switch = { ok: null, why: 'first turn failed' }; rec.artifact = { ok: null, why: 'first turn failed' }; rec.recycle = { ok: null, why: 'first turn failed' }; }
      } catch (e) {
        rec.error = String(e).slice(0, 300); log(`ERROR ${k} ${rec.error}`);
        if (/browser has been closed/.test(rec.error)) throw e;   // the browser itself is gone: end the worker, the next launch resumes
        if (CRASHED.test(rec.error) && !retried.has(k)) {
          // one retry on a fresh page: the crash is this driver's, and the pair has not been measured
          retried.add(k); log(`RECOVER ${k} rebuilding the page and running this pair again`);
          try { await freshPage(); enabledQueue.push(m); } catch (e2) { log(`RECOVER failed: ${String(e2).slice(0, 160)}`); throw e; }
        }
      }
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
        // The switch row, judged on the SERVED model and not only on the word it echoed back.
        const partner = rec.switch && rec.switch.to;
        if (partner && withModel.length) {
          const swTurns = withModel.filter((t) => String(t.model) === String(partner));
          rec.switch_served = [...new Set(swTurns.map((t) => String(t.served_model)))];
          const took = swTurns.length > 0 && swTurns.every((t) => sameModel(partner, String(t.served_model)));
          if (rec.switch.ok === true && !took) {
            rec.switch.ok = false;
            rec.switch.why = swTurns.length
              ? `the chip moved to ${partner} and the turn was served by ${rec.switch_served.join(',')}`
              : `no turn record names ${partner}, so the switch cannot be shown to have happened`;
            log(`SWITCH ${k} -> ${partner} FAIL (on the served model) ${rec.switch.why}`);
          }
        }
        // No turn of this pair asked for the pair's own model: the picker's choice did not reach the
        // request (a wrong option clicked, a composer that reset it), so every check keyed on
        // `t.model === m` above would pass over nothing. A finding of its own (render.py), never a clean row.
        if (withModel.length && !turnsList.some((t) => t && t.model === m))
          rec.wrong_model = [...new Set(turnsList.map((t) => t && t.model).filter(Boolean).map(String))];
        if (process.env.EXPECT_CONNECTION) rec.foreign = rec.connections.filter((c) => c !== process.env.EXPECT_CONNECTION);
        // A turn on this pair's model with NO served model is a turn rule 2 could not judge, and a
        // finding of its own: the direct Anthropic route on Claude Code reported none for months
        // (the CLI lists usage by model and names no model on its result), so a substitution there
        // would have passed as a pass. Reported, never counted as a pass (render.py).
        rec.unlabelled = turnsList.filter((t) => t && t.model === m && !t.served_model).length;
        // The pair's prompt-cache share, read off each turn's own usage: cache reads over all input.
        // A Claude pair whose turns read no cache at all after the artifact scenario (two provider
        // calls at the least) paid full price for every token of its system prompt and tools, which
        // is how an aggregator's OpenAI-compatible surface cost 6 to 8 times the Claude Code price
        // for the same task in a customer's benchmark (2026-09-30) while every scenario here passed.
        const usages = await Promise.all(turnsList.filter((t) => t && t.id).map((t) => page.evaluate(async (rid) => {
          const r = await fetch(`/api/harness/v1/responses/${rid}`); return r.ok ? (await r.json()).usage || null : null; }, t.id).catch(() => null)));
        const inTok = usages.reduce((n, u) => n + (u ? Number(u.input_tokens || 0) : 0), 0);
        const cached = usages.reduce((n, u) => n + (u ? Number(u.cache_read_tokens || (u.input_tokens_details || {}).cached_tokens || 0) : 0), 0);
        rec.tokens = { input: inTok, cache_read: cached, turns_with_usage: usages.filter(Boolean).length };
        // A PASSING pair is cleaned up; a FAILING one is kept. The delete used to be
        // unconditional, and that is why two failing jcode rows (2026-10-06) could not be
        // investigated afterwards: the session was gone, so /files and /turns answered 404 and all
        // that survived was the judge's own sentence about what it saw. The record says what the
        // JUDGE saw; the session is the only place that says what the SYSTEM did.
        const failed = ['first', 'followup', 'switch', 'artifact', 'recycle']
          .some((n) => rec[n] && rec[n].ok === false);
        if (failed) { rec.kept = rec.sid; rec.deleted = 0; }
        else rec.deleted = await page.evaluate(async (sid) => { const r = await fetch(`/api/harness/v1/sessions/${sid}`, { method: 'DELETE' }); return r.status; }, rec.sid).catch(() => 0);
      }
      const all = load(); all[k] = rec; save(all); log(`PAIR_DONE ${k} connection=${rec.connection || '?'} turns=${(rec.connections || []).join('+') || '?'}${(rec.foreign || []).length ? ' FOREIGN=' + rec.foreign.join('+') : ''}${(rec.served || []).length ? ' served=' + rec.served.join('+') : ''}${(rec.substituted || []).length ? ' SUBSTITUTED=' + rec.substituted.join('+') : ''}${rec.kept ? ' KEPT=' + rec.kept : ' deleted=' + (rec.deleted || '?')}`);
    }
  }
} catch (e) { log(`FATAL ${String(e).slice(0, 300)}`); }
await b.close(); log(`WORKER_DONE ${process.env.HARNESSES}`);
