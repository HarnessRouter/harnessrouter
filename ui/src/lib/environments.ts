// Environments (UHP Environments chapter): a project's files and its installed dependencies,
// built once and read by every Task session that names it, read-only at a fixed path beside the
// session's own writable workspace. Every function here is one call to the service; nothing is
// derived on the client.
import { authHeaders } from '@/lib/chat';
import { harnessFetch } from '@/lib/hfetch';
import { gw } from '@/lib/harness';

export interface EnvironmentPackage { manager: string; name: string; version: string }
export interface EnvironmentVersion {
  version: number; status: 'building' | 'ready' | 'failed' | 'unknown';
  started_at?: number | null; finished_at?: number | null; error?: string; files?: number; bytes?: number; packages?: number;
}
export interface Environment {
  id: string; object: 'environment'; name: string; slug: string; description: string; entry: string;
  status: 'empty' | 'building' | 'ready' | 'failed'; mount: string;
  version: number | null; latestVersion: number | null;
  files: { count: number; bytes: number };
  packages: EnvironmentPackage[];
  versions: EnvironmentVersion[];
  build: EnvironmentVersion | null;
  member: string; workspace: string; createdAt: number; updatedAt: number;
}
export interface EnvironmentBuildRecord {
  id: string; version: number; status: 'building' | 'ready' | 'failed';
  started_at?: number | null; finished_at?: number | null; error?: string; log?: string;
  packages?: EnvironmentPackage[]; files?: number; bytes?: number;
}
export interface EnvironmentFileEntry { path: string; dir: boolean; bytes: number; mtime: number; link?: boolean }

export const listEnvironments = () => gw<{ environments: Environment[] }>('GET', '/v1/environments').then((d) => d.environments);
export const getEnvironment = (id: string) => gw<Environment>('GET', `/v1/environments/${id}`);
export const createEnvironment = (body: { name: string; description?: string; entry?: string }) =>
  gw<Environment>('POST', '/v1/environments', body);
export const updateEnvironment = (id: string, body: { name: string; description?: string; entry?: string }) =>
  gw<Environment>('PUT', `/v1/environments/${id}`, body);
export const deleteEnvironment = (id: string) => gw<{ id: string; deleted: boolean }>('DELETE', `/v1/environments/${id}`);
export const listEnvironmentFiles = (id: string) =>
  gw<{ entries: EnvironmentFileEntry[]; count: number; bytes: number }>('GET', `/v1/environments/${id}/files`);
export const buildEnvironment = (id: string) => gw<{ version: number; status: string }>('POST', `/v1/environments/${id}/build`);
export const getEnvironmentBuild = (id: string, version: number) =>
  gw<EnvironmentBuildRecord>('GET', `/v1/environments/${id}/builds/${version}`);
export const activateEnvironmentVersion = (id: string, version: number) =>
  gw<Environment>('POST', `/v1/environments/${id}/versions/${version}/activate`);
export const environmentHarnesses = (id: string) =>
  gw<{ harnesses: { id: string; name: string; base: string }[] }>('GET', `/v1/environments/${id}/harnesses`).then((d) => d.harnesses);

const encodePath = (p: string) => p.split('/').map(encodeURIComponent).join('/');

async function raw(method: string, path: string, body?: BodyInit | null, contentType?: string): Promise<Response> {
  const headers: Record<string, string> = { ...authHeaders() };
  delete headers['content-type']; delete headers['Content-Type'];
  if (contentType) headers['content-type'] = contentType;
  const r = await harnessFetch(`/api/harness${path}`, { method, headers, body: body ?? undefined, cache: 'no-store' });
  if (!r.ok) {
    let detail = `${r.status}`;
    try { const j = await r.json(); detail = j?.error?.message || j?.detail || detail; } catch { /* keep the status */ }
    throw new Error(String(detail));
  }
  return r;
}

/** One file's bytes, as text when it is text (the caller decides what to do with a binary). */
export async function readEnvironmentFile(id: string, path: string): Promise<{ text: string | null; bytes: number; type: string }> {
  const r = await raw('GET', `/v1/environments/${id}/files/${encodePath(path)}`);
  const type = r.headers.get('content-type') || 'application/octet-stream';
  const buf = await r.arrayBuffer();
  const textual = /^(text\/|application\/(json|xml|yaml|x-yaml|javascript|toml|x-sh|x-python))/.test(type) || /\.(md|txt|py|js|ts|tsx|jsx|json|yaml|yml|toml|sh|cfg|ini|csv|html|css|env|lock)$/i.test(path);
  let text: string | null = null;
  if (textual && buf.byteLength <= 2 * 1024 * 1024) {
    const dec = new TextDecoder('utf-8', { fatal: true });
    try { text = dec.decode(buf); } catch { text = null; }
  }
  return { text, bytes: buf.byteLength, type };
}
export const writeEnvironmentFile = (id: string, path: string, body: Blob | string) =>
  raw('PUT', `/v1/environments/${id}/files/${encodePath(path)}`, body, typeof body === 'string' ? 'text/plain; charset=utf-8' : (body.type || 'application/octet-stream')).then((r) => r.json());
export const makeEnvironmentDir = (id: string, path: string) =>
  gw<{ path: string; dir: boolean }>('POST', `/v1/environments/${id}/directories`, { path: path.replace(/\/+$/, '') });
export const deleteEnvironmentPath = (id: string, path: string) =>
  raw('DELETE', `/v1/environments/${id}/files/${encodePath(path)}`).then((r) => r.json());
export const importEnvironmentArchive = (id: string, file: File, replace = false) =>
  raw('POST', `/v1/environments/${id}/import${replace ? '?replace=1' : ''}`, file, file.type || 'application/octet-stream').then((r) => r.json());
export const importEnvironmentGit = (id: string, url: string, ref = '', replace = false) =>
  gw<{ written?: number; count: number; bytes: number }>('POST', `/v1/environments/${id}/import`, { git: { url, ref }, replace });

export const fmtBytes = (n: number) => n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB` : n < 1024 ** 3 ? `${(n / 1024 ** 2).toFixed(1)} MB` : `${(n / 1024 ** 3).toFixed(2)} GB`;
