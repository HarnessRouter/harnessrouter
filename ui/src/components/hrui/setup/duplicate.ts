// What Duplicate harness gives the copy on top of what the sheet already sends (its instructions, skills, plugins,
// environment, tools switched off, limits, reasoning effort and request headers): the harness's own MCP servers and
// its variables. A copy that left them behind had no tools on its first task, and a server that signs in with a
// request header the copy does declare came out missing.
//
// A stored token is kept as its reference: the instance keeps it for the organization and never removes it with a
// harness, so the copy can name it too. A server this instance hosts for one harness alone (a database connection,
// the media tools) names a record that only that harness may use and that is removed with it, so the copy cannot
// take it over: it is left out and named, so the person knows.
import type { CustomHarness, McpServer } from '@/lib/harness';
import { newMcpId } from '../mcp/McpSheet';
import { isServiceEntry } from './setupParts';

/** The reference a server this instance hosts for one harness carries as its auth (the gateway's
 *  `harness-hosted-` records): served to that harness only, and removed with it. */
const ONE_HARNESS_AUTH = 'vault:harness-hosted-';

const tiedToOne = (m: McpServer) => String(m.auth || '').startsWith(ONE_HARNESS_AUTH);

export interface DuplicateParts {
  /** the copy's own servers: each with the same address, auth and on/off as the original's, under a new id, so a
   *  later edit of a server on one harness never moves the other's */
  mcpServers: McpServer[];
  /** the names of the servers tied to the original alone, which the copy does not get */
  notCopied: string[];
  /** the variables every task of the copy starts with, as the original's are */
  env: Record<string, string>;
}

/** The parts of `h` its copy takes as they are. The service's own entries (workspace plugins, memories) are never
 *  among the servers: the sheet adds the workspace plugins through their own route, and a new harness gets its
 *  memory from the service. */
export function duplicateParts(h: CustomHarness): DuplicateParts {
  const own = (h.mcpServers || []).filter((m) => !isServiceEntry(m));
  return {
    mcpServers: own.filter((m) => !tiedToOne(m)).map((m) => ({ ...m, id: newMcpId() })),
    notCopied: own.filter(tiedToOne).map((m) => m.name || m.id),
    env: { ...(h.env || {}) },
  };
}

const andList = (names: string[]) => (names.length <= 2 ? names.join(' and ') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`);

/** What the sheet says of the servers the copy does not get: before Save, and in the saved message. '' for none. */
export function notCopiedLine(names: string[], when: 'before' | 'after'): string {
  if (!names.length) return '';
  const one = names.length === 1;
  return when === 'before'
    ? `${andList(names)} ${one ? 'is' : 'are'} tied to this harness, so the copy won’t have ${one ? 'it' : 'them'}.`
    : `${andList(names)} ${one ? 'is' : 'are'} tied to the original, so the copy doesn’t have ${one ? 'it' : 'them'}.`;
}
