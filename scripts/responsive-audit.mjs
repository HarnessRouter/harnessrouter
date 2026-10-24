// Responsive audit: every console surface at every width that matters, looking for content wider
// than the box that holds it. Run it after any layout change, and before a release that touches
// one, since the project's rule is that no surface ships until it survives narrow widths:
//
//   BASE=https://<instance> HR_AUTH_USER=… HR_AUTH_PASSWORD=… node scripts/responsive-audit.mjs
//
// The routes are the redesigned console's (0.36.0): Start, Studio, Shop, Add-ons and its tabs, API Keys,
// Bring your own key, Profile and the AGENTS.md page. ROUTES adds a setup's own pages
// (/studio/<id>, /studio/<id>?tab=settings) where a setup is known.
//
// Every console surface at every width that matters, looking for content wider than the box that
// holds it. An element counts as broken when its own scrollWidth exceeds its client width and its
// overflow-x is visible or hidden — content spilling or being clipped with no way to reach it.
// A container that scrolls on purpose (auto/scroll) is not a finding.
import { chromium } from 'playwright';
const BASE = process.env.BASE;
const ROUTES = (process.env.ROUTES || '/start,/studio,/shop,/extensions,/extensions?tab=skills,/extensions?tab=tools,/extensions?tab=envs,/keys,/byok,/profile,/agents').split(',');
const WIDTHS = (process.env.WIDTHS || '1440,1280,1180,1140,1100,1024,980,900,860,820,768,700,600,480,390').split(',').map(Number);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const findings = [];
try {
  // self-hosted signs in with a username and password on its own form, not an email
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 45000 }); await sleep(2500);
  if (page.url().includes('/login')) {
    const set = async (sel, v) => page.$eval(sel, (el, x) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, x); el.dispatchEvent(new Event('input', { bubbles: true })); }, v);
    await set('#sh-user', process.env.HR_AUTH_USER || 'harnessrouter');
    await set('#sh-pass', process.env.HR_AUTH_PASSWORD);
    await page.click('button[type=submit]'); await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000 });
  }
  await sleep(2000);
  for (const route of ROUTES) {
    for (const w of WIDTHS) {
      await page.setViewportSize({ width: w, height: 900 });
      await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' }).catch(() => {});
      await sleep(2600);
      const found = await page.evaluate(() => {
        const path = (el) => { const p = []; let n = el; for (let i = 0; n && i < 4; i++, n = n.parentElement) { const c = (n.className || '').toString().trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.'); p.unshift(n.tagName.toLowerCase() + (c ? '.' + c : '')); } return p.join(' > '); };
        const out = [];
        for (const el of document.querySelectorAll('body *')) {
          const r = el.getBoundingClientRect();
          if (r.width < 40 || r.height < 8) continue;                    // invisible or trivial
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden') continue;
          if (cs.overflowX === 'auto' || cs.overflowX === 'scroll') continue;  // scrolls on purpose
          if (cs.textOverflow === 'ellipsis') continue;                        // clips on purpose
          // inside something that scrolls: reachable, so not a finding
          let scroller = false;
          for (let a = el.parentElement; a; a = a.parentElement) {
            const acs = getComputedStyle(a);
            if (acs.overflowX === 'auto' || acs.overflowX === 'scroll') { scroller = true; break; }
            if (acs.textOverflow === 'ellipsis') { scroller = true; break; }
          }
          if (scroller) continue;
          const over = el.scrollWidth - el.clientWidth;
          if (over > 2) out.push({ over, sel: path(el), w: Math.round(r.width) });
          // and content that pokes out past the viewport's right edge
          if (r.right > window.innerWidth + 2 && cs.position !== 'fixed') out.push({ over: Math.round(r.right - window.innerWidth), sel: path(el), w: Math.round(r.width), beyond: true });
        }
        const seen = new Set();
        return out.sort((a, b) => b.over - a.over).filter((f) => !seen.has(f.sel) && seen.add(f.sel)).slice(0, 6)
          .concat([{ doc: document.documentElement.scrollWidth - document.documentElement.clientWidth }]);
      });
      const doc = found.pop().doc;
      const real = found.filter((f) => f.over > 2);
      if (real.length || doc > 2) {
        findings.push({ route, w, doc, items: real });
        console.log(`${route} @${w}px  pageOverflow=${doc}`);
        for (const f of real.slice(0, 4)) console.log(`    +${f.over}px ${f.beyond ? '(past the viewport) ' : ''}${f.sel} [box ${f.w}px]`);
      }
    }
  }
  console.log(`\nroutes with a finding: ${new Set(findings.map((f) => f.route)).size} of ${ROUTES.length}`);
} finally { await b.close(); }
