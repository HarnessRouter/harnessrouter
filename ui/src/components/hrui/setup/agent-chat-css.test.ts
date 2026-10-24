// The #hrui-scoped copy of reifyui's agent-chat stylesheet must be the one the installed package
// gives: a reifyui bump without regenerating it would ship the old look under the new components.
import { execFileSync } from 'node:child_process';
import path from 'node:path';

test('agent-chat.scoped.css matches the installed reifyui', () => {
  const root = path.resolve(__dirname, '../../../..');
  expect(() => execFileSync(process.execPath, [path.join(root, 'scripts/scope-agent-chat-css.mjs'), '--check'], { cwd: root, stdio: 'pipe' })).not.toThrow();
});
