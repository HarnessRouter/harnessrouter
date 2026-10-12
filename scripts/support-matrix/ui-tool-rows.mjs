// ui-tool-rows.mjs: one console task on HARNESS that runs a shell command; then every tool row of the
// answer must open, and the Bash row must show the command it ran. Env BASE, HR_PASS, HARNESS, SHOT.
import { chromium } from 'playwright';
const BASE = process.env.BASE, H = process.env.HARNESS || 'jcode', WORD = `ui-row-${Date.now() % 100000}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const b = await chromium.launch(); const page = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
try {
  // run.mjs's login: the native value setter plus an input event (React reads the event, not fill's keystrokes)
  const rt = (sel, v) => page.$eval(sel, (el, x) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, x); el.dispatchEvent(new Event('input', { bubbles: true })); }, v);
  const dismissWelcome = async () => { for (let i = 0; i < 4 && (await page.locator('.welcome-overlay').count()); i++) { await page.locator('.welcome-overlay .welcome-wide-close').click().catch(() => {}); await sleep(600); } };
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2500);
  if (page.url().includes('/login')) { await rt('#sh-user', 'harnessrouter'); await rt('#sh-pass', process.env.HR_PASS); await page.click('button[type=submit]'); await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000, waitUntil: 'commit' }); }
  await sleep(1500); await dismissWelcome();
  await page.goto(`${BASE}/harnesses?h=${H}`, { waitUntil: 'domcontentloaded' }); await sleep(3500); await dismissWelcome();
  for (let i = 0; i < 10 && !(await page.locator('.wbx-conv-main.is-hero').count()); i++) { await page.click('button:has-text("New task")').catch(() => {}); await sleep(800); }
  await page.fill('textarea.wbx-composer-input', `Run the shell command \`echo ${WORD}\` and reply with its output.`);
  await page.locator('button.wbx-send').click();
  await page.waitForURL((u) => u.searchParams.get('sid'), { timeout: 30000, waitUntil: 'commit' });
  const sid = new URL(page.url()).searchParams.get('sid');
  for (let i = 0; i < 100; i++) {
    const st = await page.evaluate(async (s) => { const r = await fetch(`/api/harness/v1/sessions/${s}/turns`); const j = await r.json(); const t = (j.turns || []).slice(-1)[0] || {}; return t.status || ''; }, sid);
    if (['completed', 'failed', 'incomplete', 'cancelled'].includes(st)) break; await sleep(3000);
  }
  await sleep(3000);
  // a finished turn folds its tools under "Used N tools": open the group first, as a person would
  const group = page.getByText(/^Used \d+ tools?$/).first();
  if (await group.count()) { await group.click(); await sleep(800); }
  const rows = await page.evaluate(() => [...document.querySelectorAll('button.wbx-act-row')].map((x) => ({ label: x.textContent.trim().slice(0, 40), disabled: x.disabled })));
  console.log('ROWS', JSON.stringify(rows));
  const bash = page.locator('button.wbx-act-row', { hasText: /bash/i }).first();
  let shown = '';
  if (await bash.count()) { await bash.click(); await sleep(800); shown = await bash.evaluate((x) => (x.parentElement?.textContent || '').replace(/\s+/g, ' ').slice(0, 400)); }
  await page.screenshot({ path: process.env.SHOT || 'ui-tool-rows.png', fullPage: false });
  const ok = rows.length > 0 && rows.every((r) => !r.disabled) && shown.includes(`echo ${WORD}`);
  console.log(ok ? 'PASS' : 'FAIL', H, 'bash row shows:', shown.slice(0, 200));
} finally { await b.close(); }
