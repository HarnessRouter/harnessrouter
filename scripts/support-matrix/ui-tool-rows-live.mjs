// ui-tool-rows-live.mjs: a turn's steps show WHILE it runs, not all at once when it ends. One console
// task on the setup SETUP (its id, chrn_…) runs two shell commands that each sleep 8 s, then answers
// with a fixed word. The page is read every half second: the first command must be on screen at
// least 6 s before the answer, and the second at least 4 s after the first. A base that holds its
// record until the turn ends shows every step in one frame and fails both.
// Env BASE, HR_USER (default harnessrouter), HR_PASS, SETUP, MODEL (optional), SHOT (a mid-turn
// screenshot). Exit 0 on PASS.
import { chromium } from 'playwright';
const BASE = process.env.BASE, SETUP = process.env.SETUP, TAG = `live${Date.now() % 100000}`;
const ONE = `sleep 8; echo ${TAG}-ONE`, TWO = `sleep 8; echo ${TAG}-TWO`, WORD = `${TAG}-DONE`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const b = await chromium.launch(); const page = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const rt = (sel, v) => page.$eval(sel, (el, x) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, x); el.dispatchEvent(new Event('input', { bubbles: true })); }, v);
let code = 1;
try {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2500);
  if (page.url().includes('/login')) {
    await rt('#sh-user', process.env.HR_USER || 'harnessrouter'); await rt('#sh-pass', process.env.HR_PASS); await page.click('button[type=submit]');
    await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000, waitUntil: 'commit' });
  }
  await page.goto(`${BASE}/studio/${SETUP}`, { waitUntil: 'domcontentloaded' }); await sleep(4000);
  await page.click('button.tk-newb'); await sleep(1500);
  if (process.env.MODEL) {
    const pick = page.locator('button.nw-pk');
    if (!(await pick.textContent()).includes(process.env.MODEL)) throw new Error(`the composer's model is ${await pick.textContent()}, not ${process.env.MODEL}`);
  }
  await page.locator('textarea:visible').first().fill(
    `Use your shell tool to run \`${ONE}\`. After it finishes, run \`${TWO}\`. Then reply with exactly: ${WORD}`);
  await page.locator('button.uac-send').click();
  const t0 = Date.now(); const seen = {}; let shot = false;
  const at = (k) => { if (seen[k] === undefined) seen[k] = (Date.now() - t0) / 1000; };
  for (let i = 0; i < 360 && seen.answer === undefined; i++) {
    // Collapsed activity summaries open, so a command row's own text is on the page.
    for (const s of await page.locator('button.uac-sum[aria-expanded="false"]').all()) await s.click().catch(() => {});
    const text = await page.locator('main, body').first().innerText();
    // The command the agent ran, never the prompt's own copy of it: the prompt holds both commands
    // inside one sentence, so a row is the command text followed by its own line end.
    const rows = text.split('\n').map((l) => l.trim());
    if (rows.some((l) => l.endsWith(ONE) && !l.includes('Use your shell tool'))) at('first command');
    if (rows.some((l) => l.endsWith(TWO) && !l.includes('Use your shell tool'))) at('second command');
    if (rows.some((l) => l === WORD)) at('answer');
    if (process.env.DEBUG && i % 4 === 0) {
      console.log(((Date.now() - t0) / 1000).toFixed(1), JSON.stringify(rows.filter((l) => l.includes(TAG) || /^(Running|Ran|Used|Using)\b/.test(l)).slice(0, 8)));
    }
    if (seen['first command'] !== undefined && seen.answer === undefined && !shot && process.env.SHOT) {
      await page.screenshot({ path: process.env.SHOT }); shot = true;
    }
    await sleep(500);
  }
  const lead = (seen.answer ?? 0) - (seen['first command'] ?? Infinity);
  const apart = (seen['second command'] ?? -Infinity) - (seen['first command'] ?? Infinity);
  const ok = lead >= 6 && apart >= 4;
  console.log(ok ? 'PASS' : 'FAIL', SETUP, JSON.stringify(seen),
              `first command ${lead.toFixed(1)} s before the answer, ${apart.toFixed(1)} s before the second`);
  code = ok ? 0 : 1;
} catch (e) { console.log('FAIL', SETUP, String(e).slice(0, 300)); } finally { await b.close(); }
process.exit(code);
