/** @jest-environment jsdom */
// The phone bar's More tab is the same box as the other tabs (Richard, 2026-10-19: the More tab was
// "sloppy"). jsdom draws no layout and reads no media query, so this test runs the cascade itself over
// the two stylesheets the frame loads (hrui.css, then hrui-console.css) as a 390px phone sees them:
// every rule whose selector matches the element, the most specific declaration winning and the later
// one on a tie. It reads what decides where the tab sits: its margin, padding and gap, its avatar's box
// against the icons', its label's type, and where the unread dot and a photo's edge are drawn.
import { readFileSync } from 'fs';
import { join } from 'path';

const PHONE = 390;

type Rule = { selector: string; pseudo: string; spec: number[]; order: number; style: Decls };

/** The specificity of one complex selector: ids, then classes, attributes and pseudo-classes, then
 *  types and pseudo-elements. :where() counts nothing; :not(), :is() and :has() count their argument. */
function specificity(sel: string): number[] {
  const out = [0, 0, 0];
  let s = sel;
  // the arguments of the functional pseudo-classes, innermost last
  for (;;) {
    const m = /:(where|not|is|has)\(/.exec(s);
    if (!m) break;
    let depth = 0, end = m.index + m[0].length - 1;
    for (let i = end; i < s.length; i++) {
      if (s[i] === '(') depth++;
      else if (s[i] === ')') { depth--; if (depth === 0) { end = i; break; } }
    }
    const inner = s.slice(m.index + m[0].length, end);
    if (m[1] !== 'where') {
      const best = inner.split(',').map((x) => specificity(x.trim())).sort((a, b) => b[0] - a[0] || b[1] - a[1] || b[2] - a[2])[0];
      out[0] += best[0]; out[1] += best[1]; out[2] += best[2];
    }
    s = s.slice(0, m.index) + ' ' + s.slice(end + 1);
  }
  s = s.replace(/\[[^\]]*\]/g, () => { out[1]++; return ' '; });
  s = s.replace(/::[\w-]+/g, () => { out[2]++; return ' '; });
  s = s.replace(/#[\w-]+/g, () => { out[0]++; return ' '; });
  s = s.replace(/\.[\w-]+/g, () => { out[1]++; return ' '; });
  s = s.replace(/:[\w-]+/g, () => { out[1]++; return ' '; });
  (s.match(/(^|[\s>+~])([a-zA-Z][\w-]*)/g) || []).forEach(() => { out[2]++; });
  return out;
}

/** A media query as a 390px phone in a light theme answers it. */
function phoneMatches(media: string): boolean {
  const q = media.replace(/\s+/g, '');
  if (!/^\((max|min)-width:\d+px\)$/.test(q)) return false;
  const n = Number(/\d+/.exec(q)![0]);
  return q.startsWith('(max') ? PHONE <= n : PHONE >= n;
}

type Decls = Map<string, { v: string; imp: boolean }>;

/** Split at `sep` where it is outside parentheses, brackets and strings. */
function splitTop(text: string, sep: string): string[] {
  const out: string[] = [];
  let depth = 0, quote = '', from = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) { if (ch === '\\') i++; else if (ch === quote) quote = ''; continue; }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === '(' || ch === '[') depth++;
    else if (ch === ')' || ch === ']') depth--;
    else if (ch === sep && depth === 0) { out.push(text.slice(from, i)); from = i + 1; }
  }
  out.push(text.slice(from));
  return out;
}

function decls(body: string): Decls {
  const m: Decls = new Map();
  for (const d of splitTop(body, ';')) {
    const at = d.indexOf(':');
    if (at < 0) continue;
    const prop = d.slice(0, at).trim().toLowerCase();
    let v = d.slice(at + 1).trim();
    const imp = /!important$/.test(v);
    if (imp) v = v.replace(/\s*!important$/, '');
    if (prop && v) { m.delete(prop); m.set(prop, { v, imp }); }    // a later declaration in the rule wins
  }
  return m;
}

/** The two stylesheets as a list of rules, the way a 390px phone applies them (a small reader: the
 *  files are plain rules, @media blocks, and at-rules that hold no rules for these elements). */
function load(): Rule[] {
  const rules: Rule[] = [];
  let order = 0;
  const parse = (css: string, apply: boolean) => {
    let i = 0;
    while (i < css.length) {
      const open = css.indexOf('{', i);
      if (open < 0) break;
      const head = css.slice(i, open).trim();
      // the matching close brace, minding strings
      let depth = 0, j = open, quote = '';
      for (; j < css.length; j++) {
        const ch = css[j];
        if (quote) { if (ch === '\\') j++; else if (ch === quote) quote = ''; continue; }
        if (ch === '"' || ch === "'") quote = ch;
        else if (ch === '{') depth++;
        else if (ch === '}') { depth--; if (depth === 0) break; }
      }
      const body = css.slice(open + 1, j);
      i = j + 1;
      if (head.startsWith('@media')) { parse(body, apply && phoneMatches(head.slice(6).trim())); continue; }
      if (head.startsWith('@')) continue;
      if (!apply) continue;
      const style = decls(body);
      for (const raw of splitTop(head, ',')) {
        const selector = raw.trim();
        const pm = /::?(after|before)$/.exec(selector);
        rules.push({ selector: pm ? selector.slice(0, pm.index) : selector, pseudo: pm ? pm[1] : '', spec: specificity(selector), order: order++, style });
      }
    }
  };
  for (const file of ['hrui.css', 'hrui-console.css']) {
    parse(readFileSync(join(__dirname, file), 'utf8').replace(/\/\*[\s\S]*?\*\//g, ''), true);
  }
  return rules;
}

const rules = load();

const SIDES: Record<string, string[]> = { margin: ['top', 'right', 'bottom', 'left'], padding: ['top', 'right', 'bottom', 'left'] };
/** A longhand's value in one rule, from the longhand or its shorthand, whichever the rule declares last. */
function declared(style: Decls, prop: string): { v: string; imp: boolean } | null {
  const [box, side] = prop.split('-');
  const short = SIDES[box] && side ? box : prop === 'row-gap' ? 'gap' : '';
  const keys = [...style.keys()];
  const own = style.get(prop), sh = short ? style.get(short) : undefined;
  if (own && (!sh || keys.indexOf(prop) > keys.indexOf(short))) return own;
  if (!sh) return null;
  const v = sh.v.split(/\s+(?![^(]*\))/);
  if (short === 'gap') return { v: v[0], imp: sh.imp };
  const i = SIDES[box].indexOf(side);
  return { v: [v[0], v[1] ?? v[0], v[2] ?? v[0], v[3] ?? v[1] ?? v[0]][i], imp: sh.imp };
}

/** The winning declaration for `prop` on `el` (or its ::after / ::before), as the cascade picks it. */
function computed(el: Element, prop: string, pseudo = ''): string {
  let best: { v: string; imp: boolean; spec: number[]; order: number } | null = null;
  for (const r of rules) {
    if (r.pseudo !== pseudo) continue;
    const d = declared(r.style, prop);
    if (!d) continue;
    // every element here is outside the old pages' frame, so the generated rules' guard always holds
    const sel = r.selector.replace(/:where\(:not\(\.hrui-legacy \*\)\)/g, '');
    let hit = false;
    try { hit = el.matches(sel); } catch { hit = false; }
    if (!hit) continue;
    const c = { v: d.v, imp: d.imp, spec: r.spec, order: r.order };
    const wins = !best || (c.imp !== best.imp ? c.imp
      : c.spec[0] !== best.spec[0] ? c.spec[0] > best.spec[0]
        : c.spec[1] !== best.spec[1] ? c.spec[1] > best.spec[1]
          : c.spec[2] !== best.spec[2] ? c.spec[2] > best.spec[2] : c.order > best.order);
    if (wins) best = c;
  }
  return best ? best.v : '';
}
const px = (v: string) => (v === '0' ? 0 : Number(/^(-?[\d.]+)px$/.exec(v)?.[1] ?? NaN));

document.body.innerHTML = `
  <div id="hrui"><div class="app"><nav class="rail">
    <a class="rail-btn" data-nav="tasks"><svg></svg>Tasks</a>
    <a class="rail-btn rail-letter" data-nav="letter"><svg></svg>Letter</a>
    <button type="button" class="rail-me more-on dot"><span class="av me-av pic"><img alt=""></span><span class="me-l">More</span></button>
  </nav></div></div>`;
const tab = document.querySelector('.rail-btn[data-nav="tasks"]')!;
const icon = tab.querySelector('svg')!;
const more = document.querySelector('.rail-me')!;
const av = more.querySelector('.me-av')!;
const label = more.querySelector('.me-l')!;

test('the More tab is the same box as the other tabs: no margin of its own, their padding and gap', () => {
  // the desktop rule that spaces the account button from the Letter matched on a phone too (8px down)
  for (const side of ['top', 'right', 'bottom', 'left']) expect(px(computed(more, `margin-${side}`) || '0')).toBe(0);
  for (const side of ['top', 'bottom']) expect(computed(more, `padding-${side}`)).toBe(computed(tab, `padding-${side}`));
  expect(computed(more, 'row-gap')).toBe(computed(tab, 'row-gap'));
  expect(computed(more, 'display')).toBe(computed(tab, 'display'));
  expect(computed(more, 'flex-direction')).toBe(computed(tab, 'flex-direction'));
  expect(computed(more, 'font-size')).toBe(computed(tab, 'font-size'));
});

test('its avatar is the icons’ box, so its label shares their baseline', () => {
  expect(computed(icon, 'width')).toBe('18px');
  expect(computed(av, 'width')).toBe(computed(icon, 'width'));
  expect(computed(av, 'height')).toBe(computed(icon, 'height'));
  // the label keeps the tab's own type: nothing sets its size or line height apart from the other labels
  expect(computed(label, 'font-size')).toBe('');
  expect(computed(label, 'line-height')).toBe('');
  expect(computed(more, 'line-height')).toBe(computed(tab, 'line-height'));
});

test('the unread dot sits on the avatar’s top right, not on the tab’s far edge', () => {
  expect(computed(more, 'position')).toBe('relative');
  expect(computed(more, 'right', 'after')).toBe('auto');
  const left = /^calc\(50% \+ ([\d.]+)px\)$/.exec(computed(more, 'left', 'after'));
  expect(left).not.toBeNull();
  const size = px(computed(more, 'width', 'after'));
  const top = px(computed(more, 'top', 'after'));
  // the avatar is centred in the tab under its top padding; the dot's centre lands on its rim
  const r = px(computed(av, 'width')) / 2;
  const dx = Number(left![1]) + size / 2;                       // from the tab's centre line
  const dy = top + size / 2 - (px(computed(more, 'padding-top')) + r);   // from the avatar's centre
  expect(dx).toBeGreaterThan(0);
  expect(dy).toBeLessThan(0);
  expect(Math.abs(Math.hypot(dx, dy) - r)).toBeLessThanOrEqual(1.5);
});

test('a photo disc keeps its edge: a 1px line ring drawn over the photo', () => {
  expect(computed(av, 'position')).toBe('relative');
  expect(computed(av, 'box-shadow', 'after')).toBe('inset 0 0 0 1px var(--line)');
  expect(computed(av, 'content', 'after')).toBe('""');
});
