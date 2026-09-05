// Support matrix runner: harness x model x provider x {first, followup, switch, artifact}.
// Drives the console as one user; one task at a time per worker; resumable (pairs already complete
// in the results file are skipped). Env: BASE, HR_USER, HR_PASS, HARNESSES (comma), PROVIDER
// (a label for the column), RESULTS (json path), LOG (append log), MODELS (optional comma filter),
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
const dismissWelcome = async () => { for (let i = 0; i < 4 && (await page.locator('.welcome-overlay').count()); i++) { await page.locator('.welcome-overlay button').last().click().catch(() => {}); await sleep(600); } };
// send one message on the open session and wait for it to settle; returns the outcome
async function turn(text, { maxS = 420 } = {}) {
  const before = await transcript(); const t0 = Date.now();
  await page.fill('.wbx-composer textarea, textarea', text); await page.keyboard.press('Enter');
  let p = '', started = false;
  // the pill still shows the previous turn's state for a moment: wait for this turn to start
  for (let i = 0; i < 50 && !started; i++) { await sleep(500); p = await pill(); started = /running|working|starting/.test(p); }
  for (let i = 0; i < maxS / 3; i++) { await sleep(3000); p = await pill(); const d = await door(); if (d) return { ok: false, s: (Date.now() - t0) / 1000, why: 'door: ' + d.slice(0, 160) }; if (/done|incomplete|failed|cancelled/.test(p)) break; }
  await sleep(3000);
  const t = await transcript(); const tail = t.slice(before.length).trim().slice(-400);
  return { ok: /done/.test(p), pill: p, s: Math.round((Date.now() - t0) / 10) / 100, tail, why: /done/.test(p) ? '' : tail.slice(-220) };
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
    await page.click('.ar2-chip'); await sleep(600);
    const models = await page.evaluate(() => [...document.querySelectorAll('.wbx-model-opt')].map((o) => ({ id: o.querySelector('span')?.textContent.trim(), ok: !o.disabled })));
    await page.keyboard.press('Escape'); await sleep(300);
    const enabled = models.filter((m) => m.ok && (!process.env.MODELS || process.env.MODELS.split(',').includes(m.id))).map((m) => m.id);
    log(`HARNESS ${h} models ${models.length} runnable ${enabled.length}: ${enabled.join(',')}`);
    for (const m of enabled) {
      const res = load(); const k = key(h, m);
      if (res[k] && res[k].artifact && !res[k].error) { log(`SKIP ${k} (done)`); continue; }   // a runner error is not a result
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
          const other = enabled.find((x) => x !== m) || null;
          if (other) { await page.click('.ar2-chip'); await sleep(500); await page.locator('.wbx-model-opt', { hasText: other }).first().click(); await sleep(300); rec.switch = { to: other, ...expectWord(await turn(`Reply with exactly: M3-${other}`), `M3-${other}`) }; }
          else rec.switch = { to: null, ok: null, why: 'only one model' };
          log(`SWITCH ${k} -> ${other} ${rec.switch.ok ? 'ok' : 'FAIL'} ${rec.switch.s || ''}s ${rec.switch.why || ''}`);
          if (other) { await page.click('.ar2-chip'); await sleep(500); await page.locator('.wbx-model-opt', { hasText: m }).first().click(); await sleep(300); }
          const a = await turn(`Create a file named hello-${h}.txt containing exactly the word HELLO, then reply DONE.`);
          const fl = await files(); rec.artifact = { ...a, files: fl, ok: a.ok && fl.some((f) => f.includes(`hello-${h}.txt`)), why: a.ok && !fl.some((f) => f.includes(`hello-${h}.txt`)) ? `no file card (files: ${fl.join(',') || 'none'}); ${a.tail.slice(-160)}` : a.why };
          log(`ARTIFACT ${k} ${rec.artifact.ok ? 'ok' : 'FAIL'} ${rec.artifact.s}s ${rec.artifact.why}`);
        } else { rec.followup = { ok: null, why: 'first turn failed' }; rec.switch = { ok: null, why: 'first turn failed' }; rec.artifact = { ok: null, why: 'first turn failed' }; }
      } catch (e) { rec.error = String(e).slice(0, 300); log(`ERROR ${k} ${rec.error}`); if (/has been closed/.test(rec.error)) throw e; }   // a closed browser ends the worker; the next launch resumes
      const all = load(); all[k] = rec; save(all); log(`PAIR_DONE ${k}`);
    }
  }
} catch (e) { log(`FATAL ${String(e).slice(0, 300)}`); }
await b.close(); log(`WORKER_DONE ${process.env.HARNESSES}`);
