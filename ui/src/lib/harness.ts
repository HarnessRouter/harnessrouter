// The harness shape, and the one place that converts it for the wire.
//
// The API is deliberately asymmetric and it matters: it RETURNS camelCase (the shape the console
// renders) but ACCEPTS snake_case, and it ignores unknown fields instead of rejecting them. Send
// the returned shape straight back and the write succeeds while quietly persisting an empty model
// and empty instructions.
//
// Shared by the console client and the server-side cloud-push route so there is exactly one
// definition of what a harness is on the wire. The local gateway and the hosted API take the same
// body, which is the whole point of the open-core split — a promotion is a copy, not a
// translation.

export interface Harness {
  id: string;
  name: string;
  base: string;
  baseLabel?: string;
  defaultModel?: string;
  systemPrompt?: string;
  mcpServers?: unknown[];
  skills?: unknown[];
  disabledTools?: string[];
  additionalHeaders?: string[];
  maxStep?: number | null;
  timeoutSeconds?: number | null;
  createdAt?: number;
  [k: string]: unknown;
}

/** Console shape -> wire body.
 *
 *  Always the COMPLETE harness, never a patch: a write replaces the record, so any field left
 *  out comes back empty. Editors pass the whole object they loaded with their edits applied, and
 *  fields the console doesn't expose survive the round trip.
 *
 *  Local bookkeeping — id, timestamps, org, workspace, member — is dropped by construction
 *  rather than by a deny-list, which is also what makes this safe to push to a hosted account:
 *  the destination mints its own. */
export function harnessBody(h: Partial<Harness> & { name: string; base: string }) {
  return {
    name: h.name,
    base: h.base,
    base_label: h.baseLabel || h.base,
    default_model: h.defaultModel || '',
    system_prompt: h.systemPrompt || '',
    mcp_servers: h.mcpServers || [],
    skills: h.skills || [],
    disabled_tools: h.disabledTools || [],
    additional_headers: h.additionalHeaders || [],
    max_step: h.maxStep ?? null,
    timeout_seconds: h.timeoutSeconds ?? null,
  };
}
