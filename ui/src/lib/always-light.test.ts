// The console is always light, whatever the system's appearance (Richard, 2026-11-03): its design is drawn for one palette.
// The generated stylesheets keep their dark rules, each guarded on :not([data-theme="light"]), so that a re-port of the design
// stays a plain copy. So these hold the guard: a new root without the attribute, or a dark rule with no such guard, fails here.
import { readdirSync, readFileSync, statSync } from 'fs';
import { join } from 'path';

const UI = join(__dirname, '..', '..');

function walk(dir: string, keep: (f: string) => boolean, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, keep, out);
    else if (keep(p)) out.push(p);
  }
  return out;
}

describe('the console never follows the system into dark', () => {
  it('every root of the design says light', () => {
    const roots = walk(join(UI, 'src'), (f) => f.endsWith('.tsx') && !f.includes('.test.'))
      .flatMap((f) => (readFileSync(f, 'utf8').match(/<div id="hrui"[^>]*>/g) || []).map((tag) => [f, tag]));
    expect(roots.length).toBeGreaterThan(1);
    for (const [f, tag] of roots) expect(`${f}: ${tag}`).toContain('data-theme="light"');
  });

  it('no stylesheet has a dark rule the attribute does not turn off', () => {
    for (const f of walk(join(UI, 'src'), (p) => p.endsWith('.css'))) {
      const css = readFileSync(f, 'utf8');
      for (const m of css.matchAll(/@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*([^{]*)/g)) {
        expect(`${f}: ${m[1].slice(0, 60)}`).toContain(':not([data-theme="light"])');
      }
    }
  });

  it('public pages and pictures carry no dark rule of their own', () => {
    for (const f of walk(join(UI, 'public'), (p) => /\.(svg|html|css)$/.test(p))) {
      const text = readFileSync(f, 'utf8');
      if (!text.includes('prefers-color-scheme')) continue;
      expect(`${f}: ${text.includes('data-theme="light"') ? 'says light' : 'follows the system'}`).toContain('says light');
    }
  });

  it('the page says so to the browser, and Tailwind does not follow the system', () => {
    expect(readFileSync(join(UI, 'src/app/layout.tsx'), 'utf8')).toMatch(/viewport: Viewport = \{ colorScheme: 'light' \}/);
    expect(readFileSync(join(UI, 'src/components/hrui/hrui-console.css'), 'utf8')).toMatch(/#hrui\{[^}]*color-scheme:light/);
    expect(readFileSync(join(UI, 'tailwind.config.ts'), 'utf8')).toMatch(/darkMode: 'class'/);
  });
});
