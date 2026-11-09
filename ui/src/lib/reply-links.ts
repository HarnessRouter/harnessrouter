// How a link in an agent's reply names a file of its own task (#594).
//
// Agents write a file they made as `report.pdf`, `/workspace/report.pdf` or
// `sandbox:/workspace/report.pdf`, and none of those point anywhere as written. They resolve against
// the files the task made: an exact path first, then the same name in any folder, then a folder that
// holds one of them. A name the task did not make stays plain text rather than a link to nothing.
//
// Only the path is decided here. Where it opens is the surface's: the signed-in console reads it with
// the sign-in (TaskThread Md, Playground), a shared view reads it through its own link (share page).

const WS_LINK_RE = /^(?:sandbox:)?\/?(?:workspace\/)?(.+)$/;

/** Whether a link is written as a file of the task's workspace, rather than an address of its own. */
export function isWorkspaceHref(href: string): boolean {
  if (!href || href.startsWith('#')) return false;
  if (/^[a-z][a-z0-9+.-]*:/i.test(href) && !href.startsWith('sandbox:')) return false;
  return href.startsWith('sandbox:') || href.startsWith('/workspace/') || href.startsWith('workspace/')
    || (!href.startsWith('/') && /\.[A-Za-z0-9]{1,8}$/.test(href));
}

/** What a reply's link names: null when it is not a file of the workspace (a web address, an anchor,
 *  an address of the console's own), '' when it names a file the task did not make (drawn as plain
 *  text), otherwise the file's path in the workspace. `made`: the paths of the files the task made;
 *  with none known yet, a name is taken as written. */
export function replyFilePath(href: string | undefined, made: readonly string[] = []): string | null {
  if (!href || !isWorkspaceHref(href)) return null;
  let written = href;
  try { written = decodeURIComponent(href); } catch { /* a stray %: the link as written */ }
  const m = written.match(WS_LINK_RE);
  let path = m ? m[1].replace(/^\/+/, '') : '';
  if (!path) return null;
  if (made.length) {
    const base = path.split('/').pop() || path;
    const hit = made.find((f) => f === path) || made.find((f) => (f.split('/').pop() || f) === base);
    if (hit) path = hit;
    else if (!made.some((f) => f.startsWith(path))) return '';
  }
  return path;
}

/** A `sandbox:` link, as some agents write the files they made. Markdown's own sanitizer blanks a
 *  scheme it does not know, so a surface keeps these for replyFilePath to resolve (and never draws one
 *  as written: a name the task did not make is plain text). */
export function isSandboxHref(url: string): boolean {
  return url.startsWith('sandbox:');
}

/** A workspace path as URL path segments, each one escaped. */
export function pathSegments(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/');
}
