// ui-conversation-switch.mjs: the conversation a person ran by hand, through the console. A custom
// harness on HBASE whose instruction makes a PDF; five turns in ONE conversation, each on the next
// model in MODELS, chosen on the model chip: "say hi", "improve the style", then three colour
// changes. Every turn must complete inside CAP_S (else it is stopped and called a loop), be served
// by the model asked for, hand back a PDF that differs from the turn before's, and answer for itself
// (no earlier answer replayed in front of it).
// Env BASE, HR_PASS, HBASE, MODELS (comma list, one per turn), CAP_S (default 480), SHOT, RESULTS.
import fs from 'node:fs';
import { chromium } from 'playwright';
const BASE = process.env.BASE, HB = process.env.HBASE, MODELS = (process.env.MODELS || '').split(',').filter(Boolean);
const CAP_S = Number(process.env.CAP_S || 480);
const INSTR = 'Use pdf gen skill to generate a pdf with your desired output text';
// the first turn asks for the instruction outright: "say hi" alone leaves a PDF to the model's
// judgement, and gpt-5.6-luna (nanobot) and qfmodel (qoder) answered "Hi!" without one although the
// instruction reached them (a marker it asked for came back, 2026-10-13)
const PROMPTS = ['follow your instruction: say hi', 'improve the style', 'change background to purple', 'change to red', 'change to green'];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const b = await chromium.launch(); const page = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const rt = (sel, v) => page.$eval(sel, (el, x) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, x); el.dispatchEvent(new Event('input', { bubbles: true })); }, v);
const dismissWelcome = async () => { for (let i = 0; i < 4 && (await page.locator('.welcome-overlay').count()); i++) { await page.locator('.welcome-overlay .welcome-wide-close').click().catch(() => {}); await sleep(600); } };
const api = (method, path, body) => page.evaluate(async ([m, p, bd]) => { const r = await fetch('/api/harness' + p, { method: m, headers: { 'content-type': 'application/json' }, body: bd ? JSON.stringify(bd) : undefined }); let j = null; try { j = await r.json(); } catch {} return { s: r.status, j }; }, [method, path, body]);
const sha = (url) => page.evaluate(async (u) => { const r = await fetch('/api/harness' + u); if (!r.ok) return ''; const d = await crypto.subtle.digest('SHA-256', await r.arrayBuffer()); return [...new Uint8Array(d)].map((x) => x.toString(16).padStart(2, '0')).join('').slice(0, 16); }, url);
const pickModel = async (id) => {
  await page.click('.ar2-chip'); await sleep(500);
  const opt = page.locator('.wbx-model-opt', { hasText: new RegExp('^' + id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\s|$)') }).first();
  await opt.waitFor({ timeout: 15000 }); await opt.click(); await sleep(400);
};
const rows = []; let fails = 0;
try {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2500);
  if (page.url().includes('/login')) { await rt('#sh-user', 'harnessrouter'); await rt('#sh-pass', process.env.HR_PASS); await page.click('button[type=submit]'); await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000, waitUntil: 'commit' }); }
  await sleep(1500); await dismissWelcome();
  const made = await api('POST', '/v1/harnesses', { name: `overnight-${HB}-conversation`, base: HB, system_prompt: INSTR, default_model: MODELS[0] });
  if (made.s !== 200) throw new Error(`harness create ${made.s} ${JSON.stringify(made.j).slice(0, 200)}`);
  const hid = made.j.id;
  await page.goto(`${BASE}/harnesses?h=${hid}`, { waitUntil: 'domcontentloaded' }); await sleep(3500); await dismissWelcome();
  for (let i = 0; i < 10 && !(await page.locator('.wbx-conv-main.is-hero').count()); i++) { await page.click('button:has-text("New task")').catch(() => {}); await sleep(800); }
  let sid = '', prevSha = '', prevAnswers = [];
  for (let k = 0; k < PROMPTS.length; k++) {
    const model = MODELS[k % MODELS.length];
    await page.locator('textarea.wbx-composer-input:not([disabled])').waitFor({ timeout: 120000 });
    await pickModel(model);
    await page.fill('textarea.wbx-composer-input', PROMPTS[k]); await page.locator('button.wbx-send').click();
    if (!sid) { await page.waitForURL((u) => u.searchParams.get('sid'), { timeout: 30000, waitUntil: 'commit' }); sid = new URL(page.url()).searchParams.get('sid'); }
    const t0 = Date.now(); let last = null, loop = false;
    while (true) {
      const t = (await api('GET', `/v1/sessions/${sid}/turns`)).j?.turns || [];
      if (t.length === k + 1 && ['completed', 'failed', 'incomplete', 'cancelled'].includes(t[k].status)) { last = t[k]; break; }
      if ((Date.now() - t0) / 1000 > CAP_S) {
        loop = true;
        const stop = page.locator('button.wbx-stop, button:has-text("Stop")').first();
        if (await stop.count()) await stop.click().catch(() => {}); else await api('POST', `/v1/sessions/${sid}/cancel`, {});
        await sleep(8000); last = ((await api('GET', `/v1/sessions/${sid}/turns`)).j?.turns || [])[k] || null; break;
      }
      await sleep(4000);
    }
    const secs = Math.round((Date.now() - t0) / 1000);
    const ans = String(last?.assistant || '');
    const pdfs = (last?.files || []).filter((f) => /\.pdf$/i.test(f.filename || f.name || ''));
    const h = pdfs.length ? await sha(pdfs[pdfs.length - 1].download_url) : '';
    const served = String(last?.served_model || '');
    const servedOk = last?.model === model && (!served || served.toLowerCase().replace(/^[a-z-]+\//, '').replace(/[._-]/g, '').includes(model.toLowerCase().replace(/[._-]/g, '').slice(0, 6)));
    const replay = prevAnswers.some((p) => p.length > 12 && ans.startsWith(p.slice(0, 40)));
    const changed = k === 0 ? !!h : (!!h && h !== prevSha);
    const ok = !loop && last?.status === 'completed' && changed && servedOk && !replay;
    if (!ok) fails++;
    const row = { turn: k + 1, prompt: PROMPTS[k], model, served, status: loop ? `stopped after ${CAP_S}s (loop)` : last?.status, seconds: secs,
      tools: (last?.tools || []).length, pdf: pdfs.map((f) => f.filename || f.name), pdf_changed: changed, replay, ok, answer: ans.replace(/\s+/g, ' ').slice(0, 160) };
    rows.push(row);
    log(ok ? 'PASS' : 'FAIL', HB, `turn ${k + 1}`, model, `served ${served || '-'}`, row.status, `${secs}s`, `tools ${row.tools}`, `pdf ${row.pdf.join(',') || 'none'}${changed ? '' : ' (unchanged)'}`, replay ? 'REPLAY' : '', '|', row.answer.slice(0, 80));
    if (h) prevSha = h; prevAnswers.push(ans);
    if (loop) break;
  }
  await sleep(2000);
  await page.screenshot({ path: process.env.SHOT || `conv-${HB}.png`, fullPage: false });
  log(fails ? 'FAIL' : 'PASS', HB, `${rows.filter((r) => r.ok).length} of ${PROMPTS.length} turns`, `session ${sid}`);
} catch (e) {
  fails++; log('FAIL', HB, 'driver error', String(e).slice(0, 300));
} finally {
  if (process.env.RESULTS) fs.writeFileSync(process.env.RESULTS, JSON.stringify({ base: HB, models: MODELS, rows, fails }, null, 1));
  await b.close();
}
