// ui-tool-rows-live.mjs: the tool row opens WHILE the turn runs. One console task on HARNESS (model
// MODEL, optional) runs a command that sleeps; while the turn still shows Working…, the shell row
// (ROW, a regex) must be openable and show the command. Env BASE, HR_PASS, HARNESS, MODEL, ROW, SHOT.
import { chromium } from 'playwright';
const BASE = process.env.BASE, H = process.env.HARNESS || 'opensquilla', WORD = `live-row-${Date.now() % 100000}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const b = await chromium.launch(); const page = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const rt = (sel, v) => page.$eval(sel, (el, x) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, x); el.dispatchEvent(new Event('input', { bubbles: true })); }, v);
const dismissWelcome = async () => { for (let i = 0; i < 4 && (await page.locator('.welcome-overlay').count()); i++) { await page.locator('.welcome-overlay .welcome-wide-close').click().catch(() => {}); await sleep(600); } };
try {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2500);
  if (page.url().includes('/login')) { await rt('#sh-user', 'harnessrouter'); await rt('#sh-pass', process.env.HR_PASS); await page.click('button[type=submit]'); await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000, waitUntil: 'commit' }); }
  await sleep(1500); await dismissWelcome();
  await page.goto(`${BASE}/harnesses?h=${H}`, { waitUntil: 'domcontentloaded' }); await sleep(3500); await dismissWelcome();
  for (let i = 0; i < 10 && !(await page.locator('.wbx-conv-main.is-hero').count()); i++) { await page.click('button:has-text("New task")').catch(() => {}); await sleep(800); }
  if (process.env.MODEL) {
    await page.click('.ar2-chip'); await sleep(500);
    await page.locator('.wbx-model-opt', { hasText: new RegExp('^' + process.env.MODEL.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\s|$)') }).first().click(); await sleep(300);
  }
  await page.fill('textarea.wbx-composer-input', `Run exactly this one shell command and nothing else: sleep 30; echo ${WORD}  Then reply with its output.`);
  await page.locator('button.wbx-send').click();
  const row = page.locator('button.wbx-act-row', { hasText: new RegExp(process.env.ROW || 'exec', 'i') }).first();
  let shown = '', running = false, t0 = Date.now();
  for (let i = 0; i < 90; i++) {
    running = (await page.getByText('Working…').count()) > 0;
    if (await row.count()) {
      if (!(await row.isDisabled())) { await row.click(); await sleep(600); shown = await row.evaluate((x) => (x.parentElement?.textContent || '').replace(/\s+/g, ' ').slice(0, 400)); running = (await page.getByText('Working…').count()) > 0; break; }
    }
    await sleep(1000);
  }
  await page.screenshot({ path: process.env.SHOT || 'ui-tool-rows-live.png', fullPage: false });
  const ok = running && shown.includes(`echo ${WORD}`);
  console.log(ok ? 'PASS' : 'FAIL', H, `${Math.round((Date.now() - t0) / 1000)}s`, 'turn still running:', running, '| row shows:', shown.slice(0, 220));
} finally { await b.close(); }
