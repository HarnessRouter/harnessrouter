'use client';
// The workspace's API keys for the key step every coding-agent sheet has (start/KeyStep: the guides, Set
// up the app): the same list and the same create call as the API Keys page (GET / POST
// /v1/orgs/{org}/keys). A new key's secret comes back once from the create call; the caller keeps it
// for as long as its sheet is open and shows it in that sheet only. A key reaches the workspace it is
// made in, or, asked for (`everywhere`), every workspace: a key with no workspace. A key made in the
// Default Workspace reaches every workspace already (the gateway's rule).
import { useCallback, useEffect, useMemo, useState } from 'react';
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { readSettled } from '@/lib/settle';
import { useWorkspace } from '@/lib/workspace';
import { track } from '@/lib/analytics';
import { toast } from '../toast';

export interface WsKey { id: string; name?: string; created_at?: string | number; revoked?: boolean; tail?: string; workspace?: string; last_used?: string | number }

/** A key that reaches every workspace: one with no workspace, or one of the Default Workspace. */
export const reachesAll = (k: Pick<WsKey, 'workspace'>, defaultId: string): boolean => !k.workspace || (!!defaultId && k.workspace === defaultId);

/** A key's mask, "sk-hr-••••" and its last four as the gateway keeps them, or '' when it keeps none:
 *  a key made before the gateway kept them (2026-09-02) has none, and its secret is never stored, so
 *  there is nothing true to show after the dots. */
export const keyMask = (tail?: string): string => { const t = (tail || '').trim(); return t ? `sk-hr-••••${t}` : ''; };

const toMs = (s?: string | number): number => { const n = Number(s); return n ? n * (n < 1e12 ? 1000 : 1) : 0; };

/** Why the gateway refused a key call, in its own words, or '' when it gave none to show. Its refusals of
 *  who may make or revoke a key (403: "Only the owner or an Admin of your organization can…", "Only the
 *  person who made this key…", a workspace not in reach) and a key's state (409) are sentences written for
 *  a person ({error: {message}, detail}); anything else (a 5xx, a sign-in that ended, a body that is not
 *  the gateway's) has none, and the caller says its own line. */
export function keyRefusal(status: number, body: unknown): string {
  if (status !== 403 && status !== 409) return '';
  const b = body && typeof body === 'object' ? body as { error?: { message?: unknown }; detail?: unknown } : null;
  const say = typeof b?.error?.message === 'string' ? b.error.message : typeof b?.detail === 'string' ? b.detail : '';
  return say.trim();
}

export interface KeysState {
  /** the workspace's keys, newest first: null until a read has answered. A read that fails keeps the
   *  last answered list (null when none has answered), never an empty one */
  keys: WsKey[] | null;
  /** the newest key that still works (the design's liveKey); null while `keys` is null */
  live: WsKey | null;
  /** the last read of the list failed (after its quiet second try): the names in use are not known */
  error: boolean;
  /** read the list again (a person's Try again) */
  retry: () => void;
  busy: boolean;
  /** make a key; resolves to its id and secret, or null. The gateway's refusal (who can make it, by role)
   *  goes to `onRefused`, for the caller to say under its name field; any other failure was toasted.
   *  `everywhere`: a key for every workspace (no workspace of its own) */
  create: (name: string, surface: string, onRefused?: (why: string) => void, opts?: { everywhere?: boolean }) => Promise<{ id: string; secret: string } | null>;
  /** why a name cannot be used, or '' */
  nameProblem: (name: string) => string;
}

export function useWsKeys(): KeysState {
  const s = getSession();
  const org = s?.orgId || '';
  const member = s?.member?.email || s?.member?.id || '';
  const base = `/api/harness/v1/orgs/${encodeURIComponent(org)}/keys`;
  const { current, defaultId } = useWorkspace();
  const isDefaultWs = !current.id || current.id === defaultId;
  const [keys, setKeys] = useState<WsKey[] | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    if (!org) { setKeys([]); setError(false); return; }
    try {
      const d = await readSettled(async (signal) => {
        const r = await harnessFetch(base, { signal });
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      });
      // a key belongs to a workspace; an organization key (no workspace) reaches every one
      const list = ((d.keys || []) as WsKey[]).filter((k) => !current.id || !k.workspace || k.workspace === current.id);
      setKeys(list.sort((a, b) => toMs(b.created_at) - toMs(a.created_at)));
      setError(false);
    } catch { setError(true); }
  }, [base, org, current.id]);
  useEffect(() => { void reload(); }, [reload]);

  const live = useMemo(() => (keys || []).find((k) => !k.revoked) || null, [keys]);
  const nameProblem = useCallback((nm: string) => {
    if (!nm.trim()) return 'Name the key first, e.g. production.';
    if ((keys || []).some((k) => !k.revoked && (k.name || '').toLowerCase() === nm.trim().toLowerCase())) return `A key named ${nm.trim()} already exists. Use another name.`;
    return '';
  }, [keys]);

  const create = useCallback(async (name: string, surface: string, onRefused?: (why: string) => void, opts?: { everywhere?: boolean }) => {
    const nm = name.trim();
    if (busy || !org || !nm) return null;
    setBusy(true);
    try {
      const ws = opts?.everywhere ? '' : current.id || '';
      const r = await harnessFetch(base, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name: nm, member_id: member, workspace: ws, workspace_name: ws ? current.name || '' : '', workspace_default: !!ws && isDefaultWs }),
      });
      const d = await r.json().catch(() => null);
      const why = r.ok ? '' : keyRefusal(r.status, d);
      if (why) {
        if (onRefused) onRefused(why); else toast(why);
        return null;
      }
      if (!r.ok || !d?.key) throw new Error('create');
      track('api_key_created', { surface, is_first_key: (keys || []).length === 0, workspace_is_default: isDefaultWs, workspace_id: current.id || null });
      await reload();
      return { id: String(d.id || ''), secret: String(d.key) };
    } catch {
      toast('The key could not be created. Try again.');
      return null;
    } finally { setBusy(false); }
  }, [busy, org, base, member, current.id, current.name, isDefaultWs, keys, reload]);

  const retry = useCallback(() => { void reload(); }, [reload]);

  return { keys, live, error, retry, busy, create, nameProblem };
}
