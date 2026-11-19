// ui-antigravity.mjs: an Antigravity base in the console, as a person uses it. On a harness of AG_BASE (agy, the
// Antigravity CLI, or antigravity, Google's managed agent) it checks:
//   - Antigravity's own mark shows on the harness page;
//   - the model menu offers exactly the models the instance lists for the base;
//   - a first task writes a file, which the files API returns, and the turn shows its steps;
//   - a follow-up is answered from that file;
//   - at 1440, 1024, 768 and 390 wide, nothing scrolls sideways (a screenshot of each: SHOT-<width>.png).
// The harness and its sessions are deleted at the end. Env BASE (the console's address), HR_USER and HR_PASS (its
// sign-in, from the environment, never the command line), AG_BASE, SHOT (screenshot prefix). npm install here first.
import { chromium } from 'playwright';
const BASE = process.env.BASE, AG = process.env.AG_BASE || 'agy', SHOT = process.env.SHOT || `ui-${AG}`;
const N = Date.now() % 100000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const b = await chromium.launch();
const page = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const rt = (sel, v) => page.$eval(sel, (el, x) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, x); el.dispatchEvent(new Event('input', { bubbles: true })); }, v);
const dismissWelcome = async () => { for (let i = 0; i < 4 && (await page.locator('.welcome-overlay').count()); i++) { await page.locator('.welcome-overlay .welcome-wide-close').click().catch(() => {}); await sleep(600); } };
const api = (method, path, body) => page.evaluate(async ([m, p, bd]) => {
  const r = await fetch(`/api/harness${p}`, { method: m, headers: { 'content-type': 'application/json' }, body: bd ? JSON.stringify(bd) : undefined });
  const t = await r.text(); let j = {}; try { j = JSON.parse(t); } catch { j = { text: t }; }
  return { status: r.status, body: j };
}, [method, path, body]);
let fails = 0, hid = '';
const sids = new Set();
const check = (ok, what, note = '') => { if (!ok) fails++; console.log(ok ? 'PASS' : 'FAIL', what, note ? `| ${String(note).replace(/\s+/g, ' ').slice(0, 100)}` : ''); };
const waitTurn = async (sid, k) => {
  for (let i = 0; i < 200; i++) {
    const t = (await api('GET', `/v1/sessions/${sid}/turns`)).body.turns || [];
    if (t.length >= k + 1 && ['completed', 'failed', 'incomplete', 'cancelled'].includes(t[k].status)) return t[k];
    await sleep(3000);
  }
  return null;
};
try {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2500);
  if (page.url().includes('/login')) { await rt('#sh-user', process.env.HR_USER || 'harnessrouter'); await rt('#sh-pass', process.env.HR_PASS); await page.click('button[type=submit]'); await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000, waitUntil: 'commit' }); }
  await sleep(1500); await dismissWelcome();
  const bases = (await api('GET', '/v1/bases')).body;
  const doc = (bases.data || bases.bases || []).find((x) => x.id === AG);
  check(doc && doc.status === 'ready', `base ${AG} listed and ready`, doc ? doc.label : 'not listed');
  const listed = (doc?.models || []).filter((m) => m.available !== false).map((m) => m.id);
  const made = await api('POST', '/v1/harnesses', { name: `E2E console ${AG} ${N}`, base: AG });
  hid = made.body.id || '';
  check(made.status === 200 && hid, 'harness created', made.status);
  await page.goto(`${BASE}/harnesses?h=${hid}`, { waitUntil: 'domcontentloaded' }); await sleep(3500); await dismissWelcome();
  const marks = await page.locator('img[src*="logos/antigravity"]').evaluateAll((els) => els.filter((e) => e.complete && e.naturalWidth > 0 && e.getBoundingClientRect().width > 0).length);
  check(marks > 0, "Antigravity's own mark shows on the harness page", `${marks} shown`);
  await page.locator('.uac-composer .nw-pk').click(); await sleep(600);
  // the first option is the harness's default, named with its model; the others are the models themselves
  const offered = (await page.locator('.nw-opt').allInnerTexts()).map((t) => t.trim()).filter((t) => !/^Harness default/.test(t)).map((t) => t.split(/\s/)[0]);
  const same = offered.length === listed.length && listed.every((m) => offered.includes(m));
  check(same, 'the model menu offers exactly the base\'s models', offered.join(', '));
  await page.keyboard.press('Escape'); await sleep(300);
  // a first task that writes a file, then a follow-up answered from it
  const owner = `Dana-${N}`;
  const steps = [`Write a file named status.md with three short bullet points about a project launch. The first bullet must say that ${owner} owns the budget check. Then summarise the file in one sentence.`,
                 'Who owns the budget check, according to status.md? Reply with the name only.'];
  let sid = '';
  for (let k = 0; k < steps.length; k++) {
    await page.locator('.uac-composer textarea:not([disabled])').waitFor({ timeout: 300000 });
    await page.fill('.uac-composer textarea', steps[k]); await page.locator('.uac-send').click();
    for (let i = 0; i < 40 && !sid; i++) {      // the task's session: from the address, else the harness's newest session
      await sleep(1500);
      sid = new URL(page.url()).searchParams.get('sid') || '';
      if (!sid) { const ss = (await api('GET', '/v1/sessions?limit=50')).body; sid = ((ss.data || ss.sessions || []).find((x) => x.harness_id === hid) || {}).session_id || ''; }
    }
    if (sid) sids.add(sid);
    const t = await waitTurn(sid, k);
    const ans = String(t?.assistant || '');
    if (k === 0) {
      const f = await api('GET', `/v1/sessions/${sid}/files/status.md`);
      const text = typeof f.body.text === 'string' ? f.body.text : JSON.stringify(f.body);
      check(t?.status === 'completed' && f.status === 200 && text.includes(owner), 'first task: status.md written, the files API returns it', `${t?.status} files ${f.status}`);
      check((t?.tools || []).length > 0, 'first task: the turn shows its steps', `${(t?.tools || []).length} steps`);
    } else {
      check(t?.status === 'completed' && ans.includes(owner), 'follow-up: answered from the file', ans);
    }
  }
  await sleep(2500);
  for (const w of [1440, 1024, 768, 390]) {
    await page.setViewportSize({ width: w, height: w === 390 ? 844 : 900 }); await sleep(1200);
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await page.screenshot({ path: `${SHOT}-${w}.png`, fullPage: false });
    check(over <= 1, `${w} wide: nothing scrolls sideways`, `${SHOT}-${w}.png`);
  }
} catch (e) {
  fails++; console.log('FAIL', 'walk stopped:', String(e?.message || e).slice(0, 160));
} finally {
  for (const s of sids) await api('DELETE', `/v1/sessions/${s}`).catch(() => {});
  if (hid) await api('DELETE', `/v1/harnesses/${hid}`).catch(() => {});
  console.log(fails ? 'FAIL' : 'PASS', AG, `console walk, ${fails} failed`);
  await b.close();
  process.exit(fails ? 1 : 0);
}
