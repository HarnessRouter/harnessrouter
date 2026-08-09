'use client';
// PUBLIC read-only Task view (session share). No auth: the unguessable token is the credential;
// the gateway serves it only while sharing is enabled. Shows the conversation (user/assistant
// turns, markdown-rendered) and every workspace artifact, files open inline via the public
// share file route, so html pages render in the browser with their relative assets loading.
import '@/app/revamp.css';
import 'iconify-icon';   // registers the web component, this page renders outside the app Shell
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { FileTypeIcon } from '@/components/FileTypeIcon';

interface ShareMeta { session_id?: string; title?: string; status?: string; model?: string;
  backend?: string; harness_id?: string; harness_name?: string; event_count?: number; elapsed?: number; finished_at?: number }
interface ShareTurn { id: string; status?: string; user?: string; assistant?: string;
  tools?: { name?: string; arguments?: string }[]; files?: { filename?: string }[] }
interface ShareFile { path: string; bytes?: number; media_type?: string }

function fmtDur(s?: number): string {
  if (!s) return '';
  const m = Math.floor(s / 60), sec = Math.round(s % 60);
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
  const [gone, setGone] = useState(false);

  useEffect(() => {
    if (!token) return;
    let alive = true;
    fetch(`/api/share/${encodeURIComponent(token)}/meta`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (alive) setMeta(d); })
      .catch(() => { if (alive) setGone(true); });
    fetch(`/api/share/${encodeURIComponent(token)}/turns`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (alive) setTurns(d.turns || []); })
      .catch(() => { if (alive) setTurns([]); });
    fetch(`/api/share/${encodeURIComponent(token)}/files`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (alive) setFiles(d.files || []); })
      .catch(() => { if (alive) setFiles([]); });
    return () => { alive = false; };
  }, [token]);

  // Canonical artifact address: /{harness}/{session}/workspace/{path} (single cached
  // shared-flag check server-side). Token route stays as the fallback while meta loads.
  const fileUrl = useMemo(() => (path: string) => {
    const enc = path.split('/').map(encodeURIComponent).join('/');
    if (meta?.harness_id && meta?.session_id)
      return `/${encodeURIComponent(meta.harness_id)}/${encodeURIComponent(meta.session_id)}/workspace/${enc}`;
    return `/api/share/${encodeURIComponent(token)}/f/${enc}`;
  }, [token, meta]);

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
            <p className="share-brand"><img src="/harnessrouter-logo.svg" alt="" width={20} height={20} /> Shared from <strong>HarnessRouter</strong></p>
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
          {turns === null && <span className="sk" style={{ display: 'block', height: 120, borderRadius: 10 }} />}
          {turns?.map((t) => (
            <div key={t.id} className="share-turn">
              {t.user && <div className="share-user"><div className="share-user-bubble">{t.user}</div></div>}
              {t.assistant && (
                <div className="share-asst">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{t.assistant}</ReactMarkdown>
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
          {files && files.length === 0 && <p style={{ color: 'var(--muted)', fontSize: 13 }}>No artifacts in this Task.</p>}
        </div>
        <p style={{ color: 'var(--faint)', fontSize: 12, marginTop: 14 }}>
          Shared read-only. The owner can revoke this link at any time.
        </p>
      </div>
    </main>
  );
}
