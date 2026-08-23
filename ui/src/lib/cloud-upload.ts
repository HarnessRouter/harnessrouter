// Upload a local harness to a hosted workspace. One-way: this instance is the source of truth
// and the hosted copy is a deployment target; an upload replaces it. The key never reaches the
// browser after Save; the gateway does the upload. Self-hosted only.
import { gw } from '@/lib/harness';

export interface CloudTarget {
  configured: boolean; base_url: string; key_hint: string;
  org: string; org_name: string; workspace: string; workspace_name: string;
}
export interface CloudStatus { uploaded: boolean; uploaded_at?: number; target?: string; changed?: boolean }
export interface UploadRow { id: string; ok: boolean; action: 'create' | 'replace' | 'skip'; name?: string; error?: string }

export const destination = (t: { org?: string; org_name?: string; workspace?: string; workspace_name?: string }) =>
  `${t.org_name || t.org || ''} / ${t.workspace_name || t.workspace || ''}`;

export const getTarget = () => gw<CloudTarget>('GET', '/v1/cloud-upload/target');
export const testTarget = (api_key?: string) =>
  gw<{ ok: true; org: string; org_name: string; workspace: string; workspace_name: string }>('POST', '/v1/cloud-upload/target/test', api_key ? { api_key } : {});
export const saveTarget = (api_key: string) => gw<CloudTarget>('PUT', '/v1/cloud-upload/target', { api_key });
export const clearTarget = () => gw<{ configured: false }>('DELETE', '/v1/cloud-upload/target');
export const uploadOne = (id: string) => gw<UploadRow & { status: CloudStatus }>('POST', `/v1/harnesses/${encodeURIComponent(id)}/upload`);
export const uploadMany = (ids: string[]) => gw<{ results: UploadRow[]; target: CloudTarget }>('POST', '/v1/harnesses/upload', { ids });
export const statusOne = (id: string) => gw<CloudStatus>('GET', `/v1/harnesses/${encodeURIComponent(id)}/upload`);
export const statusAll = () => gw<{ harnesses: Record<string, CloudStatus> }>('GET', '/v1/cloud-upload/status');
