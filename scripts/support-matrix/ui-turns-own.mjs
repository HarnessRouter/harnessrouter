// ui-turns-own.mjs: several turns in ONE console conversation on HARNESS (model MODEL); each turn's
// stored answer and tool count must be that turn's alone, never the conversation so far replayed.
// Env BASE, HR_PASS, HARNESS, MODEL, SHOT.
import { chromium } from 'playwright';
const BASE = process.env.BASE, H = process.env.HARNESS || 'opensquilla', N = Date.now() % 100000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const b = await chromium.launch(); const page = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const rt = (sel, v) => page.$eval(sel, (el, x) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, x); el.dispatchEvent(new Event('input', { bubbles: true })); }, v);
const dismissWelcome = async () => { for (let i = 0; i < 4 && (await page.locator('.welcome-overlay').count()); i++) { await page.locator('.welcome-overlay .welcome-wide-close').click().catch(() => {}); await sleep(600); } };
const steps = [`Reply with exactly: ONE-${N}`, `Run the shell command \`echo TWO-${N}\` and reply with its output only.`,
               `Reply with exactly: THREE-${N}`, `Run the shell command \`echo FOUR-${N}\` and reply with its output only.`];
let fails = 0;
try {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2500);
  if (page.url().includes('/login')) { await rt('#sh-user', 'harnessrouter'); await rt('#sh-pass', process.env.HR_PASS); await page.click('button[type=submit]'); await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000, waitUntil: 'commit' }); }
  await sleep(1500); await dismissWelcome();
  await page.goto(`${BASE}/harnesses?h=${H}`, { waitUntil: 'domcontentloaded' }); await sleep(3500); await dismissWelcome();
  for (let i = 0; i < 10 && !(await page.locator('.wbx-conv-main.is-hero').count()); i++) { await page.click('button:has-text("New task")').catch(() => {}); await sleep(800); }
  if (process.env.MODEL) { await page.click('.ar2-chip'); await sleep(500); await page.locator('.wbx-model-opt', { hasText: new RegExp('^' + process.env.MODEL.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\s|$)') }).first().click(); await sleep(300); }
  let sid = '';
  for (let k = 0; k < steps.length; k++) {
    await page.locator('textarea.wbx-composer-input:not([disabled])').waitFor({ timeout: 120000 });
    await page.fill('textarea.wbx-composer-input', steps[k]); await page.locator('button.wbx-send').click();
    if (!sid) { await page.waitForURL((u) => u.searchParams.get('sid'), { timeout: 30000, waitUntil: 'commit' }); sid = new URL(page.url()).searchParams.get('sid'); }
    let last = null;
    for (let i = 0; i < 100; i++) {
      const t = await page.evaluate(async (s) => (await (await fetch(`/api/harness/v1/sessions/${s}/turns`)).json()).turns || [], sid);
      if (t.length === k + 1 && ['completed', 'failed', 'incomplete', 'cancelled'].includes(t[k].status)) { last = t[k]; break; }
      await sleep(3000);
    }
    const ans = String(last?.assistant || ''); const tools = (last?.tools || []).length;
    const earlier = ['ONE', 'TWO', 'THREE', 'FOUR'].slice(0, k).map((w) => `${w}-${N}`).filter((w) => ans.includes(w));
    const own = ans.includes(['ONE', 'TWO', 'THREE', 'FOUR'][k] + `-${N}`);
    const ok = last?.status === 'completed' && own && earlier.length === 0;
    if (!ok) fails++;
    console.log(ok ? 'PASS' : 'FAIL', `turn ${k + 1}`, `tools ${tools}`, earlier.length ? `repeats ${earlier.join(',')}` : '', '|', ans.replace(/\s+/g, ' ').slice(0, 90));
  }
  await sleep(2500);
  await page.screenshot({ path: process.env.SHOT || 'ui-turns-own.png', fullPage: false });
  console.log(fails ? 'FAIL' : 'PASS', H, `${steps.length} turns, each its own answer`);
} finally { await b.close(); }
