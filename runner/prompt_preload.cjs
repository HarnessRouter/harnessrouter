// Hand a Node program its prompt from a file instead of from the command line, for a CLI that is one
// executable with no entry script to import (prompt_launcher.mjs's way), and that takes its prompt only as an
// argument: Kimi Code, a Node single executable whose -p takes only an argument and which reads nothing on
// stdin (runner/server.py, _build_kimi).
//
//     NODE_OPTIONS="--require <this file>" HR_PROMPT_FILE=<prompt file> kimi -p {hr:prompt} ...
//
// Node loads this before the program's own code. The argument equal to PROMPT_ARG is replaced, in this process,
// by the file's text, so the program parses the prompt as it would have from its command line, while the
// command line the process was started with (what `ps` lists, /proc/<pid>/cmdline) holds only the placeholder.
// The file is the session's own, 0600 (server.py, _prompt_handover), and goes as soon as it is read. It must be
// this process's own (its owner is the effective uid) and private (no access for group or others), checked on the
// open file itself: anything else stops the program.
//
// What the program starts inherits neither variable: both are taken out of its environment here, so no shell
// or server it runs loads this file or looks for the prompt. Anything that stops the hand-over stops the
// program, loudly: a turn never runs with the placeholder as its prompt.
//
// This file ships with the runner, root-owned and read-only, never in a session's tree. Only node: modules.
'use strict';
const fs = require('node:fs');

const PROMPT_ARG = '{hr:prompt}';
const file = process.env.HR_PROMPT_FILE;
if (file !== undefined) {
  delete process.env.HR_PROMPT_FILE;
  const own = `--require ${__filename}`;
  const rest = (process.env.NODE_OPTIONS || '').split(own).join(' ').trim();
  if (rest) process.env.NODE_OPTIONS = rest;
  else delete process.env.NODE_OPTIONS;
  const at = process.argv.indexOf(PROMPT_ARG);
  let text;
  try {
    const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    try {
      // the session's own file and no one else's to read (_prompt_handover makes it 0600, as the session): a file
      // someone else made, or one others could read, is never taken as the prompt. Checked on the open file.
      const st = fs.fstatSync(fd);
      if (!st.isFile() || st.uid !== process.geteuid() || (st.mode & 0o077) !== 0) {
        process.stderr.write('the prompt could not be handed over: it is not this program\'s own private file\n');
        process.exit(2);
      }
      text = fs.readFileSync(fd, 'utf8');
    } finally {
      fs.closeSync(fd);
    }
  } catch (e) {
    process.stderr.write(`the prompt could not be read: ${e && e.code ? e.code : 'error'}\n`);
    process.exit(2);
  }
  try {
    fs.unlinkSync(file);
  } catch {
    // the runner removes it when the turn ends in any case
  }
  if (at < 1) {
    process.stderr.write('the command line holds no place for the prompt\n');
    process.exit(2);
  }
  process.argv[at] = text;
}
