'use client';
// How an agent's prose is drawn in a task (its replies, a trace step's content): Markdown, with the
// links a reply makes to files of its own workspace pointed at the task's file address.
import { useMemo } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';


// Agent replies name workspace files as /workspace/... or sandbox: links, which point nowhere as
// written. They resolve against the files this task produced, at the task's own file address (the
// same rule the console's conversation uses); a name nothing produced stays plain text.
const WS_LINK_RE = /^(?:sandbox:)?\/?(?:workspace\/)?(.+)$/;
function isWorkspaceHref(href: string): boolean {
  if (!href || href.startsWith('#')) return false;
  if (/^[a-z][a-z0-9+.-]*:/i.test(href) && !href.startsWith('sandbox:')) return false;
  return href.startsWith('sandbox:') || href.startsWith('/workspace/') || href.startsWith('workspace/')
    || (!href.startsWith('/') && /\.[A-Za-z0-9]{1,8}$/.test(href));
}

export function Md({ text, sid, harnessId, produced }: { text: string; sid?: string; harnessId?: string; produced?: string[] }) {
  const components = useMemo<Components>(() => ({
    a: ({ href, children }) => {
      if (href && sid && harnessId && isWorkspaceHref(href)) {
        const m = decodeURIComponent(href).match(WS_LINK_RE);
        let path = m ? m[1].replace(/^\/+/, '') : '';
        const made = produced || [];
        if (path && made.length) {
          const base = path.split('/').pop() || path;
          const hit = made.find((f) => f === path) || made.find((f) => (f.split('/').pop() || f) === base);
          if (hit) path = hit;
          else if (!made.some((f) => f.startsWith(path))) return <>{children}</>;
        }
        if (path) {
          const enc = path.split('/').map(encodeURIComponent).join('/');
          return <a href={`/${encodeURIComponent(harnessId)}/${encodeURIComponent(sid)}/workspace/${enc}`} target="_blank" rel="noreferrer">{children}</a>;
        }
      }
      return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
    },
  }), [sid, harnessId, produced]);
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{text}</ReactMarkdown>;
}

/** A JSON text pretty-printed, or null when it is not JSON. */
export function prettyJson(c: string): string | null {
  const x = String(c || '').trim();
  if (!/^[[{]/.test(x)) return null;
  try { return JSON.stringify(JSON.parse(x), null, 2); } catch { return null; }
}
