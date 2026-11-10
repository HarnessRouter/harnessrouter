'use client';
// How an agent's prose is drawn in a task (its replies, a trace step's content): Markdown, with the
// links a reply makes to files of its own workspace pointed at the task's file address.
import { useEffect, useMemo, useRef, type MouseEvent } from 'react';
import ReactMarkdown, { defaultUrlTransform, type Components, type UrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { isSandboxHref, pathSegments, replyFilePath } from '@/lib/reply-links';

// Agent replies name workspace files as /workspace/... or sandbox: links, which point nowhere as
// written. They resolve against the files this task produced (lib/reply-links), at the task's own
// file address; a name nothing produced stays plain text.
//
// That address is the PUBLIC one: the console relays it to a read that answers only while the task
// is shared, and a plain link carries no sign-in. So a signed-in view passes `onOpen`, and a click
// opens the file there, read with the sign-in, as the file's card does (#594). The address stays the
// link's own, for a shared view and for opening it in a new tab.

/** Markdown blanks a `sandbox:` link before a surface's own `a` sees it; this keeps it so it can resolve
 *  (the share page draws its replies with it too). */
export const keepSandbox: UrlTransform = (url, key) => (key === 'href' && isSandboxHref(url) ? url : defaultUrlTransform(url));
const asked = (e: MouseEvent) => e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey;

export function Md({ text, sid, harnessId, produced, onOpen }: {
  text: string; sid?: string; harnessId?: string; produced?: string[];
  /** open a file of this task in the signed-in view (the preview beside the conversation) */
  onOpen?: (path: string) => void;
}) {
  // the newest handler, read at the click: a new function each render must not redraw every link
  const open = useRef(onOpen);
  useEffect(() => { open.current = onOpen; });
  const canOpen = !!onOpen;
  const components = useMemo<Components>(() => ({
    a: ({ href, children }) => {
      const path = sid && harnessId ? replyFilePath(href, produced) : null;
      if (path === '') return <>{children}</>;
      if (path && sid && harnessId) {
        const onClick = canOpen ? (e: MouseEvent) => {
          if (asked(e)) return;   // a new tab, a window, a save: the browser's, at the link's address
          e.preventDefault();
          open.current?.(path);
        } : undefined;
        return (
          <a href={`/${encodeURIComponent(harnessId)}/${encodeURIComponent(sid)}/workspace/${pathSegments(path)}`}
            target="_blank" rel="noreferrer" onClick={onClick}>{children}</a>
        );
      }
      if (href && isSandboxHref(href)) return <>{children}</>;   // no task to resolve it against
      return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
    },
  }), [sid, harnessId, produced, canOpen]);
  return <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={keepSandbox} components={components}>{text}</ReactMarkdown>;
}

/** A JSON text pretty-printed, or null when it is not JSON. */
export function prettyJson(c: string): string | null {
  const x = String(c || '').trim();
  if (!/^[[{]/.test(x)) return null;
  try { return JSON.stringify(JSON.parse(x), null, 2); } catch { return null; }
}
