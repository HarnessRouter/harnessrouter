'use client';
// PUBLIC read-only Task view (session share). No auth: the unguessable token is the credential;
// the gateway serves it only while sharing is enabled. Shows the conversation (user/assistant
// turns, markdown-rendered) and every workspace artifact, files open inline via the public
// share file route, so html pages render in the browser with their relative assets loading.
// A reply's link to a file of the task opens that file the same way (#594).
import '@/app/revamp.css';
import 'iconify-icon';   // registers the web component, this page renders outside the app Shell
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { FileTypeIcon } from '@/components/FileTypeIcon';
import { keepSandbox } from '@/components/hrui/setup/TaskThread';
import { minutesAndSeconds } from '@/lib/duration';
import { isSandboxHref, pathSegments, replyFilePath } from '@/lib/reply-links';

interface ShareMeta { session_id?: string; title?: string; status?: string; model?: string;
  backend?: string; harness_id?: string; harness_name?: string; event_count?: number; elapsed?: number; finished_at?: number }
interface ShareTurn { id: string; status?: string; user?: string; assistant?: string;
  tools?: { name?: string; arguments?: string }[]; files?: { filename?: string }[] }
interface ShareFile { path: string; bytes?: number; media_type?: string }

function fmtDur(s?: number): string {
  if (!s) return '';
  const [m, sec] = minutesAndSeconds(s);
  return m ? `${m}m ${String(sec).padStart(2, '0')}s` : `${sec}s`;
}
function fmtBytes(n?: number): string {
  if (n == null) return '';
  return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
}

export default function SharePage() {
  const params = useParams<{ token: string }>();
  const token = params.token || '';
  const [meta, setMeta] = useState<ShareMeta | null>(null);
  const [turns, setTurns] = useState<ShareTurn[] | null>(null);
  const [files, setFiles] = useState<ShareFile[] | null>(null);
  // the link is gone (the server says 404: revoked, or never shared), or it could not be read just
  // now (any other answer, or none): only the first may say the link is dead (#573)
  const [gone, setGone] = useState(false);
  const [metaFailed, setMetaFailed] = useState(false);
  const [metaTry, setMetaTry] = useState(0);
  // the conversation could not be read (the service answered an error): said, with a way to read
  // again, never drawn as a conversation with nothing in it
  const [turnsFailed, setTurnsFailed] = useState(false);
  const [turnsTry, setTurnsTry] = useState(0);
  // the artifacts could not be read, same rule as the conversation above: said, never drawn as a
  // Task that produced nothing (the gateway answers a 500 when the workspace tarball is truncated)
  const [filesFailed, setFilesFailed] = useState(false);

  useEffect(() => {
    if (!token) return;
    let alive = true;
    setFilesFailed(false);
    setMetaFailed(false);
    fetch(`/api/share/${encodeURIComponent(token)}/meta`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (alive) setMeta(d); })
      .catch((e: Error) => { if (alive) { if (e.message === '404') setGone(true); else setMetaFailed(true); } });
    fetch(`/api/share/${encodeURIComponent(token)}/files`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (alive) setFiles(d.files || []); })
      .catch(() => { if (alive) { setFiles(null); setFilesFailed(true); } });
    return () => { alive = false; };
  }, [token, metaTry]);
  useEffect(() => {
    if (!token) return;
    let alive = true;
    setTurnsFailed(false);
    fetch(`/api/share/${encodeURIComponent(token)}/turns`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (alive) setTurns(Array.isArray(d?.turns) ? d.turns : []); })
      .catch(() => { if (alive) { setTurns(null); setTurnsFailed(true); } });
    return () => { alive = false; };
  }, [token, turnsTry]);

  // Every file opens through this link's own file route: the token is what the server checks, so
  // a link-holder reads what the share shows and nothing more. It used to move to the task's file
  // address, /{harness}/{session}/workspace/{path}, once the meta loaded; a self-hosted box asks for
  // its sign-in at that address, so anyone without one was sent to a sign-in page instead of the file.
  const fileUrl = useMemo(() => (path: string) => `/api/share/${encodeURIComponent(token)}/f/${pathSegments(path)}`, [token]);
  // A reply's links to the task's own files (lib/reply-links) open them here too, in a new tab; a name
  // the task did not make is plain text. Before, they resolved against this page's own address, as if
  // the file's name were a share link, and opened a page saying the shared Task is unavailable.
  const made = useMemo(() => {
    const out = new Set<string>();
    for (const f of files || []) if (f.path) out.add(f.path);
    for (const t of turns || []) for (const f of t.files || []) if (f.filename) out.add(f.filename);
    return Array.from(out);
  }, [files, turns]);
  const replyParts = useMemo<Components>(() => ({
    a: ({ href, title, children }) => {
      const path = replyFilePath(href, made);
      if (path === '') return <>{children}</>;
      if (path) return <a href={fileUrl(path)} target="_blank" rel="noreferrer">{children}</a>;
      if (href && isSandboxHref(href)) return <>{children}</>;
      return <a href={href} title={title}>{children}</a>;
    },
  }), [made, fileUrl]);

  if (metaFailed && !meta) {
    return (
      <main style={{ marginLeft: 0, height: '100vh', overflowY: 'auto' }}>
        <div className="page" style={{ maxWidth: 720 }}>
          <div className="page-header" role="alert"><div><h1>This shared Task could not be loaded just now</h1>
            <p>Try again in a moment.</p>
            <button type="button" className="hr-btn" onClick={() => { setMetaTry((n) => n + 1); setTurnsTry((n) => n + 1); }}>Try again</button></div></div>
        </div>
      </main>
    );
  }

  if (gone) {
    return (
      <main style={{ marginLeft: 0, height: '100vh', overflowY: 'auto' }}>
        <div className="page" style={{ maxWidth: 720 }}>
          <div className="page-header"><div><h1>This shared Task is unavailable</h1>
            <p>The link may have been revoked by its owner, or it never existed.</p></div></div>
        </div>
      </main>
    );
  }

  return (
    // The app chrome locks body scroll (main is the app's scroll surface). This page has no
    // sidebar, so main must be its OWN full-height scroll container or the page can't scroll.
    <main style={{ marginLeft: 0, height: '100vh', overflowY: 'auto' }}>
      <div className="page share-page" style={{ maxWidth: 860 }}>
        <div className="page-header">
          <div>
            <p className="share-brand"><img src="/brand/hr-mark-duo-light.svg" alt="" width={20} height={20} /> Shared from <strong>HarnessRouter</strong></p>
            <h1 style={{ fontSize: 24 }}>{meta?.title || 'Shared Task'}</h1>
            <div className="share-meta">
              {meta?.harness_name && <span className="share-tag"><iconify-icon icon="tabler:route"></iconify-icon>{meta.harness_name}</span>}
              {meta?.model && <span className="share-tag"><iconify-icon icon="tabler:box"></iconify-icon>{meta.model}</span>}
              {!!meta?.event_count && <span className="share-tag"><iconify-icon icon="tabler:list-tree"></iconify-icon>{meta.event_count} events</span>}
              {!!meta?.elapsed && <span className="share-tag"><iconify-icon icon="tabler:clock"></iconify-icon>{fmtDur(meta.elapsed)}</span>}
              {!meta && <span className="sk" style={{ display: 'inline-block', width: 220, height: 22, borderRadius: 999 }} />}
            </div>
          </div>
        </div>

        <div className="share-conv">
          {turns === null && !turnsFailed && <span className="sk" style={{ display: 'block', height: 120, borderRadius: 10 }} />}
          {turnsFailed ? (
            <div className="session-empty" role="alert">This conversation could not be loaded just now.{' '}
              <button type="button" className="hr-btn" onClick={() => setTurnsTry((n) => n + 1)}>Try again</button></div>
          ) : null}
          {turns?.map((t) => (
            <div key={t.id} className="share-turn">
              {t.user && <div className="share-user"><div className="share-user-bubble">{t.user}</div></div>}
              {t.assistant && (
                <div className="share-asst">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={keepSandbox} components={replyParts}>{t.assistant}</ReactMarkdown>
                </div>
              )}
            </div>
          ))}
          {turns && turns.length === 0 && <div className="session-empty">No conversation content.</div>}
        </div>

        <div className="section-header" style={{ marginTop: 26 }}><h2>Artifacts</h2>
          <span>{files ? `${files.length} file${files.length === 1 ? '' : 's'}` : ''}</span></div>
        {/* Same cards as the chat panel's outputs, except clicking opens the file in a new tab
            (there is no preview side panel on the public page). */}
        <div className="wbx-files" style={{ maxWidth: 'none' }}>
          {(files || []).map((f) => (
            <div key={f.path} className="wbx-filecard" role="link" tabIndex={0}
              onClick={() => window.open(fileUrl(f.path), '_blank', 'noopener')}
              onKeyDown={(e) => { if (e.key === 'Enter') window.open(fileUrl(f.path), '_blank', 'noopener'); }}>
              <span className="wbx-filecard-ic"><FileTypeIcon name={f.path} size={32} /></span>
              <span className="wbx-filecard-meta">
                <span className="wbx-filecard-name">{f.path}</span>
                <span className="wbx-filecard-sub">{(f.path.split('.').pop() || 'file').toUpperCase()} · output{f.bytes != null ? ` · ${fmtBytes(f.bytes)}` : ''}</span>
              </span>
              <a className="wbx-filecard-dl" href={fileUrl(f.path)} download={f.path.split('/').pop()} target="_blank" rel="noreferrer"
                title="Download" onClick={(e) => e.stopPropagation()}>
                <iconify-icon icon="tabler:download"></iconify-icon></a>
              <span className="wbx-filecard-open">Open</span>
            </div>
          ))}
          {filesFailed && <p style={{ color: 'var(--muted)', fontSize: 13 }} role="alert">The artifacts could not be loaded just now.</p>}
          {files && files.length === 0 && <p style={{ color: 'var(--muted)', fontSize: 13 }}>No artifacts in this Task.</p>}
        </div>
        <p style={{ color: 'var(--faint)', fontSize: 12, marginTop: 14 }}>
          Shared read-only. The owner can revoke this link at any time.
        </p>
      </div>
    </main>
  );
}
