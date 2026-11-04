// The console's build bundles its packages into files with no room for their notices, and MIT, BSD and the like
// ask that a copy carries them. So the image carries this: every production package's licence text, from the
// lockfile and what the install put on disk. A build with too little in it fails rather than ship a hollow file.
import fs from 'node:fs';
import path from 'node:path';

const lock = JSON.parse(fs.readFileSync('package-lock.json', 'utf8')).packages;
const NOTICE = /^(licen[cs]e|copying|notice|authors)(\.|-|$)/i;
const out = ['Third-party software in the HarnessRouter console, from its production dependencies.', ''];
let n = 0;
for (const [where, p] of Object.entries(lock)) {
  if (!where.startsWith('node_modules/') || p.dev || p.link) continue;
  if (!fs.existsSync(where)) continue;                 // an optional package for another platform
  const own = JSON.parse(fs.readFileSync(path.join(where, 'package.json'), 'utf8'));
  const declared = own.license || (Array.isArray(own.licenses) ? own.licenses.map((l) => l.type || l).join(' OR ') : '') || 'not declared';
  out.push(`=== ${own.name}@${own.version} (${typeof declared === 'object' ? declared.type : declared})`);
  const files = fs.readdirSync(where).filter((f) => NOTICE.test(f) && fs.statSync(path.join(where, f)).isFile());
  for (const f of files) out.push(fs.readFileSync(path.join(where, f), 'utf8').trim());
  if (!files.length) out.push(own.author ? `No licence file in the package. Author: ${typeof own.author === 'object' ? own.author.name : own.author}` : 'No licence file in the package.');
  out.push('');
  n += 1;
}
if (n < 50) {
  console.error(`only ${n} packages found: run this after installing, from the console's folder`);
  process.exit(1);
}
process.stdout.write(`${out.join('\n')}\n`);
