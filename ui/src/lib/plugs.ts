// Plugins: services a workspace connects once, each Harness including the ones it needs.
//
// One server answers all of it, the gateway: GET /v1/plugs is the catalog with each plugin's state in
// the current workspace (the workspace rides the request headers, lib/workspace), PUT and DELETE
// /v1/plugs/{type} connect, change, turn off and remove one, and what a Harness includes is the
// Harness's own binding (/v1/harnesses/{id}/servers/plugs). A credential is sent once, tried at the
// service, kept in the instance's secret store and never read back: a plugin says only which of its
// secrets are set. Every figure on the page is the server's: the catalog, the tool lists, the price,
// the Harnesses that include each plugin.
//
// The calls themselves are lib/harness's; this module is where the console reads them from, plus the
// two reads a page waits on, which take a signal so they always end (lib/settle.ts readSettled).
import { gw, type Plug } from '@/lib/harness';

export {
  setPlug, deletePlug, plugTools, microsoftStart, microsoftComplete, microsoftSignout,
  getHarnessPlugs, setHarnessPlugs, PLUGS_ENTRY_ID,
  type Plug, type PlugTool, type PlugPricing, type HarnessPlugs,
} from '@/lib/harness';

/** The plugin catalog for the current workspace, each plugin with its state here: connected,
 *  disabled (turned off, its settings kept), needs_auth (waiting for a credential or a person's
 *  sign-in) or missing (never connected). */
export function listPlugs(signal?: AbortSignal): Promise<{ workspace: string; plugs: Plug[] }> {
  return gw<{ workspace: string; plugs: Plug[] }>('GET', '/v1/plugs', undefined, signal);
}

/** The workspace's Harnesses that include one plugin, by id and name, and how many there are. */
export interface PlugUse { harnesses: number; attached: number; harness_list: { id: string; name: string }[] }
export function plugAttachments(type: string, signal?: AbortSignal): Promise<PlugUse> {
  return gw<PlugUse>('GET', `/v1/plugs/${encodeURIComponent(type)}/attachments`, undefined, signal);
}
