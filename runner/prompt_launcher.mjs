// Run a Node CLI with its prompt taken from a file instead of from the command line.
//
//     node prompt_launcher.mjs <prompt file> <the CLI's entry script> [args...]
//
// Every argument equal to PROMPT_ARG is replaced by the file's text; process.argv is then set, in this
// process, to [node, entry, ...args], and the CLI's own entry script is imported here. The command line
// this process was started with names the file and never its text. The runner writes the file 0600 as the
// session (server.py, _prompt_handover); this process runs as the session too, and removes the file as
// soon as it has read it. The node: modules are the only imports of its own, so nothing beside this file
// is loaded into the CLI.
//
// This file ships with the runner, root-owned and read-only, never in a session's tree.
import { readFileSync, unlinkSync } from "node:fs";
import { pathToFileURL } from "node:url";

const PROMPT_ARG = "{hr:prompt}";

const [file, entry, ...args] = process.argv.slice(2);
if (!file || !entry) {
  process.stderr.write("usage: prompt_launcher.mjs <prompt file> <entry script> [args...]\n");
  process.exit(2);
}
const text = readFileSync(file, "utf8");
try {
  unlinkSync(file);
} catch {
  // the runner removes it when the turn ends in any case
}
process.argv.splice(1, Infinity, entry, ...args.map((a) => (a === PROMPT_ARG ? text : a)));
await import(pathToFileURL(entry).href);
