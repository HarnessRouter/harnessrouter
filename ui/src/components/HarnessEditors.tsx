'use client';
// Harness capability editors, shared by the Harness Settings page and the Tasks workbench:
//   SkillEditor   , Agent Skills folder editor (tree + md/code editor + uploads)
//   McpRow        , one row of a harness's tool list
//   McpModal      , add/edit for a row, with a live Test connection
// Extracted from workbench/page.tsx (page files must not carry extra named exports).
import { useRef, useState } from 'react';
import { testMcp, storeMcpSecret, type McpServer } from '@/lib/harness';
// Re-exported: pages ported from the hosted console import the type from here.
export type { McpServer };
import { Svg, Chevron, IcSkill } from 'reifyui';

const IcTrash = () => <Svg s={15}><path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" /></Svg>;
const FileGlyph = ({ small }: { small?: boolean }) =>
  <Svg s={small ? 13 : 18}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></Svg>;
// Side-panel toggle (collapse/expand the task-history rail), split-rectangle glyph.
const IcPanel = () => <Svg s={18}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></Svg>;
const IcFolder = () => <Svg s={14}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></Svg>;
const IcFilePlus = () => <Svg s={17}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M12 12v6M9 15h6" /></Svg>;
const IcFolderPlus = () => <Svg s={17}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 11v5M9.5 13.5h5" /></Svg>;
const IcUpload = () => <Svg s={17}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 9l5-5 5 5" /><path d="M12 4v12" /></Svg>;
const IcFolderUp = () => <Svg s={17}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 16v-5.5" /><path d="M9.5 13 12 10.5 14.5 13" /></Svg>;
const IcPencil = () => <Svg s={14}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></Svg>;



// ── Skill folder editor (Agent Skills spec): folder tree + md/code editor + file upload ─────────
export type SkillFile = { path: string; content?: string; content_b64?: string };

// Read an uploaded file as a skill file. Valid UTF-8 text (no NUL) is kept as editable `content`;
// anything else (binaries like .exe/.png, or text with embedded NULs) is base64-encoded into
// `content_b64`. This keeps binary bytes intact AND keeps NUL out of any JSON string, a literal
//  in skill content otherwise aborts the harness PUT at the Postgres layer.
async function readSkillUpload(file: File, path: string): Promise<SkillFile> {
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    try {
      const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
      if (text.indexOf(String.fromCharCode(0)) === -1) return { path, content: text };
    } catch { /* not valid UTF-8 → binary */ }
    let bin = '';
    const CH = 0x8000;
    for (let i = 0; i < bytes.length; i += CH) bin += String.fromCharCode(...bytes.subarray(i, i + CH));
    return { path, content_b64: btoa(bin) };
  } catch {
    return { path, content: '' };
  }
}

// Human bytes from a base64 string length (4 b64 chars ≈ 3 bytes).
const b64Bytes = (b64: string) => Math.floor((b64?.length || 0) * 3 / 4);
const fmtBytes = (n: number) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
export function SkillEditor({ skill, onClose, onSave, nameEditable = false, onName }: {
  skill: { name: string; files?: SkillFile[] }; onClose: () => void; onSave: (files: SkillFile[]) => void;
  // Create-flow: the skill name is edited at the top of the SAME popup (no separate step).
  nameEditable?: boolean; onName?: (name: string) => void;
}) {
  const initial: SkillFile[] = (skill.files && skill.files.length) ? skill.files : [{ path: 'SKILL.md', content: '' }];
  const [files, setFiles] = useState<SkillFile[]>(initial);
  const [selPath, setSelPath] = useState(initial[0]?.path || 'SKILL.md');
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [emptyDirs, setEmptyDirs] = useState<Set<string>>(new Set());   // folders with no files yet
  const [adding, setAdding] = useState<null | 'file' | 'folder'>(null);
  const [newPath, setNewPath] = useState('');
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState('');
  const upRef = useRef<HTMLInputElement>(null);
  const upDirRef = useRef<HTMLInputElement>(null);
  const cur = files.find((f) => f.path === selPath) || files[0];
  const dirty = JSON.stringify(files) !== JSON.stringify(initial);

  const setContent = (content: string) =>
    setFiles((fs) => fs.map((f) => f.path === cur?.path ? { ...f, content } : f));
  const addFile = (path: string, content = '') => {
    const p = path.trim().replace(/^\/+/, '');
    if (!p || files.some((f) => f.path === p)) { setAdding(null); setNewPath(''); return; }
    setFiles((fs) => [...fs, { path: p, content }]); setSelPath(p); setAdding(null); setNewPath('');
  };
  const addFolder = (path: string) => {
    const p = path.trim().replace(/^\/+|\/+$/g, '');
    if (p) setEmptyDirs((s) => new Set(s).add(p));
    setAdding(null); setNewPath('');
  };
  const delFile = (path: string) => {
    if (files.length <= 1) return;
    setFiles((fs) => fs.filter((f) => f.path !== path));
    if (selPath === path) setSelPath((files.find((f) => f.path !== path) || files[0]).path);
  };
  const delDir = (dir: string) => {
    setFiles((fs) => { const rem = fs.filter((f) => !(f.path === dir || f.path.startsWith(dir + '/'))); return rem.length ? rem : fs; });
    setEmptyDirs((s) => new Set([...s].filter((d) => !(d === dir || d.startsWith(dir + '/')))));
  };
  const beginRename = (path: string) => { setRenaming(path); setRenameVal(path.split('/').pop() || path); };
  const applyRename = (oldPath: string, isDir: boolean) => {
    const nn = renameVal.trim(); setRenaming(null);
    if (!nn || nn.includes('/')) return;
    const parent = oldPath.includes('/') ? oldPath.slice(0, oldPath.lastIndexOf('/') + 1) : '';
    const np = (parent + nn).replace(/^\/+|\/+$/g, '');
    if (np === oldPath) return;
    if (isDir) {
      setFiles((fs) => fs.map((f) => (f.path === oldPath || f.path.startsWith(oldPath + '/')) ? { ...f, path: np + f.path.slice(oldPath.length) } : f));
      setEmptyDirs((s) => new Set([...s].map((d) => (d === oldPath || d.startsWith(oldPath + '/')) ? np + d.slice(oldPath.length) : d)));
    } else {
      if (files.some((f) => f.path === np)) return;
      setFiles((fs) => fs.map((f) => f.path === oldPath ? { ...f, path: np } : f));
      if (selPath === oldPath) setSelPath(np);
    }
  };
  const toggle = (dir: string) => setCollapsed((s) => { const n = new Set(s); n.has(dir) ? n.delete(dir) : n.add(dir); return n; });
  const [dragOver, setDragOver] = useState(false);
  const [prog, setProg] = useState<{ done: number; total: number } | null>(null);

  // Merge a batch of {path, content} into the skill, overwrite same-path, append new.
  const mergeFiles = (adds: SkillFile[]) => setFiles((fs) => {
    const map = new Map(fs.map((f) => [f.path, f]));
    for (const a of adds) map.set(a.path.replace(/^\/+/, ''), a);
    return Array.from(map.values());
  });

  // Build a folder tree from the flat path list (+ empty folders) for rendering.
  type TNode = { name: string; path: string; dir: boolean; children: TNode[] };
  const tree: TNode[] = (() => {
    const root: TNode = { name: '', path: '', dir: true, children: [] };
    const ensure = (parts: string[]): TNode => {
      let node = root, acc = '';
      for (const part of parts) {
        acc = acc ? `${acc}/${part}` : part;
        let c = node.children.find((x) => x.dir && x.name === part);
        if (!c) { c = { name: part, path: acc, dir: true, children: [] }; node.children.push(c); }
        node = c;
      }
      return node;
    };
    for (const d of emptyDirs) ensure(d.split('/').filter(Boolean));
    for (const f of files) {
      const parts = f.path.split('/').filter(Boolean);
      const fname = parts.pop() as string;
      (parts.length ? ensure(parts) : root).children.push({ name: fname, path: f.path, dir: false, children: [] });
    }
    const sortRec = (n: TNode) => { n.children.sort((a, b) => a.dir === b.dir ? a.name.localeCompare(b.name) : (a.dir ? -1 : 1)); n.children.forEach(sortRec); };
    sortRec(root);
    return root.children;
  })();

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = Array.from(e.target.files || []);
    if (!list.length) return;
    setProg({ done: 0, total: list.length });
    const adds: SkillFile[] = [];
    for (let i = 0; i < list.length; i++) {
      // a <input webkitdirectory> upload carries the folder path in webkitRelativePath
      const rel = (list[i] as File & { webkitRelativePath?: string }).webkitRelativePath || list[i].name;
      adds.push(await readSkillUpload(list[i], rel));
      setProg({ done: i + 1, total: list.length });
    }
    mergeFiles(adds);
    setProg(null);
    if (upRef.current) upRef.current.value = '';
    if (upDirRef.current) upDirRef.current.value = '';
  };

  // Drag-drop files OR folders into the editor: recurse the dropped tree (webkitGetAsEntry),
  // preserve relative paths, read text with a progress bar. Entries must be captured SYNCHRONOUSLY
  // in the drop handler (the DataTransferItemList is invalidated once the event returns).
  type FsEntry = { isFile: boolean; isDirectory: boolean; name: string;
    file: (cb: (f: File) => void, err?: (e: unknown) => void) => void;
    createReader: () => { readEntries: (cb: (e: FsEntry[]) => void, err?: (e: unknown) => void) => void } };
  const walkEntry = async (entry: FsEntry, prefix: string, out: { file: File; path: string }[]) => {
    const here = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isFile) {
      const f = await new Promise<File>((res, rej) => entry.file(res, rej)).catch(() => null);
      if (f) out.push({ file: f, path: here });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise<FsEntry[]>((res) => reader.readEntries(res, () => res([])));
        if (!batch.length) break;
        for (const e of batch) await walkEntry(e, here, out);
      }
    }
  };
  const ingest = async (roots: FsEntry[], plain: File[]) => {
    const collected: { file: File; path: string }[] = [];
    for (const r of roots) await walkEntry(r, '', collected);
    for (const f of plain) collected.push({ file: f, path: (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name });
    if (!collected.length) return;
    setProg({ done: 0, total: collected.length });
    const adds: SkillFile[] = [];
    for (let i = 0; i < collected.length; i++) {
      adds.push(await readSkillUpload(collected[i].file, collected[i].path));
      setProg({ done: i + 1, total: collected.length });
    }
    mergeFiles(adds);
    setProg(null);
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragOver(false);
    const dt = e.dataTransfer;
    const roots: FsEntry[] = [];
    if (dt.items) {
      for (const it of Array.from(dt.items)) {
        const en = (it as DataTransferItem & { webkitGetAsEntry?: () => unknown }).webkitGetAsEntry?.();
        if (en) roots.push(en as unknown as FsEntry);
      }
    }
    const plain = roots.length ? [] : Array.from(dt.files || []);
    if (roots.length || plain.length) ingest(roots, plain);
  };

  return (
    <div className="hr-modal-scrim" onClick={onClose}>
      <div className="skl-editor" onClick={(e) => e.stopPropagation()}>
        <header className="skl-head">
          {nameEditable ? (
            <span className="skl-title skl-title-edit"><IcSkill />
              <input className="skl-name-input" value={skill.name} placeholder="skill-name (kebab-case)"
                autoFocus onChange={(e) => onName?.(e.target.value)} /></span>
          ) : (
            <span className="skl-title"><IcSkill /> {skill.name}</span>
          )}
          <button className="fp-close" title="Close" onClick={onClose}>×</button>
        </header>
        <div className="skl-body">
          <aside className={'skl-tree' + (dragOver ? ' dragover' : '')}
            onDragOver={(e) => { e.preventDefault(); if (!dragOver) setDragOver(true); }}
            onDragLeave={(e) => { if (e.currentTarget === e.target) setDragOver(false); }}
            onDrop={onDrop}>
            <div className="skl-tree-top">
              <span className="hr-meta">Files</span>
              <div className="skl-tree-acts">
                <button className="skl-icbtn" title="New file" onClick={() => { setAdding('file'); setNewPath(''); }}><IcFilePlus /></button>
                <button className="skl-icbtn" title="New folder" onClick={() => { setAdding('folder'); setNewPath(''); }}><IcFolderPlus /></button>
                <button className="skl-icbtn" title="Upload files" onClick={() => upRef.current?.click()}><IcUpload /></button>
                <button className="skl-icbtn" title="Upload folder" onClick={() => upDirRef.current?.click()}><IcFolderUp /></button>
                <input ref={upRef} type="file" multiple hidden onChange={onUpload} />
                {/* the picker only offers folders when the input carries webkitdirectory, the
                    "upload a skill bundle folder" path was dead without it (drag-drop worked) */}
                <input ref={upDirRef} type="file" hidden onChange={onUpload}
                  {...({ webkitdirectory: '', directory: '' } as Record<string, string>)} />
              </div>
            </div>
            {adding && (
              <div className="skl-newfile">
                <input autoFocus value={newPath}
                  placeholder={adding === 'folder' ? 'folder name' : 'path/to/file.md'}
                  onChange={(e) => setNewPath(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') (adding === 'folder' ? addFolder(newPath) : addFile(newPath));
                    if (e.key === 'Escape') { setAdding(null); setNewPath(''); }
                  }} onBlur={() => { if (!newPath.trim()) { setAdding(null); } }} />
              </div>
            )}
            <div className="skl-filelist">
              {(function render(nodes: TNode[], depth: number): React.ReactNode {
                return nodes.map((n) => n.dir ? (
                  <div key={'d:' + n.path}>
                    <div className="skl-fileitem" style={{ paddingLeft: 6 + depth * 13 }} onClick={() => toggle(n.path)}>
                      <Chevron dir={collapsed.has(n.path) ? 'right' : 'down'} size={12} />
                      <span className="skl-ic"><IcFolder /></span>
                      {renaming === n.path
                        ? <input className="skl-rename" autoFocus value={renameVal} onClick={(e) => e.stopPropagation()}
                            onChange={(e) => setRenameVal(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter') applyRename(n.path, true); if (e.key === 'Escape') setRenaming(null); }}
                            onBlur={() => applyRename(n.path, true)} />
                        : <span className="skl-fname">{n.name}</span>}
                      <span className="skl-row-acts">
                        <button title="Rename" onClick={(e) => { e.stopPropagation(); beginRename(n.path); }}><IcPencil /></button>
                        <button title="Delete folder" onClick={(e) => { e.stopPropagation(); delDir(n.path); }}><IcTrash /></button>
                      </span>
                    </div>
                    {!collapsed.has(n.path) && render(n.children, depth + 1)}
                  </div>
                ) : (
                  <div key={'f:' + n.path} className={'skl-fileitem' + (selPath === n.path ? ' sel' : '')}
                    style={{ paddingLeft: 6 + depth * 13 + 14 }} onClick={() => setSelPath(n.path)}>
                    <span className="skl-ic"><FileGlyph small /></span>
                    {renaming === n.path
                      ? <input className="skl-rename" autoFocus value={renameVal} onClick={(e) => e.stopPropagation()}
                          onChange={(e) => setRenameVal(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') applyRename(n.path, false); if (e.key === 'Escape') setRenaming(null); }}
                          onBlur={() => applyRename(n.path, false)} />
                      : <span className="skl-fname">{n.name}</span>}
                    <span className="skl-row-acts">
                      <button title="Rename" onClick={(e) => { e.stopPropagation(); beginRename(n.path); }}><IcPencil /></button>
                      {files.length > 1 && <button title="Delete" onClick={(e) => { e.stopPropagation(); delFile(n.path); }}><IcTrash /></button>}
                    </span>
                  </div>
                ));
              })(tree, 0)}
            </div>
            {prog && (
              <div className="skl-prog"><div className="skl-prog-bar"><div className="skl-prog-fill" style={{ width: `${Math.round((prog.done / Math.max(prog.total, 1)) * 100)}%` }} /></div>
                <span className="hr-meta">Uploading {prog.done}/{prog.total}…</span></div>
            )}
            {dragOver && <div className="skl-droptip">Drop files or folders to upload</div>}
          </aside>
          <div className="skl-edit">
            <div className="skl-edit-path">{cur?.path}</div>
            {cur?.content_b64 !== undefined && cur?.content === undefined ? (
              <div className="skl-binary hr-meta">
                Binary file · {fmtBytes(b64Bytes(cur.content_b64))}. Stored as-is and mounted into the
                run workspace unchanged; not editable here.
              </div>
            ) : (
              <textarea className="skl-textarea" spellCheck={false} value={cur?.content || ''}
                onChange={(e) => setContent(e.target.value)} placeholder="File contents…" />
            )}
          </div>
        </div>
        <footer className="skl-foot">
          <span className="hr-meta">SKILL.md needs YAML frontmatter (name, description). Enabled skills mount into the run.</span>
          <div className="skl-foot-acts">
            <button className="hr-btn" onClick={onClose}>Cancel</button>
            <button className="hr-btn primary" disabled={!dirty} onClick={() => onSave(files)}>Save folder</button>
          </div>
        </footer>
      </div>
    </div>
  );
}

// ── A harness's tool list: ONE row renderer, no kinds ─────────────────────────────────────────
// Every entry is an MCP server named by a URL, and that is the whole story this row tells. A
// database a kit connected is one of them: it has a name, an address and a credential like any
// other, so it gets the same icon, the same subtitle, the same Edit, Delete and toggle. There is
// deliberately no branch here — a branch would need a field to branch on, and inventing that
// field on the entry is what made the database a parallel path in the first place.
export function McpRow({ server, busy, onEdit, onDelete, onToggle }: {
  server: McpServer; busy?: boolean;
  onEdit: () => void; onDelete: () => void; onToggle: () => void;
}) {
  const enabled = server.enabled !== false;
  return (
    <div className="capability-row">
      <span className="capability-icon">
        <iconify-icon icon="tabler:world-www"></iconify-icon>
      </span>
      <div className="capability-copy"><strong>{server.name}</strong>
        <span>Custom MCP · {server.url || 'endpoint'}</span></div>
      <div className="capability-actions">
        <button className="button quiet small" type="button" disabled={busy} onClick={onEdit}>Edit</button>
        <button className="button quiet small" type="button" disabled={busy} onClick={onDelete}>Delete</button>
        <button className="toggle-button" type="button" disabled={busy} aria-pressed={enabled} onClick={onToggle}>
          {enabled ? 'Enabled' : 'Disabled'}</button>
      </div>
    </div>
  );
}

// ── Tool add/edit modal ───────────────────────────────────────────────────────────────────────
// Name + endpoint + bearer token, with a live Test connection that lists the server's tools
// (handshake runs server-side via the gateway). One form, because there is one kind of entry:
// a database a kit connected edits here too, and editing its address away from the gateway
// breaks it exactly the way editing any server's address to the wrong host breaks that one.
export function McpModal({ server, declaredHeaders = [], onClose, onSave }: {
  server: McpServer | null; declaredHeaders?: string[];
  onClose: () => void; onSave: (s: McpServer) => void;
}) {
  const [name, setName] = useState(server?.name || '');
  const [url, setUrl] = useState(server?.url || '');
  // A $headers.{name} ref is not a secret, show it plainly + editable. A stored vault secret
  // stays blank (masked, 'keep current').
  const _headerRef = !!server?.auth && String(server.auth).startsWith('$headers.');
  const [token, setToken] = useState(_headerRef ? String(server!.auth) : '');
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<null | { busy?: boolean; ok?: boolean; error?: string; server?: string; tools?: { name: string; description?: string }[] }>(null);
  const id = server?.id || ('mcp.' + (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : String(Date.now())));

  async function runTest() {
    if (!url.trim()) return;
    setTest({ busy: true });
    const auth = token.trim() || server?.auth || '';
    setTest(await testMcp(url.trim(), auth));
  }
  async function save() {
    setBusy(true);
    let auth = server?.auth;
    const tok = token.trim();
    try {
      // A $headers.{Name} ref is a per-request app-auth placeholder resolved at task start, store it
      // inline (NOT in the vault; it's not a static secret). A plain token is vaulted as before.
      if (tok) auth = tok.startsWith('$headers.') ? tok : await storeMcpSecret(id, tok);
    } catch { setBusy(false); return; }
    onSave({ id, name: name.trim() || 'mcp', url: url.trim(), transport: 'http', enabled: server?.enabled !== false, ...(auth ? { auth } : {}) });
    setBusy(false);
  }

  return (
    <div className="hr-modal-scrim" onClick={() => !busy && onClose()}>
      <div className="hr-auth-card" style={{ width: 480 }} onClick={(e) => e.stopPropagation()}>
        <h1>{server ? 'Edit MCP server' : 'Add MCP server'}</h1>
        <p className="sub">Connect a remote MCP server (a set of tools) by endpoint and an optional bearer token. Tokens are encrypted at rest and never shown again.</p>
        <div className="hr-field"><label>Name</label>
          <input value={name} autoFocus onChange={(e) => setName(e.target.value)} placeholder="docs-search" /></div>
        <div className="hr-field"><label>Endpoint URL</label>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/mcp" /></div>
        <div className="hr-field">
          <label>Bearer token{' '}
            {token.startsWith('$headers.')
              ? <span className="mcp-authkind hdr">per-request header</span>
              : <span className="hr-meta">{server?.auth ? '(leave blank to keep current)' : '(optional)'}</span>}
          </label>
          <input value={token} type={token.startsWith('$headers.') ? 'text' : 'password'} onChange={(e) => setToken(e.target.value)}
            placeholder={(server?.auth && !token.startsWith('$headers.')) ? '•••••••• stored' : 'token, or $headers.X-App-JWT'} />
          {token.startsWith('$headers.')
            ? <span className="hr-meta">Not stored. The value of the <code>{token.slice('$headers.'.length) || '{Name}'}</code> request header is forwarded to this server on every call.</span>
            : <span className="hr-meta">A static token is stored securely. To forward a per-user token from each request, use a declared Additional Header instead.</span>}
          {declaredHeaders.length > 0 && !token.startsWith('$headers.') && (
            <div className="mcp-hdr-chips">
              {declaredHeaders.map((h) => (
                <button key={h} type="button" className="mcp-hdr-chip"
                  onClick={() => setToken('$headers.' + h)}>
                  Use per-request {h}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="mcp-test-row">
          <button className="hr-btn" disabled={!url.trim() || test?.busy} onClick={runTest}>{test?.busy ? 'Testing…' : 'Test connection'}</button>
          {test && !test.busy && (test.ok
            ? <span className="mcp-test-status ok"><span className="mcp-dot" />Connected{test.server ? ` · ${test.server}` : ''} · {test.tools?.length || 0} tools</span>
            : <span className="mcp-test-status err"><span className="mcp-dot" />{test.error || 'Failed'}</span>)}
        </div>
        {test?.ok && (test.tools?.length || 0) > 0 && (
          <div className="mcp-tools">{test.tools!.map((t) => (
            <div key={t.name} className="mcp-tool-card">
              <div className="mcp-tool-n">{t.name}</div>
              {t.description && <div className="mcp-tool-d">{t.description}</div>}
            </div>
          ))}</div>
        )}
        <div className="hr-card-actions" style={{ marginTop: 14 }}>
          <button className="hr-btn" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="hr-btn primary" disabled={busy || !url.trim()} onClick={save}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
    </div>
  );
}

// Attachment card, image thumbnail or a typed file icon + name + type chip; × remove on hover.
