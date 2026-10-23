// Upload a local harness to a hosted workspace. One-way: this instance is the source of truth
// and the hosted copy is a deployment target; an upload replaces it. Several destinations can be
// stored; every upload names one. Keys live encrypted on this instance's gateway, which does the
// upload; the browser never holds them after save. Self-hosted only.
import { gw } from '@/lib/harness';

export interface CloudTarget { id: string; base_url: string; key_hint: string; member: string; workspace_name: string; revoked: boolean; label: string }
/** `open_url`: where the copy opens in HarnessRouter Cloud's console ('' when the destination is another address). */
export interface CloudStatus { uploaded: boolean; uploaded_at?: number; target?: string; changed?: boolean; open_url?: string }
export interface UploadRow { id: string; ok: boolean; action: 'create' | 'replace' | 'skip'; name?: string; remote_id?: string; error?: string; open_url?: string; target_name?: string }

export const listTargets = () => gw<{ targets: CloudTarget[]; last: string }>('GET', '/v1/cloud-upload/targets');
export const addTarget = (api_key: string) => gw<CloudTarget>('POST', '/v1/cloud-upload/targets', { api_key });
export const removeTarget = (id: string) => gw<{ targets: CloudTarget[]; last: string }>('DELETE', `/v1/cloud-upload/targets?id=${encodeURIComponent(id)}`);
export const uploadOne = (id: string, target: string) => gw<UploadRow & { status: CloudStatus }>('POST', `/v1/harnesses/${encodeURIComponent(id)}/upload`, { target });
export const uploadMany = (ids: string[], target: string) => gw<{ results: UploadRow[]; target: CloudTarget }>('POST', '/v1/harnesses/upload', { ids, target });
export const statusOne = (id: string) => gw<CloudStatus>('GET', `/v1/harnesses/${encodeURIComponent(id)}/upload`);
export const statusAll = () => gw<{ harnesses: Record<string, CloudStatus> }>('GET', '/v1/cloud-upload/status');

// Deploy to Cloud, the first time: the HarnessRouter Cloud sign-in hand-off. This instance opens it
// (the page to sign in on, `url`), and its poll answers 202 until the person has signed in, then the
// destination this instance now keeps (the key stays on this instance's server, never here).
export const startDeploySignIn = () => gw<{ code: string; url: string; expires_in?: number }>('POST', '/v1/cloud-upload/connect',
  { instance: typeof window !== 'undefined' ? window.location.host : '' });
/** One read of the sign-in: the destination once it is ready, 'waiting' while it is not. A code that
 *  is gone (expired, or not a deploy sign-in) throws, as any refused call does. */
export async function pollDeploySignIn(code: string): Promise<CloudTarget | 'waiting'> {
  const r = await gw<{ status: string; target?: CloudTarget }>('GET', `/v1/cloud-upload/connect/${encodeURIComponent(code)}`);
  return r?.status === 'ready' && r.target ? r.target : 'waiting';
}
