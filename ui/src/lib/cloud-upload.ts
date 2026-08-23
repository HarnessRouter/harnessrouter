// Upload a local harness to a hosted workspace. One-way: this instance is the source of truth
// and the hosted copy is a deployment target; an upload replaces it. Several destinations can be
// stored; every upload names one. Keys live encrypted on this instance's gateway, which does the
// upload; the browser never holds them after save. Self-hosted only.
import { gw } from '@/lib/harness';

export interface CloudTarget { id: string; base_url: string; key_hint: string; member: string; workspace_name: string; label: string }
export interface CloudStatus { uploaded: boolean; uploaded_at?: number; target?: string; changed?: boolean }
export interface UploadRow { id: string; ok: boolean; action: 'create' | 'replace' | 'skip'; name?: string; remote_id?: string; error?: string }

export const listTargets = () => gw<{ targets: CloudTarget[]; last: string }>('GET', '/v1/cloud-upload/targets');
export const addTarget = (api_key: string) => gw<CloudTarget>('POST', '/v1/cloud-upload/targets', { api_key });
export const testKey = (api_key: string) => gw<{ ok: true; label: string }>('POST', '/v1/cloud-upload/targets/test', { api_key });
export const removeTarget = (id: string) => gw<{ targets: CloudTarget[]; last: string }>('DELETE', `/v1/cloud-upload/targets?id=${encodeURIComponent(id)}`);
export const uploadOne = (id: string, target: string) => gw<UploadRow & { status: CloudStatus }>('POST', `/v1/harnesses/${encodeURIComponent(id)}/upload`, { target });
export const uploadMany = (ids: string[], target: string) => gw<{ results: UploadRow[]; target: CloudTarget }>('POST', '/v1/harnesses/upload', { ids, target });
export const statusOne = (id: string) => gw<CloudStatus>('GET', `/v1/harnesses/${encodeURIComponent(id)}/upload`);
export const statusAll = () => gw<{ harnesses: Record<string, CloudStatus> }>('GET', '/v1/cloud-upload/status');
